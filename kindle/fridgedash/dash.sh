#!/bin/sh
# fridgedash: hourly e-ink dashboard for a jailbroken Kindle 4 Non-Touch.
#
# Loop: WiFi on -> fetch PNG -> eips -> WiFi off -> RTC alarm -> suspend to RAM.
# Power button: wake, fetch all pages freshly rendered, browse them with the page keys.
# Runs from /tmp (see start.sh) so a USB plug that unmounts /mnt/us cannot kill it.
#
# Usage: dash.sh [once]     "once" = single refresh, framework left running (testing)
#        DEBUG=1 dash.sh    use sleep instead of suspend-to-RAM

# Reason: eips lives in /usr/sbin, which is not on PATH for KUAL/SSH launches.
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH

HERE=${DASH_HERE:-$(dirname "$0")}
# shellcheck source-path=SCRIPTDIR source=config.sh
. "$HERE/config.sh"

WORK=/tmp/fridgedash
PNG=$WORK/dash.png
KEYS=$WORK/keys
PIDFILE=$WORK/pid
LOG=/mnt/us/fridgedash/dash.log
RTC_WAKE=/sys/devices/platform/mxc_rtc.0/wakeup_enable
DEBUG=${DEBUG:-0}

mkdir -p "$WORK"

log() {
    # /mnt/us may be unmounted (USB storage mode); logging is best effort.
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >>"$LOG" 2>/dev/null
}

battery() {
    gasgauge-info -c 2>/dev/null | tr -dc '0-9'
}

# Same sequence KOReader uses on legacy Kindles.
wifi() {
    if [ "$1" = 1 ]; then
        lipc-set-prop -i com.lab126.cmd wirelessEnable 1 2>/dev/null
        lipc-set-prop -i com.lab126.wifid enable 1 2>/dev/null
    else
        lipc-set-prop -i com.lab126.wifid enable 0 2>/dev/null
        lipc-set-prop -i com.lab126.cmd wirelessEnable 0 2>/dev/null
    fi
}

# Poll the server until it answers or NET_TIMEOUT expires.
wait_for_server() {
    n=0
    while [ "$n" -lt "$NET_TIMEOUT" ]; do
        curl -s -f -m 3 -o /dev/null "$SERVER/healthz" 2>/dev/null && return 0
        sleep 1
        n=$((n + 1))
    done
    return 1
}

# Fetch and show the dashboard. $1 = epoch of the next scheduled wake (reported to the
# server so Home Assistant knows when to expect us); $2 = "keepwifi" to leave WiFi on;
# $3 non-empty = ask the server to render fresh first (manual refresh).
refresh() {
    wifi 1
    batt=$(battery)
    chg=$(lipc-get-prop com.lab126.powerd isCharging 2>/dev/null | tr -dc '0-9')
    # Reason: send only values actually read, so a failed gauge read never reports 0%.
    query="${batt:+batt=$batt&}${chg:+chg=$chg&}${1:+next=$1&}${3:+fresh=1}"
    status=fail
    if wait_for_server &&
        curl -s -f -m 30 --connect-timeout 5 -o "$PNG.tmp" "$SERVER/dash.png?$query" 2>/dev/null &&
        [ -s "$PNG.tmp" ]; then
        mv "$PNG.tmp" "$PNG"
        eips -f -g "$PNG" >/dev/null 2>&1
        status=ok
    else
        rm -f "$PNG.tmp"
        # Keep the old picture; mark the bottom line so a stale screen is obvious.
        eips 32 39 " offline $(date +%H:%M) " >/dev/null 2>&1
    fi
    log "batt=${batt}% chg=${chg:-?} fetch=$status"
    [ "$status" = ok ] && upload_log
    [ "$2" = keepwifi ] || wifi 0
}

# Post our log tail plus powerd/e-ink syslog lines to the server (GET /log there): the
# Kindle is asleep and offline nearly all the time, so it cannot be read directly.
upload_log() {
    {
        tail -n 40 "$LOG" 2>/dev/null
        echo "--- syslog (powerd/eink)"
        grep -e powerd -e eink /var/log/messages 2>/dev/null |
            grep -v -e battLevel -e "Get int" -e "Get string" | tail -n 25
        echo "--- eink power_level: $(cat /proc/eink_fb/power_level 2>/dev/null)"
    } | curl -s -m 5 --data-binary @- "$SERVER/log" >/dev/null 2>&1
}

# Offset of local time from UTC in seconds, from `date +%z` (e.g. +0100 -> 3600).
utc_offset() {
    z=$(date +%z)
    sign=${z%????}
    hh=${z#?}
    hh=${hh%??}
    mm=${z#???}
    off=$(((${hh#0} * 60 + ${mm#0}) * 60))
    [ "$sign" = "-" ] && off=$((-off))
    echo "$off"
}

# Local HH:MM of epoch $1 (BusyBox 1.7.2 date has no -d @epoch).
hhmm() {
    l=$(($1 + $(utc_offset)))
    printf '%02d:%02d' $((l / 3600 % 24)) $((l / 60 % 60))
}

# Is local hour $1 inside QUIET_HOURS ("START-END", may wrap past midnight)?
is_quiet() {
    [ -n "$QUIET_HOURS" ] || return 1
    qs=${QUIET_HOURS%-*}
    qe=${QUIET_HOURS#*-}
    if [ "$qs" -le "$qe" ]; then
        [ "$1" -ge "$qs" ] && [ "$1" -lt "$qe" ]
    else
        [ "$1" -ge "$qs" ] || [ "$1" -lt "$qe" ]
    fi
}

# Epoch of the next clock-aligned wake that is not in quiet hours.
next_wake() {
    now=$(date +%s)
    off=$(utc_offset)
    t=$((now - now % INTERVAL + INTERVAL))
    # Reason: too close to the boundary, the next slot would fire before we sleep.
    [ $((t - now)) -lt 60 ] && t=$((t + INTERVAL))
    guard=0
    while is_quiet $((((t + off) / 3600) % 24)) && [ "$guard" -lt 48 ]; do
        t=$((t + INTERVAL))
        guard=$((guard + 1))
    done
    echo "$t"
}

# Set the RTC alarm for epoch $1 (the sysfs value is relative: seconds from now).
arm_rtc() {
    secs=$(($1 - $(date +%s)))
    [ "$secs" -lt 1 ] && secs=1
    echo 0 >"$RTC_WAKE" 2>/dev/null
    echo "$secs" >"$RTC_WAKE" 2>/dev/null
}

suspend_until() {
    if [ "$DEBUG" = 1 ]; then
        secs=$(($1 - $(date +%s)))
        [ "$secs" -gt 0 ] && sleep "$secs"
        return
    fi
    if arm_rtc "$1"; then
        sync
        echo mem >/sys/power/state
    else
        log "cannot arm RTC; staying awake"
        sleep "$secs"
    fi
}

# Download pages 2..N (page 1 comes from refresh) for browsing with the page keys.
fetch_pages() {
    n=$(curl -s -f -m 5 "$SERVER/pages" 2>/dev/null | tr -dc '0-9')
    [ -n "$n" ] || n=1
    i=2
    while [ "$i" -le "$n" ]; do
        curl -s -f -m 15 -o "$WORK/page$i.png.tmp" "$SERVER/page/$i.png" 2>/dev/null &&
            mv "$WORK/page$i.png.tmp" "$WORK/page$i.png"
        i=$((i + 1))
    done
    # Drop pages left over from a longer list.
    while [ -f "$WORK/page$i.png" ]; do
        rm -f "$WORK/page$i.png"
        i=$((i + 1))
    done
    echo "$n" >"$WORK/pages"
}

show_page() {
    if [ "$1" -eq 1 ]; then f=$PNG; else f=$WORK/page$1.png; fi
    [ -s "$f" ] && eips -f -g "$f" >/dev/null 2>&1
}

# Append the code of every key press on input device $1 to $KEYS.
# Reason: one long-lived fd, so events arriving in a batch (scan code + key) are not
# lost between reads, as they would be if the device were reopened per event.
key_reader() {
    kdev=$1
    kev=$WORK/ev.${kdev##*/}
    exec 3<"$kdev" || return
    while dd bs=16 count=1 <&3 >"$kev" 2>/dev/null && [ -s "$kev" ]; do
        # struct input_event (32-bit kernel): sec, usec, type | code << 16, value
        # shellcheck disable=SC2046 # splitting hexdump's four numbers is intended
        set -- $(hexdump -v -e '4/4 "%u " "\n"' "$kev")
        [ $# -eq 4 ] || continue
        [ $(($3 & 65535)) -eq 1 ] && [ "$4" -eq 1 ] && echo $(($3 >> 16)) >>"$KEYS"
    done
}

start_key_readers() {
    : >"$KEYS"
    seen=0
    readers=""
    for dev in /dev/input/event0 /dev/input/event1; do
        key_reader "$dev" &
        readers="$readers $!"
    done
}

stop_key_readers() {
    # shellcheck disable=SC2086 # word splitting of the pid list is intended
    kill $readers 2>/dev/null
    # Reason: a reader's dd stays blocked on the device after its shell is killed.
    killall dd 2>/dev/null
    wait 2>/dev/null
}

# Wait up to $1 seconds for the next key press; sets KEY. Returns 1 on timeout.
next_key() {
    deadline=$(($(date +%s) + $1))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        if [ "$(grep -c . "$KEYS" 2>/dev/null)" -gt "$seen" ]; then
            seen=$((seen + 1))
            KEY=$(sed -n "${seen}p" "$KEYS")
            return 0
        fi
        usleep 200000 2>/dev/null || sleep 1
    done
    return 1
}

# Browse the downloaded pages until idle for BROWSE_IDLE seconds or Back (returns 0),
# or HOME (returns 1: exit to the Kindle UI). Kindle 4 key codes (KOReader's map):
# next page 104/191, previous page 193/109, 5-way 103/105/106/108, Home 102, Back 158.
browse() {
    pages=$(cat "$WORK/pages" 2>/dev/null)
    [ -n "$pages" ] || pages=1
    page=1
    rc=0
    start_key_readers
    while next_key "$BROWSE_IDLE"; do
        case "$KEY" in
        104 | 191 | 106 | 108) page=$((page % pages + 1)) ;;
        193 | 109 | 105 | 103) page=$(((page + pages - 2) % pages + 1)) ;;
        102)
            rc=1
            break
            ;;
        158) break ;;
        *) continue ;;
        esac
        show_page "$page"
    done
    stop_key_readers
    [ "$rc" -eq 0 ] && show_page1_after_nap "browse end"
    return $rc
}

# Show page 1 via a 2-second RTC nap. Reason: after ~60 s awake and idle, the e-ink
# controller's next full update comes out inverted and washed out, while a draw right
# after resume (as on every hourly wake) is always clean. $1 = log tag.
show_page1_after_nap() {
    log "$1: eink=$(cat /proc/eink_fb/power_level 2>/dev/null), napping before redraw"
    [ "$DEBUG" = 1 ] || suspend_until $(($(date +%s) + 2))
    show_page 1
}

restore_kindle() {
    killall -CONT volumd 2>/dev/null
    lipc-set-prop com.lab126.powerd preventScreenSaver 0 2>/dev/null
    wifi 1
    rm -f "$PIDFILE"
    eips -c >/dev/null 2>&1
    /etc/init.d/framework start
}

start_dashboard() {
    echo $$ >"$PIDFILE"
    log "start (interval=${INTERVAL}s quiet=${QUIET_HOURS:-none})"
    /etc/init.d/framework stop
    # Reason: a paused volumd cannot switch to USB storage and unmount /mnt/us on charge.
    killall -STOP volumd 2>/dev/null
    lipc-set-prop com.lab126.powerd preventScreenSaver 1 2>/dev/null
    gov=/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
    [ -w "$gov" ] && echo powersave >"$gov"
    trap 'restore_kindle; exit 0' TERM INT
}

# Tests source this file with DASH_LIB=1 to get the functions without running the loop.
# shellcheck disable=SC2317
[ "${DASH_LIB:-0}" = 1 ] && return 0

if [ "$1" = once ]; then
    refresh "" keepwifi
    exit 0
fi

start_dashboard
while true; do
    woke=$(date +%s)
    wake_at=$(next_wake)
    refresh "$wake_at"
    log "awake $(($(date +%s) - woke))s, next wake $(hhmm "$wake_at")"
    # Early-wake loop: a power-button press wakes us before the alarm.
    while true; do
        suspend_until "$wake_at"
        [ "$(date +%s)" -ge $((wake_at - 30)) ] && break
        # Power button: refresh all pages freshly rendered, then browse them locally.
        log "early wake: manual refresh"
        # Reason: keep the schedule even if something suspends us while browsing.
        arm_rtc "$wake_at"
        eips 0 39 " Refreshing...                                   " >/dev/null 2>&1
        refresh "$wake_at" keepwifi fresh
        fetch_pages
        wifi 0
        if ! browse; then
            log "exit by HOME"
            restore_kindle
            exit 0
        fi
    done
done

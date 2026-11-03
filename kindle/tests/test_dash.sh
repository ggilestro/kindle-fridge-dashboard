#!/bin/sh
# shellcheck disable=SC2034  # variables are read by the sourced dash.sh
# Unit tests for dash.sh time logic. Run on the Kindle (BusyBox ash) or any POSIX sh:
#   sh test_dash.sh /path/to/dash.sh
# date is stubbed so results do not depend on the real clock.
DASH=${1:-/tmp/fridgedash/dash.sh}
fails=0

check() {
    if [ "$2" = "$3" ]; then
        echo "ok   $1"
    else
        echo "FAIL $1: got '$2' want '$3'"
        fails=$((fails + 1))
    fi
}

# Stub: FAKE_NOW (epoch, UTC) and FAKE_Z (+HHMM) drive `date +%s` / `date +%z`.
date() {
    case "$1" in
    +%s) echo "$FAKE_NOW" ;;
    +%z) echo "$FAKE_Z" ;;
    *) command date "$@" ;;
    esac
}

DASH_LIB=1
DASH_HERE=$(dirname "$DASH")
# shellcheck source=/dev/null
. "$DASH"
LOG=/dev/null
INTERVAL=3600

# 2026-11-01 17:05:00 UTC = 1793552700; winter: GMT (+0000)
FAKE_NOW=1793552700
FAKE_Z=+0000
QUIET_HOURS="23-6"
check "next wake is top of next hour" "$(next_wake)" 1793556000
check "hhmm of that wake" "$(hhmm 1793556000)" "18:00"

# 22:30 UTC -> next slot 23:00 is quiet, so skip to 06:00 next day.
FAKE_NOW=1793572200
check "quiet hours skip the night" "$(hhmm "$(next_wake)")" "06:00"

QUIET_HOURS=""
check "no quiet hours -> 23:00" "$(hhmm "$(next_wake)")" "23:00"

# Too close to the boundary (30 s before 18:00) -> skip to 19:00.
FAKE_NOW=1793555970
check "boundary guard" "$(hhmm "$(next_wake)")" "19:00"

# Summer time: offset +0100 shifts local hours.
FAKE_Z=+0100
QUIET_HOURS="23-6"
check "utc_offset +0100" "$(utc_offset)" 3600
FAKE_NOW=1793568600 # 21:30 UTC = 22:30 local -> 23:00 local is quiet -> 06:00 local
check "quiet hours in BST" "$(hhmm "$(next_wake)")" "06:00"
FAKE_Z=-0130
check "negative offset" "$(utc_offset)" -5400

check "is_quiet 23 in 23-6" "$(is_quiet 23 && echo y || echo n)" y
check "is_quiet 5 in 23-6" "$(is_quiet 5 && echo y || echo n)" y
check "is_quiet 6 in 23-6" "$(is_quiet 6 && echo y || echo n)" n
QUIET_HOURS="1-3"
check "is_quiet 2 in 1-3 (no wrap)" "$(is_quiet 2 && echo y || echo n)" y
check "is_quiet 3 in 1-3 (no wrap)" "$(is_quiet 3 && echo y || echo n)" n

# ---- key reader: decode raw input_event records (little-endian, 16 bytes each)
WORK=$(mktemp -d /tmp/dashtest.XXXXXX)
KEYS=$WORK/keys
# ev TYPE CODE VALUE -> one 16-byte record (sec=1, usec=2)
ev() {
    # shellcheck disable=SC2059 # the format is built from octal escapes on purpose
    printf "\001\000\000\000\002\000\000\000\\$(printf %03o "$1")\000\\$(printf %03o "$2")\000\\$(printf %03o "$3")\000\000\000"
}
{
    ev 4 4 104   # EV_MSC scan code: ignored
    ev 1 104 1   # next page pressed
    ev 0 0 0     # EV_SYN
    ev 1 104 0   # released: ignored
    ev 1 102 1   # Home pressed
} >"$WORK/events"
: >"$KEYS"
key_reader "$WORK/events"
check "key_reader keeps presses only" "$(tr '\n' ' ' <"$KEYS")" "104 102 "

# ---- browse: page wrap-around, Back and Home (readers and display stubbed)
start_key_readers() { seen=0; }
stop_key_readers() { :; }
show_page() { shown="$shown $1"; }
show_page1_after_nap() { show_page 1; }
usleep() { :; }
BROWSE_IDLE=1
echo 3 >"$WORK/pages"
printf '104\n104\n104\n109\n158\n' >"$KEYS"
shown=""
browse
check "browse next/next/wrap/prev then Back" "$shown" " 2 3 1 3 1"
printf '191\n102\n' >"$KEYS"
shown=""
browse
check "browse Home returns 1, no redraw" "$? $shown" "1  2"
rm -rf "$WORK"

echo "failures: $fails"
[ "$fails" -eq 0 ]

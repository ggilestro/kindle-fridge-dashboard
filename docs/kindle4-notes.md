# Kindle 4 Non-Touch: device notes

These are facts about the Kindle 4 Non-Touch (D01100, firmware 4.1.4, kernel
2.6.31-rt11-lab126), all checked over SSH on the device. They are what `dash.sh` is
built on, and they should help anyone scripting this model.

## Shell and tools

- **BusyBox 1.7.2.** It has no `setsid`, `nohup`, `od` or `grep -E`, `date -d @epoch`
  does not work, and `wget` has no timeout option.
  - `curl` 7.21.4 (`/usr/bin/curl`) is there. Plain HTTP works; with OpenSSL 0.9.8,
    modern HTTPS does not.
  - Detach a process with `/sbin/start-stop-daemon -S -b`.
  - `hexdump -v -e '4/4 "%u " "\n"'` works, and so does `usleep`.
- **PATH.** SSH sessions get only `/usr/bin:/bin`. `eips` and `iptables` live in
  `/usr/sbin`.
- **Init** is SysV: `/etc/init.d/framework` (rc5.d `S95framework`) runs the Kindle UI,
  and USBNetwork starts at `S82usbnet`. The root filesystem is read-only; `mntroot rw`
  and `mntroot ro` toggle it.

## Power and display

- **Suspend to RAM.** `/sys/power/state` offers `standby mem`.
  - **RTC wake:** write the delay in seconds (relative, not an epoch) to
    `/sys/devices/platform/mxc_rtc.0/wakeup_enable`, then `echo mem > /sys/power/state`.
  - In a test, a 20 s alarm woke the Kindle after 21 s, and WiFi was `CONNECTED` again
    within 15 s.
- **The power button and powerd.** While `lipc-set-prop com.lab126.powerd
  preventScreenSaver 1` is set, powerd **ignores** the power button. Syslog says
  "Prevent screen saver set. Ignoring power button". The button still wakes the
  hardware from suspend-to-RAM, so a script can treat an early wake as a button press.
  powerd also has the properties `wakeUp`, `rtcWakeup`, `deferSuspend` and `state`.
- **Drawing.** `eips -f -g file.png` shows an 8-bit grayscale 600×800 PNG with a full
  refresh. `eips COL ROW "text"` writes text on a 50×40 character grid.
- **E-ink after idle.** A full update after about 60 s awake and idle comes out
  inverted, ghosted and low in contrast. Draws right after a resume are always clean,
  so `dash.sh` takes a 2-second RTC nap before its final redraw
  (`show_page1_after_nap`). `/proc/eink_fb/power_level` reads e.g. `0 (on)` or
  `2 (standby)`.
- **CPU governors:** conservative, ondemand (the default), userspace, powersave and
  performance.
- **Battery.** `gasgauge-info -c` prints e.g. `100%`;
  `lipc-get-prop com.lab126.powerd isCharging` gives 0 or 1.

## Network

- **WiFi.** `lipc-get-prop com.lab126.wifid cmState` gives e.g. `CONNECTED`. To toggle
  WiFi, set `com.lab126.cmd wirelessEnable` and `com.lab126.wifid enable`, in that
  order to switch on and the reverse order to switch off. KOReader uses the same
  sequence.
- **Firewall.** The Kindle drops ICMP and every incoming port except 22 (which
  USBNetwork opens with `K3_WIFI=true`). An nmap scan showing "all filtered" does not
  mean the Kindle is offline.
- **The IP changes** with DHCP. Look it up by MAC address in your router, or reserve
  one there.
- **USB networking** (USBNetwork's RNDIS/CDC-ECM gadget) never came up on the Kindle
  side on this unit: the host saw the gadget, but the link had no carrier. Use SSH over
  WiFi (`K3_WIFI_SSHD_ONLY="true"`).

## Input

- **Devices:** `event0` is the keypad (`tequila-keypad`), `event1` the 5-way pad
  (`fiveway`), `event2` the volume keys.
- **Key codes** (the same map KOReader uses):

  | Key | Code(s) |
  |---|---|
  | Next page (the keys on both sides) | 104, 191 |
  | Previous page (the keys on both sides) | 193, 109 |
  | 5-way up, left, right, down | 103, 105, 106, 108 |
  | Home | 102 |
  | Back | 158 |

- **Reading events.** Each event is 16 bytes: `sec, usec, type | code << 16, value`, as
  32-bit little-endian words. `hexdump -v -e '4/4 "%u " "\n"'` decodes it. Keep one
  file descriptor open per device: reopening the device for each event loses events
  that arrive in a batch.
- **The page keys don't wake** a suspended Kindle 4; only the power button does.

## KUAL

- **Expired keystore.** KUAL stopped working in April 2025, when the jailbreak's
  developer keystore expired. It runs again with NiLuJe's renewed keystore (DevCerts
  20250419) plus the KUAL 2.7.37 kindlet of the same date.
- **"User interface call took longer than 5000ms".** This appears when KUAL is opened
  too soon after the UI restarts. A retry works.

# Kindle

The Kindle side is a handful of BusyBox shell scripts launched from KUAL. They need no
extra binaries: everything they use (`curl`, `eips`, `lipc-*`, `gasgauge-info`) ships
with the stock firmware.

Tested on a Kindle 4 Non-Touch (D01100) with firmware 4.1.4. Other Kindle 4 models
should behave the same. Later models have other input devices, key codes and RTC paths
(see [kindle4-notes.md](kindle4-notes.md)).

## What it does

```
every hour (clock-aligned), outside quiet hours:
  RTC alarm wakes the Kindle from suspend-to-RAM
  → WiFi on → GET /dash.png?batt=..&chg=..&next=.. → eips (full refresh)
  → upload log tail to the server → WiFi off
  → arm the RTC alarm for the next slot → suspend to RAM
```

A wake takes about 15 s, nearly all of it rejoining WiFi. Between wakes the CPU is off
and the e-ink panel keeps the picture without power. If the server can't be reached,
the old picture stays and the bottom line shows ` offline HH:MM `.

While the dashboard runs, the normal Kindle UI (the "framework") is stopped and the
screensaver is disabled. `volumd` is paused, so plugging in a charger or a computer does
not switch to USB-drive mode.

## Prerequisites

1. **Jailbreak, KUAL and USBNetwork.** All three are in NiLuJe's
   [snapshots thread](https://www.mobileread.com/forums/showthread.php?t=225030)
   on MobileRead. For KUAL itself, see the
   [KUAL thread](https://www.mobileread.com/forums/showthread.php?t=203326).
   - On a Kindle 4 jailbroken before April 2025, KUAL now fails with "permissions to
     open this item have expired". See [Recovery](#recovery).
2. **WiFi.** Connect the Kindle to your network from the normal UI.
3. **SSH over WiFi** (recommended, for debugging and autostart):
   - In `usbnet/etc/config` on the USB drive, set `K3_WIFI="true"` and
     `K3_WIFI_SSHD_ONLY="true"`. The USB port then stays a normal USB drive, and SSH
     listens on WiFi.
   - Put your public key in `usbnet/etc/authorized_keys`.
   - Create an empty file `usbnet/auto` to start it at boot.
   - Log in with `ssh root@<kindle-ip>`. The Kindle's firewall drops ping and every
     port except 22, so a scan that finds nothing does not mean it is off the network.

## Install

1. Connect the Kindle to a computer as a USB drive and copy:
   - `kindle/fridgedash/` to `fridgedash/` at the root of the drive (`/mnt/us/fridgedash/`
     on the device);
   - `kindle/extensions/fridgedash/` to `extensions/fridgedash/`.
2. Edit `fridgedash/config.sh` (see [Configuration](#configuration)). At least set
   `SERVER`.
3. Eject the drive. Open KUAL → **Fridge dashboard** → **Test: show dashboard once**.
   The dashboard should appear within a few seconds; the Kindle UI stays running.
4. KUAL → **Fridge dashboard** → **Start dashboard (hourly, low power)**. The Kindle UI
   stops and the hourly loop begins.

### Start at boot (optional)

Starting at boot needs a hook in the root filesystem, installed once over SSH:

```sh
sh /mnt/us/fridgedash/autostart.sh install
```

This installs `/etc/init.d/fridgedash` (plus `/etc/rc5.d/S99fridgedash`) and creates
the flag file `/mnt/us/fridgedash/AUTOSTART`. At boot, the hook waits 3 minutes for the
Kindle UI to finish starting, then starts the dashboard if the flag file exists.

- KUAL's **Start automatically at boot** / **Don't start at boot** items only create or
  delete the flag file.
- `autostart.sh remove` takes the hook out again.
- If a **computer** is connected at boot, the Kindle enters USB-drive mode, `/mnt/us`
  is not available, and the dashboard does not start. A wall charger is fine.

## Configuration

`fridgedash/config.sh` on the device:

| Setting | Default | Meaning |
|---|---|---|
| `SERVER` | `http://192.168.68.124:8090` | Dashboard server. Use plain HTTP: the Kindle 4's TLS is too old for modern HTTPS. |
| `INTERVAL` | `3600` | Seconds between refreshes, aligned to the clock (3600 = on the hour) |
| `QUIET_HOURS` | `"23-6"` | Local hours with no refresh, as `START-END` (it may wrap past midnight). `""` refreshes around the clock. |
| `TZ` | UK (`GMT0BST,…`) | POSIX timezone string used for quiet hours and log times |
| `NET_TIMEOUT` | `45` | Seconds to wait for WiFi and the server before giving up on a refresh |
| `BROWSE_IDLE` | `60` | Seconds without a key press before browsing ends (see below) |

Changes take effect the next time the dashboard starts.

## Using it

The page keys cannot wake a sleeping Kindle 4; only the power button can. A short
press of the power button:

1. shows "Refreshing..." at the bottom;
2. asks the server for a fresh render, then downloads every page (about 15 s), and
   turns WiFi off again;
3. waits for keys:
   - **Next / previous page** (either side) or the **5-way pad**: flip through the
     pages, wrapping around;
   - **Back**: return to page 1 and sleep;
   - **HOME**: leave the dashboard and restart the normal Kindle UI (this takes about
     2½ minutes);
   - **no key for `BROWSE_IDLE` seconds**: return to page 1 and sleep.

The hourly schedule is kept throughout.

## Stopping and updating

- **To the normal Kindle UI:** press power, then HOME. Over SSH:
  `sh /mnt/us/fridgedash/stop.sh`.
- **Updating the scripts:**
  - Over USB: return to the Kindle UI first, so that USB-drive mode works.
  - Over SSH: connect while the Kindle is awake (press power first), e.g.
    `ssh root@<ip> 'cat > /mnt/us/fridgedash/dash.sh' < kindle/fridgedash/dash.sh`.
  - Either way, the running loop is a copy in `/tmp/fridgedash/`, so the new scripts are
    used from the next start.
- **The Kindle's IP address:** the server records it at every check-in:
  `curl http://<server>:8090/status` (`ip`).

## Logs

- `/mnt/us/fridgedash/dash.log` on the device logs every wake: battery, charging and
  fetch result, then the seconds awake and the next wake time. Starts, power-button
  wakes and the end of browsing are logged too.
- After every successful check-in the Kindle uploads the log's tail, plus its
  powerd/e-ink syslog lines, to the server: `curl http://<server>:8090/log`.
  Since the Kindle is reachable only seconds per hour, this is the practical way to
  read it.
- The server's `data/battery.csv` has one row per check-in, for measuring battery
  drain.

## Tests

```sh
sh kindle/tests/test_dash.sh kindle/fridgedash/dash.sh      # also runs on the device
shellcheck -s sh -x kindle/fridgedash/*.sh
```

The tests cover quiet hours, clock-aligned wake times (including summer time and the
guard near the hour boundary), key-event decoding and page browsing. `date` is stubbed,
so they do not depend on the real clock.

## Recovery

- **KUAL: "permissions to open this item have expired".** The jailbreak's developer
  keystore expired in April 2025. Install NiLuJe's renewed keystore (DevCerts
  20250419; on firmware 4.1.4 via `Update_mkk-20250419-k4-ALL_keystore-install.bin`,
  or by copying `developer.keystore` to `/var/local/java/keystore/` over SSH), plus the
  20250419 build of KUAL (`KUAL-KDK-1.0.azw2` in `documents/`). Both are in the
  snapshots thread.
- **KUAL: "User interface call took longer than 5000ms".** The UI is still busy after a
  restart. Wait a minute and try again.
- **No way in.** Hold power for about 20 s to restart the Kindle. If the dashboard
  autostarts, you have 3 minutes after boot to use KUAL, or connect a computer at boot
  and delete `fridgedash/AUTOSTART` from the USB drive.
- **USBNetwork over USB.** On this unit, USB networking never came up on the Kindle
  side, which is why SSH runs over WiFi. Before changing USBNetwork settings, check
  that you still have another way in. The firmware's own toggle (type `;debugOn`, then
  `~usbNetwork`, in the search box) is a last resort.

# Lessons

_Patterns and corrections captured during work on this project._

## 2026-11-01 — Don't give up the USB-storage path before a shell is proven
- I renamed `usbnet/DISABLED_auto` → `auto` (USBNetwork at boot) to get around the broken KUAL.
  On this K4 the USB link never came up on the Kindle side: the host saw the gadget
  (0525:a4a2), but there was no carrier in CDC-ECM and only TX errors in RNDIS. Meanwhile,
  USB mass storage was gone.
- **Rule:** before any change that removes a recovery path (USB storage, framework, KUAL),
  prove the replacement access path works end to end first, e.g. SSH over WiFi with the
  Kindle still in USBMS mode (`K3_WIFI_SSHD_ONLY`).
- **Recovery options if it happens again:**
  - SSH over WiFi (dropbear still starts at boot with `K3_WIFI=true`).
  - The Kindle's built-in debug toggle: type `;debugOn`, then `~usbNetwork`, in the search box.
- Kindle 4 KUAL "permissions to open this item have expired" = the developer keystore
  expired in April 2025. The fix is NiLuJe's `Update_mkk-20250419-k4-ALL_keystore-install.bin`,
  which needs firmware 4.1.4.

## 2026-11-01 — Kindle 4 power button, e-ink after idle, moving IPs
- With `preventScreenSaver=1`, powerd **ignores** the power button (syslog: "Prevent screen
  saver set. Ignoring power button"). My first theory, that powerd caused the inverted
  redraw, was wrong. I should have read the syslog before building a workaround.
- A full `eips -f -g` after about 60 s awake and idle comes out inverted and low-contrast.
  Draws straight after a resume, or seconds after another draw, are always clean.
  Fix: a 2-second RTC nap before the final redraw.
- The Kindle's DHCP address changed (.100 → .101) and a Meross plug took .100, so watchers
  pointed at a fixed IP silently waited on the wrong host. Resolve the IP by MAC (ARP) or
  from the server's check-in record, and pin the host key with `HostKeyAlias=fridge-kindle`
  (the user's known_hosts had another device's key for .101).
- The Kindle is reachable only seconds per hour: make it upload its own log (POST /log)
  instead of racing wake windows over SSH.

## 2026-11-03 — `docker compose config` prints secrets
- To check one interpolated value, I ran `docker compose config` on the live stack. It prints
  the fully resolved service, **including every variable from `env_file`**, so the HA token
  ended up in the session transcript and had to be rotated.
- **Rule:** never run `docker compose config` (or `docker inspect`, `printenv`, `env`) on a
  stack with secrets in its environment. Check one value with
  `docker exec <c> printenv NAME` for a known non-secret NAME, or grep keys only
  (`grep -o '^[A-Z_]*=' .env`).

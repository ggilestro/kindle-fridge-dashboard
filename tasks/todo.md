# TODO

## Open

- [ ] Measure battery drain from `battery.csv` over several days and report days per
      charge. So far: 97% on 2026-11-01 20:03, 96% on 2026-11-03 12:00, with hourly wakes
      and quiet hours.
- [ ] Verify the e-ink nap fix on hardware: press power, browse, wait 60 s; page 1 should
      come back clean (log line "browse end: eink=…, napping before redraw").
- [ ] Test autostart with a real reboot (Menu → Settings → Menu → Restart): the dashboard
      should start about 3 minutes after the home screen.
- [ ] Router DHCP reservation for the Kindle (the address moved from .100 to .101).

## Done

### 2026-11-01: Kindle 4 fridge dashboard
- [x] Device bring-up over SSH (facts in `docs/kindle4-notes.md`).
- [x] Server: config, sources (HA + iCal), render (HTML → Chromium → 16-gray PNG),
      FastAPI app, pytest suite, Docker deploy with Watchtower disabled.
- [x] Kindle loop: RTC suspend tested unattended, escape hatch, hourly via KUAL, boot
      autostart hook; shell unit tests pass on the device's BusyBox 1.7.2.
- [x] KUAL fixed: renewed developer keystore (DevCerts 20250419) and KUAL 20250419.
- [x] USB networking never came up on the Kindle side, so SSH now runs over WiFi only
      (`K3_WIFI_SSHD_ONLY`).
- [x] HA integration: `/status` endpoint and the `ha/fridge_kindle.yaml` package.
- [x] Power button: fresh render, plus a server render 20 s before each announced wake
      (confirmed live: rendered 19:59:42, fetched 20:00:11).
- [x] Layout v2: compact weather, bins strip, multi-page render, `/pages` and
      `/page/N.png`.
- [x] Browse mode (page keys, Back, HOME) verified on hardware.
- [x] Log upload (`POST /log`), so the Kindle's log can be read without SSH.

### 2026-11-03
- [x] Agenda covers two weeks: `AGENDA_DAYS` 6 → 14, page-1 budget 14 → 17 lines,
      checked visually in the worst case.
- [x] Repo cleanup for publishing:
  - docs split into `docs/` (server, Kindle, HA, device notes) with screenshots made
    from the fixtures;
  - `scripts/preview.py` and `scripts/deploy-server.sh`;
  - MIT license; serial number and MAC removed;
  - pushed to GitHub as `ggilestro/kindle-fridge-dashboard`.

## Review (2026-11-03)
- 46 server tests and 16 shell tests pass; shellcheck and black are clean.
- The live server renders real data with no errors, and the Kindle has checked in
  hourly since 2026-11-01 (one failed fetch on 2026-11-02 12:00, fine on the next wake).

## Potential Agents

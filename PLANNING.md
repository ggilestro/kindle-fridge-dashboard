# Planning

An old Kindle 4 Non-Touch (D01100) on the fridge shows a household dashboard, refreshed
once an hour. Between refreshes the Kindle is suspended to RAM, so it draws almost no
power, and the e-ink panel holds the last image without power. User documentation is in
`README.md` and `docs/`; this file covers architecture, conventions and constraints.

## Architecture

- **server/** (Python, Docker Compose on a LAN host, port 8090)
  - A background loop collects data from Home Assistant (REST API, including
    `?return_response` services) and iCal feeds.
  - It fills a Jinja2 template with page 1 plus the shopping pages, and takes one
    Chromium screenshot of the stacked pages.
  - The screenshot is cut into `page1..N.png` at 600×800 and snapped to 16 gray levels.
  - Renders run every `RENDER_INTERVAL_S`, plus one 20 s before the Kindle's announced
    wake.
  - FastAPI serves the pages, `/status` (Kindle check-ins, for HA) and `/log` (log
    uploads from the Kindle).
  - All configuration comes from `.env`, via python-dotenv and pydantic.
- **kindle/** (BusyBox `ash` on firmware 4.1.4, launched from KUAL or a boot hook)
  - `dash.sh` runs from a copy in `/tmp`, with the framework stopped and `volumd`
    paused.
  - Each hour: RTC wake → WiFi on → fetch page 1 (reporting battery, charging and the
    next wake) → `eips` → upload log → WiFi off → arm RTC → `echo mem >
    /sys/power/state`.
  - An early wake is a power-button press: fresh render, fetch all pages, browse with
    the page keys; HOME exits to the Kindle UI.
- **ha/**: a Home Assistant package with REST sensors on `/status`, plus an image
  entity.

## Conventions

- Python 3.14 in Docker (python:3.14-slim plus Debian chromium). Tests run with pytest
  in the project `.venv`. Format with `black`; Google-style docstrings; type hints;
  files under 500 lines.
- Each data source fails soft: an unavailable value renders as "—" or a placeholder
  and never breaks the render. Failed sources are listed in `/status` and in the footer
  (unless the low-battery banner replaces it).
- Page-1 capacity is a line budget in `render.py` (`AGENDA_LINES`, `SHOP_PAGE1`). It is
  tuned visually for the worst case, with the low-battery banner shown and a two-line
  bins strip.
- Shell scripts target BusyBox 1.7.2, pass `shellcheck -s sh`, and have unit tests in
  `kindle/tests/` that run on the host and on the device.
- The Kindle is reachable only seconds per hour. It reports to the server (check-ins,
  log upload) instead of being polled.

## Device facts

See `docs/kindle4-notes.md`. Highlights that shape the design:

- **Power button:** powerd ignores it while `preventScreenSaver=1`. The button still
  wakes the Kindle from suspend.
- **E-ink:** a full `eips` update after about 60 s awake and idle is corrupted, so
  redraw right after a (2 s RTC) resume.
- **Network:** the DHCP address moves, so the server records the Kindle's IP at each
  check-in.

## Deployment (author's setup)

- **Server:** `homelab` (ssh alias), compose stack in `~/Dockers/basic/kindle-dash/`,
  updated with `scripts/deploy-server.sh`. Watchtower runs there, so the container is
  labelled `com.centurylinklabs.watchtower.enable=false`.
- **Home Assistant:** `http://192.168.68.124:8123`. The package lives in
  `<config>/packages/`.
- **Kindle SSH:** `root@<ip>` with key authentication (dropbear from USBNetwork
  0.57.N), over WiFi only. Get the IP from `GET /status`.

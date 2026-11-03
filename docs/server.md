# Server

The server collects the data, renders the dashboard pages and serves them to the Kindle
as ready-to-display PNGs. It is a small FastAPI app with headless Chromium, packaged
with Docker Compose.

## How a render works

1. **Collect.** The server fetches four things:
   - **Weather.** Current conditions come from the weather entity's state. The forecasts
     come from the `weather.get_forecasts` service, hourly and daily.
   - **Shopping list.** Items still to buy, via `todo.get_items`.
   - **Sensors and bins.** Read from `/api/states`.
   - **Calendar.** Events from every iCal feed in `ICAL_URLS`, between today's midnight
     and `AGENDA_DAYS` later. Recurring and all-day events are expanded and converted
     to `TZ`.

   A source that fails is left empty: its panel shows a placeholder ("List
   unavailable", "—"), the footer names it after a ⚠ (unless the low-battery banner
   has replaced the footer), and `/status` lists it in `render_errors`. A broken source
   never stops the render.
2. **Lay out.** `templates/dashboard.html` is filled in. Page 1 is the dashboard.
   Pages 2..N are the full shopping list, in two columns with 44 items per page, up to
   4 shopping pages. Page 2 always exists, and says "Nothing to buy" when the list is
   empty.
3. **Screenshot.** Chromium takes one screenshot of all the pages stacked vertically.
   It is cut into `page1.png` … `pageN.png`, each 600×800, converted to grayscale and
   snapped to 16 gray levels (the Kindle 4 panel's depth). Text stays crisp because no
   dithering is applied.

Renders run every `RENDER_INTERVAL_S` seconds. Another render runs 20 s before the
Kindle's next announced wake, so it always fetches a dashboard made seconds earlier.

## Install

You need a Linux host with Docker Compose on the same network as the Kindle. The Kindle
fetches over plain HTTP: its TLS stack is too old for modern HTTPS.

On the host, in `server/` (from a `git clone`, or a copy of the folder):

1. Create `.env` next to `docker-compose.yml`, starting from `.env.example`:
   - `HA_URL` and `HA_TOKEN`: create the token in Home Assistant under **Profile →
     Security → Long-lived access tokens**.
   - `ICAL_URLS`: in Google Calendar, open **Settings → (calendar) → Integrate
     calendar** and copy the **Secret address in iCal format**. Separate several feeds
     with commas. Any other iCal feed works too.
   - Treat both values as passwords: `chmod 600 .env`.
2. `mkdir -p data`. Rendered pages and the Kindle's history persist there. The
   container runs as uid 1000, so if your user has another uid, run
   `sudo chown 1000 data`.
3. `docker compose up -d --build`, then open `http://<host>:8090/` for a live preview,
   or `http://<host>:8090/page/1.png` for the image the Kindle gets.

The image is built locally, and the container is labelled so that Watchtower leaves it
alone.

### Updating

From a checkout on another machine, `scripts/deploy-server.sh` copies `server/` to the
host with rsync, then rebuilds and restarts the container. It never touches `.env` or
`data/` on the host, and it stops before starting the container if `.env` is missing,
so on a first deploy create `.env` there and run the script again.

```bash
scripts/deploy-server.sh -n          # dry run: list what would change
scripts/deploy-server.sh             # copy and rebuild
DEPLOY_HOST=myserver DEPLOY_DIR=docker/fridgedash scripts/deploy-server.sh
```

## Configuration

Every setting is an environment variable, read from `.env`. The entity defaults are the
author's own Home Assistant entity ids, so set the ones you need. `DATA_DIR`,
`CHROMIUM_BIN`, `WIDTH`, `HEIGHT` and `GRAY_LEVELS` can also be set, but the defaults
suit the Docker image and the Kindle 4.

| Variable | Default | Meaning |
|---|---|---|
| `HA_URL` | `http://192.168.68.124:8123` | Home Assistant base URL |
| `HA_TOKEN` | — | Long-lived access token |
| `ICAL_URLS` | — | iCal feeds, comma separated. Empty means the agenda says "No calendar set up". |
| `TZ` | `Europe/London` | IANA timezone for every displayed time |
| `WEATHER_ENTITY` | `weather.forecast_home` | Weather entity (the default Met.no integration's name) |
| `SHOPPING_ENTITY` | `todo.shopping_list` | To-do list shown as the shopping list |
| `ROOM_CLIMATE_ENTITY` | `climate.heater` | Its `current_temperature` is shown as "Inside" |
| `EV_BATTERY_ENTITY`, `EV_RANGE_ENTITY` | `sensor.e_niro_…` | Car battery % and range |
| `VACUUM_ENTITY`, `VACUUM_BATTERY_ENTITY` | `vacuum.robovac`, `sensor.robovac_battery` | Robot vacuum state and battery |
| `BIN_DEVICE_CLASS` | `bin_collection_schedule` | Bin sensors are found by this device class (as set by [UKBinCollectionData](https://github.com/robbrad/UKBinCollectionData)) |
| `BIN_ENTITIES` | — | Alternatively, an explicit comma-separated list of bin sensors |
| `AGENDA_DAYS` | `14` | Calendar window in days, starting today |
| `RENDER_INTERVAL_S` | `600` | Seconds between regular renders |
| `LOW_BATTERY_PCT` | `15` | Below this Kindle battery level a "please charge" banner replaces the footer |

Bin sensors need the next collection date in a `date` or `next_collection` attribute,
as `yyyy-mm-dd` or `dd/mm/yyyy`. The bin name is the friendly name without the "Bins"
prefix and "collection" suffix, with "and" shortened to "&". The sensor strip's labels ("Inside", "e-Niro",
"RoboVac") are written in the template.

## Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /dash.png` | Page 1. It counts as a Kindle check-in when it carries `batt=` (battery %) or `next=` (epoch of the next wake). `chg=0/1` reports charging. `fresh=1` renders before answering, which the power-button refresh uses. |
| `GET /pages` | Number of pages, as plain text |
| `GET /page/N.png` | Page N (1 = dashboard, 2.. = shopping list) |
| `GET /status` | JSON for monitoring: `online`, `battery`, `charging`, `last_seen`, `next_expected`, `ip`, `rendered_at`, `render_errors` |
| `POST /log`, `GET /log` | The Kindle uploads its log tail after each successful fetch (up to 16 KiB is kept); read it here |
| `GET /` | Live HTML preview, built fresh without a screenshot |
| `POST /render` | Render now |
| `GET /healthz` | Liveness check; the Kindle also uses it to test the network |

The Kindle counts as **online** while it keeps to the schedule it announced: until 10
minutes after its announced next wake. Quiet hours count as on schedule. A check-in
that announced no next wake counts for 75 minutes.

## Data files (`data/`)

| File | Content |
|---|---|
| `page1.png` … `pageN.png` | The latest render |
| `kindle.json` | The latest check-in: battery, charging, times and IP |
| `battery.csv` | One row per check-in: `time, battery %, Kindle IP, charging`. Use it to measure battery drain. |
| `kindle.log` | The Kindle's last uploaded log |

## Changing the layout

The page is HTML and CSS in `server/fridgedash/templates/dashboard.html`. It uses the
Atkinson Hyperlegible font and Material Design Icons, both embedded in the page.
`server/fridgedash/render.py` holds the line budgets that decide how much goes on page 1
(`AGENDA_LINES`, `SHOP_PAGE1`, `SHOP_PER_PAGE`). Raising them needs a visual check,
because overflowing panels are clipped.

To see the pages without Home Assistant, render the test fixtures (from the repo root,
with the dev requirements and `chromium` installed):

```bash
python scripts/preview.py /tmp/preview --items 26    # writes page1.png, page2.png, preview.html
```

Look at the result in the worst case too: `--battery 9` shows the low-battery banner,
which takes space from the agenda.

## Tests

From the repo root:

```bash
pip install -r server/requirements-dev.txt
cd server && python -m pytest
```

The tests cover parsing Home Assistant responses (including unavailable entities),
calendar expansion, the layout helpers, the endpoints and check-in tracking. When
`chromium` is installed, one end-to-end render runs as well.

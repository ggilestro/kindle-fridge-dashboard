"""Turn dashboard data into HTML, screenshot it with Chromium, and make a Kindle PNG."""

import base64
import os
import subprocess
import tempfile
import math
from datetime import datetime, time, timedelta
from functools import cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from PIL import Image
from pydantic import BaseModel

from .config import Settings
from .sources import Bin, Event, Forecast, Sensors, Weather

HERE = Path(__file__).parent
STATIC = HERE / "static"

# Layout capacities (tuned visually for 600×800 at the template's font sizes).
# Reason: 17 still fits with the low-battery banner and a two-line bins strip shown.
AGENDA_LINES = 17  # page 1 agenda: day headers + events
SHOP_PAGE1 = 16  # page 1 shopping panel
SHOP_PER_PAGE = 44  # dedicated shopping pages: 2 columns × 22 rows
MAX_SHOP_PAGES = 4

# Home Assistant weather conditions → Material Design Icons (the set HA itself uses).
CONDITION_ICONS = {
    "clear-night": "weather-night",
    "cloudy": "weather-cloudy",
    "exceptional": "alert-circle-outline",
    "fog": "weather-fog",
    "hail": "weather-hail",
    "lightning": "weather-lightning",
    "lightning-rainy": "weather-lightning-rainy",
    "partlycloudy": "weather-partly-cloudy",
    "pouring": "weather-pouring",
    "rainy": "weather-rainy",
    "snowy": "weather-snowy",
    "snowy-rainy": "weather-snowy-rainy",
    "sunny": "weather-sunny",
    "windy": "weather-windy",
    "windy-variant": "weather-windy-variant",
}
CONDITION_LABELS = {
    "clear-night": "Clear",
    "partlycloudy": "Partly cloudy",
    "lightning-rainy": "Thunderstorms",
    "snowy-rainy": "Sleet",
    "windy-variant": "Windy",
    "exceptional": "Severe weather",
}


class DashboardData(BaseModel):
    """Everything the template needs, as collected from the sources."""

    now: datetime
    weather: Weather | None = None
    events: list[Event] | None = None
    shopping: list[str] | None = None
    bins: list[Bin] | None = None
    sensors: Sensors = Sensors()
    kindle_battery: int | None = None
    errors: list[str] = []


@cache
def icon(name: str, css_class: str = "") -> Markup:
    """
    Return an inline SVG icon from the vendored MDI set.

    Args:
        name (str): Icon file name without extension.
        css_class (str): CSS class added to the <svg> element.

    Returns:
        Markup: Safe SVG markup (empty if the icon is missing).
    """
    path = STATIC / "icons" / f"{name}.svg"
    if not path.exists():
        return Markup("")
    svg = path.read_text().replace("<svg ", f'<svg class="{css_class}" ', 1)
    return Markup(svg)


def condition_icon(condition: str | None, when: datetime | None = None) -> str:
    """
    Pick the icon name for an HA weather condition, using night variants after dark.

    Args:
        condition (str | None): HA condition string.
        when (datetime | None): Slot time, used to choose a night icon.

    Returns:
        str: Icon name.
    """
    name = CONDITION_ICONS.get(condition or "", "alert-circle-outline")
    is_night = when is not None and (when.hour < 7 or when.hour >= 19)
    if is_night and condition == "partlycloudy":
        return "weather-night-partly-cloudy"
    if is_night and condition == "sunny":
        return "weather-night"
    return name


def condition_label(condition: str | None) -> str:
    """
    Human-readable label for an HA weather condition.

    Args:
        condition (str | None): HA condition string.

    Returns:
        str: Label such as "Partly cloudy".
    """
    if not condition:
        return "—"
    return CONDITION_LABELS.get(condition, condition.replace("-", " ").capitalize())


def day_label(day: datetime, now: datetime) -> str:
    """
    Label a day relative to now: "Today", "Tomorrow" or "Tue 3 Nov".

    Args:
        day (datetime): Any time on the day to label.
        now (datetime): Current time.

    Returns:
        str: Day label.
    """
    delta = (day.date() - now.date()).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    return f"{day:%a} {day.day} {day:%b}"


def build_agenda(
    events: list[Event], now: datetime, max_lines: int
) -> tuple[list[dict], int]:
    """
    Group upcoming events by day within a line budget (day headers count as lines).

    Args:
        events (list[Event]): Events sorted by start.
        now (datetime): Current time; events that already ended are skipped.
        max_lines (int): Maximum number of lines the panel can show.

    Returns:
        tuple[list[dict], int]: Day groups ``{"label", "events": [{"time", "title"}]}``
        and the number of events that did not fit.
    """
    upcoming = [e for e in events if e.end > now]
    groups: list[dict] = []
    lines = shown = 0
    for event in upcoming:
        # Reason: an all-day event that started earlier is shown under today.
        start = max(event.start, now) if event.all_day else event.start
        label = day_label(start, now)
        new_group = not groups or groups[-1]["label"] != label
        if lines + (2 if new_group else 1) > max_lines:
            break
        if new_group:
            groups.append({"label": label, "events": []})
            lines += 1
        last_day = event.end - timedelta(seconds=1)
        if event.all_day:
            time_txt = "all day"
            if last_day.date() > start.date():
                time_txt = f"→ {last_day:%a}"
        else:
            time_txt = f"{event.start:%H:%M}"
        groups[-1]["events"].append({"time": time_txt, "title": event.title})
        lines += 1
        shown += 1
    return groups, len(upcoming) - shown


def build_bins(bins: list[Bin], now: datetime, groups: int = 2) -> list[dict]:
    """
    Group upcoming bin collections by day.

    Args:
        bins (list[Bin]): Collections sorted by date.
        now (datetime): Current time; past collections are dropped.
        groups (int): How many collection days to return.

    Returns:
        list[dict]: ``{"label", "names", "soon"}`` per day; ``soon`` = today or tomorrow.
    """
    by_day: dict = {}
    for b in bins:
        if b.date >= now.date():
            by_day.setdefault(b.date, []).append(b.name)
    out = []
    for day in sorted(by_day)[:groups]:
        when = datetime.combine(day, time(12), now.tzinfo)
        out.append(
            {
                "label": day_label(when, now),
                "names": by_day[day],
                "soon": (day - now.date()).days <= 1,
            }
        )
    return out


def chunk(items: list, size: int) -> list[list]:
    """
    Split a list into consecutive chunks.

    Args:
        items (list): Items.
        size (int): Chunk size.

    Returns:
        list[list]: Chunks (at least one, possibly empty).
    """
    return [items[i : i + size] for i in range(0, len(items), size)] or [[]]


def build_context(data: DashboardData, settings: Settings) -> dict:
    """
    Turn collected data into template variables.

    Args:
        data (DashboardData): Collected data.
        settings (Settings): Layout options.

    Returns:
        dict: Jinja2 context.
    """
    now = data.now
    weather = data.weather
    hourly: list[Forecast] = []
    daily: list[Forecast] = []
    today: Forecast | None = None
    if weather:
        hourly = [h for h in weather.hourly if h.when >= now - timedelta(minutes=30)]
        hourly = hourly[::3][:4]
        today = next((d for d in weather.daily if d.when.date() == now.date()), None)
        daily = [d for d in weather.daily if d.when.date() > now.date()][:4]

    agenda, agenda_more = build_agenda(data.events or [], now, max_lines=AGENDA_LINES)
    shopping = data.shopping or []
    shop_pages = chunk(shopping, SHOP_PER_PAGE)[:MAX_SHOP_PAGES]
    batt = data.kindle_battery
    return {
        "now": now,
        "weekday": f"{now:%A}",
        "date": f"{now.day} {now:%B}",
        "weather": weather,
        "today": today,
        "hourly": hourly,
        "daily": daily,
        "agenda": agenda,
        "agenda_more": agenda_more,
        "calendar_ok": data.events is not None,
        "calendar_configured": bool(settings.ical_urls),
        "shopping": shopping[:SHOP_PAGE1],
        "shopping_more": max(0, len(shopping) - SHOP_PAGE1),
        "shopping_ok": data.shopping is not None,
        "shopping_total": len(shopping),
        # Reason: balance the two columns (12 + 11, not 22 + 1).
        "shop_pages": [
            chunk(page, math.ceil(len(page) / 2) or 1) for page in shop_pages
        ],
        "page_count": 1 + len(shop_pages),
        "bins": build_bins(data.bins or [], now),
        "bins_ok": data.bins is not None,
        "s": data.sensors,
        "battery": batt,
        "battery_low": batt is not None and batt < settings.low_battery_pct,
        "errors": data.errors,
    }


def _font_face(weight: int, file_name: str) -> str:
    """
    Build an @font-face rule with the font embedded as a data URI.

    Args:
        weight (int): CSS font weight.
        file_name (str): File in static/fonts.

    Returns:
        str: CSS rule.
    """
    data = base64.b64encode((STATIC / "fonts" / file_name).read_bytes()).decode()
    return (
        f'@font-face{{font-family:"AH";font-weight:{weight};'
        f'src:url(data:font/ttf;base64,{data}) format("truetype");}}'
    )


@cache
def _environment() -> Environment:
    """
    Create the Jinja2 environment with helpers registered.

    Returns:
        Environment: Template environment.
    """
    env = Environment(
        loader=FileSystemLoader(HERE / "templates"),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals.update(
        icon=icon,
        condition_icon=condition_icon,
        condition_label=condition_label,
        fonts=Markup(
            _font_face(400, "AtkinsonHyperlegible-Regular.ttf")
            + _font_face(700, "AtkinsonHyperlegible-Bold.ttf")
        ),
    )
    env.filters["deg"] = lambda v: "—" if v is None else f"{round(v)}°"
    env.filters["num"] = lambda v, unit="": "—" if v is None else f"{round(v)}{unit}"
    return env


def render_html(
    data: DashboardData, settings: Settings, context: dict | None = None
) -> str:
    """
    Render the dashboard HTML: every page stacked vertically in one document.

    Args:
        data (DashboardData): Collected data.
        settings (Settings): Layout options.
        context (dict | None): Precomputed ``build_context`` result, if available.

    Returns:
        str: Complete, self-contained HTML document.
    """
    context = context or build_context(data, settings)
    template = _environment().get_template("dashboard.html")
    return template.render(**context, width=settings.width, height=settings.height)


def screenshot(html: str, out_png: Path, settings: Settings, pages: int = 1) -> None:
    """
    Screenshot an HTML document with headless Chromium at the Kindle resolution.

    Args:
        html (str): Self-contained HTML (pages stacked vertically).
        out_png (Path): Where to write the raw screenshot.
        settings (Settings): Chromium binary and size.
        pages (int): Number of stacked pages (the window is this many screens tall).

    Raises:
        RuntimeError: If Chromium fails or produces no file.
    """
    with tempfile.TemporaryDirectory(prefix="fridgedash-") as tmp:
        page = Path(tmp) / "page.html"
        page.write_text(html, encoding="utf-8")
        cmd = [
            settings.chromium_bin,
            "--headless",
            "--no-sandbox",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            # Reason: a private profile avoids clashing with a desktop Chromium session.
            f"--user-data-dir={tmp}/profile",
            # Reason: lets the embedded web fonts load before the shot is taken.
            "--virtual-time-budget=3000",
            f"--window-size={settings.width},{settings.height * pages}",
            f"--screenshot={out_png}",
            page.as_uri(),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if proc.returncode != 0 or not out_png.exists():
            raise RuntimeError(f"chromium failed: {proc.stderr[-500:]}")


def to_kindle_png(src: Path | Image.Image, dst: Path, settings: Settings) -> None:
    """
    Convert a screenshot to the Kindle format: exact size, 8-bit gray, N gray levels.

    The file is written atomically so a Kindle never downloads a half-written image.

    Args:
        src (Path | Image.Image): Source image or path.
        dst (Path): Destination PNG.
        settings (Settings): Target size and number of gray levels.
    """
    img = (src if isinstance(src, Image.Image) else Image.open(src)).convert("L")
    size = (settings.width, settings.height)
    if img.size != size:
        canvas = Image.new("L", size, 255)
        # Reason: crop() beyond the source bounds fills with black, so clamp it first.
        w, h = min(img.width, size[0]), min(img.height, size[1])
        canvas.paste(img.crop((0, 0, w, h)), (0, 0))
        img = canvas
    step = 255 / (settings.gray_levels - 1)
    img = img.point([round(round(v / step) * step) for v in range(256)])
    tmp = dst.with_name(f".{dst.name}.tmp")
    img.save(tmp, "PNG", optimize=True)
    os.replace(tmp, dst)


def render_pages(
    data: DashboardData, settings: Settings, out_dir: Path
) -> tuple[str, int]:
    """
    Full pipeline: data → HTML (all pages stacked) → one screenshot → ``page<N>.png``.

    Stale pages from a previous, longer render are removed.

    Args:
        data (DashboardData): Collected data.
        settings (Settings): Configuration.
        out_dir (Path): Directory for ``page1.png`` … ``pageN.png``.

    Returns:
        tuple[str, int]: The rendered HTML (for the browser preview) and the page count.
    """
    context = build_context(data, settings)
    pages = context["page_count"]
    html = render_html(data, settings, context)
    with tempfile.TemporaryDirectory(prefix="fridgedash-shot-") as tmp:
        raw = Path(tmp) / "raw.png"
        screenshot(html, raw, settings, pages=pages)
        sheet = Image.open(raw)
        w, h = settings.width, settings.height
        for i in range(pages):
            page = sheet.crop((0, i * h, w, min((i + 1) * h, sheet.height)))
            to_kindle_png(page, out_dir / f"page{i + 1}.png", settings)
    for stale in out_dir.glob("page*.png"):
        if stale.stem[4:].isdigit() and int(stale.stem[4:]) > pages:
            stale.unlink()
    return html, pages

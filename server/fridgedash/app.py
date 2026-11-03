"""FastAPI service: periodically renders the dashboard and serves it to the Kindle."""

import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

from .config import Settings, load_settings
from .kindle import KindleTracker
from .render import DashboardData, render_html, render_pages
from .sources import HomeAssistant, fetch_events

log = logging.getLogger("fridgedash")

# Largest Kindle log tail accepted by POST /log.
LOG_MAX_BYTES = 16384

# Render this long before the Kindle's announced wake (it fetches ~15 s after waking).
PRE_WAKE_LEAD = timedelta(seconds=20)


def collect(
    settings: Settings, ha: HomeAssistant, battery: int | None
) -> DashboardData:
    """
    Gather all dashboard data; a failing source is recorded and left empty.

    Args:
        settings (Settings): Configuration.
        ha (HomeAssistant): Home Assistant client.
        battery (int | None): Last battery level reported by the Kindle.

    Returns:
        DashboardData: Collected data, with ``errors`` naming failed sources.
    """
    tz = ZoneInfo(settings.tz)
    now = datetime.now(tz)
    data = DashboardData(now=now, kindle_battery=battery)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=settings.agenda_days)
    steps = {
        "weather": lambda: ha.weather(settings.weather_entity, tz),
        "shopping": lambda: ha.todo_items(settings.shopping_entity),
        "sensors": lambda: ha.sensors(settings),
        "bins": lambda: ha.bins(settings),
        "events": lambda: fetch_events(settings.ical_urls, tz, start, end),
    }
    if not settings.ical_urls:
        del steps["events"]  # leave events as None: the panel says "not set up"
    for name, fetch in steps.items():
        try:
            setattr(data, name, fetch())
        except (
            Exception
        ) as exc:  # noqa: BLE001 — any source failure must not stop the render
            log.warning("source %s failed: %s", name, exc)
            data.errors.append(name)
    return data


class Renderer:
    """Owns the render state shared between the background loop and the endpoints."""

    def __init__(self, settings: Settings):
        """
        Args:
            settings (Settings): Configuration.
        """
        self.settings = settings
        self.png = settings.data_dir / "page1.png"
        self.page_count = 0
        self.html = ""
        self.rendered_at: datetime | None = None
        self.render_errors: list[str] = []
        self.kindle = KindleTracker(settings.data_dir)
        self.ha = HomeAssistant(settings)
        self._lock = threading.Lock()

    def render(self) -> None:
        """Collect data and write a fresh PNG (serialised; runs in a worker thread)."""
        with self._lock:
            data = collect(self.settings, self.ha, self.kindle.battery)
            self.html, self.page_count = render_pages(
                data, self.settings, self.settings.data_dir
            )
            self.rendered_at = datetime.now(timezone.utc)
            self.render_errors = data.errors
            log.info("rendered %s (errors: %s)", self.png, data.errors or "none")

    def seconds_until_next_render(self, now: datetime | None = None) -> float:
        """
        Time until the next render: the regular interval, or sooner if the Kindle's
        announced wake (minus a short lead) falls inside it.

        Args:
            now (datetime | None): Current time (for tests).

        Returns:
            float: Seconds to sleep, at least 1.
        """
        now = now or datetime.now(timezone.utc)
        wait = float(self.settings.render_interval_s)
        nxt = self.kindle.status.next_expected
        if nxt is not None:
            until = (nxt - PRE_WAKE_LEAD - now).total_seconds()
            if 0 < until < wait:
                wait = until
        return max(wait, 1.0)

    def preview_html(self) -> str:
        """
        HTML for the browser preview, freshly built without a screenshot.

        Returns:
            str: Dashboard HTML.
        """
        data = collect(self.settings, self.ha, self.kindle.battery)
        return render_html(data, self.settings)


def create_app(settings: Settings | None = None) -> FastAPI:
    """
    Build the FastAPI application.

    Args:
        settings (Settings | None): Configuration; loaded from the environment if None.

    Returns:
        FastAPI: The application.
    """
    settings = settings or load_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    renderer = Renderer(settings)

    async def loop() -> None:
        while True:
            try:
                await asyncio.to_thread(renderer.render)
            except Exception:  # noqa: BLE001 — keep the loop alive, retry next tick
                log.exception("render failed")
            await asyncio.sleep(renderer.seconds_until_next_render())

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        task = asyncio.create_task(loop())
        yield
        task.cancel()

    app = FastAPI(title="fridgedash", lifespan=lifespan)
    app.state.renderer = renderer

    @app.get("/dash.png")
    def dash_png(
        request: Request,
        batt: int | None = Query(default=None, ge=0, le=100),
        chg: int | None = Query(default=None, ge=0, le=1),
        next: int | None = Query(default=None, ge=0),
        fresh: int | None = Query(default=None, ge=0, le=1),
    ) -> FileResponse:
        """
        Latest Kindle image. The Kindle's check-in rides on this request:
        ``batt`` (percent), ``chg`` (1 = charging) and ``next`` (epoch of its next wake).
        Requests without ``batt``/``next`` (browsers, Home Assistant) are not check-ins.
        ``fresh=1`` (power-button refresh on the Kindle) renders before serving.
        """
        if batt is not None or next is not None:
            renderer.kindle.check_in(
                batt,
                None if chg is None else bool(chg),
                next,
                request.client.host if request.client else "",
            )
        if fresh:
            try:
                renderer.render()
            except Exception:  # noqa: BLE001 — fall back to the last good image
                log.exception("fresh render failed")
        if not renderer.png.exists():
            raise HTTPException(503, "not rendered yet")
        return FileResponse(
            renderer.png, media_type="image/png", headers={"Cache-Control": "no-store"}
        )

    @app.get("/pages", response_class=PlainTextResponse)
    def pages() -> str:
        """Number of pages, so the Kindle knows what to download for browsing."""
        return f"{renderer.page_count}\n"

    @app.get("/page/{number}.png")
    def page_png(number: int) -> FileResponse:
        """Page ``number`` (1 = main dashboard, 2.. = shopping list)."""
        path = settings.data_dir / f"page{number}.png"
        if number < 1 or number > renderer.page_count or not path.exists():
            raise HTTPException(404, "no such page")
        return FileResponse(
            path, media_type="image/png", headers={"Cache-Control": "no-store"}
        )

    @app.get("/", response_class=HTMLResponse)
    async def preview() -> str:
        """Live HTML preview of the dashboard for a desktop browser."""
        return await asyncio.to_thread(renderer.preview_html)

    @app.get("/healthz", response_class=PlainTextResponse)
    def healthz() -> str:
        """Cheap liveness probe the Kindle uses to wait for WiFi."""
        return "ok\n"

    @app.get("/status")
    def status() -> dict:
        """Kindle check-in state and render info, polled by Home Assistant."""
        s = renderer.kindle.status
        return {
            "online": renderer.kindle.online(),
            "battery": s.battery,
            "charging": s.charging,
            "last_seen": s.last_seen,
            "next_expected": s.next_expected,
            "ip": s.ip,
            "rendered_at": renderer.rendered_at,
            "render_errors": renderer.render_errors,
        }

    @app.post("/log", response_class=PlainTextResponse)
    async def upload_log(request: Request) -> str:
        """The Kindle posts the tail of its own log at each check-in (it is unreachable
        while asleep, so this is the only practical way to read it)."""
        body = (await request.body())[:LOG_MAX_BYTES]
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        (settings.data_dir / "kindle.log").write_bytes(
            f"# uploaded {stamp}\n".encode() + body
        )
        return "ok\n"

    @app.get("/log", response_class=PlainTextResponse)
    def read_log() -> str:
        """Last log tail uploaded by the Kindle."""
        path = settings.data_dir / "kindle.log"
        return path.read_text(errors="replace") if path.exists() else ""

    @app.post("/render")
    async def force_render() -> dict:
        """Render immediately (handy after editing the template or HA data)."""
        await asyncio.to_thread(renderer.render)
        return {"ok": True}

    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

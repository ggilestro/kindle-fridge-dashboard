"""Tests for the HTTP endpoints and data collection."""

import time
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from PIL import Image

from fridgedash.app import collect, create_app


def client_for(settings):
    # Reason: no `with` block, so the lifespan render loop does not start.
    return TestClient(create_app(settings))


def test_healthz(settings):
    r = client_for(settings).get("/healthz")
    assert r.status_code == 200 and r.text == "ok\n"


def test_dash_png_not_rendered_yet(settings):
    assert client_for(settings).get("/dash.png").status_code == 503


def test_dash_png_serves_file_and_records_battery(settings):
    Image.new("L", (600, 800), 255).save(settings.data_dir / "page1.png")
    client = client_for(settings)
    r = client.get("/dash.png?batt=64")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "no-store"
    assert client.app.state.renderer.kindle.battery == 64
    assert ",64," in (settings.data_dir / "battery.csv").read_text()


def test_dash_png_rejects_bad_battery(settings):
    assert client_for(settings).get("/dash.png?batt=150").status_code == 422


class BrokenHA:
    """HA stand-in whose every call fails."""

    def __getattr__(self, name):
        def fail(*args, **kwargs):
            raise ConnectionError("HA down")

        return fail


def test_collect_survives_failing_sources(settings):
    settings.ical_urls = ["http://127.0.0.1:9/none.ics"]
    data = collect(settings, BrokenHA(), battery=50)
    assert set(data.errors) == {"weather", "shopping", "sensors", "bins", "events"}
    assert data.kindle_battery == 50 and data.weather is None


def test_collect_without_calendar_is_not_an_error(settings):
    data = collect(settings, BrokenHA(), battery=None)
    assert data.events is None and "events" not in data.errors


def test_collect_fetches_two_weeks_of_events(settings, monkeypatch):
    seen = {}

    def fake_fetch(urls, tz, start, end):
        seen.update(start=start, end=end)
        return []

    monkeypatch.setattr("fridgedash.app.fetch_events", fake_fetch)
    settings.ical_urls = ["http://example.invalid/cal.ics"]
    data = collect(settings, BrokenHA(), battery=None)
    assert data.events == [] and "events" not in data.errors
    assert (seen["start"].hour, seen["start"].minute) == (0, 0)
    assert (seen["end"] - seen["start"]).days == 14


def test_dash_png_without_batt_is_not_a_check_in(settings):
    Image.new("L", (600, 800), 255).save(settings.data_dir / "page1.png")
    client = client_for(settings)
    assert client.get("/dash.png?v=123").status_code == 200
    assert not (settings.data_dir / "kindle.json").exists()


def test_status_reports_check_in(settings):
    Image.new("L", (600, 800), 255).save(settings.data_dir / "page1.png")
    client = client_for(settings)
    before = client.get("/status").json()
    assert before["online"] is False and before["battery"] is None
    next_wake = int(time.time()) + 3600
    client.get(f"/dash.png?batt=81&chg=1&next={next_wake}")
    s = client.get("/status").json()
    assert s["online"] is True and s["battery"] == 81 and s["charging"] is True
    assert s["next_expected"].startswith(
        datetime.fromtimestamp(next_wake, timezone.utc).strftime("%Y-%m-%dT%H:%M")
    )


def test_status_rejects_bad_charging_flag(settings):
    assert client_for(settings).get("/dash.png?batt=50&chg=2").status_code == 422


def test_check_in_without_battery_reading(settings):
    Image.new("L", (600, 800), 255).save(settings.data_dir / "page1.png")
    client = client_for(settings)
    client.get(f"/dash.png?next={int(time.time()) + 3600}")
    s = client.get("/status").json()
    assert s["online"] is True and s["battery"] is None
    assert ",," in (settings.data_dir / "battery.csv").read_text()


def test_render_scheduled_just_before_announced_wake(settings):
    from datetime import timedelta

    from fridgedash.app import PRE_WAKE_LEAD

    renderer = create_app(settings).state.renderer
    now = datetime(2026, 11, 1, 18, 55, tzinfo=timezone.utc)
    interval = float(settings.render_interval_s)
    assert renderer.seconds_until_next_render(now) == interval  # never seen
    wake = int(datetime(2026, 11, 1, 19, 0, tzinfo=timezone.utc).timestamp())
    renderer.kindle.check_in(90, False, wake, "k", now=now)
    expected = (timedelta(minutes=5) - PRE_WAKE_LEAD).total_seconds()
    assert renderer.seconds_until_next_render(now) == expected
    # Wake far away -> regular interval; wake already passed -> regular interval.
    assert renderer.seconds_until_next_render(now - timedelta(hours=2)) == interval
    assert renderer.seconds_until_next_render(now + timedelta(minutes=10)) == interval


def test_fresh_fetch_renders_first(settings, monkeypatch):
    Image.new("L", (600, 800), 255).save(settings.data_dir / "page1.png")
    client = client_for(settings)
    calls = []
    monkeypatch.setattr(client.app.state.renderer, "render", lambda: calls.append(1))
    assert client.get("/dash.png?batt=50&fresh=1").status_code == 200
    assert client.get("/dash.png?batt=50").status_code == 200
    assert calls == [1]


def test_fresh_fetch_survives_render_failure(settings, monkeypatch):
    Image.new("L", (600, 800), 255).save(settings.data_dir / "page1.png")
    client = client_for(settings)

    def boom():
        raise RuntimeError("chromium died")

    monkeypatch.setattr(client.app.state.renderer, "render", boom)
    assert client.get("/dash.png?fresh=1").status_code == 200


def test_pages_endpoints(settings):
    for i in (1, 2):
        Image.new("L", (600, 800), 255).save(settings.data_dir / f"page{i}.png")
    client = client_for(settings)
    client.app.state.renderer.page_count = 2
    assert client.get("/pages").text == "2\n"
    assert client.get("/page/2.png").status_code == 200
    assert client.get("/page/3.png").status_code == 404
    assert client.get("/page/0.png").status_code == 404


def test_log_upload_roundtrip_and_cap(settings):
    from fridgedash.app import LOG_MAX_BYTES

    client = client_for(settings)
    assert client.get("/log").text == ""
    assert client.post("/log", content=b"line one\nline two\n").text == "ok\n"
    text = client.get("/log").text
    assert text.startswith("# uploaded ") and text.endswith("line two\n")
    client.post("/log", content=b"x" * (LOG_MAX_BYTES + 100))
    assert client.get("/log").text.count("x") == LOG_MAX_BYTES


def test_status_reports_kindle_ip(settings):
    Image.new("L", (600, 800), 255).save(settings.data_dir / "page1.png")
    client = client_for(settings)
    client.get(f"/dash.png?batt=70&next={int(time.time()) + 3600}")
    assert client.get("/status").json()["ip"] == "testclient"

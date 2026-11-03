"""Tests for HA / iCal parsing and the HA client."""

from datetime import datetime, timedelta

import httpx
import pytest
from conftest import FIXTURES, NOW, TZ, load

from fridgedash.config import Settings, load_settings
from fridgedash.sources import (
    HomeAssistant,
    bin_date,
    bin_name,
    parse_bins,
    parse_events,
    parse_sensors,
    parse_todo_items,
    parse_weather,
    to_float,
)


def window():
    start = NOW.replace(hour=0, minute=0)
    return start, start + timedelta(days=6)


def test_to_float_handles_unavailable_and_garbage():
    assert to_float("21.5") == 21.5
    assert to_float(3) == 3.0
    for bad in ("unavailable", "unknown", None, "", "n/a"):
        assert to_float(bad) is None


def test_parse_weather_converts_to_local_time():
    entity = "weather.forecast_home"
    weather = parse_weather(
        load("ha_states.json")[entity],
        load("ha_forecast_hourly.json")["service_response"][entity]["forecast"],
        load("ha_forecast_daily.json")["service_response"][entity]["forecast"],
        TZ,
    )
    assert weather.condition == "cloudy"
    assert weather.temperature == 10.2
    assert len(weather.hourly) == 24
    assert weather.hourly[0].when.tzinfo is not None
    assert weather.daily[0].templow == 6.8


def test_parse_weather_tolerates_missing_state_and_bad_items():
    weather = parse_weather(None, [{"condition": "rainy"}], [], TZ)
    assert weather.condition is None and weather.hourly == []


def test_parse_sensors_maps_unavailable_to_none():
    s = parse_sensors(load("ha_states.json"), Settings())
    assert s.room_temp == 20.0
    assert s.ev_battery == 82.0
    assert s.ev_range is None  # fixture state is "unavailable"
    assert s.vacuum_state == "docked"


def test_parse_sensors_missing_entities():
    s = parse_sensors({}, Settings())
    assert s.model_dump() == {k: None for k in s.model_dump()}


def test_parse_todo_skips_completed():
    items = parse_todo_items(
        load("ha_todo.json")["service_response"], "todo.shopping_list"
    )
    assert "Milk" in items and "Bananas" not in items
    assert parse_todo_items({}, "todo.shopping_list") == []


def test_parse_events_window_recurrence_and_timezones():
    events = parse_events((FIXTURES / "sample.ics").read_bytes(), TZ, *window())
    titles = [e.title for e in events]
    assert "Yesterday's event" not in titles
    assert "Too far ahead" not in titles
    swim = [e for e in events if e.title == "Swimming"]
    assert len(swim) == 1 and swim[0].start == datetime(2026, 11, 3, 7, 0, tzinfo=TZ)
    bins = next(e for e in events if e.title.startswith("Bin day"))
    assert bins.all_day and bins.start.date().isoformat() == "2026-11-02"
    floating = next(e for e in events if e.title == "Parents' evening")
    assert floating.start.hour == 15
    assert events == sorted(events, key=lambda e: (e.start, not e.all_day, e.title))


def test_parse_events_rejects_garbage():
    with pytest.raises(ValueError):
        parse_events(b"not a calendar", TZ, *window())


def test_settings_split_ical_urls(monkeypatch):
    monkeypatch.setenv("ICAL_URLS", "https://a/x.ics, https://b/y.ics")
    monkeypatch.setenv("RENDER_INTERVAL_S", "300")
    s = load_settings("/nonexistent/.env")
    assert s.ical_urls == ["https://a/x.ics", "https://b/y.ics"]
    assert s.render_interval_s == 300


def test_ha_client_weather_and_missing_entity():
    entity = "weather.forecast_home"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test"
        path = request.url.path
        if path == f"/api/states/{entity}":
            return httpx.Response(200, json=load("ha_states.json")[entity])
        if path == "/api/services/weather/get_forecasts":
            assert "return_response" in str(request.url)
            kind = httpx.Request("POST", "/", content=request.content).read()
            name = "hourly" if b"hourly" in kind else "daily"
            return httpx.Response(200, json=load(f"ha_forecast_{name}.json"))
        return httpx.Response(404)

    client = httpx.Client(
        base_url="http://ha",
        headers={"Authorization": "Bearer test"},
        transport=httpx.MockTransport(handler),
    )
    ha = HomeAssistant(Settings(ha_token="test"), client=client)
    weather = ha.weather(entity, TZ)
    assert len(weather.hourly) == 24 and len(weather.daily) == 6
    assert ha.state("sensor.does_not_exist") is None


def test_bin_name_and_date():
    assert bin_name("Bins Paper and card collection") == "Paper & card"
    assert bin_name("Wheelie bins") == "Wheelie bins"
    assert bin_date({"next_collection": "02/11/2026"}).isoformat() == "2026-11-02"
    assert bin_date({"date": "2026-11-09"}).isoformat() == "2026-11-09"
    assert bin_date({"next_collection": "soon"}) is None


def test_parse_bins_discovery_and_explicit_list():
    states = load("ha_bins.json")
    found = parse_bins(states, "bin_collection_schedule", [])
    assert [b.name for b in found][:2] == ["Food waste", "Mixed recycling"]
    assert len(found) == 5  # the plain sensor.mixed_recycling has no device class
    only = parse_bins(states, "bin_collection_schedule", ["sensor.mixed_recycling"])
    assert [(b.name, b.date.isoformat()) for b in only] == [
        ("Mixed recycling", "2026-11-02")
    ]

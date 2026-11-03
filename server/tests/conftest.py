"""Shared fixtures: sample HA responses and calendar, frozen at Sun 1 Nov 2026 17:05 London."""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fridgedash.config import Settings  # noqa: E402
from fridgedash.render import DashboardData  # noqa: E402
from fridgedash.sources import (  # noqa: E402
    parse_bins,
    parse_events,
    parse_sensors,
    parse_todo_items,
    parse_weather,
)

FIXTURES = Path(__file__).parent / "fixtures"
TZ = ZoneInfo("Europe/London")
NOW = datetime(2026, 11, 1, 17, 5, tzinfo=TZ)


def load(name: str) -> dict:
    """
    Load a JSON fixture.

    Args:
        name (str): File name in the fixtures directory.

    Returns:
        dict: Parsed JSON.
    """
    return json.loads((FIXTURES / name).read_text())


def sample_data(settings: Settings, battery: int | None = 87) -> DashboardData:
    """
    Build a fully populated DashboardData from the fixtures.

    Args:
        settings (Settings): Entity ids.
        battery (int | None): Kindle battery level to show.

    Returns:
        DashboardData: Sample data.
    """
    states = load("ha_states.json")
    entity = settings.weather_entity
    hourly = load("ha_forecast_hourly.json")["service_response"][entity]["forecast"]
    daily = load("ha_forecast_daily.json")["service_response"][entity]["forecast"]
    start = NOW.replace(hour=0, minute=0)
    return DashboardData(
        now=NOW,
        weather=parse_weather(states[entity], hourly, daily, TZ),
        events=parse_events(
            (FIXTURES / "sample.ics").read_bytes(),
            TZ,
            start,
            start + timedelta(days=settings.agenda_days),
        ),
        shopping=parse_todo_items(
            load("ha_todo.json")["service_response"], settings.shopping_entity
        ),
        sensors=parse_sensors(states, settings),
        bins=parse_bins(load("ha_bins.json"), settings.bin_device_class, []),
        kindle_battery=battery,
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Default settings writing to a temporary data dir."""
    return Settings(data_dir=tmp_path, ha_token="test")

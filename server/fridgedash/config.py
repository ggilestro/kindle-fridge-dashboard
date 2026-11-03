"""Settings loaded from environment variables (and an optional .env file)."""

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, field_validator


class Settings(BaseModel):
    """
    Runtime configuration. Each field is read from the upper-cased env var of the same name.

    Attributes:
        ha_url (str): Base URL of Home Assistant.
        ha_token (str): Long-lived access token for Home Assistant.
        ical_urls (list[str]): Calendar feeds (comma separated in the env var).
        tz (str): IANA timezone used for all displayed times.
    """

    ha_url: str = "http://192.168.68.124:8123"
    ha_token: str = ""
    ical_urls: list[str] = []
    tz: str = "Europe/London"

    weather_entity: str = "weather.forecast_home"
    shopping_entity: str = "todo.shopping_list"
    room_climate_entity: str = "climate.heater"
    ev_battery_entity: str = "sensor.e_niro_e_niro_e_niro_ev_battery_level"
    ev_range_entity: str = "sensor.e_niro_e_niro_e_niro_ev_range"
    vacuum_entity: str = "vacuum.robovac"
    vacuum_battery_entity: str = "sensor.robovac_battery"
    # Bins: every sensor with this device class, unless BIN_ENTITIES lists them explicitly.
    bin_device_class: str = "bin_collection_schedule"
    bin_entities: list[str] = []

    render_interval_s: int = 600
    agenda_days: int = 14  # calendar window from today's midnight
    low_battery_pct: int = 15
    width: int = 600
    height: int = 800
    gray_levels: int = 16
    data_dir: Path = Path("/data")
    chromium_bin: str = "chromium"

    @field_validator("ical_urls", "bin_entities", mode="before")
    @classmethod
    def _split_urls(cls, value: object) -> object:
        """
        Accept a comma/whitespace separated string for list settings.

        Args:
            value (object): Raw value from the environment.

        Returns:
            object: A list of non-empty items, or the value unchanged if already a list.
        """
        if isinstance(value, str):
            return [u for u in value.replace(",", " ").split() if u]
        return value


def load_settings(env_file: str | Path | None = None) -> Settings:
    """
    Build Settings from the process environment, after loading an optional .env file.

    Args:
        env_file (str | Path | None): Path to a .env file; None searches the usual places.

    Returns:
        Settings: Validated configuration.
    """
    load_dotenv(env_file)
    raw = {
        name: os.environ[name.upper()]
        for name in Settings.model_fields
        if name.upper() in os.environ
    }
    return Settings(**raw)

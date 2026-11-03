"""Data sources: Home Assistant REST API and iCal feeds, parsed into pydantic models."""

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
import icalendar
import recurring_ical_events
from pydantic import BaseModel

from .config import Settings

UNAVAILABLE = {"unavailable", "unknown", "none", ""}


class Forecast(BaseModel):
    """One forecast slot (hourly or daily)."""

    when: datetime
    condition: str | None = None
    temperature: float | None = None
    templow: float | None = None
    precipitation: float | None = None
    precipitation_probability: float | None = None


class Weather(BaseModel):
    """Current conditions plus hourly and daily forecasts."""

    condition: str | None = None
    temperature: float | None = None
    hourly: list[Forecast] = []
    daily: list[Forecast] = []


class Event(BaseModel):
    """A calendar event already converted to the display timezone."""

    title: str
    start: datetime
    end: datetime
    all_day: bool = False


class Sensors(BaseModel):
    """Home Assistant values shown in the sensor strip."""

    room_temp: float | None = None
    ev_battery: float | None = None
    ev_range: float | None = None
    vacuum_state: str | None = None
    vacuum_battery: float | None = None


class Bin(BaseModel):
    """A bin collection: what goes out and when."""

    name: str
    date: date


def bin_name(friendly_name: str) -> str:
    """
    Shorten a bin sensor's friendly name: "Bins Paper and card collection" -> "Paper & card".

    Args:
        friendly_name (str): HA friendly name.

    Returns:
        str: Short display name.
    """
    name = re.sub(r"^bins?\s+", "", friendly_name.strip(), flags=re.I)
    name = re.sub(r"\s+collection$", "", name, flags=re.I).replace(" and ", " & ")
    return name[:1].upper() + name[1:]


def bin_date(attrs: dict) -> date | None:
    """
    Read the next collection date from a bin sensor's attributes.

    Accepts ISO (``date: 2026-11-02``) and UK style (``next_collection: 02/11/2026``).

    Args:
        attrs (dict): Entity attributes.

    Returns:
        date | None: The date, or None if no attribute parses.
    """
    for key in ("date", "next_collection"):
        value = str(attrs.get(key) or "")
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(value[:10], fmt).date()
            except ValueError:
                continue
    return None


def parse_bins(states: list[dict], device_class: str, entities: list[str]) -> list[Bin]:
    """
    Pick bin collection sensors out of the full HA state list.

    Args:
        states (list[dict]): ``/api/states`` JSON.
        device_class (str): Device class marking bin sensors (used if ``entities`` empty).
        entities (list[str]): Explicit entity ids; overrides discovery when non-empty.

    Returns:
        list[Bin]: Bins with a parseable date, sorted by date then name.
    """
    bins = []
    for s in states:
        attrs = s.get("attributes", {})
        if entities:
            if s.get("entity_id") not in entities:
                continue
        elif attrs.get("device_class") != device_class:
            continue
        when = bin_date(attrs)
        if when is not None:
            name = attrs.get("friendly_name") or s.get("entity_id", "")
            bins.append(Bin(name=bin_name(name), date=when))
    return sorted(bins, key=lambda b: (b.date, b.name))


def to_float(value: object) -> float | None:
    """
    Convert an HA state/attribute to float, mapping unavailable values to None.

    Args:
        value (object): Raw state or attribute value.

    Returns:
        float | None: The number, or None if missing or not numeric.
    """
    if value is None or str(value).strip().lower() in UNAVAILABLE:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_text(value: object) -> str | None:
    """
    Normalise an HA state string, mapping unavailable values to None.

    Args:
        value (object): Raw state.

    Returns:
        str | None: The state text, or None.
    """
    if value is None or str(value).strip().lower() in UNAVAILABLE:
        return None
    return str(value)


def parse_forecast(items: list[dict], tz: ZoneInfo) -> list[Forecast]:
    """
    Parse the forecast list returned by ``weather.get_forecasts``.

    Args:
        items (list[dict]): Forecast entries with ISO ``datetime`` strings.
        tz (ZoneInfo): Display timezone.

    Returns:
        list[Forecast]: Forecast slots in chronological order.
    """
    out = []
    for item in items:
        try:
            when = datetime.fromisoformat(item["datetime"]).astimezone(tz)
        except (KeyError, ValueError):
            continue
        out.append(
            Forecast(
                when=when,
                condition=to_text(item.get("condition")),
                temperature=to_float(item.get("temperature")),
                templow=to_float(item.get("templow")),
                precipitation=to_float(item.get("precipitation")),
                precipitation_probability=to_float(
                    item.get("precipitation_probability")
                ),
            )
        )
    return sorted(out, key=lambda f: f.when)


def parse_weather(
    state: dict | None, hourly: list[dict], daily: list[dict], tz: ZoneInfo
) -> Weather:
    """
    Combine the weather entity state with its forecasts.

    Args:
        state (dict | None): ``/api/states/<weather entity>`` JSON.
        hourly (list[dict]): Hourly forecast entries.
        daily (list[dict]): Daily forecast entries.
        tz (ZoneInfo): Display timezone.

    Returns:
        Weather: Parsed weather.
    """
    attrs = (state or {}).get("attributes", {})
    return Weather(
        condition=to_text((state or {}).get("state")),
        temperature=to_float(attrs.get("temperature")),
        hourly=parse_forecast(hourly, tz),
        daily=parse_forecast(daily, tz),
    )


def parse_sensors(states: dict[str, dict | None], settings: Settings) -> Sensors:
    """
    Pick the sensor-strip values out of a mapping of entity_id to state JSON.

    Args:
        states (dict[str, dict | None]): State JSON per entity (None if missing).
        settings (Settings): Entity ids to read.

    Returns:
        Sensors: Parsed values; anything unavailable is None.
    """

    def state_of(entity: str) -> object:
        return (states.get(entity) or {}).get("state")

    climate = states.get(settings.room_climate_entity) or {}
    return Sensors(
        room_temp=to_float(climate.get("attributes", {}).get("current_temperature")),
        ev_battery=to_float(state_of(settings.ev_battery_entity)),
        ev_range=to_float(state_of(settings.ev_range_entity)),
        vacuum_state=to_text(state_of(settings.vacuum_entity)),
        vacuum_battery=to_float(state_of(settings.vacuum_battery_entity)),
    )


def parse_todo_items(response: dict, entity: str) -> list[str]:
    """
    Extract open item names from a ``todo.get_items`` service response.

    Args:
        response (dict): ``service_response`` JSON keyed by entity id.
        entity (str): The todo entity id.

    Returns:
        list[str]: Summaries of items that still need action.
    """
    items = response.get(entity, {}).get("items", [])
    return [
        i["summary"]
        for i in items
        if i.get("status", "needs_action") == "needs_action" and i.get("summary")
    ]


def _as_local(value: date | datetime, tz: ZoneInfo) -> datetime:
    """
    Convert an iCal DTSTART/DTEND value to an aware datetime in ``tz``.

    Args:
        value (date | datetime): All-day date, floating or aware datetime.
        tz (ZoneInfo): Display timezone.

    Returns:
        datetime: Aware datetime in the display timezone.
    """
    if not isinstance(value, datetime):
        return datetime.combine(value, time.min, tzinfo=tz)
    if value.tzinfo is None:
        # Reason: floating times in iCal mean "local wall time" of the viewer.
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)


def parse_events(
    ics: bytes, tz: ZoneInfo, start: datetime, end: datetime
) -> list[Event]:
    """
    Expand an iCal feed (including recurrences) into events overlapping [start, end).

    Args:
        ics (bytes): Raw .ics content.
        tz (ZoneInfo): Display timezone.
        start (datetime): Window start (aware).
        end (datetime): Window end (aware).

    Returns:
        list[Event]: Events sorted by start time.
    """
    cal = icalendar.Calendar.from_ical(ics)
    events = []
    for comp in recurring_ical_events.of(cal).between(start, end):
        dtstart = comp.get("DTSTART").dt
        dtend_prop = comp.get("DTEND")
        all_day = not isinstance(dtstart, datetime)
        if dtend_prop is not None:
            dtend = dtend_prop.dt
        else:
            duration = comp.get("DURATION")
            if duration is not None:
                dtend = dtstart + duration.dt
            else:
                dtend = dtstart + (timedelta(days=1) if all_day else timedelta(0))
        events.append(
            Event(
                title=str(comp.get("SUMMARY", "(no title)")).strip(),
                start=_as_local(dtstart, tz),
                end=_as_local(dtend, tz),
                all_day=all_day,
            )
        )
    return sorted(events, key=lambda e: (e.start, not e.all_day, e.title))


class HomeAssistant:
    """Minimal synchronous Home Assistant REST client."""

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        """
        Args:
            settings (Settings): Provides the URL and token.
            client (httpx.Client | None): Injected client (for tests).
        """
        self.client = client or httpx.Client(
            base_url=settings.ha_url.rstrip("/"),
            headers={"Authorization": f"Bearer {settings.ha_token}"},
            timeout=15,
        )

    def state(self, entity: str) -> dict | None:
        """
        Fetch one entity state.

        Args:
            entity (str): Entity id.

        Returns:
            dict | None: State JSON, or None if the entity does not exist.
        """
        r = self.client.get(f"/api/states/{entity}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def service(self, domain: str, service: str, data: dict) -> dict:
        """
        Call a service that returns data (``?return_response``).

        Args:
            domain (str): Service domain, e.g. ``weather``.
            service (str): Service name, e.g. ``get_forecasts``.
            data (dict): Service data.

        Returns:
            dict: The ``service_response`` payload.
        """
        r = self.client.post(
            f"/api/services/{domain}/{service}?return_response", json=data
        )
        r.raise_for_status()
        return r.json().get("service_response", {})

    def weather(self, entity: str, tz: ZoneInfo) -> Weather:
        """
        Fetch current weather plus hourly and daily forecasts.

        Args:
            entity (str): Weather entity id.
            tz (ZoneInfo): Display timezone.

        Returns:
            Weather: Parsed weather.
        """
        forecasts = {}
        for kind in ("hourly", "daily"):
            resp = self.service(
                "weather", "get_forecasts", {"entity_id": entity, "type": kind}
            )
            forecasts[kind] = resp.get(entity, {}).get("forecast", [])
        return parse_weather(
            self.state(entity), forecasts["hourly"], forecasts["daily"], tz
        )

    def todo_items(self, entity: str) -> list[str]:
        """
        Fetch open items of a todo list.

        Args:
            entity (str): Todo entity id.

        Returns:
            list[str]: Item names still to do.
        """
        resp = self.service(
            "todo", "get_items", {"entity_id": entity, "status": "needs_action"}
        )
        return parse_todo_items(resp, entity)

    def bins(self, settings: Settings) -> list[Bin]:
        """
        Fetch upcoming bin collections.

        Args:
            settings (Settings): Device class or explicit entity list.

        Returns:
            list[Bin]: Collections sorted by date.
        """
        r = self.client.get("/api/states")
        r.raise_for_status()
        return parse_bins(r.json(), settings.bin_device_class, settings.bin_entities)

    def sensors(self, settings: Settings) -> Sensors:
        """
        Fetch the sensor-strip entities.

        Args:
            settings (Settings): Entity ids to read.

        Returns:
            Sensors: Parsed values.
        """
        entities = [
            settings.room_climate_entity,
            settings.ev_battery_entity,
            settings.ev_range_entity,
            settings.vacuum_entity,
            settings.vacuum_battery_entity,
        ]
        return parse_sensors({e: self.state(e) for e in entities}, settings)


def fetch_events(
    urls: list[str], tz: ZoneInfo, start: datetime, end: datetime
) -> list[Event]:
    """
    Download and merge events from several iCal feeds.

    Args:
        urls (list[str]): Feed URLs.
        tz (ZoneInfo): Display timezone.
        start (datetime): Window start.
        end (datetime): Window end.

    Returns:
        list[Event]: Merged events sorted by start time.
    """
    events: list[Event] = []
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        for url in urls:
            r = client.get(url)
            r.raise_for_status()
            events.extend(parse_events(r.content, tz, start, end))
    return sorted(events, key=lambda e: (e.start, not e.all_day, e.title))

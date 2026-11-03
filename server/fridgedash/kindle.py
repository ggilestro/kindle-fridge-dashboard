"""Track the Kindle's hourly check-ins: battery, charging, last seen, next expected wake."""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel

# The Kindle is "online" until this long after the wake it announced.
GRACE = timedelta(minutes=10)
# Fallback when the Kindle did not announce its next wake (older dash.sh).
FALLBACK_WINDOW = timedelta(minutes=75)


class KindleStatus(BaseModel):
    """Latest check-in, persisted as JSON so it survives container restarts."""

    battery: int | None = None
    charging: bool | None = None
    last_seen: datetime | None = None
    next_expected: datetime | None = None
    ip: str | None = None


class KindleTracker:
    """Records check-ins to ``kindle.json`` (latest) and ``battery.csv`` (history)."""

    def __init__(self, data_dir: Path):
        """
        Args:
            data_dir (Path): Directory for ``kindle.json`` and ``battery.csv``.
        """
        self.json_path = data_dir / "kindle.json"
        self.csv_path = data_dir / "battery.csv"
        self.status = KindleStatus()
        if self.json_path.exists():
            self.status = KindleStatus.model_validate_json(self.json_path.read_text())

    @property
    def battery(self) -> int | None:
        """Last reported battery percent."""
        return self.status.battery

    def check_in(
        self,
        battery: int | None,
        charging: bool | None,
        next_wake: int | None,
        client: str,
        now: datetime | None = None,
    ) -> None:
        """
        Record a check-in from the Kindle.

        Args:
            battery (int | None): Battery percent.
            charging (bool | None): Whether it is on a charger.
            next_wake (int | None): Epoch seconds of its next scheduled wake.
            client (str): Reporting client address.
            now (datetime | None): Current time (for tests).
        """
        now = now or datetime.now(timezone.utc)
        self.status = KindleStatus(
            battery=battery,
            charging=charging,
            last_seen=now,
            next_expected=(
                datetime.fromtimestamp(next_wake, timezone.utc) if next_wake else None
            ),
            ip=client or None,
        )
        tmp = self.json_path.with_name(f".{self.json_path.name}.tmp")
        tmp.write_text(self.status.model_dump_json())
        os.replace(tmp, self.json_path)
        chg = "" if charging is None else int(charging)
        pct = "" if battery is None else battery
        with self.csv_path.open("a") as f:
            f.write(f"{now.isoformat(timespec='seconds')},{pct},{client},{chg}\n")

    def online(self, now: datetime | None = None) -> bool:
        """
        Whether the Kindle is keeping to its schedule.

        It sleeps between check-ins, so "online" means it has not missed the wake it
        announced (plus a grace period), not that it answers right now.

        Args:
            now (datetime | None): Current time (for tests).

        Returns:
            bool: True if the last check-in is still current.
        """
        now = now or datetime.now(timezone.utc)
        s = self.status
        if s.last_seen is None:
            return False
        if s.next_expected is not None:
            return now <= s.next_expected + GRACE
        return now - s.last_seen <= FALLBACK_WINDOW

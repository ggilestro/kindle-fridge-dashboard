"""Tests for the Kindle check-in tracker."""

from datetime import datetime, timedelta, timezone

from fridgedash.kindle import FALLBACK_WINDOW, GRACE, KindleTracker

T0 = datetime(2026, 11, 1, 18, 0, 15, tzinfo=timezone.utc)
NEXT = int(datetime(2026, 11, 1, 19, 0, tzinfo=timezone.utc).timestamp())


def test_online_follows_announced_wake(tmp_path):
    k = KindleTracker(tmp_path)
    assert not k.online(T0)  # never seen
    k.check_in(87, False, NEXT, "kindle", now=T0)
    wake = datetime.fromtimestamp(NEXT, timezone.utc)
    assert k.online(T0 + timedelta(minutes=30))
    assert k.online(wake + GRACE)
    assert not k.online(wake + GRACE + timedelta(seconds=1))


def test_online_survives_quiet_hours_gap(tmp_path):
    k = KindleTracker(tmp_path)
    night = datetime(2026, 11, 1, 22, 0, 15, tzinfo=timezone.utc)
    morning = int(datetime(2026, 11, 2, 6, 0, tzinfo=timezone.utc).timestamp())
    k.check_in(60, False, morning, "kindle", now=night)
    assert k.online(night + timedelta(hours=7))


def test_fallback_without_next_wake(tmp_path):
    k = KindleTracker(tmp_path)
    k.check_in(50, None, None, "kindle", now=T0)
    assert k.online(T0 + FALLBACK_WINDOW)
    assert not k.online(T0 + FALLBACK_WINDOW + timedelta(seconds=1))


def test_state_persists_and_csv_history(tmp_path):
    k = KindleTracker(tmp_path)
    k.check_in(70, True, NEXT, "kindle", now=T0)
    k.check_in(69, False, NEXT, "kindle", now=T0 + timedelta(hours=1))
    reloaded = KindleTracker(tmp_path)
    assert reloaded.battery == 69 and reloaded.status.charging is False
    rows = (tmp_path / "battery.csv").read_text().splitlines()
    assert rows[0].endswith(",70,kindle,1") and rows[1].endswith(",69,kindle,0")
    assert not list(tmp_path.glob(".*.tmp"))

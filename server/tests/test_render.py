"""Tests for the view model, HTML template and PNG conversion."""

import shutil
from datetime import datetime, timedelta

import pytest
from conftest import NOW, TZ, sample_data
from PIL import Image

from fridgedash.render import (
    build_agenda,
    condition_icon,
    day_label,
    build_bins,
    build_context,
    chunk,
    render_html,
    render_pages,
    to_kindle_png,
)
from fridgedash.sources import Event


def ev(title, start, hours=1, all_day=False):
    return Event(
        title=title, start=start, end=start + timedelta(hours=hours), all_day=all_day
    )


def test_day_label():
    assert day_label(NOW, NOW) == "Today"
    assert day_label(NOW + timedelta(days=1), NOW) == "Tomorrow"
    assert day_label(NOW + timedelta(days=2), NOW) == "Tue 3 Nov"


def test_condition_icon_night_and_unknown():
    night = datetime(2026, 11, 1, 22, tzinfo=TZ)
    assert condition_icon("partlycloudy", night) == "weather-night-partly-cloudy"
    assert (
        condition_icon("partlycloudy", NOW.replace(hour=12)) == "weather-partly-cloudy"
    )
    assert condition_icon("not-a-condition") == "alert-circle-outline"
    assert condition_icon(None) == "alert-circle-outline"


def test_agenda_skips_ended_and_marks_multiday(settings):
    groups, more = build_agenda(sample_data(settings).events, NOW, max_lines=20)
    titles = [e["title"] for g in groups for e in g["events"]]
    assert "Morning run" not in titles  # ended this morning
    assert groups[0]["label"] == "Today"
    trip = next(e for g in groups for e in g["events"] if e["title"] == "Rome trip")
    assert trip["time"] == "→ Sat"
    assert more == 0


def test_agenda_respects_line_budget():
    events = [ev(f"E{i}", NOW + timedelta(hours=1 + i)) for i in range(10)]
    groups, more = build_agenda(events, NOW, max_lines=4)
    lines = sum(1 + len(g["events"]) for g in groups)
    assert lines <= 4
    assert more == 10 - sum(len(g["events"]) for g in groups)


def test_agenda_ongoing_all_day_event_shows_today():
    start = datetime(2026, 10, 30, tzinfo=TZ)
    groups, _ = build_agenda(
        [
            Event(
                title="Half term",
                start=start,
                end=start + timedelta(days=5),
                all_day=True,
            )
        ],
        NOW,
        max_lines=5,
    )
    assert groups[0]["label"] == "Today"


def test_render_html_full_and_low_battery(settings):
    html = render_html(sample_data(settings), settings)
    for text in ("1 November", "Swimming", "Sourdough bread", "Kindle 87%", "Docked"):
        assert text in html
    low = render_html(sample_data(settings, battery=5), settings)
    assert "please charge" in low


def test_render_html_with_everything_missing(settings):
    data = sample_data(settings, battery=None)
    data.weather, data.events, data.shopping = None, None, None
    data.errors = ["weather", "events", "shopping"]
    html = render_html(data, settings)
    assert "No calendar set up" in html and "List unavailable" in html
    settings.ical_urls = ["https://example.org/cal.ics"]
    assert "Calendar unavailable" in render_html(data, settings)
    assert "⚠ weather, events, shopping" in html


def test_to_kindle_png_pads_and_quantizes(tmp_path, settings):
    src = tmp_path / "src.png"
    gradient = Image.linear_gradient("L").resize((600, 700))
    gradient.convert("RGB").save(src)
    dst = tmp_path / "out.png"
    to_kindle_png(src, dst, settings)
    out = Image.open(dst)
    assert out.size == (600, 800) and out.mode == "L"
    levels = set(out.tobytes())
    assert len(levels) <= 16 and {0, 255} <= levels
    assert out.getpixel((10, 790)) == 255  # padded area is white
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.skipif(not shutil.which("chromium"), reason="chromium not installed")
def test_render_pages_end_to_end(tmp_path, settings):
    (tmp_path / "page9.png").write_bytes(b"stale")
    data = sample_data(settings)
    data.shopping = [f"item {i}" for i in range(50)]  # page 1 + 2 shopping pages
    html, pages = render_pages(data, settings, tmp_path)
    assert pages == 3 and "item 49" in html
    for i in (1, 2, 3):
        img = Image.open(tmp_path / f"page{i}.png")
        assert img.size == (600, 800) and img.mode == "L"
        assert len(set(img.tobytes())) <= 16
        assert min(img.tobytes()) == 0  # something black was drawn
    assert not (tmp_path / "page9.png").exists()  # stale page removed


def test_build_bins_groups_by_day(settings):
    groups = build_bins(sample_data(settings).bins, NOW)
    assert groups[0]["label"] == "Tomorrow" and groups[0]["soon"] is True
    assert groups[0]["names"] == ["Food waste", "Mixed recycling"]
    assert groups[1]["label"] == "Mon 9 Nov" and groups[1]["soon"] is False
    assert len(groups[1]["names"]) == 3


def test_build_bins_drops_past_and_handles_empty():
    from datetime import date

    from fridgedash.sources import Bin

    assert build_bins([], NOW) == []
    past = [Bin(name="Old", date=date(2026, 10, 30))]
    assert build_bins(past, NOW) == []


def test_chunk_and_shopping_pagination(settings):
    assert chunk([], 5) == [[]]
    assert chunk(list(range(7)), 3) == [[0, 1, 2], [3, 4, 5], [6]]
    data = sample_data(settings)
    data.shopping = [f"i{n}" for n in range(23)]
    ctx = build_context(data, settings)
    assert ctx["page_count"] == 2
    assert [len(c) for c in ctx["shop_pages"][0]] == [12, 11]  # balanced columns
    assert ctx["shopping_more"] == 23 - len(ctx["shopping"])
    data.shopping = []
    ctx = build_context(data, settings)
    assert ctx["page_count"] == 2 and ctx["shopping_more"] == 0  # empty list page


def test_render_html_bins_soon_is_highlighted(settings):
    html = render_html(sample_data(settings), settings)
    assert 'class="bins soon"' in html and "Tomorrow: Food waste" in html

from datetime import datetime
from pathlib import Path

from app.core.albums import calendar_albums
from app.core.library import MediaItem


def item(path, date=None, kind="image"):
    return MediaItem(Path(path), kind, date, 1, 2)


def test_year_albums_count_mixed_media():
    entries = [item("IMG.jpg", datetime(2026, 1, 1)),
               item("VID.mp4", datetime(2026, 2, 1), "video"),
               item("older.jpg", datetime(2025, 3, 1)), item("unknown.jpg")]
    albums = calendar_albums(entries)
    assert [album.route for album in albums] == [("year", 2025), ("year", 2026), ("unknown",)]
    assert (albums[1].photos, albums[1].videos, albums[1].months) == (1, 1, 2)


def test_month_albums_are_chronological_and_keep_years_separate():
    entries = [item("feb.mp4", datetime(2026, 2, 1), "video"),
               item("jan.jpg", datetime(2026, 1, 2)), item("jan.mp4", datetime(2026, 1, 1), "video"),
               item("previous.jpg", datetime(2025, 1, 1)), item("unknown.jpg")]
    albums = calendar_albums(entries, 2026)
    assert [album.route for album in albums] == [("month", 2026, 1), ("month", 2026, 2)]
    assert (albums[0].photos, albums[0].videos) == (1, 1)
    assert (albums[1].photos, albums[1].videos) == (0, 1)


def test_empty_calendar_and_missing_year():
    assert calendar_albums([]) == []
    assert calendar_albums([item("unknown.jpg")], 2026) == []

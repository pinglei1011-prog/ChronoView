import hashlib
import os
from datetime import datetime
from pathlib import Path
from threading import Event

import pytest

from app.core.filename_parser import parse_filename
from app.core.library import MediaItem, calendar_counts, filter_items, sort_items
from app.core.scanner import scan_library


@pytest.mark.parametrize("name, expected", [
    ("IMG20260101103000.jpg", datetime(2026, 1, 1, 10, 30)),
    ("VID20260215150030.mov", datetime(2026, 2, 15, 15, 0, 30)),
    ("img20240229010203.JPEG", datetime(2024, 2, 29, 1, 2, 3)),
    ("IMG20260230000000.jpg", None),
    ("IMG20250229000000.jpg", None),
    ("IMG20261301000000.jpg", None),
    ("IMG20260101240000.jpg", None),
    ("IMG20260101006000.jpg", None),
    ("VID20260101000060.mp4", None),
    ("IMG00000101000000.jpg", None),
    ("IMG2026010110300.jpg", None),
    ("IMG202601011030001.jpg", None),
    ("IMG20260101103000_edited.jpg", None),
    ("20260101103000.jpg", None),
    ("IMG２０２６０１０１１０３０００.jpg", None),
    ("hello.png", None),
])
def test_filename_dates(name, expected):
    assert parse_filename(name) == expected


def item(path, date=None, kind="image"):
    return MediaItem(Path(path), kind, date, 1, 2)


def test_mixed_sorting_and_stable_ties():
    first = datetime(2026, 1, 1, 10)
    second = datetime(2026, 1, 1, 10, 30)
    third = datetime(2026, 1, 1, 11)
    items = [item("z/unknown.jpg"), item("b/tie.jpg", first),
             item("a/IMG.jpg", first), item("VID.mp4", second, "video"), item("IMG.jpg", third)]
    assert [x.path.as_posix() for x in sort_items(items, False)] == [
        "a/IMG.jpg", "b/tie.jpg", "VID.mp4", "IMG.jpg", "z/unknown.jpg"]
    assert [x.path.as_posix() for x in sort_items(items, True)] == [
        "IMG.jpg", "VID.mp4", "a/IMG.jpg", "b/tie.jpg", "z/unknown.jpg"]


def test_calendar_uses_filename_not_directories(tmp_path):
    folder = tmp_path / "2025" / "12" / "多层 & [回忆]"
    folder.mkdir(parents=True)
    (folder / "IMG20260101103000.jpg").write_bytes(b"test")
    (folder / "VID20260101110000.mp4").write_bytes(b"test")
    (folder / "IMG20260230000000.png").write_bytes(b"test")
    (folder / "notes.txt").write_text("ignore")
    result = scan_library(tmp_path)
    assert len(result.items) == 3
    assert len(filter_items(result.items, year=2026)) == 2
    assert len(filter_items(result.items, year=2026, month=1)) == 2
    assert len(filter_items(result.items, year=2025)) == 0
    assert len(filter_items(result.items, unknown=True)) == 1
    assert calendar_counts(result.items) == {(2026, 1): 2}


def test_same_filename_in_different_directories_and_read_only(tmp_path):
    for directory in [tmp_path / "a", tmp_path / "中文 空格", tmp_path / "层" / "2" / "3"]:
        directory.mkdir(parents=True)
        (directory / "IMG20260101103000.jpg").write_bytes(b"original-not-an-image")
    files = list(tmp_path.rglob("*.jpg"))
    before = {p: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in files}
    result = scan_library(tmp_path)
    assert len(result.items) == 3
    assert len({x.path for x in result.items}) == 3
    after = {p: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in files}
    assert before == after
    assert len(list(tmp_path.rglob("*.*"))) == 3


def test_missing_library_is_safe(tmp_path):
    result = scan_library(tmp_path / "not connected")
    assert result.unavailable
    assert result.error_count == 1
    assert result.items == []


def test_cancelled_scan(tmp_path):
    (tmp_path / "IMG20260101000000.jpg").touch()
    cancel = Event()
    cancel.set()
    result = scan_library(tmp_path, cancel)
    assert result.cancelled
    assert not result.items


def test_refresh_discovers_added_and_removed_files(tmp_path):
    first = tmp_path / "IMG20260101000000.jpg"
    first.touch()
    assert len(scan_library(tmp_path).items) == 1
    (tmp_path / "VID20260101003000.mp4").touch()
    assert len(scan_library(tmp_path).items) == 2
    first.unlink()  # Only our temporary test file, never a real photo.
    assert len(scan_library(tmp_path).items) == 1


def test_batching_and_progress(tmp_path):
    for i in range(520):
        (tmp_path / f"file{i}.jpg").touch()
    batches, progress = [], []
    result = scan_library(tmp_path, batch=batches.append, progress=lambda n, d: progress.append((n, d)))
    assert [len(b) for b in batches] == [256, 256, 8]
    assert sum(map(len, batches)) == len(result.items) == 520
    assert progress[-1] == (520, 1)


def test_permission_error_does_not_stop_other_folders(tmp_path, monkeypatch):
    denied = tmp_path / "denied"
    denied.mkdir()
    (tmp_path / "IMG20260101000000.jpg").touch()
    original = os.scandir

    def guarded(path):
        if Path(path) == denied:
            raise PermissionError("test: access denied")
        return original(path)

    monkeypatch.setattr(os, "scandir", guarded)
    result = scan_library(tmp_path)
    assert result.error_count == 1
    assert len(result.items) == 1
    assert not result.unavailable


def test_directory_symlink_loop_is_skipped(tmp_path, monkeypatch):
    # Windows junctions can be created without enabling developer symlink privileges.
    import subprocess
    child = tmp_path / "child"
    child.mkdir()
    (child / "IMG20260101000000.jpg").touch()
    link = child / "loop"
    if os.name == "nt":
        process = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(tmp_path)], capture_output=True)
        if process.returncode:
            pytest.skip("Cannot create test junction")
    else:
        link.symlink_to(tmp_path, target_is_directory=True)
    try:
        result = scan_library(tmp_path)
        assert len(result.items) == 1
        assert result.directories == 2
    finally:
        if os.name == "nt":
            os.rmdir(link)  # Remove only the temporary junction itself.
        else:
            link.unlink()

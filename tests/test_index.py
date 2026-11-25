from pathlib import Path

from app.core.scanner import scan_library
from app.storage.index import LibraryIndex
from app.ui.main_window import MainWindow
from PySide6.QtCore import QSettings
from tests.test_images import wait_until
from tests.test_ui import make_library


def test_index_reconcile_and_libraries(tmp_path):
    root = make_library(tmp_path / "照片")
    index = LibraryIndex(tmp_path / "local" / "library.sqlite3")
    assert index.load(root) is None
    items = scan_library(root).items
    index.save(root, items)
    assert set(index.load(root)) == set(items)
    index.save(root, items[:2])
    assert set(index.load(root)) == set(items[:2])
    other = tmp_path / "other"
    index.save(other, [])
    assert index.load(other) == []
    assert len(index.load(root)) == 2


def test_index_restore_without_scanning_and_offline(tmp_path, qapp, monkeypatch):
    root = make_library(tmp_path / "照片库")
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("library", str(root))
    index = LibraryIndex(tmp_path / "library.sqlite3")
    entries = scan_library(root).items
    index.save(root, entries)
    # Simulate a disconnected root while retaining its index snapshot.
    # Use the actual same library identity; never save another root's absolute
    # paths as an offline alias, which would itself be a cross-library leak.
    original_is_dir = Path.is_dir
    monkeypatch.setattr(Path, "is_dir", lambda path: False if path == root else original_is_dir(path))
    monkeypatch.setattr("app.ui.main_window.scan_library", lambda *args: (_ for _ in ()).throw(
        AssertionError("Startup should restore the index without enumerating directories")))
    window = MainWindow(settings)
    window.show()
    try:
        assert window.startup_pending and not window.items
        window.safe_page.resume.click()
        wait_until(qapp, lambda: window.scan is None and len(window.items) == 5)
        assert "离线" in window.banner.text()
        assert set(window.items) == set(entries)
    finally:
        window.close()
        qapp.processEvents()


def test_changed_photo_is_readable_from_restored_index_without_refresh(tmp_path, qapp, monkeypatch):
    import os
    from PIL import Image
    from app.services.thumbnail_service import cache_key
    from PySide6.QtCore import Qt
    root = tmp_path / "photo library"
    root.mkdir()
    path = root / "IMG20261016103000.jpg"
    Image.new("RGB", (120, 60), "red").save(path)
    entries = scan_library(root).items
    index = LibraryIndex(tmp_path / "library.sqlite3")
    index.save(root, entries)
    Image.new("RGB", (120, 60), "blue").save(path)
    os.utime(path, ns=(entries[0].mtime_ns + 2_000_000_000, entries[0].mtime_ns + 2_000_000_000))
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("library", str(root))
    monkeypatch.setattr("app.ui.main_window.scan_library", lambda *args: (_ for _ in ()).throw(
        AssertionError("Index restore must not require a full rescan")))
    window = MainWindow(settings)
    window.show()
    try:
        assert window.startup_pending and not window.items
        window.safe_page.resume.click()
        wait_until(qapp, lambda: window.scan is None and len(window.items) == 1)
        window.select_route(("month", 2026, 10))
        current = window.items[0]
        assert current.path == entries[0].path and current.mtime_ns != entries[0].mtime_ns
        window.thumbnails.get(current)
        wait_until(qapp, lambda: cache_key(current) in window.thumbnails.memory)
        pixmap, error = window.thumbnails.get(current)
        assert not error and not pixmap.isNull()
        assert pixmap.toImage().pixelColor(10, 10).blue() > 200
        assert "文件已更改" not in window.grid.model().index(0, 0).data(Qt.ItemDataRole.ToolTipRole)
    finally:
        window.close()
        qapp.processEvents()

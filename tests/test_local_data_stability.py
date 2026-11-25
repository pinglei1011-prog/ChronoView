import ctypes as C
from ctypes import wintypes as W
import logging
from logging.handlers import RotatingFileHandler
import sys
from threading import Event
import time

import pytest
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QMessageBox

from app.core.scanner import ScanResult, scan_library
from app.services.local_logs import PrivateFormatter
from app.storage.index import LibraryIndex
from app.ui.main_window import MainWindow
from app.ui.privacy_preview import handle_private_preview
from tests.test_images import wait_until
from tests.test_ui import make_library


@pytest.mark.parametrize("message", [
    r"Cannot open F:\private family\Vacation in 2026.mp4",
    'decoder: 无法打开 我的私密 照片.jpg',
    r"opening \\server\secret\library",
    r"PermissionError: D:/private collection/path",
])
def test_logs_never_reveal_media_or_library_names(message):
    record = logging.LogRecord("test", logging.WARNING, __file__, 1, message, (), None)
    text = PrivateFormatter().format(record)
    assert "private" not in text and "Vacation" not in text and "私密" not in text and "server" not in text


def test_log_cleanup_does_not_truncate_unrelated_handlers(tmp_path, monkeypatch):
    import app.services.local_logs as logs
    owned, elsewhere = tmp_path / "logs", tmp_path / "elsewhere"
    owned.mkdir(); elsewhere.mkdir()
    target = owned / "chronoview-123.log"
    target.write_text("private")
    foreign = owned / "family.txt"
    foreign.write_text("keep")
    external = elsewhere / "chronoview-456.log"
    handler = RotatingFileHandler(external)
    handler.stream.write("keep external"); handler.flush()
    logger = logging.getLogger()
    logger.addHandler(handler)
    monkeypatch.setattr(logs, "_directory", owned)
    monkeypatch.setattr(logs, "_native", None)
    try:
        logs.clear_logs()
        assert not target.exists()
        assert foreign.read_text() == "keep"
        assert external.read_text() == "keep external"
    finally:
        logger.removeHandler(handler); handler.close()


def test_clear_records_removes_sql_and_changes_generation(tmp_path):
    root = make_library(tmp_path / "originals")
    index = LibraryIndex(tmp_path / "library.sqlite3")
    items = scan_library(root).items
    index.save(root, items)
    before = index.generation()
    index.clear()
    assert before != index.generation()
    assert index.load(root) is None
    with index.connect() as db:
        for table in ("media", "libraries", "media_v2", "libraries_v2", "aliases_v2"):
            assert db.execute("SELECT count(*) FROM " + table).fetchone()[0] == 0
    contents = index.path.read_bytes()
    assert items[0].path.name.encode() not in contents
    assert len(scan_library(root).items) == len(items)


def test_record_clear_requires_confirmation_and_blocks_new_work(tmp_path, qapp, monkeypatch):
    root = make_library(tmp_path / "originals")
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("library", str(root))
    window = MainWindow(settings, auto_load=False)
    window.show(); window.show_settings()
    wait_until(qapp, lambda: window.thumbnails._maintenance_task is None)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    window.clear_local_data(True)
    assert settings.contains("library") and not window._resetting_history
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.clear_local_data(True)
    assert window._resetting_history and window.route == ("privacy",)
    window.start_scan(root)
    window.resume_browsing(); window.open_previous_library(); window.refresh()
    assert window.scan is None and not settings.contains("library")
    wait_until(qapp, lambda: not window._resetting_history)
    assert window.items == [] and window.grid.media_model.items == [] and window.root is None
    assert window.settings_dialog.cache_button.isEnabled()
    window.close()
    wait_until(qapp, lambda: window._close_ready)


def test_close_during_blocked_scan_stays_responsive_and_ignores_late_data(tmp_path, qapp, monkeypatch):
    root = make_library(tmp_path / "originals")
    entered, release = Event(), Event()
    entries = scan_library(root).items
    def blocked(directory, cancel, progress, batch):
        entered.set()
        release.wait(5)
        batch(entries)
        return ScanResult(items=entries, cancelled=cancel.is_set())
    monkeypatch.setattr("app.ui.main_window.scan_library", blocked)
    window = MainWindow(QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat), auto_load=False)
    window.show(); window.start_scan(root)
    wait_until(qapp, entered.is_set)
    ticks = []
    QTimer.singleShot(20, lambda: ticks.append(True))
    start = time.monotonic(); window.close()
    assert time.monotonic() - start < .2 and window._closing and not window._close_ready
    wait_until(qapp, lambda: bool(ticks))
    assert window.route == ("privacy",) and not window.grid.media_model.items
    release.set()
    wait_until(qapp, lambda: window._close_ready)
    assert not window.grid.media_model.items and window.scan is None


def test_idle_close_really_hides_window_after_initial_close_event(tmp_path, qapp):
    window = MainWindow(QSettings(str(tmp_path / 'idle-close.ini'), QSettings.Format.IniFormat))
    window.show()
    qapp.processEvents()
    window.close()
    wait_until(qapp, lambda: window._close_ready and not window.isVisible())


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows DWM/GDI')
def test_private_taskbar_bitmaps_do_not_leak_gdi_handles(tmp_path, qapp):
    window = MainWindow(QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat))
    class Message:
        pass
    msg = W.MSG()
    msg.hwnd = int(window.winId())
    msg.message = 0x323
    msg.lParam = (240 << 16) | 120
    kernel, user = C.windll.kernel32, C.windll.user32
    kernel.GetCurrentProcess.restype = W.HANDLE
    user.GetGuiResources.argtypes = [W.HANDLE, W.DWORD]
    user.GetGuiResources.restype = W.DWORD
    process = kernel.GetCurrentProcess()
    before = user.GetGuiResources(process, 0)
    for _ in range(100):
        assert handle_private_preview(window, C.addressof(msg))
    assert user.GetGuiResources(process, 0) <= before + 1
    msg.message = 123
    assert not handle_private_preview(window, C.addressof(msg))
    window.close()
    wait_until(qapp, lambda: window._close_ready)

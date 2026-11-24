from pathlib import Path

from PIL import Image
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest

from app.core.scanner import scan_library
from app.ui.main_window import MainWindow
from app.ui.photo_viewer import PhotoViewer
from tests.test_images import wait_until


def make_library(root):
    folder = root / "错误年份 2025" / "子目录"
    folder.mkdir(parents=True)
    for name in ["IMG20260101100000.jpg", "IMG20260202120000.jpg", "IMG20240101000000.jpg", "invalid.jpg"]:
        Image.new("RGB", (120, 60), "#4389f5").save(folder / name)
    (folder / "VID20260101103000.mp4").write_bytes(b"video-placeholder")
    return root


def test_ui_scan_filter_sort_and_offline_preservation(tmp_path, qapp):
    root = make_library(tmp_path / "照片库")
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, auto_load=False)
    window.show()
    try:
        window.start_scan(root)
        # Timer events and UI changes remain usable while a scan is running.
        window.toggle_theme()
        wait_until(qapp, lambda: window.scan is None)
        assert len(window.items) == 5
        assert window.counts.text() == "4 张照片  ·  1 个视频"
        assert window.grid.media_model.items[0].path.name == "IMG20260202120000.jpg"
        window.route = ("month", 2026, 1)
        window.update_view()
        assert len(window.grid.media_model.items) == 2
        window.sort_box.setCurrentIndex(1)
        assert [x.kind for x in window.grid.media_model.items] == ["image", "video"]
        window.go_back()
        assert window.route == ("year", 2026)
        assert len(window.grid.media_model.items) == 3
        window.go_back()
        assert window.route == ("all",)
        window.route = ("unknown",)
        window.update_view()
        assert len(window.grid.media_model.items) == 1
        snapshot = list(window.items)
        window.start_scan(tmp_path / "disconnected")
        wait_until(qapp, lambda: window.scan is None)
        assert window.items == snapshot
        assert window.root == root
        assert "不可访问" in window.banner.text()
        assert settings.value("library") == str(root)
    finally:
        window.close()
        qapp.processEvents()


def test_viewer_load_zoom_navigation_and_bad_file(tmp_path, qapp):
    root = make_library(tmp_path / "library")
    items = sorted(scan_library(root).items, key=lambda x: x.path.name)
    viewer = PhotoViewer(items, 0)
    viewer.show()
    try:
        wait_until(qapp, lambda: viewer.pages.currentWidget() == viewer.view)
        viewer.view.actual()
        assert viewer.view.transform().m11() == 1
        viewer.view.zoom(1.25)
        assert viewer.view.transform().m11() == 1.25
        viewer.view.fit()
        QTest.keyClick(viewer, Qt.Key.Key_Right)
        assert viewer.position == 1
        wait_until(qapp, lambda: viewer.pages.currentWidget() == viewer.view)
        video_index = next(i for i, x in enumerate(items) if x.kind == "video")
        viewer.position = video_index
        viewer.load()
        assert "第二阶段" in viewer.message.text()
        assert viewer.pages.currentWidget() == viewer.message
        viewer.toggle_fullscreen()
        assert viewer.isFullScreen()
        viewer.escape()
        assert not viewer.isFullScreen()
    finally:
        viewer.close()
        qapp.processEvents()


def test_settings_restore_and_added_files(tmp_path, qapp):
    root = make_library(tmp_path / "library")
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("library", str(root))
    settings.setValue("thumbnail_size", 220)
    window = MainWindow(settings)
    window.show()
    try:
        wait_until(qapp, lambda: window.scan is None and len(window.items) == 5)
        assert window.root == root
        assert window.grid.requested_edge == 220
        Image.new("RGB", (20, 20)).save(root / "IMG20261124000000.png")
        window.refresh()
        wait_until(qapp, lambda: window.scan is None)
        assert len(window.items) == 6
    finally:
        window.close()
        qapp.processEvents()


def test_cancel_running_scan_restores_snapshot(tmp_path, qapp, monkeypatch):
    from app.core.scanner import ScanResult
    root = make_library(tmp_path / "library")
    entries = scan_library(root).items
    settings = QSettings(str(tmp_path / "cancel.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, auto_load=False)
    window.root, window.items = root, entries

    def controlled_scan(root, cancel, progress, batch):
        batch(entries[:1])
        cancel.wait(3)
        return ScanResult(items=entries[:1], cancelled=cancel.is_set())

    monkeypatch.setattr("app.ui.main_window.scan_library", controlled_scan)
    window.show()
    try:
        window.start_scan(root)
        wait_until(qapp, lambda: len(window.items) == 1)
        assert window.scan is not None
        window.toggle_theme()  # GUI stays interactive while worker waits.
        window.cancel_scan()
        wait_until(qapp, lambda: window.scan is None)
        assert window.items == entries
        assert "已取消" in window.banner.text()
    finally:
        window.close()
        qapp.processEvents()


def test_double_click_opens_once_and_enter_works(tmp_path, qapp, monkeypatch):
    settings = QSettings(str(tmp_path / "click.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, auto_load=False)
    root = make_library(tmp_path / "library")
    window.items = scan_library(root).items
    window.update_view()
    opened = []

    class FakeViewer:
        def __init__(self, items, index, parent):
            opened.append(index)

        def exec(self):
            pass

        def deleteLater(self):
            pass

    monkeypatch.setattr("app.ui.main_window.PhotoViewer", FakeViewer)
    window.show()
    try:
        qapp.processEvents()
        index = window.grid.media_model.index(0, 0)
        rect = window.grid.visualRect(index)
        QTest.mouseClick(window.grid.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
        QTest.mouseDClick(window.grid.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
        assert opened == [0]
        window.grid.setFocus()
        QTest.keyClick(window.grid, Qt.Key.Key_Return)
        assert opened == [0, 0]
    finally:
        window.close()
        qapp.processEvents()

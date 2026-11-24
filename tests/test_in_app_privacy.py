from threading import Event

import pytest
from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtTest import QTest

from app.core.scanner import ScanResult, scan_library
from app.ui.main_window import MainWindow
from tests.test_images import wait_until
from tests.test_ui import make_library


def prepared_window(tmp_path):
    root = make_library(tmp_path / "private library")
    window = MainWindow(QSettings(str(tmp_path / "session.ini"), QSettings.Format.IniFormat),
                        auto_load=False)
    window.root = root
    window.items = scan_library(root).items
    window.select_route(("month", 2026, 1))
    window.show()
    return window, root


def assert_hidden(window, root):
    assert window.route == ("privacy",)
    assert window.browser.isVisible() and window.pages.currentWidget() == window.safe_page
    assert window.grid.media_model.items == [] and window.albums.album_model.items == []
    assert window.visible_items == [] and window.thumbnails.paused
    assert not window.counts.isVisible() and not window.statusBar().isVisible()
    assert not window.banner.isVisible() and not window.sort_box.isVisible()
    assert str(root) not in window.path_label.text() + window.path_label.toolTip()
    assert window.navigation.topLevelItemCount() == 1
    assert window.navigation.topLevelItem(0).childCount() == 0


@pytest.mark.parametrize("dark", [False, True])
def test_main_privacy_buttons_hide_metadata_and_resume_classification(tmp_path, qapp, monkeypatch, dark):
    window, root = prepared_window(tmp_path)
    if window.dark != dark:
        window.toggle_theme()
    try:
        qapp.processEvents()
        expected = list(window.grid.media_model.items)
        retained = list(window.items)
        QTest.mouseClick(window.privacy_button, Qt.MouseButton.LeftButton)
        assert_hidden(window, root)
        assert window.items == retained
        picker_directories = []

        def cancelled_picker(parent, title, directory):
            picker_directories.append(directory)
            return ""

        monkeypatch.setattr("app.ui.main_window.QFileDialog.getExistingDirectory", cancelled_picker)
        window.choose_button.click()
        assert picker_directories and str(root) not in picker_directories
        assert_hidden(window, root)
        window.privacy_button.click()
        QTest.keyClick(window, Qt.Key.Key_F5)
        window.toggle_theme()
        window.resize(1100, 760)
        window.update_view()
        assert_hidden(window, root)
        assert window.scan is None
        window.safe_page.resume.click()
        assert window.route == ("month", 2026, 1)
        assert window.grid.media_model.items == expected and not window.thumbnails.paused
        assert window.counts.isVisible() and window.path_label.text() == str(root)
        window.set_sidebar_visible(False)
        QTest.mouseClick(window.privacy_action, Qt.MouseButton.LeftButton)
        assert_hidden(window, root)
        QTest.keyClick(window, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
        qapp.processEvents()
        assert_hidden(window, root)
        assert window.sidebar.isVisible()
        # Deliberately selecting All Photos can also leave the safe page.
        item = window.navigation.topLevelItem(0)
        QTest.mouseClick(window.navigation.viewport(), Qt.MouseButton.LeftButton,
                         pos=window.navigation.visualItemRect(item).center())
        assert window.route == ("all",) and not window.thumbnails.paused
        assert len(window.grid.media_model.items) == len(retained)
    finally:
        window.close()
        qapp.processEvents()


@pytest.mark.parametrize("outcome", ["success", "cancelled", "unavailable"])
def test_scan_completion_cannot_leave_in_app_privacy(tmp_path, qapp, monkeypatch, outcome):
    window, root = prepared_window(tmp_path)
    entries = list(window.items)
    ready = Event()

    def controlled_scan(directory, cancel, progress, batch):
        batch(entries[:1])
        ready.wait(3)
        return ScanResult(items=entries, cancelled=outcome == "cancelled",
                          unavailable=outcome == "unavailable")

    monkeypatch.setattr("app.ui.main_window.scan_library", controlled_scan)
    try:
        window.start_scan(root)
        wait_until(qapp, lambda: len(window.items) == 1)
        window.show_privacy()
        window.preview_scan()
        assert_hidden(window, root)
        ready.set()
        wait_until(qapp, lambda: window.scan is None)
        assert_hidden(window, root)
        window.safe_page.resume.click()
        assert window.route == ("month", 2026, 1)
        assert window.pages.currentWidget() == window.grid and not window.thumbnails.paused
    finally:
        ready.set()
        window.close()
        qapp.processEvents()


def test_viewer_privacy_shortcut_closes_viewer_and_keeps_media_hidden(tmp_path, qapp):
    window, root = prepared_window(tmp_path)
    observed = []
    hide_timer = QTimer(window)
    hide_timer.setSingleShot(True)

    def hide():
        viewer = window.active_viewer
        observed.append(viewer)
        viewer.activateWindow()
        viewer.setFocus()
        QTest.qWait(20)
        QTest.keyClick(viewer, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)

    hide_timer.timeout.connect(hide)
    timeout = QTimer(window)
    timeout.setSingleShot(True)
    timeout.timeout.connect(lambda: window.active_viewer.close() if window.active_viewer else None)
    try:
        qapp.processEvents()
        hide_timer.start(120)
        timeout.start(2000)
        image = next(i for i, item in enumerate(window.grid.media_model.items) if item.kind == "image")
        window.open_item(window.grid.media_model.index(image, 0))
        assert observed and window.active_viewer is None
        assert not window.viewer_open
        assert_hidden(window, root)
        window.safe_page.resume.click()
        assert not window.thumbnails.paused
    finally:
        timeout.stop()
        hide_timer.stop()
        window.close()
        qapp.processEvents()

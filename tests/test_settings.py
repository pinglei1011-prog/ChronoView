import hashlib

import pytest
from PIL import Image
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QMessageBox

from app import __display_version__
from app.core.scanner import scan_library
from app.ui.main_window import MainWindow
from app.ui.settings_dialog import RELEASES_URL, REPOSITORY_URL
from tests.test_images import wait_until


@pytest.mark.parametrize("dark", [False, True])
def test_settings_open_from_privacy_without_loading_library(tmp_path, qapp, monkeypatch, dark):
    settings = QSettings(str(tmp_path / "private.ini"), QSettings.Format.IniFormat)
    remembered = tmp_path / "private album"
    settings.setValue("library", str(remembered))
    settings.setValue("dark", dark)
    window = MainWindow(settings)
    window.show()
    monkeypatch.setattr(window, "start_scan", lambda *a, **kw: pytest.fail("Settings must not open a library"))
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: pytest.fail("Opening settings must stay offline"))
    try:
        assert window.settings_button.text() == "设置"
        assert not window.settings_button.icon().isNull()
        sidebar_text = [label.text() for label in window.sidebar.findChildren(QLabel)]
        assert all(__display_version__ not in text and "本地只读" not in text for text in sidebar_text)
        QTest.mouseClick(window.settings_button, Qt.MouseButton.LeftButton)
        qapp.processEvents()
        dialog = window.settings_dialog
        assert dialog.isVisible() and dialog.isModal()
        assert dialog.dark is dark
        assert dialog.version_label.text() == f"{__display_version__} 正式版"
        assert not dialog.app_icon.pixmap().isNull()
        assert dialog.app_name.text() == "ChronoView" and "瞬间" in dialog.tagline.text()
        assert "只读" in dialog.privacy_note.text() and "不加密" in dialog.privacy_note.text()
        assert window.route == ("privacy",) and window.pages.currentWidget() is window.safe_page
        assert window.startup_pending and window.scan is None and not window.items
        assert not window.grid.media_model.items
        assert window.root == remembered and settings.value("library") == str(remembered)
        dialog.done_button.click()
        assert not dialog.isVisible() and not window.settings_button.isChecked()
        window.show_settings()
        assert window.settings_dialog is dialog
        dialog.reject()
        assert window.route == ("privacy",) and window.startup_pending
    finally:
        window.close()
        qapp.processEvents()


@pytest.mark.parametrize("dark", [False, True])
def test_settings_preferences_share_state_and_persist(tmp_path, qapp, dark):
    settings = QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat)
    settings.setValue("dark", dark)
    window = MainWindow(settings)
    window.show()
    try:
        window.show_settings()
        dialog = window.settings_dialog
        (dialog.light_button if dark else dialog.dark_button).click()
        assert window.dark is not dark and dialog.dark is not dark
        assert settings.value("dark", type=bool) is not dark
        assert dialog.light_button.isChecked() is dark
        assert dialog.dark_button.isChecked() is not dark
        # The switch uses the same persistence path as the existing sidebar checkbox.
        dialog.remember_switch.click()
        assert not window.remember_checkbox.isChecked() and not window.remember_library
        assert settings.value("remember_library", type=bool) is False
        assert not settings.contains("library")
        window.remember_checkbox.setChecked(True)
        assert dialog.remember_switch.isChecked() and window.remember_library
        assert window.route == ("privacy",) and window.scan is None
        dialog.done_button.click()
        window.toggle_theme()
        window.show_settings()
        assert dialog.dark is dark
        assert dialog.dark_button.isChecked() is dark
    finally:
        window.close()
        qapp.processEvents()
    reopened = MainWindow(settings)
    try:
        assert reopened.dark is dark and reopened.remember_library
    finally:
        reopened.close()
        qapp.processEvents()


def test_settings_links_are_explicit_and_licenses_remain_available(tmp_path, qapp, monkeypatch):
    urls, notices = [], []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: urls.append(url.toString()) or True)
    monkeypatch.setattr(QMessageBox, "about", lambda parent, title, text: notices.append((title, text)))
    window = MainWindow(QSettings(str(tmp_path / "links.ini"), QSettings.Format.IniFormat))
    window.show()
    try:
        window.show_settings()
        dialog = window.settings_dialog
        qapp.processEvents()
        assert not urls
        QTest.mouseClick(dialog.repository_button, Qt.MouseButton.LeftButton)
        QTest.mouseClick(dialog.updates_button, Qt.MouseButton.LeftButton)
        assert urls == [REPOSITORY_URL, RELEASES_URL]
        dialog.licenses_button.click()
        assert notices[0][0] == "开源许可"
        assert "FFmpeg" in notices[0][1] and "LGPL" in notices[0][1] and "licenses" in notices[0][1]
        assert window.route == ("privacy",) and not window.grid.media_model.items
    finally:
        window.close()
        qapp.processEvents()


def test_settings_preserves_gallery_selection_order_and_scroll(tmp_path, qapp, monkeypatch):
    library = tmp_path / "album"
    library.mkdir()
    for day in range(1, 10):
        Image.new("RGB", (80, 60), "#90afcc").save(library / f"IMG202601{day:02d}100000.png")
    original = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in library.iterdir()}
    window = MainWindow(QSettings(str(tmp_path / "gallery.ini"), QSettings.Format.IniFormat), auto_load=False)
    window.resize(900, 580)
    window.root = library
    window.items = scan_library(library).items
    window.select_route(("month", 2026, 1))
    window.grid.set_thumbnail_size(280)
    window.show()
    qapp.processEvents()
    window.grid.setCurrentIndex(window.grid.model().index(5, 0))
    window.grid.verticalScrollBar().setValue(window.grid.verticalScrollBar().maximum())
    before = (window.route, list(window.grid.media_model.items), window.grid.currentIndex().row(),
              window.grid.verticalScrollBar().value(), window.sort_box.currentIndex())
    monkeypatch.setattr(window, "start_scan", lambda *a, **kw: pytest.fail("Settings must not rescan"))
    try:
        window.show_settings()
        window.settings_dialog.dark_button.click()
        window.settings_dialog.done_button.click()
        qapp.processEvents()
        after = (window.route, list(window.grid.media_model.items), window.grid.currentIndex().row(),
                 window.grid.verticalScrollBar().value(), window.sort_box.currentIndex())
        assert before[:3] == after[:3] and before[4] == after[4]
        # Native theme repolishing can change the scroll range by one pixel.
        assert abs(before[3] - after[3]) <= 2
        assert all(hashlib.sha256(p.read_bytes()).hexdigest() == digest for p, digest in original.items())
        window.show_settings()
        dialog = window.settings_dialog
        dialog.activateWindow()
        QTest.qWait(50)
        QTest.keyClick(dialog, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
        qapp.processEvents()
        assert not dialog.isVisible()
        assert window.route == ("privacy",) and not window.grid.media_model.items
    finally:
        window.close()
        qapp.processEvents()


def test_background_scan_can_complete_while_settings_are_open(tmp_path, qapp):
    library = tmp_path / "nested" / "album"
    library.mkdir(parents=True)
    Image.new("RGB", (60, 60), "#e8bf9f").save(library / "IMG20260203100000.png")
    window = MainWindow(QSettings(str(tmp_path / "scan.ini"), QSettings.Format.IniFormat), auto_load=False)
    window.show()
    try:
        window.start_scan(library.parent)
        window.show_settings()
        wait_until(qapp, lambda: window.scan is None)
        assert window.settings_dialog.isVisible()
        assert len(window.items) == 1 and window.root == library.parent
        window.settings_dialog.done_button.click()
        assert len(window.grid.media_model.items) == 1
    finally:
        window.close()
        qapp.processEvents()

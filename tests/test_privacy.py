from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest

from app.core.scanner import scan_library
from app.storage.index import LibraryIndex
from app.ui.main_window import MainWindow
from tests.test_images import wait_until
from tests.test_ui import make_library


@pytest.mark.parametrize("dark", [False, True])
def test_startup_waits_for_explicit_open_even_with_index(tmp_path, qapp, monkeypatch, dark):
    root = make_library(tmp_path / "private library")
    entries = scan_library(root).items
    LibraryIndex(tmp_path / "library.sqlite3").save(root, entries)
    settings = QSettings(str(tmp_path / "privacy.ini"), QSettings.Format.IniFormat)
    settings.setValue("library", str(root))
    settings.setValue("dark", dark)
    settings.setValue("thumbnail_size", 220)
    loads = []
    original_load = LibraryIndex.load

    def load(index, directory, **kwargs):
        loads.append(directory)
        return original_load(index, directory, **kwargs)

    monkeypatch.setattr(LibraryIndex, "load", load)
    window = MainWindow(settings)
    window.show()
    try:
        QTest.qWait(160)
        assert window.startup_pending and window.scan is None
        assert loads == [] and window.items == []
        assert window.centralWidget() is window.browser
        assert window.pages.currentWidget() == window.safe_page
        assert not hasattr(window, "privacy_page") and not hasattr(window, "shell")
        assert window.browser.isVisible() and not window.statusBar().isVisible()
        assert window.navigation.topLevelItemCount() == 1
        assert window.navigation.topLevelItem(0).childCount() == 0
        assert window.grid.media_model.items == [] and window.albums.album_model.items == []
        assert str(root) not in window.path_label.text() + window.path_label.toolTip()
        assert not window.thumbnails.pending and not window.thumbnails.memory
        assert window.grid.requested_edge == 220 and window.dark == dark
        QTest.keyClick(window, Qt.Key.Key_F5)
        QTest.keyClick(window, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
        window.update_view()
        qapp.processEvents()
        assert window.startup_pending and loads == [] and window.items == []
        window.safe_page.resume.click()
        wait_until(qapp, lambda: window.scan is None and len(window.items) == 5)
        assert not window.startup_pending and loads == [root]
        assert window.browser.isVisible() and window.pages.currentWidget() == window.grid
        assert window.sort_box.currentText() == "从旧到新"
        assert set(window.items) == set(entries)
    finally:
        window.close()
        qapp.processEvents()
    reopened = MainWindow(settings)
    reopened.show()
    try:
        QTest.qWait(80)
        assert reopened.startup_pending and reopened.items == [] and loads == [root]
        assert reopened.browser.isVisible()
        assert reopened.pages.currentWidget() == reopened.safe_page
    finally:
        reopened.close()
        qapp.processEvents()


def test_forget_library_applies_immediately_and_survives_scan_and_restart(tmp_path, qapp, monkeypatch):
    root = make_library(tmp_path / "private library")
    settings = QSettings(str(tmp_path / "forget.ini"), QSettings.Format.IniFormat)
    settings.setValue("library", str(root))
    window = MainWindow(settings)
    window.show()
    try:
        window.remember_checkbox.setChecked(False)
        assert not settings.contains("library") and window.root is None
        assert window.safe_page.resume.isEnabled()
        assert window.safe_page.resume.text() == "打开照片库"
        assert not window.remember_checkbox.isChecked()
        monkeypatch.setattr("app.ui.main_window.QFileDialog.getExistingDirectory", lambda *args: str(root))
        QTest.mouseClick(window.safe_page.resume, Qt.MouseButton.LeftButton)
        wait_until(qapp, lambda: window.scan is None and len(window.items) == 5)
        assert window.root == root and not settings.contains("library")
        window.refresh()
        wait_until(qapp, lambda: window.scan is None)
        assert not settings.contains("library")
        window.remember_checkbox.setChecked(True)
        assert settings.value("library") == str(root)
        window.remember_checkbox.setChecked(False)
        assert not settings.contains("library")
    finally:
        window.close()
        qapp.processEvents()
    reopened = MainWindow(settings)
    try:
        assert reopened.startup_pending and reopened.root is None
        assert reopened.safe_page.resume.isEnabled()
        assert reopened.safe_page.resume.text() == "打开照片库"
        assert not reopened.remember_checkbox.isChecked()
    finally:
        reopened.close()
        qapp.processEvents()


def test_cancel_picker_stays_private_and_explicit_path_also_waits(tmp_path, qapp, monkeypatch):
    root = make_library(tmp_path / "private library")
    settings = QSettings(str(tmp_path / "picker.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, initial_library=root)
    window.show()
    picker_directories = []

    def cancelled_picker(parent, title, directory):
        picker_directories.append(directory)
        return ""

    monkeypatch.setattr("app.ui.main_window.QFileDialog.getExistingDirectory", cancelled_picker)
    try:
        QTest.qWait(80)
        assert window.startup_pending and window.scan is None and window.items == []
        window.choose_button.click()
        assert picker_directories == [str(Path.home())]
        assert window.startup_pending and window.browser.isVisible()
        window.safe_page.resume.click()
        wait_until(qapp, lambda: window.scan is None and len(window.items) == 5)
        assert not window.startup_pending
    finally:
        window.close()
        qapp.processEvents()


def test_disabled_memory_discards_legacy_saved_path(tmp_path, qapp):
    settings = QSettings(str(tmp_path / "legacy.ini"), QSettings.Format.IniFormat)
    settings.setValue("remember_library", False)
    settings.setValue("library", str(tmp_path / "old private folder"))
    window = MainWindow(settings)
    try:
        assert window.root is None and not settings.contains("library")
        assert window.safe_page.resume.isEnabled()
        assert window.safe_page.resume.text() == "打开照片库"
    finally:
        window.close()
        qapp.processEvents()


def test_main_startup_all_photos_entry_can_retry_after_cancel(tmp_path, qapp, monkeypatch):
    settings = QSettings(str(tmp_path / "main-start.ini"), QSettings.Format.IniFormat)
    root = make_library(tmp_path / "photos")
    selections = iter(["", str(root)])
    monkeypatch.setattr("app.ui.main_window.QFileDialog.getExistingDirectory", lambda *args: next(selections))
    window = MainWindow(settings)
    window.show()
    try:
        qapp.processEvents()
        assert window.centralWidget() is window.browser and window.browser.isVisible()
        assert window.privacy_button.isVisible() and window.theme_button.isVisible()
        assert window.route == ("privacy",) and window.pages.currentWidget() == window.safe_page
        for attempt in range(2):
            item = window.navigation.topLevelItem(0)
            QTest.mouseClick(window.navigation.viewport(), Qt.MouseButton.LeftButton,
                             pos=window.navigation.visualItemRect(item).center())
            if attempt == 0:
                assert window.startup_pending and window.route == ("privacy",)
                assert not window.items
        wait_until(qapp, lambda: window.scan is None and len(window.items) == 5)
        assert window.route == ("all",) and not window.startup_pending
    finally:
        window.close()
        qapp.processEvents()


@pytest.mark.parametrize("remember", [False, True])
def test_first_open_primary_button_selects_folder_and_cancel_stays_private(tmp_path, qapp, monkeypatch, remember):
    settings = QSettings(str(tmp_path / "first-open.ini"), QSettings.Format.IniFormat)
    settings.setValue("remember_library", remember)
    root = make_library(tmp_path / "photos")
    selections = iter(["", str(root)])
    picker_calls = []

    def picker(parent, title, directory):
        picker_calls.append(directory)
        return next(selections)

    monkeypatch.setattr("app.ui.main_window.QFileDialog.getExistingDirectory", picker)
    window = MainWindow(settings)
    window.show()
    try:
        qapp.processEvents()
        button = window.safe_page.resume
        assert button.isEnabled() and button.text() == "打开照片库"
        assert window.choose_button.isVisible()
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        assert picker_calls == [str(Path.home())]
        assert window.startup_pending and window.items == [] and window.scan is None
        assert window.browser.isVisible()
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        wait_until(qapp, lambda: window.scan is None and len(window.items) == 5)
        assert len(picker_calls) == 2 and not window.startup_pending
        assert settings.contains("library") == remember
    finally:
        window.close()
        qapp.processEvents()

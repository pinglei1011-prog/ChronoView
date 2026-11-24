from pathlib import Path

from PIL import Image
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest

from app.core.scanner import scan_library
from app.ui.main_window import MainWindow
from app.ui.photo_viewer import PhotoViewer
from tests.test_images import wait_until
import pytest


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
        assert window.pages.currentWidget() == window.grid
        assert window.grid.media_model.items == window.visible_items
        assert len(window.grid.media_model.items) == 5
        assert any(item.taken_at is None for item in window.grid.media_model.items)
        assert window.sort_box.isVisible()
        assert window.sort_box.currentText() == "从旧到新"
        assert window.visible_items[0].path.name == "IMG20240101000000.jpg"
        window.route = ("month", 2026, 1)
        window.update_view()
        assert len(window.grid.media_model.items) == 2
        window.sort_box.setCurrentIndex(1)
        assert [x.kind for x in window.grid.media_model.items] == ["image", "video"]
        window.go_back()
        assert window.route == ("year", 2026)
        assert window.pages.currentWidget() == window.albums
        assert len(window.visible_items) == 3
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


def test_all_media_sort_and_viewer_scope_survive_calendar_navigation(tmp_path, qapp, monkeypatch):
    from app.core.library import sort_items

    window = MainWindow(QSettings(str(tmp_path / "all-media.ini"), QSettings.Format.IniFormat),
                        auto_load=False)
    window.items = scan_library(make_library(tmp_path / "library")).items
    window.select_route(("all",))
    opened = []

    class FakeViewer:
        def __init__(self, items, position, parent):
            opened.append((list(items), position))

        def exec(self):
            pass

        def deleteLater(self):
            pass

    monkeypatch.setattr("app.ui.main_window.PhotoViewer", FakeViewer)
    try:
        for sort_index in (0, 1):
            window.sort_box.setCurrentIndex(sort_index)
            expected = sort_items(window.items, sort_index == 0)
            assert window.grid.media_model.items == expected
            assert {item.path for item in expected} == {item.path for item in window.items}
            video_position = next(i for i, item in enumerate(expected) if item.kind == "video")
            window.open_item(window.grid.media_model.index(video_position, 0))
            assert opened[-1] == (expected, video_position)
            window.select_route(("year", 2026))
            assert window.pages.currentWidget() == window.albums
            assert [album.route for album in window.albums.album_model.items] == [
                ("month", 2026, 1), ("month", 2026, 2)]
            window.select_route(("month", 2026, 1))
            assert len(window.grid.media_model.items) == 2
            window.go_back()
            window.go_back()
            assert window.route == ("all",)
            assert window.pages.currentWidget() == window.grid
            assert window.grid.media_model.items == expected
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
        assert viewer.pages.currentWidget() == viewer.video
        wait_until(qapp, lambda: "无法播放视频" in viewer.video.status.text())
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
        assert window.startup_pending and not window.items and window.scan is None
        window.safe_page.resume.click()
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
    window.select_route(("month", 2026, 1))
    window.sort_box.setCurrentIndex(1)
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


@pytest.mark.parametrize("dark", [False, True])
def test_calendar_single_click_toggles_rows_and_branch_arrows(tmp_path, qapp, dark):
    from PySide6.QtCore import QPoint

    settings = QSettings(str(tmp_path / "single-click.ini"), QSettings.Format.IniFormat)
    settings.setValue("dark", dark)
    window = MainWindow(settings, auto_load=False)
    window.items = scan_library(make_library(tmp_path / "library")).items
    window.rebuild_navigation()
    window.show()
    try:
        qapp.processEvents()
        tree = window.navigation
        collection = tree.topLevelItem(0)

        def click(item, arrow=False):
            rect = tree.visualItemRect(item)
            pos = (QPoint(rect.left() - tree.indentation() // 2, rect.center().y())
                   if arrow else rect.center())
            assert tree.itemAt(pos) is item
            QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=pos)
            qapp.processEvents()

        assert collection.isExpanded()
        click(collection)
        assert not collection.isExpanded() and window.route == ("all",)
        click(collection)
        assert collection.isExpanded()
        for number in range(2):
            year = collection.child(number)
            route = year.data(0, Qt.ItemDataRole.UserRole)
            assert not year.isExpanded()
            click(year)
            assert year.isExpanded() and window.route == route
            click(year)
            assert not year.isExpanded() and window.route == route
            click(year, arrow=True)
            assert year.isExpanded()
            click(year, arrow=True)
            assert not year.isExpanded()
            click(year)
            month = year.child(0)
            click(month)
            assert window.route == month.data(0, Qt.ItemDataRole.UserRole)
            assert year.isExpanded() and not month.isExpanded()
            # Selecting an already-open parent must still collapse it immediately.
            click(year)
            assert not year.isExpanded() and window.route == route
            tree.setFocus()
            QTest.keyClick(tree, Qt.Key.Key_Right)
            assert year.isExpanded()
            QTest.keyClick(tree, Qt.Key.Key_Left)
            assert not year.isExpanded()
        click(collection, arrow=True)
        assert not collection.isExpanded()
        click(collection, arrow=True)
        assert collection.isExpanded()
        # A double-click's second press must not undo the first click's toggle.
        click(collection)
        assert not collection.isExpanded()
        QTest.mouseDClick(tree.viewport(), Qt.MouseButton.LeftButton,
                         pos=tree.visualItemRect(collection).center())
        assert not collection.isExpanded()
    finally:
        window.close()
        qapp.processEvents()


def test_calendar_album_drill_down_and_back(tmp_path, qapp):
    settings = QSettings(str(tmp_path / "calendar.ini"), QSettings.Format.IniFormat)
    root = make_library(tmp_path / "library")
    window = MainWindow(settings, auto_load=False)
    window.items = scan_library(root).items
    window.rebuild_navigation()
    window.update_view()
    window.show()
    try:
        qapp.processEvents()
        collection = window.navigation.topLevelItem(0)
        assert collection.text(0) == "全部照片"
        assert window.navigation.topLevelItemCount() == 1
        assert [collection.child(i).data(0, Qt.ItemDataRole.UserRole)
                for i in range(collection.childCount())] == [("year", 2024), ("year", 2026), ("unknown",)]
        year = collection.child(1)
        assert year.data(0, Qt.ItemDataRole.UserRole) == ("year", 2026)
        assert [year.child(i).text(0).split('月')[0] for i in range(year.childCount())] == ["1", "2"]
        assert window.pages.currentWidget() == window.grid
        assert not window.back_button.isVisible()
        assert len(window.grid.media_model.items) == len(window.items)
        assert window.albums.album_model.items == []
        QTest.mouseClick(window.navigation.viewport(), Qt.MouseButton.LeftButton,
                         pos=window.navigation.visualItemRect(year).center())
        qapp.processEvents()
        year = window.navigation.topLevelItem(0).child(1)
        assert year.isExpanded()
        assert window.route == ("year", 2026)
        assert window.back_button.text() == "返回全部照片"
        assert not window.back_button.icon().isNull()
        assert window.pages.currentWidget() == window.albums
        assert window.grid.media_model.items == []
        assert [album.route for album in window.albums.album_model.items] == [
            ("month", 2026, 1), ("month", 2026, 2)]
        window.albums.setCurrentIndex(window.albums.album_model.index(0, 0))
        window.albums.setFocus()
        QTest.keyClick(window.albums, Qt.Key.Key_Return)
        assert window.route == ("month", 2026, 1)
        assert window.back_button.text() == "返回 2026年"
        assert len(window.grid.media_model.items) == 2
        assert [item.kind for item in window.grid.media_model.items] == ["image", "video"]
        assert window.pages.currentWidget() == window.grid
        window.back_button.click()
        assert window.route == ("year", 2026)
        assert window.pages.currentWidget() == window.albums
        assert len(window.albums.album_model.items) == 2
        window.back_button.click()
        assert window.route == ("all",)
        assert window.pages.currentWidget() == window.grid
        assert len(window.grid.media_model.items) == len(window.items)
        year = window.navigation.topLevelItem(0).child(1)
        QTest.mouseClick(window.navigation.viewport(), Qt.MouseButton.LeftButton,
                         pos=window.navigation.visualItemRect(year).center())
        assert window.route == ("year", 2026)
        assert window.pages.currentWidget() == window.albums
    finally:
        window.close()
        qapp.processEvents()


def test_refresh_keeps_selected_month_and_ancestors(tmp_path, qapp):
    root = make_library(tmp_path / "library")
    settings = QSettings(str(tmp_path / "refresh.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, auto_load=False)
    window.show()
    try:
        window.start_scan(root)
        wait_until(qapp, lambda: window.scan is None)
        window.select_route(("month", 2026, 1))
        window.refresh()
        wait_until(qapp, lambda: window.scan is None)
        current = window.navigation.currentItem()
        assert current.data(0, Qt.ItemDataRole.UserRole) == ("month", 2026, 1)
        assert current.parent().isExpanded() and current.parent().parent().isExpanded()
        assert window.pages.currentWidget() == window.grid
        assert len(window.grid.media_model.items) == 2
    finally:
        window.close()
        qapp.processEvents()


def test_unknown_album_remains_accessible(tmp_path, qapp):
    root = tmp_path / "unknown-only"
    root.mkdir()
    Image.new("RGB", (30, 30)).save(root / "旧照片.jpg")
    settings = QSettings(str(tmp_path / "unknown.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, auto_load=False)
    window.items = scan_library(root).items
    window.select_route(("all",))
    window.show()
    try:
        qapp.processEvents()
        assert window.pages.currentWidget() == window.grid
        assert len(window.grid.media_model.items) == 1
        collection = window.navigation.topLevelItem(0)
        QTest.mouseClick(window.navigation.viewport(), Qt.MouseButton.LeftButton,
                         pos=window.navigation.visualItemRect(collection.child(0)).center())
        assert window.route == ("unknown",)
        assert window.pages.currentWidget() == window.grid
        assert len(window.grid.media_model.items) == 1
        selected = window.navigation.currentItem()
        assert selected.data(0, Qt.ItemDataRole.UserRole) == ("unknown",)
        assert selected.parent().data(0, Qt.ItemDataRole.UserRole) == ("all",)
        assert selected.parent().isExpanded()
        window.back_button.click()
        assert window.route == ("all",)
        collection = window.navigation.topLevelItem(0)
        QTest.mouseClick(window.navigation.viewport(), Qt.MouseButton.LeftButton,
                         pos=window.navigation.visualItemRect(collection.child(0)).center())
        assert window.route == ("unknown",)
        assert len(window.grid.media_model.items) == 1
    finally:
        window.close()
        qapp.processEvents()


def test_unknown_entry_appears_only_with_content_and_updates_after_refresh(tmp_path, qapp):
    root = tmp_path / "generated-library"
    root.mkdir()
    Image.new("RGB", (30, 30)).save(root / "IMG20260101120000.jpg")
    settings = QSettings(str(tmp_path / "conditional-unknown.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, auto_load=False)
    window.show()

    def navigation_routes():
        collection = window.navigation.topLevelItem(0)
        return [collection.child(i).data(0, Qt.ItemDataRole.UserRole)
                for i in range(collection.childCount())]

    try:
        window.start_scan(root)
        wait_until(qapp, lambda: window.scan is None)
        assert navigation_routes() == [("year", 2026)]
        assert len(window.grid.media_model.items) == len(window.items)
        window.select_route(("month", 2026, 1))
        unknown = root / "旧照片.jpg"
        Image.new("RGB", (30, 30)).save(unknown)
        window.refresh()
        wait_until(qapp, lambda: window.scan is None)
        assert window.route == ("month", 2026, 1)
        assert navigation_routes() == [("year", 2026), ("unknown",)]
        window.select_route(("all",))
        assert len(window.grid.media_model.items) == len(window.items)
        assert any(item.taken_at is None for item in window.grid.media_model.items)
        window.select_route(("unknown",))
        assert len(window.grid.media_model.items) == 1
        # Only this generated fixture is renamed, simulating an external correction.
        unknown.rename(root / "IMG20260201120000.jpg")
        window.refresh()
        wait_until(qapp, lambda: window.scan is None)
        assert window.route == ("all",)
        assert navigation_routes() == [("year", 2026)]
        assert len(window.grid.media_model.items) == len(window.items)
        assert window.navigation.currentItem().data(0, Qt.ItemDataRole.UserRole) == ("all",)
        assert len(window.items) == 2
    finally:
        window.close()
        qapp.processEvents()


@pytest.mark.parametrize("dark", [False, True])
def test_sort_popup_has_opaque_theme_and_distinct_rows(tmp_path, qapp, dark):
    from PySide6.QtGui import QColor
    settings = QSettings(str(tmp_path / "popup.ini"), QSettings.Format.IniFormat)
    settings.setValue("dark", dark)
    window = MainWindow(settings, auto_load=False)
    window.items = scan_library(make_library(tmp_path / "library")).items
    window.select_route(("month", 2026, 1))
    window.show()
    try:
        qapp.processEvents()
        window.sort_box.showPopup()
        qapp.processEvents()
        view = window.sort_box.view()
        first = view.visualRect(view.model().index(0, 0))
        second = view.visualRect(view.model().index(1, 0))
        assert first.height() >= 30 and second.height() >= 30
        assert second.top() > first.bottom()
        assert view.objectName() == "sortPopup"
        image = view.viewport().grab().toImage()
        color = image.pixelColor(image.width() - 3, image.height() - 3)
        assert color.alpha() == 255
        assert color == QColor("#1c2028" if dark else "#ffffff")
        window.sort_box.hidePopup()
        window.sort_box.setCurrentIndex(0)
        assert window.sort_box.currentText() == "从新到旧"
        assert [item.kind for item in window.grid.media_model.items] == ["video", "image"]
        window.sort_box.setCurrentIndex(1)
        assert window.sort_box.currentText() == "从旧到新"
        assert [item.kind for item in window.grid.media_model.items] == ["image", "video"]
    finally:
        window.sort_box.hidePopup()
        window.close()
        qapp.processEvents()


def test_broken_photo_tooltip_explains_read_error(tmp_path, qapp):
    from app.services.thumbnail_service import cache_key
    path = tmp_path / "IMG20261016103000.jpg"
    path.write_bytes(b"not a photo")
    settings = QSettings(str(tmp_path / "broken.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, auto_load=False)
    window.items = scan_library(tmp_path).items
    window.select_route(("month", 2026, 10))
    try:
        item = window.items[0]
        window.thumbnails.get(item)
        wait_until(qapp, lambda: cache_key(item) in window.thumbnails.memory)
        tooltip = window.grid.model().index(0, 0).data(Qt.ItemDataRole.ToolTipRole)
        assert "无法识别此照片的内容" in tooltip
        assert str(path) in tooltip
    finally:
        window.close()
        qapp.processEvents()


@pytest.mark.parametrize("count", [24, 72])
def test_media_rows_fill_width_after_sidebar_resize_and_thumbnail_changes(tmp_path, qapp, count):
    root = tmp_path / "library"
    root.mkdir()
    for number in range(count):
        Image.new("RGB", (30, 20), "#4389f5").save(root / f"IMG20240201{number // 60:02d}{number % 60:02d}00.jpg")
    settings = QSettings(str(tmp_path / "reflow.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, auto_load=False)
    window.items = scan_library(root).items
    window.select_route(("month", 2024, 2))
    window.show()
    try:
        paths = [item.path for item in window.grid.media_model.items]
        for sidebar, width, edge in [(True, 1280, 144), (False, 1280, 144),
                                      (False, 1282, 144),
                                      (False, 1100, 180), (False, 1280, 110), (True, 1280, 144)]:
            window.set_sidebar_visible(sidebar)
            window.resize(width, 1000)
            window.grid.set_thumbnail_size(edge)
            QTest.qWait(60)
            qapp.processEvents()
            grid = window.grid
            rectangles = [grid.visualRect(grid.model().index(i, 0)) for i in range(count)]
            first_row = [rect for rect in rectangles if rect.top() == rectangles[0].top()]
            assert len(first_row) >= 2
            assert 0 <= grid.viewport().width() - max(rect.right() + 1 for rect in first_row) <= 32
            assert grid.horizontalScrollBar().maximum() == 0
            assert window.route == ("month", 2024, 2)
            assert [item.path for item in grid.media_model.items] == paths
    finally:
        window.close()
        qapp.processEvents()


@pytest.mark.parametrize("fail", [False, True])
def test_viewer_prioritizes_playback_and_restores_cover_work(tmp_path, qapp, monkeypatch, fail):
    window = MainWindow(QSettings(str(tmp_path / "priority.ini"), QSettings.Format.IniFormat),auto_load=False)
    window.items = scan_library(make_library(tmp_path / "library")).items
    window.select_route(("month", 2026, 1))

    class FakeViewer:
        def __init__(self, *args):
            assert window.thumbnails.paused

        def exec(self):
            assert window.thumbnails.paused
            if fail:
                raise RuntimeError("test viewer failure")

        def deleteLater(self):
            pass

    monkeypatch.setattr("app.ui.main_window.PhotoViewer", FakeViewer)
    try:
        index = window.grid.media_model.index(0, 0)
        if fail:
            with pytest.raises(RuntimeError,match="test viewer failure"):
                window.open_item(index)
        else:
            window.open_item(index)
        assert not window.thumbnails.paused
        assert not window.viewer_open
    finally:
        window.close()
        qapp.processEvents()

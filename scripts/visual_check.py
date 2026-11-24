"""Generate synthetic, disposable media and render the real window for visual QA."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from scripts.media_fixtures import make_video


def run():
    root = Path(__file__).resolve().parents[1]
    work = root / "work"
    library = work / "演示照片库" / "任意嵌套目录"
    library.mkdir(parents=True, exist_ok=True)
    palettes = [((212, 229, 236), (94, 144, 157), (43, 86, 104)),
                ((242, 209, 183), (180, 132, 119), (98, 96, 125)),
                ((210, 221, 199), (133, 157, 119), (65, 105, 95)),
                ((209, 216, 239), (139, 151, 187), (87, 104, 150))]
    for i in range(18):
        width, height = ((800, 600) if i % 4 != 0 else (600, 800))
        sky, mountain, foreground = palettes[i % 4]
        image = Image.new("RGB", (width, height), sky)
        draw = ImageDraw.Draw(image)
        draw.ellipse((width * .65, height * .12, width * .8, height * .12 + width * .15), fill="#fff6dc")
        draw.polygon([(0, height * .65), (width * .25, height * .31),
                      (width * .52, height * .64), (width * .77, height * .4),
                      (width, height * .66), (width, height), (0, height)], fill=mountain)
        draw.polygon([(0, height * .78), (width * .3, height * .66),
                      (width * .67, height * .86), (width, height * .64),
                      (width, height), (0, height)], fill=foreground)
        year = 2026 if i < 12 else 2025
        month = 11 if i < 8 else 10
        destination = library / f"IMG{year}{month:02d}{24 - i:02d}103000.jpg"
        if not destination.exists():
            image.save(destination)
    video = library / "VID20261123120000.mp4"
    if not video.exists():
        make_video(video)
    old_photo = library / "旧照片.jpg"
    if not old_photo.exists():
        Image.new("RGB", (600, 600), "#a8b9c9").save(old_photo)
    for year, color in [(2023, "#91b3c7"), (2024, "#b3c7a1")]:
        destination = library / f"IMG{year}0201120000.jpg"
        if not destination.exists():
            Image.new("RGB", (600, 400), color).save(destination)
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("ChronoViewQA")
    app.setApplicationName("ChronoViewQA")
    settings = QSettings(str(work / "visual.ini"), QSettings.Format.IniFormat)
    settings.setValue("dark", False)
    settings.setValue("sidebar_visible", True)
    window = MainWindow(settings, auto_load=False)
    window.show()
    window.start_scan(library.parent)

    for _ in range(300):
        app.processEvents()
        QTest.qWait(20)
        if window.scan is None:
            break
    QTest.qWait(400)
    app.processEvents()
    # The all-photos page now paints media immediately. Wait for these small
    # synthetic fixtures before capturing the preview rather than loading tiles.
    for _ in range(200):
        if all(window.thumbnails.get(item)[0] is not None for item in window.items):
            break
        QTest.qWait(20)
        app.processEvents()
    expected_routes = [("year", 2023), ("year", 2024), ("year", 2025), ("year", 2026), ("unknown",)]
    assert window.pages.currentWidget() == window.grid
    assert window.grid.media_model.items == window.visible_items
    assert len(window.grid.media_model.items) == len(window.items)
    assert window.navigation.topLevelItemCount() == 1
    collection = window.navigation.topLevelItem(0)
    assert [collection.child(i).data(0, Qt.ItemDataRole.UserRole)
            for i in range(collection.childCount())] == expected_routes
    window.grab().save(str(work / "qa-light.png"))
    window.grab().save(str(work / "qa-years.png"))
    window.select_route(("year", 2026))
    QTest.qWait(300)
    app.processEvents()
    window.grab().save(str(work / "qa-year.png"))
    window.grab().save(str(work / "qa-months.png"))
    window.toggle_theme()
    QTest.qWait(100)
    window.grab().save(str(work / "qa-dark.png"))
    window.select_route(("month", 2026, 11))
    for _ in range(200):
        app.processEvents()
        QTest.qWait(20)
        if all(window.thumbnails.get(item)[0] is not None for item in window.grid.media_model.items):
            break
    QTest.qWait(100)
    window.grab().save(str(work / "qa-media.png"))
    window.grab().save(str(work / "qa-sidebar-visible.png"))
    route_before = window.route
    paths_before = [item.path for item in window.grid.media_model.items]
    width_before = window.grid.viewport().width()
    window.hide_sidebar_button.click()
    window.resize(1280, 850)
    window.grid.set_thumbnail_size(144)
    QTest.qWait(150)
    assert not window.sidebar.isVisible() and window.show_sidebar_button.isVisible()
    assert window.grid.viewport().width() > width_before
    assert window.route == route_before
    assert [item.path for item in window.grid.media_model.items] == paths_before
    assert settings.value("sidebar_visible", type=bool) is False
    rectangles = [window.grid.visualRect(window.grid.model().index(i, 0))
                  for i in range(window.grid.model().rowCount())]
    first_row = [rect for rect in rectangles if rect.top() == rectangles[0].top()]
    right_gap = window.grid.viewport().width() - max(rect.right() + 1 for rect in first_row)
    assert 0 <= right_gap <= 32, (right_gap, window.grid.size(), window.grid.viewport().size(),
                                window.grid.maximumViewportSize(), window.grid.gridSize(), rectangles)
    window.grab().save(str(work / "qa-sidebar-hidden.png"))
    window.toggle_theme()
    QTest.qWait(100)
    window.grab().save(str(work / "qa-sidebar-hidden-light.png"))
    window.activateWindow()
    window.grid.setFocus()
    QTest.qWait(50)
    QTest.keyClick(window, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
    QTest.qWait(100)
    assert window.sidebar.isVisible() and not window.show_sidebar_button.isVisible()
    window.hide_sidebar_button.click()
    QTest.qWait(100)
    window.show_sidebar_button.click()
    QTest.qWait(100)
    assert window.sidebar.isVisible()
    assert settings.value("sidebar_visible", type=bool) is True
    print(f"Full media row: {len(first_row)} columns; unused viewport gutter: {right_gap}px.")
    print("Sidebar hide, responsive width, route preservation, Ctrl+B, restore button and saved preference verified.")
    print(f"Rendered {len(window.items)} items to {work}")
    window.close()
    app.processEvents()


if __name__ == "__main__":
    run()

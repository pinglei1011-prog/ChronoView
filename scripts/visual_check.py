"""Generate synthetic, disposable media and render the real window for visual QA."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow


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
        image.save(library / f"IMG{year}{month:02d}{24 - i:02d}103000.jpg")
    (library / "VID20261123120000.mp4").write_bytes(b"Synthetic QA placeholder, no video stream")
    Image.new("RGB", (600, 600), "#a8b9c9").save(library / "旧照片.jpg")
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("ChronoViewQA")
    app.setApplicationName("ChronoViewQA")
    settings = QSettings(str(work / "visual.ini"), QSettings.Format.IniFormat)
    settings.setValue("dark", False)
    window = MainWindow(settings, auto_load=False)
    window.show()
    window.start_scan(library.parent)
    for _ in range(300):
        app.processEvents()
        QTest.qWait(20)
        if window.scan is None and len(window.thumbnails.memory) >= 14:
            break
    QTest.qWait(400)
    app.processEvents()
    window.grab().save(str(work / "qa-light.png"))
    window.toggle_theme()
    QTest.qWait(100)
    window.grab().save(str(work / "qa-dark.png"))
    print(f"Rendered {len(window.items)} items to {work}")
    window.close()
    app.processEvents()


if __name__ == "__main__":
    run()

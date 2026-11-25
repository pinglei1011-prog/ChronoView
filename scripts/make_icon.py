"""Export the existing SVG brand icon to Windows ICO sizes."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtCore import Qt
from PySide6.QtSvg import QSvgRenderer
from PIL import Image

root = Path(__file__).resolve().parents[1]
app = QGuiApplication([])
image = QImage(256, 256, QImage.Format.Format_ARGB32)
image.fill(Qt.GlobalColor.transparent)
painter = QPainter(image)
QSvgRenderer(str(root / 'assets/chronoview.svg')).render(painter)
painter.end()
temp = root / 'work/chronoview-icon.png'
temp.parent.mkdir(exist_ok=True)
image.save(str(temp))
Image.open(temp).save(root / 'assets/chronoview.ico', sizes=[(s,s) for s in (16,24,32,48,64,128,256)])
print('Exported Windows brand icon')

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")
os.environ.setdefault("CHRONOVIEW_VIDEO_BACKEND", "qt")
os.environ.setdefault("QT_DISABLE_HW_TEXTURES_CONVERSION", "1")
os.environ.setdefault("QT_FFMPEG_DECODING_HW_DEVICE_TYPES", ",")

import pytest
from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("ChronoViewTests")
    app.setApplicationName("ChronoViewTests")
    QStandardPaths.setTestModeEnabled(True)
    yield app
    app.processEvents()

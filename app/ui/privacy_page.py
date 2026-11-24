from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from app.ui.theme import asset_path


class InAppPrivacyPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(18)
        layout.addStretch()
        icon = QLabel()
        icon.setPixmap(QIcon(str(asset_path("privacy.svg"))).pixmap(64, 64))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)
        self.title = title = QLabel("照片和视频已隐藏")
        title.setObjectName("privacyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        self.hint = hint = QLabel("可以把软件停留在这里\n点击继续浏览，返回刚才的分类")
        hint.setObjectName("muted")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        self.resume = QPushButton("继续浏览")
        self.resume.setObjectName("primary")
        self.resume.setFixedWidth(160)
        self.resume.setMinimumHeight(42)
        self.resume.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.resume, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch()

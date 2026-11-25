from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from app.ui.theme import tinted_pixmap, tokens


class InAppPrivacyPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch()

        card = QFrame()
        card.setObjectName("privacyCard")
        card.setFixedWidth(392)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(36, 38, 36, 32)
        layout.setSpacing(12)

        self.icon_label = QLabel()
        self.icon_label.setObjectName("emblemBadge")
        self.icon_label.setFixedSize(68, 68)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(4)

        self.title = title = QLabel("照片和视频已隐藏")
        title.setObjectName("privacyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self.hint = hint = QLabel("可以把软件停留在这里\n点击继续浏览，返回刚才的分类")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        layout.addSpacing(10)

        self.resume = QPushButton("继续浏览")
        self.resume.setObjectName("primary")
        self.resume.setFixedWidth(188)
        self.resume.setMinimumHeight(40)
        self.resume.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.resume, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.shortcut_hint = QLabel("快捷键 Ctrl+L 可随时隐藏媒体")
        self.shortcut_hint.setObjectName("shortcutHint")
        self.shortcut_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.shortcut_hint)

        outer.addWidget(card, alignment=Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch()
        self.apply_theme(False)

    def apply_theme(self, dark: bool):
        t = tokens(dark)
        self.icon_label.setPixmap(tinted_pixmap("privacy.svg", t["accent"], 30))

"""A lightweight settings sheet; opening it never opens or scans a library."""
from PySide6.QtCore import QSize, Qt, QSignalBlocker, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QKeySequence, QPainter, QShortcut
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QFrame, QHBoxLayout,
                               QLabel, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from app import __display_version__
from app.ui.theme import apply_window_chrome, asset_path, stylesheet, tinted_icon, tinted_pixmap, tokens

REPOSITORY_URL = "https://github.com/pinglei1011-prog/ChronoView"
RELEASES_URL = REPOSITORY_URL + "/releases/latest"


class PreferenceSwitch(QCheckBox):
    """Keep native checkbox keyboard/accessibility behavior with a quiet switch face."""
    def __init__(self, label, parent=None):
        super().__init__(parent)
        self.setAccessibleName(label)
        self.setFixedSize(40, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dark = False

    def hitButton(self, position):
        return self.rect().contains(position)

    def paintEvent(self, event):
        t = tokens(self.dark)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(t["accent"] if self.isChecked() else t["border_strong"]))
        painter.drawRoundedRect(2, 3, 36, 20, 10, 10)
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(22 if self.isChecked() else 4, 5, 16, 16)
        if self.hasFocus():
            from PySide6.QtGui import QPen
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(t["accent"]), 1))
            painter.drawRoundedRect(0, 1, 39, 24, 12, 12)


class SettingsLink(QPushButton):
    def __init__(self, text, icon, parent=None):
        super().__init__(parent)
        self.icon_name = icon
        self.setObjectName("settingsLink")
        self.setAccessibleName(text)
        self.setToolTip(f"在浏览器中打开{text}")
        self.setAutoDefault(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(44)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 12, 0)
        row.setSpacing(12)
        self.leading = QLabel()
        self.leading.setFixedSize(18, 18)
        self.label = QLabel(text)
        self.label.setObjectName("settingsLinkText")
        self.trailing = QLabel()
        self.trailing.setFixedSize(16, 16)
        for child in (self.leading, self.label, self.trailing):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(self.leading)
        row.addWidget(self.label, 1)
        row.addWidget(self.trailing)

    def apply_theme(self, dark):
        t = tokens(dark)
        self.leading.setPixmap(tinted_pixmap(self.icon_name, t["text_secondary"], 18))
        self.trailing.setPixmap(tinted_pixmap("external-link.svg", t["muted"], 16))


class SettingsDialog(QDialog):
    theme_requested = Signal(bool)
    remember_requested = Signal(bool)
    licenses_requested = Signal()
    privacy_requested = Signal()
    cache_clear_requested = Signal()
    history_clear_requested = Signal()

    def __init__(self, dark=False, remember_library=True, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsDialog")
        self.setWindowTitle("ChronoView · 设置")
        self.setWindowIcon(QIcon(str(asset_path("chronoview.svg"))))
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setMinimumSize(460, 420)
        screen = self.screen().availableGeometry()
        self.resize(min(620, screen.width() - 48), min(740, screen.height() - 72))
        self.dark = dark
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 18)
        outer.setSpacing(18)
        title = QLabel("设置")
        title.setObjectName("settingsHeading")
        outer.addWidget(title)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("settingsScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().setObjectName("settingsViewport")
        body = QWidget()
        body.setObjectName("settingsBody")
        content = QVBoxLayout(body)
        content.setContentsMargins(0, 0, 8, 0)
        content.setSpacing(10)
        section = QLabel("偏好设置")
        section.setObjectName("settingsSection")
        content.addWidget(section)

        preferences = QFrame()
        preferences.setObjectName("settingsCard")
        pref = QVBoxLayout(preferences)
        pref.setContentsMargins(18, 12, 18, 12)
        pref.setSpacing(8)
        appearance = QHBoxLayout()
        appearance.setSpacing(16)
        appearance.addWidget(QLabel("外观"), 1)
        segmented = QFrame()
        segmented.setObjectName("settingsSegments")
        segment_row = QHBoxLayout(segmented)
        segment_row.setContentsMargins(3, 3, 3, 3)
        segment_row.setSpacing(2)
        self.theme_group = QButtonGroup(self)
        self.light_button = self._theme_button("浅色", False)
        self.dark_button = self._theme_button("深色", True)
        for button in (self.light_button, self.dark_button):
            self.theme_group.addButton(button)
            segment_row.addWidget(button)
        appearance.addWidget(segmented)
        pref.addLayout(appearance)
        remember_row = QHBoxLayout()
        remember_row.setContentsMargins(0, 5, 0, 5)
        remember_row.addWidget(QLabel("记住照片库位置"), 1)
        self.remember_switch = PreferenceSwitch("记住照片库位置")
        self.remember_switch.toggled.connect(self.remember_requested)
        remember_row.addWidget(self.remember_switch)
        pref.addLayout(remember_row)
        content.addWidget(preferences)
        content.addSpacing(14)

        section = QLabel("本地数据")
        section.setObjectName("settingsSection")
        content.addWidget(section)
        data_card = QFrame()
        data_card.setObjectName("settingsCard")
        data_layout = QVBoxLayout(data_card)
        data_layout.setContentsMargins(12, 8, 12, 10)
        data_layout.setSpacing(4)
        self.cache_button = SettingsLink("清除缩略图缓存", "refresh.svg")
        self.history_button = SettingsLink("清除本地记录与缓存", "privacy.svg")
        self.cache_button.setToolTip("仅清除软件生成的预览缓存")
        self.history_button.setToolTip("清除索引、上次目录、日志和预览缓存")
        self.cache_button.clicked.connect(self.cache_clear_requested)
        self.history_button.clicked.connect(self.history_clear_requested)
        data_layout.addWidget(self.cache_button)
        data_layout.addWidget(self.history_button)
        self.data_status = QLabel("缩略图缓存上限 5 GB")
        self.data_status.setObjectName("settingsVersion")
        self.data_status.setWordWrap(True)
        self.data_status.setContentsMargins(12, 3, 8, 0)
        data_layout.addWidget(self.data_status)
        content.addWidget(data_card)
        content.addSpacing(14)

        section = QLabel("关于 ChronoView")
        section.setObjectName("settingsSection")
        content.addWidget(section)
        about = QFrame()
        about.setObjectName("settingsCard")
        self.about_card = about
        info = QVBoxLayout(about)
        info.setContentsMargins(20, 24, 20, 14)
        info.setSpacing(7)
        self.app_icon = QLabel()
        self.app_icon.setPixmap(QIcon(str(asset_path("chronoview.svg"))).pixmap(QSize(68, 68)))
        self.app_icon.setFixedSize(68, 68)
        info.addWidget(self.app_icon, alignment=Qt.AlignmentFlag.AlignHCenter)
        info.addSpacing(5)
        self.app_name = QLabel("ChronoView")
        self.app_name.setObjectName("settingsAppName")
        self.app_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info.addWidget(self.app_name)
        self.version_label = QLabel(f"{__display_version__} 正式版")
        self.version_label.setObjectName("settingsVersion")
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info.addWidget(self.version_label)
        self.tagline = QLabel("让每个瞬间，回到时间里")
        self.tagline.setObjectName("settingsTagline")
        self.tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info.addWidget(self.tagline)
        info.addSpacing(11)
        self.privacy_note = QLabel("照片与视频仅在本地浏览，原始文件只读。\n隐私页隐藏内容，不加密或清除缓存。")
        self.privacy_note.setObjectName("settingsPrivacy")
        self.privacy_note.setWordWrap(True)
        self.privacy_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info.addWidget(self.privacy_note)
        info.addSpacing(12)
        self.repository_button = SettingsLink("GitHub 仓库", "code.svg")
        self.repository_button.clicked.connect(lambda: self.open_link(REPOSITORY_URL))
        self.updates_button = SettingsLink("版本更新", "refresh.svg")
        self.updates_button.setToolTip("在浏览器中查看最新发布")
        self.updates_button.clicked.connect(lambda: self.open_link(RELEASES_URL))
        info.addWidget(self.repository_button)
        info.addWidget(self.updates_button)
        self.licenses_button = QPushButton("开源许可")
        self.licenses_button.setObjectName("settingsLicense")
        self.licenses_button.setAutoDefault(False)
        self.licenses_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.licenses_button.clicked.connect(self.licenses_requested)
        info.addWidget(self.licenses_button, alignment=Qt.AlignmentFlag.AlignHCenter)
        content.addWidget(about)
        content.addStretch(1)
        self.scroll.setWidget(body)
        outer.addWidget(self.scroll, 1)
        footer = QHBoxLayout()
        footer.addStretch()
        self.done_button = QPushButton("完成")
        self.done_button.setObjectName("primary")
        self.done_button.setFixedSize(92, 34)
        self.done_button.setDefault(True)
        self.done_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.done_button.clicked.connect(self.accept)
        footer.addWidget(self.done_button)
        outer.addLayout(footer)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.hide_media)
        self.sync_preferences(dark, remember_library)

    def _theme_button(self, text, dark):
        button = QPushButton(text)
        button.setObjectName("settingsSegment")
        button.setIconSize(QSize(14, 14))
        button.setCheckable(True)
        button.setAutoDefault(False)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda: self.theme_requested.emit(dark))
        return button

    def sync_preferences(self, dark, remember_library):
        for widget, value in ((self.light_button, not dark), (self.dark_button, dark),
                              (self.remember_switch, remember_library)):
            with QSignalBlocker(widget):
                widget.setChecked(value)
        self.apply_theme(dark)

    def apply_theme(self, dark):
        self.dark = dark
        self.setStyleSheet(stylesheet(dark))
        apply_window_chrome(self, dark)
        t = tokens(dark)
        self.light_button.setIcon(tinted_icon("sun.svg", t["text"] if not dark else t["muted"], 14))
        self.dark_button.setIcon(tinted_icon("moon.svg", t["text"] if dark else t["muted"], 14))
        self.remember_switch.dark = dark
        self.remember_switch.update()
        self.repository_button.apply_theme(dark)
        self.updates_button.apply_theme(dark)
        self.cache_button.apply_theme(dark)
        self.history_button.apply_theme(dark)

    def showEvent(self, event):
        super().showEvent(event)
        apply_window_chrome(self, self.dark)

    def hide_media(self):
        self.reject()
        self.privacy_requested.emit()

    def open_link(self, url):
        if not QDesktopServices.openUrl(QUrl(url)):
            QMessageBox.information(self, "无法打开浏览器", f"请在浏览器中打开：\n{url}")

from __future__ import annotations

import logging
import time
from pathlib import Path
from threading import Event

from PySide6.QtCore import QSettings, QSize, QStandardPaths, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QListView, QMainWindow, QMessageBox, QProgressBar, QPushButton,
                               QSlider, QStackedWidget, QStyledItemDelegate, QToolButton, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from app import __display_version__
from app.core.albums import calendar_albums
from app.core.library import calendar_counts, filter_items, sort_items
from app.core.scanner import ScanResult, scan_library
from app.services.thumbnail_service import ThumbnailService
from app.storage.index import LibraryIndex
from app.ui.album_grid import AlbumGrid
from app.ui.calendar_tree import CalendarTree
from app.ui.photo_grid import PhotoGrid
from app.ui.photo_viewer import PhotoViewer
from app.ui.privacy_preview import set_private_preview, handle_private_preview
from app.ui.privacy_page import InAppPrivacyPage
from app.ui.settings_dialog import SettingsDialog
from app.ui.theme import apply_window_chrome, asset_path, stylesheet, tinted_icon, tinted_pixmap, tokens

_closing_windows = set()


class ScanThread(QThread):
    batch_ready = Signal(object)
    progress = Signal(int, int)
    result_ready = Signal(object)

    def __init__(self, root: Path, parent=None, index_path=None, prefer_index=False):
        super().__init__(parent)
        self.root = root
        self.cancel = Event()
        self.last_progress = 0.0
        self.index_path, self.prefer_index = index_path, prefer_index

    def report(self, files, directories):
        now = time.monotonic()
        if now - self.last_progress > 0.1:
            self.progress.emit(files, directories)
            self.last_progress = now

    def run(self):
        try:
            index = LibraryIndex(self.index_path) if self.index_path else None
            index_warning = ""
            try:
                generation = index.generation() if index else None
            except Exception:
                logging.exception("本地索引不可用，继续只读扫描")
                index = None
                generation = None
                index_warning = "本地索引不可写，本次仍可浏览，下次需重新扫描。"
            if index and self.prefer_index:
                try:
                    cached = index.load(self.root, cancel=self.cancel)
                except Exception:
                    logging.exception("Cannot restore library index; scanning instead")
                    cached = None
                if cached is not None:
                    try:
                        offline = not self.root.is_dir()
                    except OSError:
                        offline = True
                    self.result_ready.emit(ScanResult(items=cached, from_index=True, offline=offline,
                                                      library_identity=index.loaded_identity,
                                                      cancelled=self.cancel.is_set()))
                    return
            result = scan_library(self.root, self.cancel, self.report, self.batch_ready.emit)
            result.index_warning = index_warning
            if index and not (result.cancelled or result.unavailable or result.error_count or result.identity_changed):
                try:
                    index.save(self.root, result.items, expected_identity=result.library_identity,
                               expected_generation=generation, cancel=self.cancel)
                except Exception as exc:
                    logging.exception("Cannot save library index")
                    result.index_warning = f"本地索引保存失败，下次启动将重新扫描：{exc}"
            if index and index.warning:
                result.index_warning = index.warning
        except Exception as exc:
            logging.exception("Scan failed")
            result = ScanResult(unavailable=True, errors=[str(exc)], error_count=1)
        self.result_ready.emit(result)


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings | None = None, initial_library: Path | None = None,
                 auto_load: bool = True):
        super().__init__()
        self.settings = settings if settings is not None else QSettings()
        data_path = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
        if self.settings.format() == QSettings.Format.IniFormat:
            data_path = Path(self.settings.fileName()).parent
        self.index_path = data_path / "library.sqlite3"
        self.items = []
        self.visible_items = []
        self.route = ("privacy",) if auto_load else ("all",)
        self.resume_route = ("all",)
        self.private_banner_visible = False
        self.remember_library = self.settings.value("remember_library", True, type=bool)
        if not self.remember_library:
            self.settings.remove("library")
        self.root = Path(str(self.settings.value("library"))) if self.settings.value("library") else None
        self.pending_library = initial_library
        # auto_load=False is the manual setup mode used by diagnostics/tests.
        # Normal startup opens the main interface on its neutral privacy page.
        self.startup_pending = auto_load
        self.scan = None
        self.scan_result = None
        self.scan_root = None
        self.snapshot = []
        self.library_identity = None
        self.snapshot_identity = None
        self.snapshot_root = None
        self.dirty = False
        self.settings_dialog = None
        self._cached_viewer = None
        self._closing = False
        self._close_ready = False
        self._maintenance = None
        self._resetting_history = False
        self._cache_clearing = False
        self._data_error = ""
        self._view_key = None
        self._summary_key = None
        self.dark = self.settings.value("dark", False, type=bool)
        self.sidebar_visible = self.settings.value("sidebar_visible", True, type=bool)
        self.crop_thumbnails = self.settings.value("thumbnail_crop", False, type=bool)
        self.setWindowTitle("ChronoView · 我的照片")
        self.resize(1280, 850)
        self.setMinimumSize(880, 580)
        cache = (data_path / "cache" if self.settings.format() == QSettings.Format.IniFormat else
                 Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)))
        self.thumbnails = ThumbnailService(cache / "thumbnails", self)
        self.build_ui()
        self.thumbnails.cache_cleared.connect(self._cache_cleared)
        self.thumbnails.cache_info_ready.connect(self._cache_info_ready)
        self.apply_theme()
        self.rebuild_navigation()
        self.update_view()
        self.preview_timer = QTimer(self)
        self.preview_timer.setInterval(400)
        self.preview_timer.timeout.connect(self.preview_scan)
        self.close_timer = QTimer(self)
        self.close_timer.setInterval(50)
        self.close_timer.timeout.connect(self._poll_close)
        QShortcut(QKeySequence("F5"), self, activated=self.refresh)
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.choose_folder)
        QShortcut(QKeySequence("Ctrl+B"), self, activated=self.toggle_sidebar)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.show_privacy)

    def build_ui(self):
        central = QWidget()
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # --- Sidebar ---
        self.sidebar = sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(244)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(16, 20, 14, 14)
        side.setSpacing(8)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(9)
        brand_icon = QLabel()
        brand_icon.setPixmap(QIcon(str(asset_path("chronoview.svg"))).pixmap(QSize(26, 26)))
        brand_icon.setFixedSize(26, 26)
        brand_row.addWidget(brand_icon)
        brand = QLabel("ChronoView")
        brand.setObjectName("brand")
        brand_row.addWidget(brand, 1)
        self.hide_sidebar_button = self.sidebar_button("隐藏侧边栏", "sidebar-hide.svg")
        brand_row.addWidget(self.hide_sidebar_button)
        side.addLayout(brand_row)

        subtitle = QLabel("让每个瞬间，回到时间里")
        subtitle.setObjectName("brandTagline")
        subtitle.setContentsMargins(2, 0, 0, 0)
        side.addWidget(subtitle)
        side.addSpacing(14)

        browse_section = QLabel("浏览")
        browse_section.setObjectName("section")
        side.addWidget(browse_section)

        self.privacy_button = self.make_privacy_button("privacyNavigation")
        side.addWidget(self.privacy_button)

        self.navigation = CalendarTree()
        self.navigation.setHeaderHidden(True)
        self.navigation.setIndentation(14)
        self.navigation.itemSelectionChanged.connect(self.navigate)
        side.addWidget(self.navigation, 1)

        # Compact Library Card
        library_card = QFrame()
        library_card.setObjectName("libraryCard")
        card_layout = QVBoxLayout(library_card)
        card_layout.setContentsMargins(12, 11, 12, 11)
        card_layout.setSpacing(8)

        card_header = QHBoxLayout()
        card_header.setSpacing(4)
        lib_section = QLabel("照片库")
        lib_section.setObjectName("section")
        lib_section.setStyleSheet("padding-left: 0;")
        card_header.addWidget(lib_section, 1)
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.setObjectName("cardAction")
        self.refresh_button.setIconSize(QSize(14, 14))
        self.refresh_button.setToolTip("刷新照片库 · F5")
        self.refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_button.clicked.connect(self.refresh)
        card_header.addWidget(self.refresh_button)
        card_layout.addLayout(card_header)

        self.path_label = QLabel("尚未选择照片库")
        self.path_label.setObjectName("libraryPath")
        self.path_label.setTextFormat(Qt.TextFormat.PlainText)
        self.path_label.setWordWrap(True)
        card_layout.addWidget(self.path_label)

        self.choose_button = QPushButton("选择文件夹")
        self.choose_button.setObjectName("primary")
        self.choose_button.setIconSize(QSize(15, 15))
        self.choose_button.setMinimumHeight(34)
        self.choose_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.choose_button.setToolTip("选择照片库文件夹 · Ctrl+O")
        self.choose_button.clicked.connect(self.choose_folder)
        card_layout.addWidget(self.choose_button)

        self.remember_checkbox = QCheckBox("记住照片库位置")
        self.remember_checkbox.setChecked(self.remember_library)
        self.remember_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remember_checkbox.toggled.connect(self.set_remember_library)
        card_layout.addWidget(self.remember_checkbox)

        side.addWidget(library_card)

        self.settings_button = QPushButton("设置")
        self.settings_button.setObjectName("settingsNavigation")
        self.settings_button.setIconSize(QSize(18, 18))
        self.settings_button.setMinimumHeight(40)
        self.settings_button.setCheckable(True)
        self.settings_button.setAccessibleName("设置")
        self.settings_button.setToolTip("外观、隐私偏好与关于 ChronoView")
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_button.clicked.connect(self.show_settings)
        side.addWidget(self.settings_button)

        outer.addWidget(sidebar)

        # --- Main Content ---
        content = QWidget()
        content.setObjectName("content")
        main = QVBoxLayout(content)
        main.setContentsMargins(28, 20, 24, 10)
        main.setSpacing(12)

        # Streamlined Header Row
        header = QHBoxLayout()
        header.setSpacing(10)
        self.show_sidebar_button = self.sidebar_button("显示侧边栏", "sidebar-show.svg")
        header.addWidget(self.show_sidebar_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.back_button = QPushButton("返回")
        self.back_button.setObjectName("backButton")
        self.back_button.setIconSize(QSize(16, 16))
        self.back_button.setFixedHeight(32)
        self.back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_button.clicked.connect(self.go_back)
        header.addWidget(self.back_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.heading = QLabel("全部照片")
        self.heading.setObjectName("heading")
        header.addWidget(self.heading, 0, Qt.AlignmentFlag.AlignVCenter)

        self.counts = QLabel("0 张照片 · 0 个视频")
        self.counts.setObjectName("subtitle")
        header.addWidget(self.counts, 0, Qt.AlignmentFlag.AlignVCenter)

        # Retained as hidden attribute for compatibility without adding header clutter.
        self.browse_hint = QLabel()
        self.browse_hint.setObjectName("muted")
        self.browse_hint.hide()

        header.addStretch(1)

        self.privacy_action = self.make_privacy_button("headerPill")
        self.privacy_action.setFixedHeight(32)
        header.addWidget(self.privacy_action, 0, Qt.AlignmentFlag.AlignVCenter)

        self.theme_button = QPushButton()
        self.theme_button.setObjectName("headerPill")
        self.theme_button.setIconSize(QSize(15, 15))
        self.theme_button.setFixedHeight(32)
        self.theme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_button.clicked.connect(self.toggle_theme)
        header.addWidget(self.theme_button, 0, Qt.AlignmentFlag.AlignVCenter)

        main.addLayout(header)

        # Compact Controls Bar (hidden on privacy page)
        self.controls_bar = QWidget()
        tools = QHBoxLayout(self.controls_bar)
        tools.setContentsMargins(0, 0, 0, 0)
        tools.setSpacing(10)

        self.sort_box = QComboBox()
        self.sort_box.addItems(["从新到旧", "从旧到新"])
        self.sort_box.setCurrentIndex(1)
        self.sort_box.setFixedHeight(32)
        self.sort_box.setCursor(Qt.CursorShape.PointingHandCursor)
        sort_view = QListView(self.sort_box)
        sort_view.setObjectName("sortPopup")
        sort_view.setUniformItemSizes(True)
        sort_view.setSpacing(0)
        sort_view.setWordWrap(False)
        sort_view.setItemDelegate(QStyledItemDelegate(sort_view))
        sort_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sort_box.setView(sort_view)
        self.sort_box.setMaxVisibleItems(2)
        self.sort_box.currentIndexChanged.connect(lambda: self.update_view())
        tools.addWidget(self.sort_box)

        # Fit / Cover Segmented Toggle
        self.crop_control = QFrame()
        self.crop_control.setObjectName("segmentedControl")
        self.crop_control.setFixedHeight(32)
        seg = QHBoxLayout(self.crop_control)
        seg.setContentsMargins(3, 3, 3, 3)
        seg.setSpacing(2)
        self.fit_button = QPushButton("完整")
        self.fit_button.setObjectName("segmentButton")
        self.fit_button.setCheckable(True)
        self.fit_button.setIconSize(QSize(14, 14))
        self.fit_button.setToolTip("完整显示图片，不裁切边缘")
        self.fit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cover_button = QPushButton("铺满")
        self.cover_button.setObjectName("segmentButton")
        self.cover_button.setCheckable(True)
        self.cover_button.setIconSize(QSize(14, 14))
        self.cover_button.setToolTip("居中铺满方格显示，点开大图仍看完整原图")
        self.cover_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.crop_group = QButtonGroup(self)
        self.crop_group.setExclusive(True)
        self.crop_group.addButton(self.fit_button)
        self.crop_group.addButton(self.cover_button)
        self.fit_button.setChecked(not self.crop_thumbnails)
        self.cover_button.setChecked(self.crop_thumbnails)
        self.fit_button.clicked.connect(lambda: self.set_crop_mode(False))
        self.cover_button.clicked.connect(lambda: self.set_crop_mode(True))
        seg.addWidget(self.fit_button)
        seg.addWidget(self.cover_button)
        tools.addWidget(self.crop_control)

        tools.addStretch(1)

        self.size_label = QLabel("缩略图")
        self.size_label.setObjectName("muted")
        tools.addWidget(self.size_label)

        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(110, 280)
        self.size_slider.setValue(self.settings.value("thumbnail_size", 180, type=int))
        self.size_slider.setFixedWidth(132)
        self.size_slider.setCursor(Qt.CursorShape.PointingHandCursor)
        tools.addWidget(self.size_slider)

        main.addWidget(self.controls_bar)

        self.banner = QLabel()
        self.banner.setObjectName("banner")
        self.banner.setTextFormat(Qt.TextFormat.PlainText)
        self.banner.setWordWrap(True)
        self.banner.hide()
        main.addWidget(self.banner)

        # --- Pages ---
        self.pages = QStackedWidget()
        self.albums = AlbumGrid(self)
        self.albums.opened.connect(self.select_route)
        self.albums.set_thumbnail_size(self.size_slider.value())

        self.grid = PhotoGrid(self.thumbnails)
        self.grid.set_thumbnail_size(self.size_slider.value())
        self.grid.set_crop_mode(self.crop_thumbnails)
        self.size_slider.valueChanged.connect(self.set_card_size)
        # Open both photos and videos on a double-click. Opening a video on
        # the first click sends the next click into the new playback window.
        self.grid.doubleClicked.connect(self.open_item)
        for key in ("Return", "Enter"):
            shortcut = QShortcut(QKeySequence(key), self.grid,
                                 activated=lambda: self.open_item(self.grid.currentIndex()))
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)

        # Elevated Empty State Card
        self.empty = QWidget()
        empty_outer = QVBoxLayout(self.empty)
        empty_outer.setContentsMargins(24, 24, 24, 24)
        empty_outer.addStretch()
        empty_card = QFrame()
        empty_card.setObjectName("emptyCard")
        empty_card.setFixedWidth(392)
        empty_layout = QVBoxLayout(empty_card)
        empty_layout.setContentsMargins(36, 38, 36, 34)
        empty_layout.setSpacing(12)
        self.empty_icon = QLabel()
        self.empty_icon.setObjectName("emblemBadge")
        self.empty_icon.setFixedSize(68, 68)
        self.empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_icon, alignment=Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addSpacing(4)
        self.empty_title = QLabel("把回忆带到这里")
        self.empty_title.setObjectName("emptyTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_title)
        self.empty_hint = QLabel("选择照片库最外层文件夹，自动发现所有子文件夹中的照片与视频。")
        self.empty_hint.setObjectName("muted")
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_hint)
        empty_layout.addSpacing(8)
        empty_choose = QPushButton("选择照片库")
        empty_choose.setObjectName("primary")
        empty_choose.setFixedWidth(168)
        empty_choose.setMinimumHeight(40)
        empty_choose.setCursor(Qt.CursorShape.PointingHandCursor)
        empty_choose.clicked.connect(self.choose_folder)
        self.empty_choose = empty_choose
        empty_layout.addWidget(empty_choose, alignment=Qt.AlignmentFlag.AlignHCenter)
        empty_outer.addWidget(empty_card, alignment=Qt.AlignmentFlag.AlignHCenter)
        empty_outer.addStretch()

        self.pages.addWidget(self.albums)
        self.pages.addWidget(self.grid)
        self.pages.addWidget(self.empty)
        self.safe_page = InAppPrivacyPage()
        self.safe_page.resume.clicked.connect(self.resume_browsing)
        self.pages.addWidget(self.safe_page)
        main.addWidget(self.pages, 1)
        outer.addWidget(content, 1)
        self.browser = central
        self.setCentralWidget(self.browser)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(110)
        self.progress.hide()
        self.cancel_button = QPushButton("取消扫描")
        self.cancel_button.setObjectName("cardAction")
        self.cancel_button.clicked.connect(self.cancel_scan)
        self.cancel_button.hide()
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().addPermanentWidget(self.cancel_button)
        self.statusBar().showMessage("选择文件夹开始浏览 · 支持中文路径与移动硬盘")
        self.set_sidebar_visible(self.sidebar_visible, persist=False)

    def showEvent(self, event):
        super().showEvent(event)
        apply_window_chrome(self, self.dark)
        set_private_preview(self, self.route == ("privacy",))

    def nativeEvent(self, event_type, message):
        if self.route == ("privacy",) and handle_private_preview(self, message):
            return True, 0
        return super().nativeEvent(event_type, message)

    def sidebar_button(self, label, icon):
        button = QToolButton()
        button.setObjectName("sidebarToggle")
        button.setFixedSize(30, 30)
        button.setIconSize(QSize(19, 19))
        button.setIcon(QIcon(str(asset_path(icon))))
        button.setToolTip(f"{label} · Ctrl+B")
        button.setAccessibleName(label)
        button.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(self.toggle_sidebar)
        return button

    def make_privacy_button(self, object_name="privacyNavigation"):
        button = QPushButton("隐私页")
        button.setObjectName(object_name)
        button.setIcon(QIcon(str(asset_path("privacy.svg"))))
        button.setIconSize(QSize(16, 16))
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip("隐藏照片和视频 · Ctrl+L")
        button.clicked.connect(self.show_privacy)
        return button

    def set_crop_mode(self, crop: bool):
        self.crop_thumbnails = crop
        self.fit_button.setChecked(not crop)
        self.cover_button.setChecked(crop)
        self.settings.setValue("thumbnail_crop", crop)
        self.grid.set_crop_mode(crop)
        self._update_themed_icons()

    def show_privacy(self):
        if self.route != ("privacy",):
            self.resume_route = self.route
            self.private_banner_visible = not self.banner.isHidden()
        self.route = ("privacy",)
        self.thumbnails.set_paused(True)
        viewer = getattr(self, "active_viewer", None)
        if viewer is not None:
            viewer.close()
        self.rebuild_navigation()
        self.update_view()
        self.safe_page.resume.setFocus()

    def resume_browsing(self):
        if self._closing or self._resetting_history:
            return
        if self.route != ("privacy",):
            return
        if self.startup_pending:
            self.open_previous_library()
            return
        route = self.resume_route
        if route[0] == "unknown" and not any(item.taken_at is None for item in self.items):
            route = ("all",)
        self.select_route(route)

    def toggle_sidebar(self):
        self.set_sidebar_visible(not self.sidebar_visible)

    def set_sidebar_visible(self, visible: bool, persist: bool = True):
        focused = self.focusWidget()
        sidebar_had_focus = focused is not None and self.sidebar.isAncestorOf(focused)
        self.sidebar_visible = visible
        self.sidebar.setVisible(visible)
        self.show_sidebar_button.setVisible(not visible)
        if sidebar_had_focus and not visible:
            self.pages.currentWidget().setFocus(Qt.FocusReason.ShortcutFocusReason)
        if persist:
            self.settings.setValue("sidebar_visible", visible)

    def _update_themed_icons(self):
        t = tokens(self.dark)
        hidden = self.route == ("privacy",)
        privacy_color = t["accent"] if hidden else t["text_secondary"]
        privacy_ic = tinted_icon("privacy.svg", privacy_color, 16)
        self.privacy_button.setIcon(privacy_ic)
        self.privacy_action.setIcon(privacy_ic)
        self.hide_sidebar_button.setIcon(tinted_icon("sidebar-hide.svg", t["muted"], 19))
        self.show_sidebar_button.setIcon(tinted_icon("sidebar-show.svg", t["text_secondary"], 19))
        self.back_button.setIcon(tinted_icon("back.svg", t["text_secondary"], 16))
        self.choose_button.setIcon(tinted_icon("folder.svg", "#ffffff", 15))
        self.refresh_button.setIcon(tinted_icon("refresh.svg", t["text_secondary"], 14))
        self.settings_button.setIcon(tinted_icon("settings.svg", t["text_secondary"], 18))
        theme_icon = "sun.svg" if self.dark else "moon.svg"
        self.theme_button.setIcon(tinted_icon(theme_icon, t["text_secondary"], 15))
        self.fit_button.setIcon(tinted_icon("fit-contain.svg", t["text"] if not self.crop_thumbnails else t["muted"], 14))
        self.cover_button.setIcon(tinted_icon("fit-cover.svg", t["text"] if self.crop_thumbnails else t["muted"], 14))
        self.empty_icon.setPixmap(tinted_pixmap("photo-gallery.svg", t["accent"], 30))

    def apply_theme(self):
        self.setStyleSheet(stylesheet(self.dark))
        apply_window_chrome(self, self.dark)
        self.grid.delegate.dark = self.dark
        self.albums.delegate.dark = self.dark
        self.navigation.delegate.dark = self.dark
        self.safe_page.apply_theme(self.dark)
        if self.settings_dialog is not None:
            self.settings_dialog.sync_preferences(self.dark, self.remember_library)
        self.theme_button.setText("浅色" if self.dark else "深色")
        self.theme_button.setToolTip("切换到浅色外观" if self.dark else "切换到深色外观")
        self._update_themed_icons()
        self.grid.viewport().update()
        self.albums.viewport().update()
        self.navigation.viewport().update()

    def set_card_size(self, edge):
        self.grid.set_thumbnail_size(edge)
        self.albums.set_thumbnail_size(edge)

    def show_settings(self):
        if self.settings_dialog is None:
            dialog = SettingsDialog(self.dark, self.remember_library, self)
            self.settings_dialog = dialog
            dialog.theme_requested.connect(self.set_theme)
            dialog.remember_requested.connect(self.remember_checkbox.setChecked)
            dialog.licenses_requested.connect(lambda: self.show_licenses(dialog))
            dialog.privacy_requested.connect(self.show_privacy)
            dialog.cache_clear_requested.connect(lambda: self.clear_local_data(False))
            dialog.history_clear_requested.connect(lambda: self.clear_local_data(True))
            dialog.finished.connect(lambda: self.settings_button.setChecked(False))
        self.settings_dialog.sync_preferences(self.dark, self.remember_library)
        self.thumbnails.request_cache_info()
        self.settings_button.setChecked(True)
        if self.settings_dialog.isVisible():
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()
        else:
            self.settings_dialog.open()

    def _cache_info_ready(self, info):
        if self.settings_dialog is not None and not self._cache_clearing:
            used = info.get("bytes", info.get("size", 0)) / 1024**3
            self.settings_dialog.data_status.setText(f"缩略图缓存 {used:.2f} GB / 5 GB")

    def clear_local_data(self, history=False):
        if self._closing or self._cache_clearing or self._maintenance is not None:
            return
        text = ("将清除所有照片库索引、上次使用的目录、软件日志和缩略图缓存，保留外观偏好。\n"
                "请先关闭其他运行中的 ChronoView 实例，避免其重新保存记录。\n\n"
                if history else "将清除软件生成的照片缩略图、视频封面和时长缓存。浏览时会重新生成。\n\n")
        answer = QMessageBox.question(self.settings_dialog, "清除本地数据", text +
                                      "原始照片和视频不会被修改、移动或删除。是否继续？",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._data_error = ""
        if not self.thumbnails.clear_cache():
            self.settings_dialog.data_status.setText("缓存正在维护，请稍后重试")
            return
        self._cache_clearing = True
        self.settings_dialog.cache_button.setEnabled(False)
        self.settings_dialog.history_button.setEnabled(False)
        self.settings_dialog.data_status.setText("正在清理本地数据…")
        if history:
            self._resetting_history = True
            self.show_privacy()
            if self._cached_viewer is not None:
                self._cached_viewer.dispose()
            if self.scan:
                self.scan.cancel.set()
            self.items = []
            self.snapshot = []
            self.root = self.pending_library = None
            self.library_identity = self.snapshot_identity = self.snapshot_root = None
            self.startup_pending = True
            self.settings.remove("library")
            self.settings.sync()
            self._view_key = self._summary_key = None
            self.update_view()
            self.safe_page.resume.setEnabled(False)
            self.choose_button.setEnabled(False)
            from app.services.local_data import ClearLocalData
            self._maintenance = ClearLocalData(self.index_path, self)
            self._maintenance.completed.connect(lambda error: setattr(self, "_data_error", error))
            self._maintenance.finished.connect(self._records_cleared)
            self._maintenance.start()

    def _records_cleared(self):
        job, self._maintenance = self._maintenance, None
        job.deleteLater()
        self._finish_data_clear()

    def _cache_cleared(self, success, message):
        self._cache_clearing = False
        if not success:
            self._data_error = message
        self._finish_data_clear()

    def _finish_data_clear(self):
        if self._cache_clearing or self._maintenance is not None:
            return
        if self.scan is not None:
            QTimer.singleShot(50, self._finish_data_clear)
            return
        self._resetting_history = False
        if self.settings_dialog is not None:
            self.settings_dialog.data_status.setText(self._data_error or "本地数据已清理")
            self.settings_dialog.cache_button.setEnabled(True)
            self.settings_dialog.history_button.setEnabled(True)
        self._data_error = ""
        if not self._closing:
            self.choose_button.setEnabled(True)
            self.safe_page.resume.setEnabled(True)

    def show_about(self):
        self.show_settings()

    def show_licenses(self, parent=None):
        import os
        video_notice = ("视频播放：libmpv 0.42.0（固定源码 LGPL 构建）。\n"
                        if os.environ.get("CHRONOVIEW_VIDEO_BACKEND") == "mpv" else "")
        QMessageBox.about(parent or self, "开源许可", f"ChronoView {__display_version__} · 本地照片与视频\n\n"
                          + video_notice +
                          "使用 Qt / PySide6 6.10.3（LGPLv3）和 FFmpeg 7.1.3（LGPLv2.1+）动态库。\n"
                          "This software uses libraries from the FFmpeg project under the LGPLv2.1 or later.\n\n"
                          "完整许可证、归属、构建配置和源码获取说明见绿色版 licenses 文件夹。\n"
                          "原始照片和视频只读访问。")

    def toggle_theme(self):
        self.set_theme(not self.dark)

    def set_theme(self, dark):
        self.dark = bool(dark)
        self.settings.setValue("dark", self.dark)
        self.apply_theme()

    def add_nav(self, parent, text, route):
        item = QTreeWidgetItem(parent, [text])
        item.setData(0, Qt.ItemDataRole.UserRole, route)
        if route == self.route:
            self.navigation.setCurrentItem(item)
        return item

    def rebuild_navigation(self):
        self.navigation.blockSignals(True)
        expanded = set()
        known = set()

        def remember(node):
            known.add(node.data(0, Qt.ItemDataRole.UserRole))
            if node.isExpanded():
                expanded.add(node.data(0, Qt.ItemDataRole.UserRole))
            for j in range(node.childCount()):
                remember(node.child(j))

        for i in range(self.navigation.topLevelItemCount()):
            remember(self.navigation.topLevelItem(i))
        self.navigation.clear()
        if self.route == ("privacy",):
            self.add_nav(self.navigation, "全部照片", ("all",))
            self.navigation.blockSignals(False)
            return
        collection = self.add_nav(self.navigation, "全部照片", ("all",))
        collection.setExpanded(("all",) in expanded or ("all",) not in known)
        summary_key = (id(self.items), len(self.items))
        if summary_key != self._summary_key:
            self._calendar_counts = calendar_counts(self.items)
            self._summary_key = summary_key
        counts = self._calendar_counts
        all_years = sorted({year for year, month in counts})
        for year in all_years:
            count = sum(n for (y, m), n in counts.items() if y == year)
            year_node = self.add_nav(collection, f"{year}年  ·  {count}", ("year", year))
            year_node.setToolTip(0, "点击浏览这一年的各个月份")
            year_node.setExpanded(("year", year) in expanded or self.route == ("year", year))
            for y, month in sorted(counts):
                if y == year:
                    self.add_nav(year_node, f"{month}月  ·  {counts[y, month]}", ("month", year, month))
        unknown = sum(item.taken_at is None for item in self.items)
        if unknown:
            self.add_nav(collection, f"未识别日期  ·  {unknown}", ("unknown",))
        current = self.navigation.currentItem()
        if current:
            ancestor = current.parent()
            while ancestor:
                ancestor.setExpanded(True)
                ancestor = ancestor.parent()
        self.navigation.blockSignals(False)

    def navigate(self):
        selected = self.navigation.currentItem()
        if selected:
            route = selected.data(0, Qt.ItemDataRole.UserRole)
            if self.route == ("privacy",):
                self.select_route(route)
                return
            self.route = route
            self.update_view()

    def go_back(self):
        if self.route == ("privacy",):
            return
        self.route = ("year", self.route[1]) if self.route[0] == "month" else ("all",)
        self.rebuild_navigation()
        self.update_view()

    def select_route(self, route):
        if route == ("privacy",):
            self.show_privacy()
            return
        if self.startup_pending:
            self.open_previous_library()
            return
        was_private = self.route == ("privacy",)
        self.route = route
        self.rebuild_navigation()
        self.update_view()
        if was_private:
            self.thumbnails.set_paused(False)
            if self.private_banner_visible:
                self.banner.show()

    def update_view(self):
        route = self.route
        hidden = route == ("privacy",)
        set_private_preview(self, hidden)
        for button in (self.privacy_button, self.privacy_action):
            button.setChecked(hidden)
        self._update_themed_icons()
        for widget in (self.counts, self.size_label, self.size_slider, self.refresh_button, self.controls_bar):
            widget.setVisible(not hidden)
        self.statusBar().setVisible(not hidden)
        if hidden:
            self._view_key = None
            self._summary_key = None
            self.thumbnails.set_paused(True)
            self.setWindowTitle("ChronoView · 隐私页")
            self.heading.setText("隐私页")
            self.browse_hint.setText("照片和视频已隐藏，继续浏览后恢复显示")
            self.back_button.hide()
            self.sort_box.hide()
            self.crop_control.hide()
            self.banner.hide()
            self.path_label.setText("照片库信息已隐藏")
            self.path_label.setToolTip("")
            self.visible_items = []
            self.grid.media_model.replace([])
            self.albums.album_model.replace([])
            if self.startup_pending:
                self.safe_page.title.setText("从这里开始浏览")
                self.safe_page.hint.setText("打开照片库后才会显示照片和视频")
                self.safe_page.resume.setText("打开上次照片库" if self.pending_library or self.root else "打开照片库")
            else:
                self.safe_page.title.setText("照片和视频已隐藏")
                self.safe_page.hint.setText("可以把软件停留在这里\n点击继续浏览，返回刚才的分类")
                self.safe_page.resume.setText("继续浏览")
            self.pages.setCurrentWidget(self.safe_page)
            return
        self.setWindowTitle("ChronoView · 我的照片")
        shown_root = self.scan_root if self.scan else self.root
        self.path_label.setText(str(shown_root) if shown_root else "尚未选择照片库")
        self.path_label.setToolTip(str(shown_root or ""))
        if route[0] == "year":
            visible = filter_items(self.items, year=route[1])
            heading = f"{route[1]}年"
        elif route[0] == "month":
            visible = filter_items(self.items, year=route[1], month=route[2])
            heading = f"{route[1]}年{route[2]}月"
        elif route[0] == "unknown":
            visible = filter_items(self.items, unknown=True)
            heading = "未识别日期"
        else:
            visible = self.items
            heading = "全部照片"
        view_key = (id(self.items), len(self.items), route, self.sort_box.currentIndex())
        if self._view_key != view_key:
            self.visible_items = sort_items(visible, self.sort_box.currentIndex() == 0)
            self._view_key = view_key
        self.heading.setText(heading)
        photos = sum(item.kind == "image" for item in visible)
        videos = len(visible) - photos
        self.counts.setText(f"{photos:,} 张照片  ·  {videos:,} 个视频" + ("  ·  正在扫描" if self.scan else ""))
        self.back_button.setEnabled(route != ("all",))
        self.back_button.setVisible(route != ("all",))
        self.back_button.setText(f"返回 {route[1]}年" if route[0] == "month" else "返回全部照片")
        self.back_button.setToolTip(f"返回 {route[1]}年的月份列表" if route[0] == "month" else "返回全部照片和视频")
        self.back_button.setAccessibleName(self.back_button.text())
        media_page = route[0] != "year"
        self.sort_box.setVisible(media_page)
        self.crop_control.setVisible(media_page)
        self.size_label.setText("缩略图" if media_page else "卡片大小")
        self.browse_hint.setText("双击照片或视频查看 · 可在左侧按年份、月份浏览" if route[0] == "all" else
                                 ("选择月份，查看照片和视频" if route[0] == "year" else
                                  "双击照片查看大图 · 双击视频自动播放"))
        if media_page:
            self.albums.album_model.replace([])
            self.grid.media_model.replace(self.visible_items)
            self.pages.setCurrentWidget(self.grid if visible else self.empty)
        else:
            self.grid.media_model.replace([])
            groups = calendar_albums(self.items, route[1])
            self.albums.album_model.replace(groups)
            self.pages.setCurrentWidget(self.albums if groups else self.empty)
        if self.scan:
            self.empty_title.setText("正在发现你的照片")
            self.empty_hint.setText("扫描在后台进行，找到的照片会陆续显示。")
        elif not self.root:
            self.empty_title.setText("把回忆带到这里")
            self.empty_hint.setText("选择照片库最外层文件夹，自动发现所有子文件夹中的照片与视频。")
        else:
            self.empty_title.setText("这里还没有照片")
            self.empty_hint.setText("此分类没有可显示的文件。可切换分类、刷新照片库或重新选择文件夹。")

    def set_remember_library(self, remember):
        self.remember_library = remember
        self.settings.setValue("remember_library", remember)
        if not remember:
            self.settings.remove("library")
            if self.startup_pending:
                self.root = None
        elif self.root and not self.scan:
            self.settings.setValue("library", str(self.root))
        self.settings.sync()
        if self.settings_dialog is not None:
            self.settings_dialog.sync_preferences(self.dark, self.remember_library)
        if self.route == ("privacy",):
            self.update_view()

    def open_previous_library(self):
        if not self.startup_pending or self._closing or self._resetting_history:
            return
        target = self.pending_library or self.root
        if target:
            self.start_scan(target, prefer_index=self.pending_library is None)
        else:
            self.choose_folder()
            if self.startup_pending:
                previous = self.navigation.blockSignals(True)
                self.navigation.setCurrentItem(None)
                self.navigation.blockSignals(previous)

    def choose_folder(self):
        if self.scan or self._closing or self._resetting_history:
            return
        initial = Path.home() if self.route == ("privacy",) else self.root or Path.home()
        folder = QFileDialog.getExistingDirectory(self, "选择照片库最外层文件夹", str(initial))
        if folder:
            self.start_scan(Path(folder))

    def refresh(self):
        if self.route == ("privacy",) or self._closing or self._resetting_history:
            return
        if not self.scan:
            self.start_scan(self.root) if self.root else self.choose_folder()

    def set_busy(self, busy):
        self.choose_button.setEnabled(not busy)
        self.empty_choose.setEnabled(not busy)
        self.refresh_button.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.cancel_button.setVisible(busy)
        self.cancel_button.setEnabled(busy)

    def start_scan(self, root: Path, prefer_index=False):
        if self.scan or self._closing or self._resetting_history:
            return
        self.startup_pending = False
        self.pending_library = None
        self.setWindowTitle("ChronoView · 我的照片")
        self.statusBar().show()
        self.snapshot = self.items
        self.snapshot_route = self.route
        self.snapshot_identity = self.library_identity
        self.snapshot_root = self.root
        self.items = []
        self.scan_root = root.absolute()
        if self.root != self.scan_root or self.route == ("privacy",):
            self.route = ("all",)
            self.thumbnails.set_paused(False)
        self.scan_result = None
        self.banner.hide()
        self.path_label.setText(str(self.scan_root))
        self.path_label.setToolTip(str(self.scan_root))
        self.scan = ScanThread(self.scan_root, self, self.index_path, prefer_index)
        self.scan.batch_ready.connect(self.receive_batch)
        self.scan.progress.connect(lambda files, dirs: self.statusBar().showMessage(
            f"正在扫描 · 已发现 {files:,} 个文件 · {dirs:,} 个文件夹"))
        self.scan.result_ready.connect(self.receive_result)
        self.scan.finished.connect(self.finish_scan)
        self.set_busy(True)
        self.update_view()
        self.preview_timer.start()
        self.scan.start()

    def receive_batch(self, batch):
        if self._closing:
            return
        self.items.extend(batch)
        self.dirty = True

    def preview_scan(self):
        if self.dirty:
            self.dirty = False
            self.rebuild_navigation()
            self.update_view()

    def receive_result(self, result):
        self.scan_result = result

    def finish_scan(self):
        if self._closing or self._resetting_history:
            thread, self.scan = self.scan, None
            if thread:
                thread.deleteLater()
            self.snapshot = []
            self.snapshot_identity = None
            self.snapshot_root = None
            self.scan_result = None
            return
        was_private = self.route == ("privacy",)
        self.preview_timer.stop()
        result = self.scan_result
        if result is None:
            result = ScanResult(unavailable=True, errors=["扫描线程未返回结果"], error_count=1)
        identity_conflict = (result.identity_changed or
                             (self.snapshot_root == self.scan_root and self.snapshot_identity is not None
                              and result.library_identity is not None
                              and self.snapshot_identity != result.library_identity))
        if (self.snapshot_root == self.scan_root and self.snapshot_identity is not None
                and result.library_identity is None and not result.offline):
            identity_conflict = True
        merged_snapshot = False
        if result.cancelled or result.unavailable:
            if identity_conflict:
                self.items = []
                self.route = ("all",)
                self.root = self.scan_root
                self.library_identity = None
                message = "硬盘身份发生变化，已停止显示此前照片库的记录，请重新选择照片库或刷新。"
            else:
                self.items = self.snapshot
                self.root = self.snapshot_root
                self.library_identity = self.snapshot_identity
                self.route = self.snapshot_route
                message = ("扫描已取消，已恢复扫描前的照片库。" if result.cancelled else
                           "照片库不可访问。请连接移动硬盘，或点击“选择文件夹”重新定位。已保留本次会话中的原有列表。")
            self.banner.setText(message)
            self.banner.show()
        else:
            self.items = result.items
            self.thumbnails.clear_errors()
            if (result.error_count and self.snapshot_root == self.scan_root
                    and self.snapshot_identity is not None
                    and self.snapshot_identity == result.library_identity and not identity_conflict):
                # A partial traversal cannot prove that unseen files were deleted.
                seen = {item.path for item in self.items}
                self.items.extend(item for item in self.snapshot if item.path not in seen)
                merged_snapshot = True
            self.root = self.scan_root
            self.library_identity = result.library_identity
            if self.remember_library:
                self.settings.setValue("library", str(self.root))
            else:
                self.settings.remove("library")
            message = f"扫描完成 · {len(self.items):,} 个文件 · {result.directories:,} 个文件夹"
            if result.from_index:
                message = f"已从本地索引恢复 {len(self.items):,} 个文件 · 点击刷新照片库检查新增或更改"
                self.banner.setText("移动硬盘当前不可访问，已保留离线照片库。重新连接后点击刷新，盘符变化可重新选择文件夹。"
                                    if result.offline else "已恢复上次照片库。新增或更改文件后，点击“刷新照片库”更新。")
                self.banner.show()
            if result.index_warning:
                self.banner.setText(result.index_warning)
                self.banner.show()
            if result.error_count:
                message += f" · {result.error_count} 处无法访问（见提示）"
                preservation = "该硬盘原有未读到的条目已保留。" if merged_snapshot else "无法确认同一照片库，未合并旧记录。"
                self.banner.setText(f"有 {result.error_count} 处无法访问，已跳过；{preservation}\n" +
                                    "\n".join(result.errors[:3]))
                self.banner.show()
                logging.warning("Partial scan: %s", result.errors)
        thread = self.scan
        self.scan = None
        thread.deleteLater()
        self.snapshot = []
        self.snapshot_identity = None
        self.snapshot_root = None
        if self.route == ("unknown",) and not any(item.taken_at is None for item in self.items):
            self.route = ("all",)
        self.path_label.setText(str(self.root) if self.root else "尚未选择照片库")
        self.path_label.setToolTip(str(self.root or ""))
        self.set_busy(False)
        if was_private:
            self.route = ("privacy",)
        if self.route == ("privacy",):
            self.private_banner_visible = not self.banner.isHidden()
        self.rebuild_navigation()
        self.update_view()
        self.statusBar().showMessage(message)

    def cancel_scan(self):
        if self.scan:
            self.scan.cancel.set()
            self.cancel_button.setEnabled(False)
            self.statusBar().showMessage("正在取消扫描…")

    def open_item(self, index):
        if self.route == ("privacy",) or not index.isValid() or getattr(self, "viewer_open", False):
            return
        self.viewer_open = True
        self.thumbnails.set_paused(True)
        try:
            viewer = self._cached_viewer
            if viewer is None:
                viewer = PhotoViewer(self.grid.media_model.items, index.row(), self)
                if hasattr(viewer, "reopen"):
                    viewer.retain_video_engine = True
                    self._cached_viewer = viewer
            else:
                viewer.retain_video_engine = True
                viewer.reopen(self.grid.media_model.items, index.row())
            self.active_viewer = viewer
            viewer.exec()
            if viewer is not self._cached_viewer:
                viewer.deleteLater()
        finally:
            self.active_viewer = None
            self.viewer_open = False
            self.thumbnails.set_paused(self.route == ("privacy",))

    def closeEvent(self, event):
        if self._close_ready:
            self.settings.setValue("thumbnail_size", self.size_slider.value())
            self.settings.setValue("thumbnail_crop", self.crop_thumbnails)
            self.settings.sync()
            super().closeEvent(event)
            _closing_windows.discard(self)
            return
        from app.ui.photo_viewer import cancel_pending_decodes
        from app.services.mpv_client import shutdown_all
        if self._closing:
            event.ignore()
            return
        self._closing = True
        self._close_started = time.monotonic()
        _closing_windows.add(self)
        self.preview_timer.stop()
        if self.settings_dialog is not None:
            self.settings_dialog.close()
        if self.scan:
            self.scan.cancel.set()
        self.show_privacy()
        if self._cached_viewer is not None:
            self._cached_viewer.dispose()
        cancel_pending_decodes()
        shutdown_all()
        self.thumbnails.shutdown()
        self.safe_page.title.setText("正在安全关闭")
        self.safe_page.hint.setText("正在结束后台任务，请稍候")
        self.safe_page.resume.setEnabled(False)
        self.settings_button.setEnabled(False)
        self.navigation.setEnabled(False)
        self.set_busy(True)
        self.close_timer.start()
        event.ignore()
        self._poll_close()

    def _poll_close(self):
        from app.ui.photo_viewer import has_pending_decodes
        from app.services.mpv_client import pending_shutdowns
        if time.monotonic() - self._close_started > 5:
            self.safe_page.hint.setText("设备读取尚未返回，已请求取消。\n窗口仍可响应，请检查硬盘连接。")
        if self.scan is not None or has_pending_decodes() or pending_shutdowns() or not self.thumbnails.is_idle():
            return
        if self._maintenance is not None and self._maintenance.isRunning():
            return
        self.close_timer.stop()
        self._close_ready = True
        # QWidget ignores recursive close() from inside the first closeEvent.
        # Defer even an already-idle close until that event has unwound.
        QTimer.singleShot(0, self.close)

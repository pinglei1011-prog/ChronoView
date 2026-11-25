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
from app.ui.privacy_page import InAppPrivacyPage
from app.ui.theme import apply_window_chrome, asset_path, stylesheet, tinted_icon, tinted_pixmap, tokens


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
            if index and self.prefer_index:
                try:
                    cached = index.load(self.root)
                except Exception:
                    logging.exception("Cannot restore library index; scanning instead")
                    cached = None
                if cached is not None:
                    try:
                        offline = not self.root.is_dir()
                    except OSError:
                        offline = True
                    self.result_ready.emit(ScanResult(items=cached, from_index=True, offline=offline,
                                                      cancelled=self.cancel.is_set()))
                    return
            result = scan_library(self.root, self.cancel, self.report, self.batch_ready.emit)
            if index and not (result.cancelled or result.unavailable or result.error_count):
                try:
                    index.save(self.root, result.items)
                except Exception as exc:
                    logging.exception("Cannot save library index")
                    result.index_warning = f"本地索引保存失败，下次启动将重新扫描：{exc}"
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
        self.dirty = False
        self.dark = self.settings.value("dark", False, type=bool)
        self.sidebar_visible = self.settings.value("sidebar_visible", True, type=bool)
        self.crop_thumbnails = self.settings.value("thumbnail_crop", False, type=bool)
        self.setWindowTitle("ChronoView · 我的照片")
        self.resize(1280, 850)
        self.setMinimumSize(880, 580)
        cache = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation))
        self.thumbnails = ThumbnailService(cache / "thumbnails", self)
        self.build_ui()
        self.apply_theme()
        self.rebuild_navigation()
        self.update_view()
        self.preview_timer = QTimer(self)
        self.preview_timer.setInterval(400)
        self.preview_timer.timeout.connect(self.preview_scan)
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

        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(4, 2, 2, 0)
        footer_row.setSpacing(4)
        footer = QLabel(f"{__display_version__} · 本地只读")
        footer.setObjectName("sidebarFooter")
        footer_row.addWidget(footer, 1)
        self.about_button = QPushButton("关于")
        self.about_button.setObjectName("ghostButton")
        self.about_button.setToolTip("关于与许可证")
        self.about_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.about_button.clicked.connect(self.show_about)
        footer_row.addWidget(self.about_button)
        side.addLayout(footer_row)

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
        self.grid.doubleClicked.connect(lambda index: self.open_item(index)
                                       if index.data(Qt.ItemDataRole.UserRole).kind == "image" else None)
        self.grid.clicked.connect(lambda index: self.open_item(index)
                                 if index.data(Qt.ItemDataRole.UserRole).kind == "video" else None)
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
        self.theme_button.setText("浅色" if self.dark else "深色")
        self.theme_button.setToolTip("切换到浅色外观" if self.dark else "切换到深色外观")
        self._update_themed_icons()
        self.grid.viewport().update()
        self.albums.viewport().update()
        self.navigation.viewport().update()

    def set_card_size(self, edge):
        self.grid.set_thumbnail_size(edge)
        self.albums.set_thumbnail_size(edge)

    def show_about(self):
        QMessageBox.about(self, "关于 ChronoView", f"ChronoView {__display_version__} · 本地照片与视频\n\n"
                          "使用 Qt / PySide6 6.10.3（LGPLv3）和 FFmpeg 7.1.3（LGPLv2.1+）动态库。\n"
                          "This software uses libraries from the FFmpeg project under the LGPLv2.1 or later.\n\n"
                          "完整许可证、归属、构建配置和源码获取说明见绿色版 licenses 文件夹。\n"
                          "原始照片和视频只读访问。")

    def toggle_theme(self):
        self.dark = not self.dark
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
        counts = calendar_counts(self.items)
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
        for button in (self.privacy_button, self.privacy_action):
            button.setChecked(hidden)
        self._update_themed_icons()
        for widget in (self.counts, self.size_label, self.size_slider, self.refresh_button, self.controls_bar):
            widget.setVisible(not hidden)
        self.statusBar().setVisible(not hidden)
        if hidden:
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
        self.visible_items = sort_items(visible, self.sort_box.currentIndex() == 0)
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
        self.browse_hint.setText("全部照片和视频 · 可在左侧按年份、月份浏览" if route[0] == "all" else
                                 ("选择月份，查看照片和视频" if route[0] == "year" else
                                  "双击照片查看大图 · 单击视频播放"))
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
        if self.route == ("privacy",):
            self.update_view()

    def open_previous_library(self):
        if not self.startup_pending:
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
        if self.scan:
            return
        initial = Path.home() if self.route == ("privacy",) else self.root or Path.home()
        folder = QFileDialog.getExistingDirectory(self, "选择照片库最外层文件夹", str(initial))
        if folder:
            self.start_scan(Path(folder))

    def refresh(self):
        if self.route == ("privacy",):
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
        if self.scan:
            return
        self.startup_pending = False
        self.pending_library = None
        self.setWindowTitle("ChronoView · 我的照片")
        self.statusBar().show()
        self.snapshot = self.items
        self.snapshot_route = self.route
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
        was_private = self.route == ("privacy",)
        self.preview_timer.stop()
        result = self.scan_result
        if result is None:
            result = ScanResult(unavailable=True, errors=["扫描线程未返回结果"], error_count=1)
        if result.cancelled or result.unavailable:
            self.items = self.snapshot
            self.route = self.snapshot_route
            message = ("扫描已取消，已恢复扫描前的照片库。" if result.cancelled else
                       "照片库不可访问。请连接移动硬盘，或点击“选择文件夹”重新定位。已保留本次会话中的原有列表。")
            self.banner.setText(message)
            self.banner.show()
        else:
            self.items = result.items
            self.thumbnails.clear_errors()
            if result.error_count and self.root == self.scan_root:
                # A partial traversal cannot prove that unseen files were deleted.
                seen = {item.path for item in self.items}
                self.items.extend(item for item in self.snapshot if item.path not in seen)
            self.root = self.scan_root
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
                self.banner.setText(f"有 {result.error_count} 处无法访问，已跳过；原有未读到的条目已保留。\n" +
                                    "\n".join(result.errors[:3]))
                self.banner.show()
                logging.warning("Partial scan: %s", result.errors)
        thread = self.scan
        self.scan = None
        thread.deleteLater()
        self.snapshot = []
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
            viewer = PhotoViewer(self.grid.media_model.items, index.row(), self)
            self.active_viewer = viewer
            viewer.exec()
            viewer.deleteLater()
        finally:
            self.active_viewer = None
            self.viewer_open = False
            self.thumbnails.set_paused(self.route == ("privacy",))

    def closeEvent(self, event):
        self.preview_timer.stop()
        if self.scan:
            self.scan.cancel.set()
            self.scan.wait()
        self.thumbnails.shutdown()
        self.settings.setValue("thumbnail_size", self.size_slider.value())
        self.settings.setValue("thumbnail_crop", self.crop_thumbnails)
        self.settings.sync()
        super().closeEvent(event)

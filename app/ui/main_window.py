from __future__ import annotations

import logging
import time
from pathlib import Path
from threading import Event

from PySide6.QtCore import QSettings, QStandardPaths, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QMainWindow, QProgressBar, QPushButton,
                               QSlider, QStackedWidget, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from app.core.library import calendar_counts, filter_items, sort_items
from app.core.scanner import ScanResult, scan_library
from app.services.thumbnail_service import ThumbnailService
from app.ui.photo_grid import PhotoGrid
from app.ui.photo_viewer import PhotoViewer
from app.ui.theme import stylesheet


class ScanThread(QThread):
    batch_ready = Signal(object)
    progress = Signal(int, int)
    result_ready = Signal(object)

    def __init__(self, root: Path, parent=None):
        super().__init__(parent)
        self.root = root
        self.cancel = Event()
        self.last_progress = 0.0

    def report(self, files, directories):
        now = time.monotonic()
        if now - self.last_progress > 0.1:
            self.progress.emit(files, directories)
            self.last_progress = now

    def run(self):
        try:
            result = scan_library(self.root, self.cancel, self.report, self.batch_ready.emit)
        except Exception as exc:
            logging.exception("Scan failed")
            result = ScanResult(unavailable=True, errors=[str(exc)], error_count=1)
        self.result_ready.emit(result)


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings | None = None, initial_library: Path | None = None,
                 auto_load: bool = True):
        super().__init__()
        self.settings = settings if settings is not None else QSettings()
        self.items = []
        self.route = ("all",)
        self.root = Path(str(self.settings.value("library", ""))) if self.settings.value("library") else None
        self.scan = None
        self.scan_result = None
        self.scan_root = None
        self.snapshot = []
        self.dirty = False
        self.dark = self.settings.value("dark", False, type=bool)
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
        if auto_load:
            target = initial_library or self.root
            if target:
                QTimer.singleShot(0, lambda: self.start_scan(target))

    def build_ui(self):
        central = QWidget()
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(238)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(20, 26, 16, 20)
        brand = QLabel("ChronoView")
        brand.setObjectName("brand")
        side.addWidget(brand)
        subtitle = QLabel("让每个瞬间，回到时间里")
        subtitle.setObjectName("muted")
        side.addWidget(subtitle)
        side.addSpacing(28)
        section = QLabel("我的照片")
        section.setObjectName("section")
        side.addWidget(section)
        self.navigation = QTreeWidget()
        self.navigation.setHeaderHidden(True)
        self.navigation.setIndentation(14)
        self.navigation.itemSelectionChanged.connect(self.navigate)
        side.addWidget(self.navigation, 1)
        section = QLabel("照片库")
        section.setObjectName("section")
        side.addWidget(section)
        self.path_label = QLabel("尚未选择照片库")
        self.path_label.setObjectName("muted")
        self.path_label.setTextFormat(Qt.TextFormat.PlainText)
        self.path_label.setWordWrap(True)
        side.addWidget(self.path_label)
        self.choose_button = QPushButton("选择文件夹")
        self.choose_button.setObjectName("primary")
        self.choose_button.clicked.connect(self.choose_folder)
        side.addWidget(self.choose_button)
        self.refresh_button = QPushButton("刷新照片库  ·  F5")
        self.refresh_button.clicked.connect(self.refresh)
        side.addWidget(self.refresh_button)
        footer = QLabel("本地浏览 · 原始文件只读\nv0.1  第一阶段")
        footer.setObjectName("muted")
        side.addSpacing(12)
        side.addWidget(footer)
        outer.addWidget(sidebar)
        content = QWidget()
        content.setObjectName("content")
        main = QVBoxLayout(content)
        main.setContentsMargins(28, 25, 24, 12)
        main.setSpacing(14)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        self.heading = QLabel("全部照片")
        self.heading.setObjectName("heading")
        titles.addWidget(self.heading)
        self.counts = QLabel("0 张照片 · 0 个视频")
        self.counts.setObjectName("subtitle")
        titles.addWidget(self.counts)
        header.addLayout(titles, 1)
        self.theme_button = QPushButton()
        self.theme_button.clicked.connect(self.toggle_theme)
        header.addWidget(self.theme_button)
        main.addLayout(header)
        tools = QHBoxLayout()
        self.back_button = QPushButton("← 返回")
        self.back_button.clicked.connect(self.go_back)
        tools.addWidget(self.back_button)
        self.sort_box = QComboBox()
        self.sort_box.addItems(["从新到旧  ▾", "从旧到新  ▾"])
        self.sort_box.currentIndexChanged.connect(lambda: self.update_view())
        tools.addWidget(self.sort_box)
        tools.addStretch()
        size_label = QLabel("缩略图")
        size_label.setObjectName("muted")
        tools.addWidget(size_label)
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(110, 280)
        self.size_slider.setValue(self.settings.value("thumbnail_size", 180, type=int))
        self.size_slider.setFixedWidth(125)
        tools.addWidget(self.size_slider)
        main.addLayout(tools)
        self.banner = QLabel()
        self.banner.setTextFormat(Qt.TextFormat.PlainText)
        self.banner.setWordWrap(True)
        self.banner.hide()
        main.addWidget(self.banner)
        self.pages = QStackedWidget()
        self.grid = PhotoGrid(self.thumbnails)
        self.grid.set_thumbnail_size(self.size_slider.value())
        self.size_slider.valueChanged.connect(self.grid.set_thumbnail_size)
        self.grid.doubleClicked.connect(self.open_item)
        for key in ("Return", "Enter"):
            shortcut = QShortcut(QKeySequence(key), self.grid,
                                 activated=lambda: self.open_item(self.grid.currentIndex()))
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self.empty = QWidget()
        empty_layout = QVBoxLayout(self.empty)
        empty_layout.addStretch()
        symbol = QLabel("▧")
        symbol.setAlignment(Qt.AlignmentFlag.AlignCenter)
        symbol.setStyleSheet("font-size: 68px; color: #4389f5;")
        empty_layout.addWidget(symbol)
        self.empty_title = QLabel("把回忆带到这里")
        self.empty_title.setObjectName("emptyTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_title)
        self.empty_hint = QLabel("选择照片库最外层文件夹，自动发现所有子文件夹中的照片与视频。")
        self.empty_hint.setObjectName("muted")
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_hint)
        empty_layout.addSpacing(15)
        empty_choose = QPushButton("选择照片库")
        empty_choose.setObjectName("primary")
        empty_choose.setFixedWidth(150)
        empty_choose.clicked.connect(self.choose_folder)
        self.empty_choose = empty_choose
        empty_layout.addWidget(empty_choose, alignment=Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch()
        self.pages.addWidget(self.grid)
        self.pages.addWidget(self.empty)
        main.addWidget(self.pages, 1)
        outer.addWidget(content, 1)
        self.setCentralWidget(central)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(110)
        self.progress.hide()
        self.cancel_button = QPushButton("取消扫描")
        self.cancel_button.clicked.connect(self.cancel_scan)
        self.cancel_button.hide()
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().addPermanentWidget(self.cancel_button)
        self.statusBar().showMessage("选择文件夹开始浏览 · 支持中文路径与移动硬盘")

    def apply_theme(self):
        self.setStyleSheet(stylesheet(self.dark))
        self.grid.delegate.dark = self.dark
        self.theme_button.setText("浅色外观" if self.dark else "深色外观")
        self.grid.viewport().update()

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
        iterator = self.navigation.invisibleRootItem()
        for i in range(iterator.childCount()):
            node = iterator.child(i)
            if node.isExpanded():
                expanded.add(node.data(0, Qt.ItemDataRole.UserRole))
            for j in range(node.childCount()):
                if node.child(j).isExpanded():
                    expanded.add(node.child(j).data(0, Qt.ItemDataRole.UserRole))
        self.navigation.clear()
        self.add_nav(self.navigation, "全部照片", ("all",))
        years = self.add_nav(self.navigation, "按年份", ("years",))
        months = self.add_nav(self.navigation, "按月份", ("months",))
        counts = calendar_counts(self.items)
        all_years = sorted({year for year, month in counts}, reverse=True)
        for year in all_years:
            count = sum(n for (y, m), n in counts.items() if y == year)
            year_node = self.add_nav(years, f"{year}年  ·  {count}", ("year", year))
            for y, month in sorted(counts, reverse=True):
                if y == year:
                    self.add_nav(year_node, f"{month}月  ·  {counts[y, month]}", ("month", year, month))
        for year, month in sorted(counts, reverse=True):
            self.add_nav(months, f"{year}年{month}月  ·  {counts[year, month]}", ("month", year, month))
        unknown = sum(item.taken_at is None for item in self.items)
        self.add_nav(self.navigation, f"未识别日期  ·  {unknown}", ("unknown",))
        for i in range(self.navigation.topLevelItemCount()):
            node = self.navigation.topLevelItem(i)
            route = node.data(0, Qt.ItemDataRole.UserRole)
            node.setExpanded(route in expanded or (route == ("years",) and not expanded))
            for j in range(node.childCount()):
                child = node.child(j)
                child.setExpanded(child.data(0, Qt.ItemDataRole.UserRole) in expanded or
                                  (len(self.route) > 1 and child.data(0, Qt.ItemDataRole.UserRole) == ("year", self.route[1])))
        self.navigation.blockSignals(False)

    def navigate(self):
        selected = self.navigation.currentItem()
        if selected:
            self.route = selected.data(0, Qt.ItemDataRole.UserRole)
            self.update_view()

    def go_back(self):
        self.route = ("year", self.route[1]) if self.route[0] == "month" else ("all",)
        self.rebuild_navigation()
        self.update_view()

    def update_view(self):
        route = self.route
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
            heading = {"years": "按年份浏览", "months": "按月份浏览"}.get(route[0], "全部照片")
        self.heading.setText(heading)
        photos = sum(item.kind == "image" for item in visible)
        videos = len(visible) - photos
        self.counts.setText(f"{photos:,} 张照片  ·  {videos:,} 个视频" + ("  ·  正在扫描" if self.scan else ""))
        self.back_button.setEnabled(route != ("all",))
        self.grid.media_model.replace(sort_items(visible, self.sort_box.currentIndex() == 0))
        self.pages.setCurrentWidget(self.grid if visible else self.empty)
        if self.scan:
            self.empty_title.setText("正在发现你的照片")
            self.empty_hint.setText("扫描在后台进行，找到的照片会陆续显示。")
        elif not self.root:
            self.empty_title.setText("把回忆带到这里")
            self.empty_hint.setText("选择照片库最外层文件夹，自动发现所有子文件夹中的照片与视频。")
        else:
            self.empty_title.setText("这里还没有照片")
            self.empty_hint.setText("此分类没有可显示的文件。可切换分类、刷新照片库或重新选择文件夹。")

    def choose_folder(self):
        if self.scan:
            return
        folder = QFileDialog.getExistingDirectory(self, "选择照片库最外层文件夹", str(self.root or Path.home()))
        if folder:
            self.start_scan(Path(folder))

    def refresh(self):
        if not self.scan:
            self.start_scan(self.root) if self.root else self.choose_folder()

    def set_busy(self, busy):
        self.choose_button.setEnabled(not busy)
        self.empty_choose.setEnabled(not busy)
        self.refresh_button.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.cancel_button.setVisible(busy)
        self.cancel_button.setEnabled(busy)

    def start_scan(self, root: Path):
        if self.scan:
            return
        self.snapshot = self.items
        self.snapshot_route = self.route
        self.items = []
        self.scan_root = root.absolute()
        if self.root != self.scan_root:
            self.route = ("all",)
        self.scan_result = None
        self.banner.hide()
        self.path_label.setText(str(self.scan_root))
        self.path_label.setToolTip(str(self.scan_root))
        self.scan = ScanThread(self.scan_root, self)
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
            self.settings.setValue("library", str(self.root))
            message = f"扫描完成 · {len(self.items):,} 个文件 · {result.directories:,} 个文件夹"
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
        self.path_label.setText(str(self.root) if self.root else "尚未选择照片库")
        self.path_label.setToolTip(str(self.root or ""))
        self.set_busy(False)
        self.rebuild_navigation()
        self.update_view()
        self.statusBar().showMessage(message)

    def cancel_scan(self):
        if self.scan:
            self.scan.cancel.set()
            self.cancel_button.setEnabled(False)
            self.statusBar().showMessage("正在取消扫描…")

    def open_item(self, index):
        if not index.isValid() or getattr(self, "viewer_open", False):
            return
        self.viewer_open = True
        try:
            viewer = PhotoViewer(self.grid.media_model.items, index.row(), self)
            viewer.exec()
            viewer.deleteLater()
        finally:
            self.viewer_open = False

    def closeEvent(self, event):
        self.preview_timer.stop()
        if self.scan:
            self.scan.cancel.set()
            self.scan.wait()
        self.thumbnails.shutdown()
        self.settings.setValue("thumbnail_size", self.size_slider.value())
        self.settings.sync()
        super().closeEvent(event)

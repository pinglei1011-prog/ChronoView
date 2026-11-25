from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Event
import weakref

from PySide6.QtCore import QEvent, QObject, QSize, QThreadPool, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QIcon, QImage, QKeySequence, QPainter, QPixmap, QShortcut, QTransform
from PySide6.QtWidgets import (QDialog, QFrame, QGraphicsScene, QGraphicsView, QHBoxLayout,
                               QApplication, QLabel, QPushButton, QStackedWidget, QToolButton, QVBoxLayout)

from app.core.library import MediaItem
from app.services.images import ImageReadCancelled, image_error_message, read_image
from app.ui.theme import apply_window_chrome, asset_path, tinted_icon, tinted_pixmap, viewer_stylesheet
from app.ui.video_player import VideoPlayer


class ImageSignals(QObject):
    done = Signal(object, QImage, str)


@dataclass
class DecodeRequest:
    owner: object
    owner_id: int
    item: MediaItem
    token: int
    edge: int | None
    cancel: Event = field(default_factory=Event)


class ImageTask:
    def __init__(self, request, signals):
        self.request = request
        self.signals = signals

    def run(self):
        try:
            image = read_image(self.request.item.path, self.request.edge, cancel=self.request.cancel)
            if self.request.cancel.is_set():
                image = QImage()
            self.signals.done.emit(self.request, image, "")
        except ImageReadCancelled:
            self.signals.done.emit(self.request, QImage(), "")
        except Exception as exc:
            self.signals.done.emit(self.request, QImage(), image_error_message(exc))


class ImageDecoder(QObject):
    """One raster at a time across viewers; pending requests carry no pixel data.

    The application owns this object until its active task finishes. A closed
    viewer never waits for a disk read and cannot be revived by an old result.
    """
    def __init__(self):
        super().__init__(QApplication.instance())
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        # The GUI-owned emitter outlives every job. Per-QRunnable signal
        # objects can be deleted while emit() is still returning on Windows.
        self.signals = ImageSignals(self)
        self.signals.done.connect(self._finished, Qt.ConnectionType.QueuedConnection)
        self.active = None
        self.pending = OrderedDict()

    def request(self, owner, item, token, edge):
        self.cancel_owner(id(owner))
        request = DecodeRequest(weakref.ref(owner), id(owner), item, token, edge)
        self.pending[request.owner_id] = request
        self._start_next()
        return request

    def cancel_owner(self, owner_id):
        pending = self.pending.pop(owner_id, None)
        if pending is not None:
            pending.cancel.set()
        if self.active is not None and self.active.request.owner_id == owner_id:
            self.active.request.cancel.set()

    def _start_next(self):
        if self.active is not None:
            return
        while self.pending:
            _, request = self.pending.popitem(last=False)
            owner = request.owner()
            if request.cancel.is_set() or owner is None or owner._closed:
                continue
            self.active = task = ImageTask(request, self.signals)
            self.pool.start(task.run)
            break

    @Slot(object, QImage, str)
    def _finished(self, request, image, error):
        self.active = None
        owner = request.owner()
        if not request.cancel.is_set() and owner is not None and not owner._closed:
            owner.loaded(request.token, image, error)
        self._start_next()


_image_decoder = None


def image_decoder():
    global _image_decoder
    if _image_decoder is None:
        _image_decoder = ImageDecoder()
    return _image_decoder


def has_pending_decodes():
    """The main window defers final application exit while this is true."""
    return bool(_image_decoder is not None and (
        _image_decoder.active is not None or _image_decoder.pending
        or _image_decoder.pool.activeThreadCount()))


def cancel_pending_decodes():
    if _image_decoder is not None:
        for owner_id in list(_image_decoder.pending):
            _image_decoder.cancel_owner(owner_id)
        if _image_decoder.active is not None:
            _image_decoder.active.request.cancel.set()


class ZoomView(QGraphicsView):
    detail_requested = Signal()
    preview_resized = Signal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setStyleSheet("border: none; background: #0b0d11;")
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.fit_mode = True

    def fit(self):
        self.fit_mode = True
        self.resetTransform()
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def actual(self):
        self.fit_mode = False
        self.resetTransform()
        self.detail_requested.emit()

    def zoom(self, factor):
        self.fit_mode = False
        next_scale = self.transform().m11() * factor
        if 0.01 <= next_scale <= 30:
            self.scale(factor, factor)
            if factor > 1:
                self.detail_requested.emit()

    def wheelEvent(self, event):
        self.zoom(1.2 if event.angleDelta().y() > 0 else 1 / 1.2)
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fit_mode:
            self.fit()
            self.preview_resized.emit()


class PhotoViewer(QDialog):
    def __init__(self, items: list[MediaItem], position: int, parent=None):
        super().__init__(parent)
        self.items, self.position = list(items), position
        self.token = 0
        self.jobs = {}
        self._closed = False
        self._is_full = False
        self._full_requested = False
        self._preview_edge = 0
        self.decoder = image_decoder()
        self.pool = self.decoder.pool
        owner_id, decoder = id(self), self.decoder
        self.destroyed.connect(lambda: decoder.cancel_owner(owner_id))
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self.resize_preview)
        self.setObjectName("photoViewer")
        self.setStyleSheet(viewer_stylesheet())
        self.setWindowTitle("ChronoView · 查看")
        self.resize(1120, 780)
        self.setMinimumSize(640, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Top Cinema Bar ---
        top_bar = QFrame()
        top_bar.setObjectName("viewerTopBar")
        top_bar.setFixedHeight(52)
        bar = QHBoxLayout(top_bar)
        bar.setContentsMargins(18, 0, 16, 0)
        bar.setSpacing(10)

        self.title = QLabel()
        self.title.setObjectName("viewerTitle")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setWordWrap(False)
        bar.addWidget(self.title, 1)

        self.previous = QPushButton("上一项")
        self.following = QPushButton("下一项")
        for button, icon, hint in [(self.previous, "back.svg", "上一项 · 左方向键"),
                                   (self.following, "forward.svg", "下一项 · 右方向键")]:
            button.setObjectName("viewerNavigation")
            button.setIcon(tinted_icon(icon, "#cbd5e1", 16))
            button.setIconSize(QSize(16, 16))
            button.setFixedHeight(32)
            button.setToolTip(hint)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.following.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.previous.clicked.connect(self.previous_item, Qt.ConnectionType.QueuedConnection)
        self.following.clicked.connect(self.next_item, Qt.ConnectionType.QueuedConnection)
        bar.addWidget(self.previous)
        bar.addWidget(self.following)
        layout.addWidget(top_bar)

        # --- Stage ---
        self.pages = QStackedWidget()
        self.view = ZoomView()
        self.view.detail_requested.connect(self.request_original)
        self.view.preview_resized.connect(lambda: self._preview_timer.start(150))
        self.video = VideoPlayer()
        self.video.fullscreen_requested.connect(self.toggle_fullscreen)
        if hasattr(self.video, "navigate_requested"):
            self.video.navigate_requested.connect(self.navigate, Qt.ConnectionType.QueuedConnection)
            self.video.escape_requested.connect(self.escape, Qt.ConnectionType.QueuedConnection)
            if parent is not None and hasattr(parent, "show_privacy"):
                self.video.privacy_requested.connect(parent.show_privacy, Qt.ConnectionType.QueuedConnection)
        self.message = QLabel()
        self.message.setObjectName("viewerMessage")
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        self.message.setMargin(35)
        self.pages.addWidget(self.view)
        self.pages.addWidget(self.message)
        self.pages.addWidget(self.video)
        self.photo_previous = self.navigation_button("viewer-prev.svg", "上一项", -1)
        self.photo_following = self.navigation_button("viewer-next.svg", "下一项", 1)
        self.view.viewport().installEventFilter(self)
        self.position_photo_arrows()
        layout.addWidget(self.pages, 1)

        # --- Bottom Cinema Bar ---
        bottom_bar = QFrame()
        bottom_bar.setObjectName("viewerBottomBar")
        bottom_bar.setFixedHeight(54)
        tools = QHBoxLayout(bottom_bar)
        tools.setContentsMargins(18, 0, 16, 0)
        tools.setSpacing(8)

        self.info = QLabel()
        self.info.setObjectName("viewerInfo")
        tools.addWidget(self.info, 1)

        self.photo_tools = []
        tool_specs = [
            ("", "zoom-out.svg", "缩小", lambda: self.view.zoom(1 / 1.25), True, "viewerTool"),
            ("", "zoom-in.svg", "放大", lambda: self.view.zoom(1.25), True, "viewerTool"),
            ("适应窗口", None, "缩放以适应窗口", self.view.fit, True, "viewerTool"),
            ("原始尺寸", None, "按 100% 原始像素显示", self.view.actual, True, "viewerTool"),
            ("全屏", "fullscreen.svg", "切换全屏 · F11", self.toggle_fullscreen, False, "viewerTool"),
            ("关闭", "close.svg", "关闭查看器 · Esc", self.close, False, "viewerClose"),
        ]
        for text, icon_name, tip, callback, is_photo_tool, obj_name in tool_specs:
            button = QPushButton(text)
            button.setObjectName(obj_name)
            button.setFixedHeight(32)
            button.setToolTip(tip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            if icon_name:
                button.setIcon(tinted_icon(icon_name, "#cbd5e1", 15))
                button.setIconSize(QSize(15, 15))
            if not text:
                button.setFixedWidth(36)
                button.setAccessibleName(tip)
            button.clicked.connect(callback)
            tools.addWidget(button)
            if is_photo_tool:
                self.photo_tools.append(button)
        layout.addWidget(bottom_bar)

        for key, callback in [("Left", lambda: self.navigate(-1)),
                              ("Right", lambda: self.navigate(1)),
                              ("F11", self.toggle_fullscreen),
                              ("Space", self.toggle_playback),
                              ("Escape", self.escape)]:
            QShortcut(QKeySequence(key), self, activated=callback)
        if parent is not None and hasattr(parent, "show_privacy"):
            QShortcut(QKeySequence("Ctrl+L"), self, activated=parent.show_privacy)
        self.load()

    def showEvent(self, event):
        super().showEvent(event)
        apply_window_chrome(self, True)

    def reopen(self, items, position):
        self.items, self.position = items, position
        self._closed = False
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowFullScreen)
        self.pages.setCurrentWidget(self.message)
        self.message.setText("正在读取…")
        self.show()
        self.load()

    def dispose(self):
        self.retain_video_engine = False
        self.close()
        if hasattr(self.video, "shutdown"):
            self.video.shutdown()

    def navigation_button(self, icon, name, direction):
        button = QToolButton(self.view.viewport())
        button.setObjectName("viewerArrow")
        arrow_icon = QIcon()
        arrow_icon.addPixmap(tinted_pixmap(icon, "#ffffff", 24), QIcon.Mode.Normal)
        arrow_icon.addPixmap(tinted_pixmap(icon, "#2b3242", 24), QIcon.Mode.Disabled)
        button.setIcon(arrow_icon)
        button.setIconSize(QSize(24, 24))
        button.setFixedSize(44, 58)
        button.setAccessibleName(name)
        button.setToolTip(f"{name} · {'←' if direction < 0 else '→'}")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.setStyleSheet("""
            QToolButton#viewerArrow {
                background: rgba(18, 22, 31, 170);
                border: 1px solid rgba(255, 255, 255, 28);
                border-radius: 22px;
            }
            QToolButton#viewerArrow:hover {
                background: rgba(37, 99, 235, 225);
                border-color: rgba(147, 197, 253, 180);
            }
            QToolButton#viewerArrow:pressed {
                background: #1d4ed8;
            }
            QToolButton#viewerArrow:focus {
                border: 2px solid #60a5fa;
            }
            QToolButton#viewerArrow:disabled {
                background: transparent;
                border-color: transparent;
            }
        """)
        button.clicked.connect(self.previous_item if direction < 0 else self.next_item,
                               Qt.ConnectionType.QueuedConnection)
        return button

    def position_photo_arrows(self):
        viewport = self.view.viewport()
        y = max(0, (viewport.height() - self.photo_previous.height()) // 2)
        self.photo_previous.move(16, y)
        self.photo_following.move(max(16, viewport.width() - self.photo_following.width() - 16), y)
        self.photo_previous.raise_()
        self.photo_following.raise_()

    def eventFilter(self, watched, event):
        if watched is self.view.viewport() and event.type() == QEvent.Type.Resize:
            self.position_photo_arrows()
        return super().eventFilter(watched, event)

    @Slot()
    def previous_item(self):
        self.navigate(-1)

    @Slot()
    def next_item(self):
        self.navigate(1)

    def navigate(self, direction):
        position = self.position + direction
        if 0 <= position < len(self.items):
            self.position = position
            self.load()

    def load(self):
        if self._closed:
            return
        self.token += 1
        self.video.release()
        self.decoder.cancel_owner(id(self))
        self.jobs.clear()
        self._preview_timer.stop()
        self._is_full = self._full_requested = False
        self._preview_edge = 0
        item = self.items[self.position]
        for button in self.photo_tools:
            button.setVisible(item.kind == "image")
        self.title.setText(item.path.name)
        self.title.setToolTip(str(item.path))
        self.info.setText(f"{self.position + 1} / {len(self.items)}  ·  {item.date_label}")
        self.previous.setEnabled(self.position > 0)
        self.following.setEnabled(self.position < len(self.items) - 1)
        self.photo_previous.setEnabled(self.position > 0)
        self.photo_following.setEnabled(self.position < len(self.items) - 1)
        self.view.scene().clear()
        self.view.scene().setSceneRect(0, 0, 0, 0)
        self.view.fit_mode = True
        self.pages.setCurrentWidget(self.message)
        if item.kind == "video":
            self.pages.setCurrentWidget(self.video)
            self.video.load(item.path)
            return
        self.message.setText("正在读取照片…")
        self.submit_decode(self.preview_edge())

    def preview_edge(self):
        return max(2048, int(max(self.view.viewport().width(), self.view.viewport().height())
                             * self.view.devicePixelRatioF()))

    def submit_decode(self, edge):
        if edge is not None:
            self._preview_edge = edge
        self.jobs[self.token] = self.decoder.request(self, self.items[self.position], self.token, edge)

    def request_original(self):
        if (not self._closed and self.items[self.position].kind == "image"
                and not self._is_full and not self._full_requested):
            self._full_requested = True
            self.submit_decode(None)

    def resize_preview(self):
        if (not self._closed and self.pages.currentWidget() is self.view and self.view.fit_mode
                and not self._is_full and not self._full_requested and self.preview_edge() > self._preview_edge):
            self.submit_decode(self.preview_edge())

    def loaded(self, token, image, error):
        self.jobs.pop(token, None)
        if token != self.token or self._closed:
            return
        if error or image.isNull():
            self.message.setText("无法读取此照片\n\n文件可能损坏、解码器不可用，或移动硬盘已断开。\n\n" + error)
            self.pages.setCurrentWidget(self.message)
            self._full_requested = False
            return
        original_width = int(image.text("chronoview.original_width") or image.width())
        original_height = int(image.text("chronoview.original_height") or image.height())
        self._is_full = image.width() >= original_width and image.height() >= original_height
        had_image = bool(self.view.scene().items())
        transform = self.view.transform()
        center = self.view.mapToScene(self.view.viewport().rect().center())
        pixmap = QPixmap.fromImage(image)
        self.view.scene().clear()
        item = self.view.scene().addPixmap(pixmap)
        item.setTransform(QTransform.fromScale(original_width / pixmap.width(), original_height / pixmap.height()))
        self.view.scene().setSceneRect(0, 0, original_width, original_height)
        self.pages.setCurrentWidget(self.view)
        if self.view.fit_mode:
            self.view.fit()
            self._preview_timer.start(150)
        else:
            self.view.setTransform(transform)
            self.view.centerOn(center if had_image else self.view.sceneRect().center())

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showMaximized() if getattr(self, "was_maximized", False) else self.showNormal()
        else:
            self.was_maximized = self.isMaximized()
            self.showFullScreen()

    def toggle_playback(self):
        if self.pages.currentWidget() == self.video:
            self.video.toggle()

    def escape(self):
        self.toggle_fullscreen() if self.isFullScreen() else self.close()

    def closeEvent(self, event):
        self._closed = True
        self.token += 1
        self._preview_timer.stop()
        self.decoder.cancel_owner(id(self))
        self.jobs.clear()
        self.view.scene().clear()
        self.video.release()
        if hasattr(self.video, "shutdown") and not getattr(self, "retain_video_engine", False):
            self.video.shutdown()
        self.items = []
        self.title.clear()
        self.title.setToolTip("")
        self.info.clear()
        if getattr(self, "retain_video_engine", False):
            # QDialog's normal close destroys/recreates native child HWNDs.
            # Hide exits its modal loop while preserving libmpv's bound surface.
            event.ignore()
            self.hide()
            return
        super().closeEvent(event)

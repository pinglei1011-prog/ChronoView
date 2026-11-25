from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRunnable, QSize, QThreadPool, Qt, Signal, Slot
from PySide6.QtGui import QIcon, QImage, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (QDialog, QFrame, QGraphicsScene, QGraphicsView, QHBoxLayout,
                               QLabel, QPushButton, QStackedWidget, QToolButton, QVBoxLayout)

from app.core.library import MediaItem
from app.services.images import image_error_message, read_image
from app.ui.theme import apply_window_chrome, asset_path, tinted_icon, tinted_pixmap, viewer_stylesheet
from app.ui.video_player import VideoPlayer


class ImageSignals(QObject):
    done = Signal(int, QImage, str)


class ImageTask(QRunnable):
    def __init__(self, item, token):
        super().__init__()
        self.item, self.token = item, token
        self.signals = ImageSignals()

    def run(self):
        try:
            image = read_image(self.item.path)
            self.signals.done.emit(self.token, image, "")
        except Exception as exc:
            self.signals.done.emit(self.token, QImage(), image_error_message(exc))


class ZoomView(QGraphicsView):
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

    def zoom(self, factor):
        self.fit_mode = False
        next_scale = self.transform().m11() * factor
        if 0.01 <= next_scale <= 30:
            self.scale(factor, factor)

    def wheelEvent(self, event):
        self.zoom(1.2 if event.angleDelta().y() > 0 else 1 / 1.2)
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fit_mode:
            self.fit()


class PhotoViewer(QDialog):
    def __init__(self, items: list[MediaItem], position: int, parent=None):
        super().__init__(parent)
        self.items, self.position = list(items), position
        self.token = 0
        self.jobs = {}
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
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
        self.video = VideoPlayer()
        self.video.fullscreen_requested.connect(self.toggle_fullscreen)
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
        self.token += 1
        self.video.release()
        self.pool.clear()
        # Retain only running tasks. Cleared queued tasks never emit a signal.
        self.jobs = {key: task for key, task in self.jobs.items() if key >= self.token - 2}
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
        self.pages.setCurrentWidget(self.message)
        if item.kind == "video":
            self.pages.setCurrentWidget(self.video)
            self.video.load(item.path)
            return
        self.message.setText("正在读取照片…")
        task = ImageTask(item, self.token)
        task.signals.done.connect(self.loaded, Qt.ConnectionType.QueuedConnection)
        self.jobs[self.token] = task
        self.pool.start(task)

    def loaded(self, token, image, error):
        self.jobs.pop(token, None)
        if token != self.token:
            return
        if error or image.isNull():
            self.message.setText("无法读取此照片\n\n文件可能损坏、解码器不可用，或移动硬盘已断开。\n\n" + error)
            return
        pixmap = QPixmap.fromImage(image)
        self.view.scene().addPixmap(pixmap)
        self.view.scene().setSceneRect(pixmap.rect())
        self.pages.setCurrentWidget(self.view)
        self.view.fit()

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
        self.token += 1
        self.video.release()
        self.pool.clear()
        self.pool.waitForDone()
        super().closeEvent(event)

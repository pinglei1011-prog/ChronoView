from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Qt
from PySide6.QtGui import QImage, QPixmap, QKeySequence, QShortcut
from PySide6.QtWidgets import (QDialog, QGraphicsScene, QGraphicsView, QHBoxLayout,
                               QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from app.core.library import MediaItem
from app.services.images import read_image


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
            self.signals.done.emit(self.token, QImage(), str(exc))


class ZoomView(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setStyleSheet("border: none; background: #10141b;")
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
        self.setWindowTitle("ChronoView · 查看")
        self.resize(1080, 760)
        self.setMinimumSize(640, 420)
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setWordWrap(True)
        bar.addWidget(self.title, 1)
        self.previous = QPushButton("← 上一项")
        self.following = QPushButton("下一项 →")
        self.previous.clicked.connect(lambda: self.navigate(-1))
        self.following.clicked.connect(lambda: self.navigate(1))
        bar.addWidget(self.previous)
        bar.addWidget(self.following)
        layout.addLayout(bar)
        self.pages = QStackedWidget()
        self.view = ZoomView()
        self.message = QLabel()
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        self.message.setMargin(35)
        self.pages.addWidget(self.view)
        self.pages.addWidget(self.message)
        layout.addWidget(self.pages, 1)
        tools = QHBoxLayout()
        self.info = QLabel()
        tools.addWidget(self.info, 1)
        for text, callback in [("−", lambda: self.view.zoom(1 / 1.25)),
                               ("+", lambda: self.view.zoom(1.25)),
                               ("适应窗口", self.view.fit), ("原始尺寸", self.view.actual),
                               ("全屏 · F11", self.toggle_fullscreen), ("关闭", self.close)]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            tools.addWidget(button)
        layout.addLayout(tools)
        for key, callback in [("Left", lambda: self.navigate(-1)),
                              ("Right", lambda: self.navigate(1)),
                              ("F11", self.toggle_fullscreen),
                              ("Escape", self.escape)]:
            QShortcut(QKeySequence(key), self, activated=callback)
        self.load()

    def navigate(self, direction):
        position = self.position + direction
        if 0 <= position < len(self.items):
            self.position = position
            self.load()

    def load(self):
        self.token += 1
        self.pool.clear()
        # Retain only running tasks. Cleared queued tasks never emit a signal.
        self.jobs = {key: task for key, task in self.jobs.items() if key >= self.token - 2}
        item = self.items[self.position]
        self.title.setText(item.path.name)
        self.title.setToolTip(str(item.path))
        self.info.setText(f"{self.position + 1} / {len(self.items)}  ·  {item.date_label}")
        self.previous.setEnabled(self.position > 0)
        self.following.setEnabled(self.position < len(self.items) - 1)
        self.view.scene().clear()
        self.pages.setCurrentWidget(self.message)
        if item.kind == "video":
            self.message.setText("视频已纳入时间排序和年月分类\n\n"
                                 "第一阶段暂未加入视频播放和视频封面。\n"
                                 "它们将在第二阶段实现。\n\n" + str(item.path))
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
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def escape(self):
        self.showNormal() if self.isFullScreen() else self.close()

    def closeEvent(self, event):
        self.token += 1
        self.pool.clear()
        self.pool.waitForDone()
        super().closeEvent(event)

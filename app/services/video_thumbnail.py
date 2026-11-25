"""Asynchronous video decoding using the same LGPL Qt backend as playback."""
from PySide6.QtCore import QMetaObject, QObject, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink, QVideoFrame


def format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes}:{secs:02}"


class VideoThumbnailJob(QObject):
    finished = Signal(QImage, str, float)

    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.item = item
        self.completed = False
        self.frame = QImage()
        self.player = QMediaPlayer(self)
        self.sink = QVideoSink(self)
        self.player.setVideoSink(self.sink)
        # No QAudioOutput: thumbnail generation must never make sound.
        self.sink.videoFrameChanged.connect(self.on_frame, Qt.ConnectionType.QueuedConnection)
        self.player.errorOccurred.connect(self.on_error)
        self.player.mediaStatusChanged.connect(self.on_status)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(lambda: self.finish(QImage(), "视频封面读取超时，请重试或检查硬盘连接。"))
        self.release_timer = QTimer(self)
        self.release_timer.setInterval(20)
        self.release_timer.timeout.connect(self._release_when_stopped)
        self.disposing = False
        self.stop_requested = False

    def start(self):
        self.timer.start(12000)
        self.player.setSource(QUrl.fromLocalFile(str(self.item.path)))
        self.player.play()

    def on_status(self, status):
        if not self.completed and status == QMediaPlayer.MediaStatus.LoadedMedia and self.player.isSeekable():
            self.player.setPosition(min(1000, self.player.duration() // 10))

    @Slot(QVideoFrame)
    def on_frame(self, frame):
        if self.completed or not frame.isValid() or not self.frame.isNull():
            return
        image = frame.toImage()
        if image.isNull():
            return
        self.frame = image.scaled(512, 512, Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
        # Stop outside the video callback to avoid reentrant decoder teardown.
        QTimer.singleShot(0, lambda: self.finish(self.frame, ""))

    def on_error(self, error, message):
        if error != QMediaPlayer.Error.NoError:
            self.finish(QImage(), "无法读取视频封面，文件可能损坏、编码不受支持或硬盘已断开。 " + message)

    def finish(self, image, error):
        if self.completed:
            return
        self.completed = True
        duration = self.player.duration() / 1000
        self.timer.stop()
        self.stop_decoder()
        self.finished.emit(image, error, duration)

    def cancel(self):
        self.completed = True
        self.timer.stop()
        self.stop_decoder()

    def stop_decoder(self):
        # Teardown belongs on the native event queue, outside Python callbacks.
        # Ignore queued LoadedMedia/frame signals once cancellation has begun.
        if not self.stop_requested:
            self.stop_requested = True
            QMetaObject.invokeMethod(self.player, "stop", Qt.ConnectionType.QueuedConnection)

    def dispose(self):
        """Do not delete the owner before its queued native stop has actually run."""
        if self.disposing:
            return
        self.disposing = True
        self.sink.videoFrameChanged.disconnect(self.on_frame)
        self.player.errorOccurred.disconnect(self.on_error)
        self.player.mediaStatusChanged.disconnect(self.on_status)
        self.cancel()
        self.release_timer.start()

    def _release_when_stopped(self):
        if self.player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            return
        self.release_timer.stop()
        self.player.setVideoSink(None)
        self.player.destroyed.connect(self.deleteLater)
        self.player.deleteLater()

import os
import logging
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QMetaObject, QSize, QTimer, QUrl, Qt, SIGNAL, Signal, Slot, qVersion
from PySide6.QtGui import QGuiApplication
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoFrame
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget

from app.services.video_thumbnail import format_duration
from app.ui.theme import tinted_icon, tinted_pixmap


class VideoSurface(QVideoWidget):
    fullscreen_requested = Signal()
    playback_toggle_requested = Signal()
    frame_presented = Signal()

    def __init__(self, parent=None):
        windows = set(QGuiApplication.allWindows())
        super().__init__(parent)
        self._native_window = None
        self._presenting = False
        self._ignore_release = False
        self._pointer_pressed = False
        self._recent_click = QTimer(self)
        self._recent_click.setSingleShot(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Qt 6.10.3's Windows QVideoWidget owns a QVideoWindow whose
        # setVideoFrame() coalesces requestUpdate() calls before a vsync-paced
        # render. With 60fps media this can discard decoded frames even though
        # the sink delivers them on time. Submit each delivered frame once,
        # then suppress only the redundant queued UpdateRequest; Expose/resize
        # still follow Qt's normal rendering. The native renderer retains vsync.
        # This bridge is explicitly scoped to the inspected Qt implementation.
        if (QGuiApplication.platformName() == "windows" and qVersion() == "6.10.3"
                and os.environ.get("CHRONOVIEW_VIDEO_PRESENTATION", "frame") != "qt"):
            candidates = [window for window in QGuiApplication.allWindows()
                          if window not in windows and window.metaObject().className() == "QVideoWindow"]
            if len(candidates) == 1:
                self._native_window = candidates[0]
                self._native_window.installEventFilter(self)
                self._native_window.destroyed.connect(self._window_destroyed)
                self.videoSink().videoFrameChanged.connect(self._present_frame)

    @property
    def frame_driven(self):
        return self._native_window is not None

    @Slot()
    def _window_destroyed(self):
        self._native_window = None

    def eventFilter(self, watched, event):
        if (watched is self._native_window and event.type() == QEvent.Type.UpdateRequest
                and not self._presenting):
            return True
        return super().eventFilter(watched, event)

    @Slot(QVideoFrame)
    def _present_frame(self, frame):
        window = self._native_window
        if window is None or not window.isExposed() or self._presenting:
            return
        self._presenting = True
        try:
            # Also present an invalid frame: clearing/releasing media must not
            # leave an old video image visible. Qt connected setVideoFrame first.
            QCoreApplication.sendEvent(window, QEvent(QEvent.Type.UpdateRequest))
        finally:
            self._presenting = False
        self.frame_presented.emit()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # The first release already toggled playback immediately. Restore
            # it for a double-click, then ignore that gesture's final release.
            if self._recent_click.isActive():
                self.playback_toggle_requested.emit()
            self._recent_click.stop()
            self._ignore_release = True
            self._pointer_pressed = False
            self.fullscreen_requested.emit()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # A fullscreen window transition may lose the double-click's final
            # release. A fresh ordinary press starts a new gesture regardless.
            self._ignore_release = False
            self._pointer_pressed = True
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._ignore_release:
                self._ignore_release = False
            elif self._pointer_pressed:
                self.playback_toggle_requested.emit()
                self._recent_click.start(QGuiApplication.styleHints().mouseDoubleClickInterval())
            # A dialog can open between the album's double-click press and
            # release. Only toggle for a complete click begun on this surface.
            self._pointer_pressed = False
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def reset_click_state(self):
        self._recent_click.stop()
        self._ignore_release = False
        self._pointer_pressed = False


class QtVideoPlayer(QWidget):
    fullscreen_requested = Signal()
    surface_type = VideoSurface
    audio_type = QAudioOutput
    backend_name = "qt"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("videoPlayer")
        self.player = None
        self.generation = 0
        self.failed = False
        self.audio = self.audio_type(self)
        self.audio.setVolume(.6)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        self.status = QLabel()
        self.status.setObjectName("videoStatus")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.hide()
        layout.addWidget(self.status)

        self.surface = self.surface_type()
        self.surface.setStyleSheet("background: #0b0d11;")
        self.surface.fullscreen_requested.connect(self.fullscreen_requested)
        self.surface.playback_toggle_requested.connect(self.toggle)
        layout.addWidget(self.surface, 1)

        control_bar = QFrame()
        control_bar.setObjectName("videoControlBar")
        control_bar.setFixedHeight(50)
        controls = QHBoxLayout(control_bar)
        controls.setContentsMargins(10, 0, 14, 0)
        controls.setSpacing(12)

        self.play_button = QPushButton("播放")
        self.play_button.setObjectName("videoPlayButton")
        self.play_button.setIcon(tinted_icon("play.svg", "#ffffff", 13))
        self.play_button.setIconSize(QSize(13, 13))
        self.play_button.setFixedHeight(32)
        self.play_button.setMinimumWidth(78)
        self.play_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_button.clicked.connect(self.toggle)
        controls.addWidget(self.play_button)

        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setObjectName("videoScrub")
        self.position_slider.setRange(0, 0)
        self.position_slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.position_slider.sliderReleased.connect(self.seek_from_slider)
        controls.addWidget(self.position_slider, 1)

        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setObjectName("videoTime")
        controls.addWidget(self.time_label)

        volume_icon = QLabel()
        volume_icon.setPixmap(tinted_pixmap("volume.svg", "#98a2b3", 16))
        volume_icon.setToolTip("音量")
        controls.addWidget(volume_icon)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setObjectName("videoVolume")
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(60)
        self.volume_slider.setFixedWidth(88)
        self.volume_slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.volume_slider.valueChanged.connect(lambda value: self.audio.setVolume(value / 100))
        controls.addWidget(self.volume_slider)

        layout.addWidget(control_bar)

        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(lambda: self.fail("打开视频超时，请检查硬盘连接后重试。"))

    def _set_status(self, message: str):
        self.status.setText(message)
        self.status.setVisible(bool(message))

    def has_video_frame(self):
        return self.surface.videoSink().videoFrame().isValid()

    def load(self, path: Path, autoplay=True):
        logging.info("Opening video: %s (GPU texture conversion disabled=%s)",
                     path, os.environ.get("QT_DISABLE_HW_TEXTURES_CONVERSION", "unset"))
        self.release()
        self.failed = False
        self.generation += 1
        generation = self.generation
        self._set_status("正在打开视频…")
        self.position_slider.setRange(0, 0)
        self.position_slider.setEnabled(False)
        self.time_label.setText("0:00 / 0:00")
        self.play_button.setEnabled(False)
        self.play_button.setText("播放")
        self.play_button.setIcon(tinted_icon("play.svg", "#ffffff", 13))
        try:
            available = path.is_file()
        except OSError:
            available = False
        if not available:
            self.fail("视频不可访问，请检查移动硬盘连接，或重新定位照片库。")
            return
        player = QMediaPlayer(self)
        self.player = player
        player.setAudioOutput(self.audio)
        player.setVideoOutput(self.surface)
        player.durationChanged.connect(self.duration_changed)
        player.positionChanged.connect(self.position_changed)
        player.seekableChanged.connect(self.position_slider.setEnabled)
        player.playbackStateChanged.connect(self.state_changed)
        player.errorOccurred.connect(lambda error, text: self.fail(
            "无法播放视频。文件可能损坏、编码不受支持，或硬盘已断开。\n" + text)
            if generation == self.generation and error != QMediaPlayer.Error.NoError else None)
        player.mediaStatusChanged.connect(self.media_status)
        player.setSource(QUrl.fromLocalFile(str(path)))
        self.timeout.start(15000)
        if autoplay:
            player.play()

    def media_status(self, status):
        if not self.player:
            return
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            self.play_button.setEnabled(True)
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.timeout.stop()
            self._set_status("播放结束 · 点击播放可重新播放")

    def duration_changed(self, duration):
        self.position_slider.setRange(0, duration)
        self.position_slider.setEnabled(bool(self.player and self.player.isSeekable()))
        self.position_changed(self.player.position() if self.player else 0)

    def position_changed(self, position):
        if position > 0 and not self.failed:
            self.timeout.stop()
            self._set_status("")
            self.play_button.setEnabled(True)
        if not self.position_slider.isSliderDown():
            self.position_slider.setValue(position)
        duration = self.player.duration() if self.player else 0
        self.time_label.setText(f"{format_duration(position / 1000)} / {format_duration(duration / 1000)}")

    def state_changed(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_button.setText("暂停" if playing else "播放")
        self.play_button.setIcon(tinted_icon("pause.svg" if playing else "play.svg", "#ffffff", 13))

    def toggle(self):
        if not self.player:
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            if self.player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia:
                self.player.setPosition(0)
            self.player.play()

    def seek_from_slider(self):
        if self.player and self.player.isSeekable():
            self.player.setPosition(self.position_slider.value())

    def fail(self, message):
        self.failed = True
        self.timeout.stop()
        if self.player:
            QMetaObject.invokeMethod(self.player, "stop", Qt.ConnectionType.QueuedConnection)
        self._set_status(message)
        self.play_button.setEnabled(False)
        self.position_slider.setEnabled(False)

    def release(self):
        self.generation += 1
        self.surface.reset_click_state()
        self.timeout.stop()
        player, self.player = self.player, None
        if player:
            # FFmpeg's audio renderer disconnects these on its worker thread.
            # A PySide QAudioOutput disconnectNotify then needs the GIL while
            # the GUI may hold it waiting for that worker during deletion.
            # Disconnect on the GUI thread first; a new player reconnects them.
            for name, signature in (("deviceChanged", "deviceChanged()"),
                                    ("volumeChanged", "volumeChanged(float)"),
                                    ("mutedChanged", "mutedChanged(bool)")):
                if self.audio.receivers(SIGNAL(signature)):
                    getattr(self.audio, name).disconnect()
            # Disconnect first: late signals from a previous file must not affect the next.
            for signal in (player.durationChanged, player.positionChanged, player.seekableChanged,
                           player.playbackStateChanged, player.errorOccurred, player.mediaStatusChanged):
                signal.disconnect()
            # Native queued stop runs outside a Python callback/GIL. On Windows,
            # synchronous stop during a seek/resume can otherwise deadlock audio teardown.
            QMetaObject.invokeMethod(player, "stop", Qt.ConnectionType.QueuedConnection)
            player.deleteLater()
        self.surface.update()


def VideoPlayer(parent=None):
    if os.environ.get("CHRONOVIEW_VIDEO_BACKEND", "mpv") == "mpv":
        from app.ui.mpv_player import MpvVideoPlayer
        return MpvVideoPlayer(parent)
    return QtVideoPlayer(parent)

"""Windows native libmpv playback using the existing ChronoView controls."""
import logging
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QWidget

from app.services.mpv_client import MpvClient, MpvError
from app.ui.video_player import QtVideoPlayer


class MpvAudio(QObject):
    volumeChanged = Signal(float)
    mutedChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._volume, self._muted = .6, False

    def setVolume(self, value):
        self._volume = max(0, min(1, value))
        self.volumeChanged.emit(self._volume)

    def volume(self):
        return self._volume

    def setMuted(self, value):
        self._muted = bool(value)
        self.mutedChanged.emit(self._muted)

    def isMuted(self):
        return self._muted


class MpvSurface(QWidget):
    fullscreen_requested = Signal()
    playback_toggle_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pressed = False
        self._ignore_release = False
        self._recent_click = QTimer(self)
        self._recent_click.setSingleShot(True)
        self.native_click = QTimer(self)
        self.native_click.setSingleShot(True)
        self._native_double_until = 0

    def native_message(self, action):
        if action == "click":
            if time.monotonic() >= self._native_double_until:
                self.playback_toggle_requested.emit()
                self.native_click.start(QGuiApplication.styleHints().mouseDoubleClickInterval())
        elif action == "double":
            if self.native_click.isActive():
                self.playback_toggle_requested.emit()
            self.native_click.stop()
            self._native_double_until = time.monotonic() + .15
            self.fullscreen_requested.emit()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed, self._ignore_release = True, False
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._pressed and not self._ignore_release:
                self.playback_toggle_requested.emit()
                self._recent_click.start(QGuiApplication.styleHints().mouseDoubleClickInterval())
            self._pressed, self._ignore_release = False, False
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._recent_click.isActive():
                self.playback_toggle_requested.emit()
            self._recent_click.stop()
            self._pressed, self._ignore_release = False, True
            self.fullscreen_requested.emit()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def reset_click_state(self):
        self._pressed, self._ignore_release = False, False
        self._recent_click.stop()
        self.native_click.stop()
        self._native_double_until = 0


class MpvTransport(QObject):
    mediaStatusChanged = Signal(object)
    playbackStateChanged = Signal(object)

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.state = QMediaPlayer.PlaybackState.StoppedState
        self.status = QMediaPlayer.MediaStatus.LoadingMedia

    def playbackState(self):
        return self.state

    def mediaStatus(self):
        return self.status

    def duration(self):
        return round((self.owner.engine.values.get("duration") or 0) * 1000) if self.owner.engine else 0

    def position(self):
        return round((self.owner.engine.values.get("time-pos") or 0) * 1000) if self.owner.engine else 0

    def isSeekable(self):
        return bool(self.owner.engine and self.owner.engine.values.get("seekable"))

    def pause(self):
        if self.owner.player is not self:
            return
        self.owner._want_autoplay = False
        self.owner.engine.set("pause", True)

    def play(self):
        if self.owner.player is not self:
            return
        self.owner._want_autoplay = True
        if self.status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.setPosition(0)
        self.owner.engine.set("pause", False)

    def setPosition(self, position):
        if self.owner.player is self:
            self.owner.engine.command("seek", max(0, position) / 1000, "absolute+exact")

    @Slot()
    def stop(self):
        if self.owner.engine and self.owner.player is self:
            self.owner.engine.command("stop")


class MpvVideoPlayer(QtVideoPlayer):
    surface_type = MpvSurface
    audio_type = MpvAudio
    backend_name = "libmpv"
    navigate_requested = Signal(int)
    escape_requested = Signal()
    privacy_requested = Signal()

    def __init__(self, parent=None):
        self.engine = None
        self._video_ready = False
        self._playback_started = False
        self._current_entry = None
        self._want_autoplay = True
        super().__init__(parent)
        self.audio.volumeChanged.connect(lambda v: self.engine.set("volume", v * 100) if self.engine else None)
        self.audio.mutedChanged.connect(lambda v: self.engine.set("mute", v) if self.engine else None)

    def load(self, path: Path, autoplay=True):
        self.release(stop=False)
        self.failed = False
        self.source = Path(path).resolve()
        self._video_ready = False
        self._playback_started = False
        self._current_entry = None
        self._want_autoplay = bool(autoplay)
        self._set_status("正在打开视频…")
        self.position_slider.setRange(0, 0)
        self.position_slider.setEnabled(False)
        self.time_label.setText("0:00 / 0:00")
        self.play_button.setEnabled(False)
        self.state_changed(QMediaPlayer.PlaybackState.StoppedState)
        try:
            if not self.source.is_file():
                raise MpvError("视频不可访问，请检查移动硬盘连接，或重新定位照片库。")
            if self.engine is None:
                self.engine = MpvClient(int(self.surface.winId()), self)
                self.engine.event.connect(self.on_event)
            # Unchanged observed properties are not emitted again on a new
            # file. Retain format/duration cache; wait for PLAYBACK_RESTART
            # before advertising the new file's rendered video as ready.
            self.engine.poll()
            self.engine.values["time-pos"] = None
            self.engine.values["eof-reached"] = False
            self.player = MpvTransport(self)
            self.engine.set("volume", self.audio.volume() * 100)
            self.engine.set("mute", self.audio.isMuted())
            # Let the GPU prepare the first paused frame before advancing the
            # audio clock. PLAYBACK_RESTART resumes automatically when ready.
            self.engine.command("loadfile", str(self.source), "replace", -1,
                                "pause=yes", token=self.generation)
            self.timeout.start(15000)
            logging.info("Opening libmpv video: %s", self.source)
        except (MpvError, OSError) as exc:
            self.fail(str(exc))

    def has_video_frame(self):
        return self._video_ready

    def toggle(self):
        if not self.player:
            return
        # Property notifications arrive asynchronously. Use the requested
        # state so rapid clicks/double-click restoration cannot toggle a stale
        # reported state twice in the same direction.
        if self._want_autoplay:
            self.player.pause()
        else:
            self.player.play()

    def update_state(self):
        if not self.player or not self.engine:
            return
        state = (QMediaPlayer.PlaybackState.StoppedState if self.engine.values.get("eof-reached") else
                 QMediaPlayer.PlaybackState.PausedState if self.engine.values.get("pause", False)
                 else QMediaPlayer.PlaybackState.PlayingState)
        if self.player.state != state:
            self.player.state = state
            self.player.playbackStateChanged.emit(state)
            self.state_changed(state)

    def on_event(self, kind, data):
        if not self.player or not self.engine:
            return
        if kind == 5 and data["error"] < 0 and data["token"] == self.generation:
            self.fail("无法打开视频：" + self.engine.lib.mpv_error_string(data["error"]).decode())
        elif kind == 6:
            if data["entry"] == self.engine.get_number("playlist/0/id"):
                self._current_entry = data["entry"]
        elif kind == 7 and data.get("reason") == 4 and data.get("entry") == self._current_entry:
            self.fail("无法播放视频。文件可能损坏、编码不受支持，或硬盘已断开。")
        elif kind == 8 and self._current_entry is not None:
            self.player.status = QMediaPlayer.MediaStatus.LoadedMedia
            self.player.mediaStatusChanged.emit(self.player.status)
            self.play_button.setEnabled(True)
            self.duration_changed(self.player.duration())
            self.update_state()
        elif kind == 21 and self._current_entry is not None:
            self._playback_started = True
            self._video_ready = bool(self.engine.values.get("vo-configured") and self.engine.values.get("video-params/w"))
            if self._video_ready:
                self.timeout.stop()
                self._set_status("")
                if self._want_autoplay:
                    self.engine.set("pause", False)
        elif kind == 22:
            name, value = data["name"], data["value"]
            if name in ("pause", "time-pos"):
                self.update_state()
            if name in ("duration", "seekable"):
                self.duration_changed(self.player.duration())
            if name in ("time-pos", "vo-configured", "video-params/w"):
                self._video_ready = bool(self._playback_started and self.engine.values.get("vo-configured") and self.engine.values.get("video-params/w"))
                self.position_changed(self.player.position())
                if self._video_ready:
                    self.timeout.stop()
                    self._set_status("播放结束 · 点击播放可重新播放" if self.engine.values.get("eof-reached") else "")
                    self.play_button.setEnabled(True)
                    if self._want_autoplay and not self.engine.values.get("eof-reached"):
                        self.engine.set("pause", False)
            if name == "eof-reached" and value:
                self._want_autoplay = False
                self.player.status = QMediaPlayer.MediaStatus.EndOfMedia
                self.player.mediaStatusChanged.emit(self.player.status)
                self.media_status(self.player.status)
                self.player.state = QMediaPlayer.PlaybackState.StoppedState
                self.state_changed(self.player.state)
            elif name == "eof-reached" and self.player.status == QMediaPlayer.MediaStatus.EndOfMedia:
                self.player.status = QMediaPlayer.MediaStatus.LoadedMedia
                self.update_state()
        elif kind == 16:
            actions = data.get("args", [])
            if not actions:
                return
            action = actions[0].removeprefix("chronoview-")
            if action in ("click", "double"):
                self.surface.native_message(action)
            elif action == "toggle":
                self.toggle()
            elif action == "previous":
                self.navigate_requested.emit(-1)
            elif action == "next":
                self.navigate_requested.emit(1)
            elif action == "fullscreen":
                self.fullscreen_requested.emit()
            elif action == "escape":
                self.escape_requested.emit()
            elif action == "privacy":
                self.privacy_requested.emit()

    def release(self, stop=True):
        self.generation += 1
        self.timeout.stop()
        self.surface.reset_click_state()
        old, self.player = self.player, None
        self._video_ready = False
        if self.engine and stop:
            self.engine.command("stop")
        if old:
            old.deleteLater()

    def shutdown(self):
        self.release()
        if self.engine:
            engine, self.engine = self.engine, None
            engine.event.disconnect(self.on_event)
            engine.close()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

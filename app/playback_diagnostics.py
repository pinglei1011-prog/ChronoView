"""Explicit, read-only playback probe for the bundled executable."""
import json
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Slot, qVersion
from PySide6.QtMultimedia import QMediaMetaData, QMediaPlayer, QVideoFrame
from PySide6.QtWidgets import QApplication

from app import __version__
from app.ui.video_player import VideoPlayer


class PlaybackMeasurement(QObject):
    def __init__(self, source: Path, report: Path, seconds: float):
        super().__init__()
        self.source, self.report = source, report
        self.finished = False
        self.frames, self.submissions, self.ticks = [], [], []
        self.video_size = None
        self.window = VideoPlayer()
        self.window.setWindowTitle("ChronoView · 静音播放检查")
        self.window.resize(1080, 650)
        self.window.audio.setMuted(True)
        self.window.surface.videoSink().videoFrameChanged.connect(self.frame)
        self.window.surface.frame_presented.connect(self.presented)
        self.timer = QTimer(self)
        self.timer.setInterval(10)
        self.timer.timeout.connect(lambda: self.ticks.append(time.perf_counter()))
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self.complete)
        self.started = time.perf_counter()
        self.window.show()
        self.timer.start()
        self.window.load(source)
        if self.window.player:
            self.window.player.mediaStatusChanged.connect(self.status)
        else:
            QTimer.singleShot(0, self.complete)
        self.deadline.start(int(seconds * 1000))

    @Slot(QVideoFrame)
    def frame(self, frame):
        if frame.isValid():
            self.frames.append(time.perf_counter())
            self.video_size = frame.size()

    @Slot()
    def presented(self):
        if self.window.surface.videoSink().videoFrame().isValid():
            self.submissions.append(time.perf_counter())

    @Slot(QMediaPlayer.MediaStatus)
    def status(self, status):
        if status in (QMediaPlayer.MediaStatus.EndOfMedia, QMediaPlayer.MediaStatus.InvalidMedia):
            QTimer.singleShot(0, self.complete)

    @staticmethod
    def rate(values):
        return (len(values) - 1) / (values[-1] - values[0]) if len(values) > 1 else 0

    @Slot()
    def complete(self):
        if self.finished:
            return
        self.finished = True
        self.timer.stop()
        self.deadline.stop()
        gaps = sorted((b - a) * 1000 for a, b in zip(self.submissions, self.submissions[1:]))
        ui_gaps = [(b - a) * 1000 for a, b in zip(self.ticks, self.ticks[1:])]
        player = self.window.player
        size = self.video_size or self.window.surface.videoSink().videoSize()
        report = {
            "version": __version__, "qt_version": qVersion(), "executable": sys.executable,
            "source": str(self.source), "elapsed_s": time.perf_counter() - self.started,
            "presentation": "frame-driven" if self.window.surface.frame_driven else "qt-default",
            "delivered_frames": len(self.frames), "submitted_frames": len(self.submissions),
            "delivery_fps": self.rate(self.frames), "native_submission_fps": self.rate(self.submissions),
            "submission_gap_p95_ms": gaps[int(len(gaps) * .95)] if gaps else None,
            "ui_gap_max_ms": max(ui_gaps, default=0),
            "width": size.width(), "height": size.height(),
            "duration_ms": player.duration() if player else 0,
            "nominal_fps": player.metaData().value(QMediaMetaData.Key.VideoFrameRate) if player else None,
            "status": self.window.status.text(),
            "success": bool(self.frames) and not self.window.failed,
            "measurement": "native render submissions, not physical display presentation",
        }
        code = 0 if report["success"] else 1
        try:
            self.report.parent.mkdir(parents=True, exist_ok=True)
            self.report.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            code = 1
        self.window.release()
        self.window.close()
        QTimer.singleShot(150, lambda: QApplication.instance().exit(code))

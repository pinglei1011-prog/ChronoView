"""Explicit libmpv probe. Counts reported drops, not physical display frames."""
import json
from pathlib import Path
import sys
import time

from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication
from app.ui.mpv_player import MpvVideoPlayer
from app.services.mpv_client import pending_shutdowns
from app.ui.photo_viewer import has_pending_decodes


class MpvPlaybackMeasurement(QObject):
    def __init__(self, source: Path, report: Path, seconds: float):
        super().__init__()
        self.report, self.source = report, source
        self.started = time.perf_counter()
        self.ticks, self.first_video_s = [], None
        self.finished = False
        self.window = MpvVideoPlayer()
        self.window.setWindowTitle("ChronoView · libmpv 静音播放检查")
        self.window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.window.resize(1080, 650)
        self.window.audio.setMuted(True)
        self.window.show()
        load_started = time.perf_counter()
        self.window.load(source)
        self.load_call_s = time.perf_counter() - load_started
        self.timer = QTimer(self)
        self.timer.setInterval(10)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self.complete)
        self.deadline.start(int(seconds * 1000))

    def tick(self):
        self.ticks.append(time.perf_counter())
        if self.window.has_video_frame() and self.first_video_s is None:
            self.first_video_s = time.perf_counter() - self.started
        player = self.window.player
        if self.window.failed or (player and player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia):
            self.complete()

    def complete(self):
        if self.finished:
            return
        self.finished = True
        self.timer.stop()
        self.deadline.stop()
        engine, player = self.window.engine, self.window.player
        values = dict(engine.values) if engine else {}
        gaps = sorted((b-a)*1000 for a,b in zip(self.ticks,self.ticks[1:]))
        ended = bool(player and player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia)
        result = dict(backend="libmpv", source=str(self.source), executable=sys.executable,
                      elapsed_s=time.perf_counter()-self.started, first_video_s=self.first_video_s,
                      load_call_s=self.load_call_s,
                      success=self.window.has_video_frame() and not self.window.failed,
                      reached_end=ended, status=self.window.status.text(), properties=values,
                      render_drop_frames=engine.get_number("frame-drop-count") if engine else None,
                      decoder_drop_frames=engine.get_number("decoder-frame-drop-count") if engine else None,
                      delayed_frames=engine.get_number("vo-delayed-frame-count") if engine else None,
                      video_sync=engine.get_text("options/video-sync") if engine else None,
                      video_output=engine.get_text("current-vo") if engine else None,
                      scaling_options={name: engine.get_text("options/" + name) for name in
                                       ("scale", "dscale", "dither", "framedrop")} if engine else {},
                      ui_gap_max_ms=max(gaps, default=0),
                      ui_gap_p95_ms=gaps[int(len(gaps)*.95)] if gaps else 0,
                      logs=engine.logs if engine else [],
                      measurement="libmpv-reported frame drops and video configuration; not monitor presentation")
        self.report.parent.mkdir(parents=True, exist_ok=True)
        self.report.write_text(json.dumps(result, indent=2,ensure_ascii=False),encoding="utf-8")
        self.window.shutdown()
        self.window.close()
        self.exit_code = 0 if result["success"] else 1
        self.drain_timer = QTimer(self)
        self.drain_timer.setInterval(20)
        self.drain_timer.timeout.connect(self.exit_when_released)
        self.drain_timer.start()

    def exit_when_released(self):
        if not pending_shutdowns() and not has_pending_decodes():
            self.drain_timer.stop()
            QApplication.instance().exit(self.exit_code)

"""Opt-in packaged media verification. Never runs during normal use."""
import json
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication

from app.core.library import sort_items
from app.services.thumbnail_service import cache_key
from app.ui.photo_viewer import PhotoViewer


class MediaVerification(QObject):
    def __init__(self, window, report: Path):
        super().__init__(window)
        self.window, self.report = window, report
        QApplication.instance().setQuitOnLastWindowClosed(False)
        self.started = time.monotonic()
        self.stage, self.position = "privacy", 0
        self.viewer = None
        self.steps = []
        self.timer = QTimer(self)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def tick(self):
        try:
            if time.monotonic() - self.started > 45:
                raise TimeoutError(f"Media verification timed out in {self.stage}")
            window = self.window
            if self.stage == "privacy":
                assert window.startup_pending and window.scan is None
                assert window.route == ("privacy",)
                assert window.centralWidget() is window.browser
                assert window.pages.currentWidget() == window.safe_page
                assert window.browser.isVisible()
                assert not window.items and not window.grid.media_model.items
                assert window.navigation.topLevelItemCount() == 1
                assert window.navigation.topLevelItem(0).childCount() == 0
                assert window.safe_page.resume.isEnabled()
                self.report.parent.mkdir(parents=True, exist_ok=True)
                window.grab().save(str(self.report.with_name(self.report.stem + "-privacy.png")))
                self.steps.append("startup_main_privacy_before_loading")
                window.safe_page.resume.click()
                self.stage = "scan"
            elif self.stage == "scan":
                if window.scan is not None:
                    return
                self.items = sort_items(window.items, False)
                assert self.items and len(self.items) <= 20, "Use a small diagnostic fixture library"
                self.videos = [i for i, item in enumerate(self.items) if item.kind == "video"]
                assert self.videos and any(x.kind == "image" for x in self.items)
                for item in self.items:
                    window.thumbnails.get(item)
                self.steps.append("recursive_scan_mixed_library")
                self.stage = "covers"
            elif self.stage == "covers":
                for item in self.items:
                    pixmap, error = window.thumbnails.get(item)
                    if error:
                        raise RuntimeError(error)
                    if pixmap is None:
                        return
                    assert not pixmap.isNull()
                    if item.kind == "video":
                        assert window.thumbnails.duration(item) > 0
                self.steps.append("real_covers_and_durations")
                dated = next(item.taken_at for item in self.items if item.taken_at)
                assert window.pages.currentWidget() == window.grid
                assert window.grid.media_model.items == window.visible_items
                assert len(window.grid.media_model.items) == len(self.items)
                self.steps.append("all_media_grid")
                window.select_route(("year", dated.year))
                assert window.pages.currentWidget() == window.albums
                assert ("month", dated.year, dated.month) in [album.route for album in window.albums.album_model.items]
                window.select_route(("month", dated.year, dated.month))
                assert window.pages.currentWidget() == window.grid
                assert window.grid.media_model.items and all(item.taken_at.month == dated.month
                                                            for item in window.grid.media_model.items)
                self.steps.append("year_month_navigation")
                window.select_route(("all",))
                self.report.parent.mkdir(parents=True, exist_ok=True)
                window.grab().save(str(self.report.with_name(self.report.stem + "-grid.png")))
                self.viewer = PhotoViewer(self.items, next(i for i, item in enumerate(self.items)
                                                          if item.kind == "image"), window)
                self.viewer.show()
                self.stage = "photo"
            elif self.stage == "photo":
                if self.viewer.pages.currentWidget() != self.viewer.view:
                    return
                self.viewer.view.actual()
                self.viewer.view.zoom(1.25)
                self.viewer.view.fit()
                self.steps.append("photo_decode_and_zoom")
                self.next_video()
            elif self.stage == "play":
                widget = self.viewer.video
                if "无法" in widget.status.text():
                    raise RuntimeError(widget.status.text())
                player = widget.player
                if player is None or player.position() < 100 or not widget.surface.videoSink().videoFrame().isValid():
                    return
                widget.toggle()
                widget.position_slider.setValue(player.duration() // 2)
                widget.seek_from_slider()
                widget.volume_slider.setValue(30)
                self.stage = "seek"
            elif self.stage == "seek":
                widget = self.viewer.video
                if abs(widget.player.position() - widget.player.duration() // 2) > 400:
                    return
                assert abs(widget.audio.volume() - .3) < .01
                self.viewer.toggle_fullscreen()
                assert self.viewer.isFullScreen()
                self.viewer.escape()
                self.viewer.grab().save(str(self.report.with_name(self.report.stem + f"-video-{self.position}.png")))
                self.steps.append(f"play_pause_seek_volume_fullscreen_video_{self.position}")
                self.position += 1
                if self.position < len(self.videos):
                    self.next_video()
                else:
                    window.active_viewer = self.viewer
                    window.privacy_action.click()
                    window.active_viewer = None
                    assert window.route == ("privacy",)
                    assert window.pages.currentWidget() == window.safe_page
                    assert not window.grid.media_model.items and not window.visible_items
                    assert self.viewer.video.player is None
                    assert not window.counts.isVisible()
                    assert not window.path_label.toolTip()
                    window.grab().save(str(self.report.with_name(self.report.stem + "-in-app-privacy.png")))
                    window.safe_page.resume.click()
                    assert window.route == ("all",)
                    assert len(window.grid.media_model.items) == len(self.items)
                    self.steps.append("in_app_privacy_and_resume")
                    self.finish(True)
        except Exception as exc:
            self.finish(False, str(exc))

    def next_video(self):
        self.viewer.position = self.videos[self.position]
        self.viewer.load()
        self.stage = "play"

    def finish(self, success, error=""):
        self.timer.stop()
        self.report.parent.mkdir(parents=True, exist_ok=True)
        self.report.write_text(json.dumps({"success": success, "steps": self.steps,
            "error": error, "elapsed_seconds": round(time.monotonic() - self.started, 2)}, indent=2), encoding="utf-8")
        if self.viewer:
            self.viewer.close()
        self.window.close()
        QTimer.singleShot(50, lambda: QApplication.instance().exit(0 if success else 1))

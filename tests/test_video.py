import hashlib

import pytest
from PySide6.QtCore import Qt
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest

from app.core.scanner import scan_library
from app.services.thumbnail_service import ThumbnailService, cache_key
from app.services.video_thumbnail import format_duration
from app.ui.photo_viewer import PhotoViewer
from app.ui.video_player import VideoPlayer
from scripts.media_fixtures import make_video
from tests.test_images import wait_until


@pytest.fixture(scope="module")
def videos(tmp_path_factory):
    root = tmp_path_factory.mktemp("真实视频 中文")
    return [make_video(root / "VID20260101103000.mp4"),
            make_video(root / "VID20260201103000.mov", "hevc"),
            make_video(root / "VID20260301103000.mkv")]


@pytest.mark.parametrize("position", [0, 1, 2])
def test_real_video_cover_duration_and_disk_cache(position, videos, tmp_path, qapp, monkeypatch):
    path = videos[position]
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    item = next(x for x in scan_library(path.parent).items if x.path == path)
    service = ThumbnailService(tmp_path / "cache")
    try:
        service.get(item)
        wait_until(qapp, lambda: cache_key(item) in service.memory, timeout=16000)
        pixmap, error = service.get(item)
        assert not error
        assert not pixmap.isNull()
        assert pixmap.width() > pixmap.height()
        assert 2.5 <= service.duration(item) <= 3.5
        assert (service.cache / f"{cache_key(item)}.json").is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before
        service.shutdown()
        service = ThumbnailService(tmp_path / "cache")
        monkeypatch.setattr(service, "_queue_video", lambda *args: pytest.fail("Disk cache should avoid video decode"))
        service.get(item)
        wait_until(qapp, lambda: cache_key(item) in service.memory)
        assert not service.get(item)[1]
        assert service.duration(item) > 2.5
    finally:
        service.shutdown()


@pytest.mark.parametrize("position", [0, 1, 2])
def test_real_play_pause_seek_volume_and_release(position, videos, qapp):
    widget = VideoPlayer()
    widget.show()
    try:
        widget.load(videos[position])
        wait_until(qapp, lambda: widget.surface.videoSink().videoFrame().isValid()
                   and widget.player.duration() > 2000 and widget.player.position() > 0)
        assert widget.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        QTest.mouseClick(widget.surface, Qt.MouseButton.LeftButton)
        assert widget.player.playbackState() == QMediaPlayer.PlaybackState.PausedState
        QTest.mouseClick(widget.surface, Qt.MouseButton.LeftButton)
        assert widget.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        from PySide6.QtTest import QSignalSpy
        fullscreen = QSignalSpy(widget.fullscreen_requested)
        # A native double-click follows a first click/release. It restores that
        # initial toggle and consumes the final release, leaving playback alone.
        QTest.mouseClick(widget.surface, Qt.MouseButton.LeftButton)
        QTest.mouseDClick(widget.surface, Qt.MouseButton.LeftButton)
        QTest.mouseRelease(widget.surface, Qt.MouseButton.LeftButton)
        assert fullscreen.count() == 1
        assert widget.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        QTest.mouseDClick(widget.surface, Qt.MouseButton.LeftButton)
        # The fullscreen transition can swallow the final release; the next
        # ordinary click must still pause rather than being swallowed as well.
        QTest.mouseClick(widget.surface, Qt.MouseButton.LeftButton)
        assert widget.player.playbackState() == QMediaPlayer.PlaybackState.PausedState
        widget.position_slider.setValue(1500)
        widget.seek_from_slider()
        wait_until(qapp, lambda: abs(widget.player.position() - 1500) < 500)
        widget.volume_slider.setValue(23)
        assert widget.audio.volume() == pytest.approx(.23)
        widget.toggle()
        wait_until(qapp, lambda: widget.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
        old_player = widget.player
        destroyed = []
        old_player.destroyed.connect(lambda: destroyed.append(True))
        widget.release()
        assert widget.player is None
        wait_until(qapp, lambda: bool(destroyed))
    finally:
        widget.release()
        widget.close()
        qapp.processEvents()


def test_broken_video_and_missing_file(tmp_path, qapp):
    path = tmp_path / "VID20260101000000.mp4"
    path.write_bytes(b"corrupt")
    item = scan_library(tmp_path).items[0]
    service = ThumbnailService(tmp_path / "cache")
    widget = VideoPlayer()
    try:
        service.get(item)
        wait_until(qapp, lambda: cache_key(item) in service.memory)
        assert service.get(item)[1]
        widget.load(path)
        wait_until(qapp, lambda: "无法播放视频" in widget.status.text())
        widget.load(tmp_path / "missing.mp4")
        assert "不可访问" in widget.status.text()
        assert not widget.play_button.isEnabled()
    finally:
        service.shutdown()
        widget.release()
        widget.close()


def test_photo_video_keyboard_navigation(videos, tmp_path, qapp):
    from PIL import Image
    from app.core.library import sort_items
    image = videos[0].parent / "IMG20260101100000.jpg"
    Image.new("RGB", (160, 80), "red").save(image)
    items = sort_items(scan_library(image.parent).items, False)
    viewer = PhotoViewer(items, 0)
    viewer.show()
    try:
        wait_until(qapp, lambda: viewer.pages.currentWidget() == viewer.view)
        assert not viewer.previous.isEnabled()
        assert not viewer.photo_previous.icon().isNull() and not viewer.photo_following.icon().isNull()
        assert abs(viewer.photo_previous.geometry().center().y() - viewer.view.viewport().rect().center().y()) <= 1
        QTest.mouseClick(viewer.photo_following, Qt.MouseButton.LeftButton)
        wait_until(qapp, lambda: viewer.position == 1)
        assert viewer.position == 1 and viewer.pages.currentWidget() == viewer.video
        wait_until(qapp, lambda: viewer.video.player is not None and viewer.video.player.position() > 0
                   and viewer.video.surface.videoSink().videoFrame().isValid())
        QTest.mouseClick(viewer.previous, Qt.MouseButton.LeftButton)
        wait_until(qapp, lambda: viewer.pages.currentWidget() == viewer.view)
        QTest.keyClick(viewer, Qt.Key.Key_Right)
        assert viewer.pages.currentWidget() == viewer.video
        wait_until(qapp, lambda: viewer.video.player is not None and viewer.video.player.position() > 0)
        QTest.keyClick(viewer, Qt.Key.Key_Left)
        assert viewer.video.player is None
        wait_until(qapp, lambda: viewer.pages.currentWidget() == viewer.view)
        viewer.toggle_fullscreen()
        assert viewer.isFullScreen()
        QTest.qWait(30)
        assert abs(viewer.photo_following.geometry().center().y() - viewer.view.viewport().rect().center().y()) <= 1
        viewer.escape()
        assert not viewer.isFullScreen()
    finally:
        viewer.close()
        qapp.processEvents()


def test_time_labels():
    assert format_duration(65) == "1:05"
    assert format_duration(3661) == "1:01:01"


def test_video_queue_keeps_ui_timer_running_and_can_cancel(videos, tmp_path, qapp):
    import shutil
    from PySide6.QtCore import QTimer
    for i in range(12):
        shutil.copyfile(videos[0], tmp_path / f"VID20260101{i:02d}0000.mp4")
    entries = scan_library(tmp_path).items
    service = ThumbnailService(tmp_path / "cache")
    ticks = []
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(len(service.video_jobs)))
    timer.start()
    try:
        for item in entries:
            service.get(item)
        wait_until(qapp, lambda: len(service.memory) >= 4)
        assert ticks and max(ticks) <= 2
        assert any(n > 0 for n in ticks)
        service.shutdown()
        assert not service.video_jobs and not service.video_queue
    finally:
        timer.stop()
        service.shutdown()


def test_video_cover_recovers_from_stale_index(videos, tmp_path, qapp):
    import shutil
    import os
    path = tmp_path / "VID20261016103000.mp4"
    shutil.copyfile(videos[0], path)
    stale = scan_library(tmp_path).items[0]
    os.utime(path, ns=(stale.mtime_ns + 2_000_000_000, stale.mtime_ns + 2_000_000_000))
    current = scan_library(tmp_path).items[0]
    service = ThumbnailService(tmp_path / "cache")
    try:
        service.get(stale)
        wait_until(qapp, lambda: cache_key(stale) in service.memory)
        pixmap, error = service.get(stale)
        assert not error and not pixmap.isNull()
        assert service.duration(stale) > 2
        assert (service.cache / f"{cache_key(current)}.png").is_file()
        assert (service.cache / f"{cache_key(current)}.json").is_file()
    finally:
        service.shutdown()


def test_cover_work_yields_to_viewer_then_resumes_without_errors(videos, tmp_path, qapp):
    entries = scan_library(videos[0].parent).items
    entries = [item for item in entries if item.kind == "video"]
    service = ThumbnailService(tmp_path / "cache")
    try:
        service.get(entries[0])
        wait_until(qapp, lambda: bool(service.video_jobs))
        service.set_paused(True)
        service.get(entries[1])
        QTest.qWait(80)
        assert not service.video_jobs
        assert cache_key(entries[0]) not in service.memory
        assert cache_key(entries[1]) not in service.pending
        service.set_paused(False)
        for item in entries:
            service.get(item)
        wait_until(qapp, lambda: all(cache_key(item) in service.memory for item in entries),timeout=16000)
        assert all(not service.get(item)[1] for item in entries)
        assert all(service.duration(item) > 2 for item in entries)
    finally:
        service.shutdown()


def test_native_surface_submits_each_frame_without_coalescing_and_can_fallback(qapp, monkeypatch):
    if qapp.platformName() != "windows":
        pytest.skip("Native Windows video presentation")
    from PySide6.QtCore import qVersion
    if qVersion() != "6.10.3":
        pytest.skip("Bridge deliberately scoped to Qt 6.10.3")
    from PySide6.QtGui import QImage, QColor
    from PySide6.QtMultimedia import QVideoFrame
    from PySide6.QtTest import QSignalSpy
    from app.ui.video_player import VideoSurface
    surface = VideoSurface()
    surface.resize(320, 180)
    surface.show()
    try:
        qapp.processEvents()
        assert surface.frame_driven
        spy = QSignalSpy(surface.frame_presented)
        for color in ["red", "green", "blue", "white", "black"]:
            image = QImage(320, 180, QImage.Format.Format_RGBA8888)
            image.fill(QColor(color))
            surface.videoSink().setVideoFrame(QVideoFrame(image))
        # No event-loop gap between submissions: Qt's default scheduling would
        # merge this batch. Every frame must reach the native renderer instead.
        assert spy.count() == 5
        surface.videoSink().setVideoFrame(QVideoFrame())
        assert spy.count() == 6
        surface.resize(480, 270)
        qapp.processEvents()
    finally:
        surface.close()
        surface.deleteLater()
        qapp.processEvents()
    monkeypatch.setenv("CHRONOVIEW_VIDEO_PRESENTATION", "qt")
    fallback = VideoSurface()
    try:
        assert not fallback.frame_driven
    finally:
        fallback.close()
        fallback.deleteLater()
        qapp.processEvents()

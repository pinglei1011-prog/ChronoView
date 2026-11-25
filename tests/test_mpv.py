import ctypes as C
import hashlib
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest, QSignalSpy

from app.core.scanner import scan_library
from app.services.mpv_client import _engines, library_path, shutdown_all
from app.ui.mpv_player import MpvVideoPlayer
from app.ui.photo_viewer import PhotoViewer
from scripts.media_fixtures import make_video
from tests.test_images import wait_until


def test_default_player_selects_mpv_without_environment_override(monkeypatch, qapp):
    from app.ui.video_player import VideoPlayer
    monkeypatch.delenv("CHRONOVIEW_VIDEO_BACKEND", raising=False)
    player = VideoPlayer()
    try:
        assert isinstance(player, MpvVideoPlayer)
    finally:
        player.shutdown()
        player.close()


@pytest.fixture
def native_mpv(qapp):
    if qapp.platformName() != "windows" or not library_path().is_file():
        pytest.skip("Requires native Windows and the pinned libmpv validation runtime")
    yield
    shutdown_all()
    wait_until(qapp, lambda: not _engines)


@pytest.fixture(scope="module")
def clips(tmp_path_factory):
    folder = tmp_path_factory.mktemp("libmpv 中文")
    return [make_video(folder / "VID20260101103000.mp4", seconds=8),
            make_video(folder / "VID20260201103000.mov", "hevc", seconds=8)]


@pytest.mark.parametrize("index", [0, 1])
def test_mpv_autoplay_orphan_release_pause_seek_volume_eof_and_reuse(index, clips, native_mpv, qapp):
    path = clips[index]
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    widget = MpvVideoPlayer()
    widget.resize(900, 600)
    widget.show()
    widget.audio.setMuted(True)
    try:
        widget.load(path)
        wait_until(qapp, lambda: widget.has_video_frame() and widget.player.position() > 100)
        assert not widget.failed, widget.status.text()
        QTest.mouseRelease(widget.surface, Qt.MouseButton.LeftButton)
        assert widget.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        QTest.mouseClick(widget.surface, Qt.MouseButton.LeftButton)
        wait_until(qapp, lambda: widget.player.playbackState() == QMediaPlayer.PlaybackState.PausedState)
        widget.position_slider.setValue(2500)
        widget.seek_from_slider()
        wait_until(qapp, lambda: abs(widget.player.position() - 2500) < 350)
        widget.volume_slider.setValue(23)
        wait_until(qapp, lambda: abs(widget.engine.get_number("volume", 0) - 23) < .1)
        QTest.mouseClick(widget.surface, Qt.MouseButton.LeftButton)
        wait_until(qapp, lambda: widget.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
        engine = widget.engine
        widget.load(clips[1-index])
        wait_until(qapp, lambda: widget.has_video_frame() and widget.player.position() > 100)
        assert widget.engine is engine
        widget.player.setPosition(7600)
        wait_until(qapp, lambda: widget.player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia)
        widget.toggle()
        wait_until(qapp, lambda: widget.player.position() < 1500
                   and widget.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    finally:
        widget.shutdown()
        widget.close()


def test_mpv_real_native_mouse_and_shortcut_messages(clips, native_mpv, qapp):
    widget = MpvVideoPlayer()
    widget.resize(900, 600)
    widget.show()
    widget.audio.setMuted(True)
    user32 = C.WinDLL("user32", use_last_error=True)
    user32.FindWindowExW.argtypes = [C.c_void_p, C.c_void_p, C.c_wchar_p, C.c_wchar_p]
    user32.FindWindowExW.restype = C.c_void_p
    user32.PostMessageW.argtypes = [C.c_void_p, C.c_uint, C.c_size_t, C.c_ssize_t]

    def click(hwnd):
        assert user32.PostMessageW(hwnd, 0x201, 1, 100 | (100 << 16))
        assert user32.PostMessageW(hwnd, 0x202, 0, 100 | (100 << 16))

    try:
        widget.load(clips[0])
        wait_until(qapp, lambda: widget.has_video_frame() and widget.player.position() > 100)
        child = user32.FindWindowExW(int(widget.surface.winId()), None, "mpv", None)
        assert child, "Expected an embedded native mpv child window"
        assert user32.PostMessageW(child, 0x202, 0, 100 | (100 << 16))
        QTest.qWait(200)
        assert widget.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        click(child)
        wait_until(qapp, lambda: widget.player.playbackState() == QMediaPlayer.PlaybackState.PausedState)
        QTest.qWait(500)
        click(child)
        wait_until(qapp, lambda: widget.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
        QTest.qWait(500)
        fullscreen = QSignalSpy(widget.fullscreen_requested)
        click(child)
        QTest.qWait(80)
        click(child)
        wait_until(qapp, lambda: fullscreen.count() == 1)
        QTest.qWait(650)
        assert widget.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        navigation = QSignalSpy(widget.navigate_requested)
        assert user32.PostMessageW(child, 0x100, 0x27, 0x014D0001)
        assert user32.PostMessageW(child, 0x101, 0x27, 0xC14D0001)
        wait_until(qapp, lambda: navigation.count() == 1)
        assert navigation.at(0)[0] == 1
    finally:
        widget.shutdown()
        widget.close()


def test_mpv_missing_corrupt_and_rapid_switch_privacy_release(clips, native_mpv, qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("CHRONOVIEW_VIDEO_BACKEND", "mpv")
    bad = tmp_path / "VID20261101120000.mp4"
    bad.write_bytes(b"corrupt video")
    widget = MpvVideoPlayer()
    widget.show()
    try:
        widget.load(tmp_path / "missing.mp4")
        assert widget.failed and "不可访问" in widget.status.text()
        widget.load(bad)
        wait_until(qapp, lambda: widget.failed)
        assert "无法" in widget.status.text()
        for _ in range(3):
            for path in clips:
                widget.load(path)
                QTest.qWait(30)
        wait_until(qapp, lambda: widget.has_video_frame() and widget.player.position() > 100)
        assert not widget.failed and widget.source == clips[-1]
    finally:
        widget.shutdown()
        widget.close()
    viewer = PhotoViewer(scan_library(clips[0].parent).items, 0)
    viewer.show()
    try:
        wait_until(qapp, lambda: viewer.video.has_video_frame())
        viewer.toggle_fullscreen()
        assert viewer.isFullScreen()
        viewer.escape()
        assert not viewer.isFullScreen()
        viewer.navigate(1)
        wait_until(qapp, lambda: viewer.video.has_video_frame() and viewer.video.player.position() > 100)
    finally:
        viewer.close()
    assert viewer.video.player is None and viewer.video.engine is None


def test_mpv_library_override_is_explicit(monkeypatch, tmp_path):
    replacement = tmp_path / "replacement.dll"
    monkeypatch.setenv("CHRONOVIEW_MPV_LIBRARY", str(replacement))
    assert library_path() == replacement.resolve()


def test_mpv_preroll_respects_pause_and_ignores_a_retired_transport(clips, native_mpv, qapp):
    widget = MpvVideoPlayer()
    widget.resize(900, 600)
    widget.show()
    widget.audio.setMuted(True)
    try:
        widget.load(clips[0])
        wait_until(qapp, lambda: widget.has_video_frame() and widget.player.position() > 100)
        old = widget.player
        widget.load(clips[1], autoplay=False)
        old.stop()
        wait_until(qapp, lambda: widget.has_video_frame())
        assert widget.player.playbackState() == QMediaPlayer.PlaybackState.PausedState
        widget.player.setPosition(2500)
        wait_until(qapp, lambda: abs(widget.player.position() - 2500) < 350)
        QTest.qWait(200)
        assert widget.player.playbackState() == QMediaPlayer.PlaybackState.PausedState
        widget.toggle()
        wait_until(qapp, lambda: widget.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
                   and widget.player.position() > 2600)
    finally:
        widget.shutdown()
        widget.close()


def test_mpv_missing_runtime_is_a_friendly_error(clips, native_mpv, qapp, monkeypatch, tmp_path):
    import app.services.mpv_client as client
    monkeypatch.setattr(client, "_library", None)
    monkeypatch.setenv("CHRONOVIEW_MPV_LIBRARY", str(tmp_path / "missing.dll"))
    widget = MpvVideoPlayer()
    try:
        widget.load(clips[0])
        assert widget.failed and "缺少 libmpv" in widget.status.text()
        assert widget.player is None
    finally:
        widget.shutdown()
        widget.close()

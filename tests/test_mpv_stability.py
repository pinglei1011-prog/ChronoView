import ctypes as C
from threading import Event

import pytest
from PySide6.QtMultimedia import QMediaPlayer

import app.services.mpv_client as client
from app.ui.mpv_player import MpvTransport, MpvVideoPlayer
from tests.test_images import wait_until


class FakeEngine:
    def __init__(self):
        self.values = {"duration": 2, "vo-configured": True, "video-params/w": 320,
                       "pause": True, "eof-reached": False}
        self.calls = []

    def set(self, *args):
        self.calls.append(("set", *args))

    def command(self, *args, **kwargs):
        self.calls.append(("command", *args))

    def get_number(self, *args):
        raise AssertionError("START_FILE must not perform a synchronous property query")


def fake_player(qapp):
    widget = MpvVideoPlayer()
    widget.engine = FakeEngine()
    widget.player = MpvTransport(widget)
    widget.generation = 7
    return widget


def dispose(widget):
    widget.engine = None
    widget.close()


def test_old_eof_and_old_start_cannot_cancel_new_autoplay(qapp):
    widget = fake_player(qapp)
    try:
        widget.on_event(22, {"name": "eof-reached", "value": True})
        assert widget._want_autoplay
        widget.on_event(6, {"entry": 10})
        widget.on_event(8, {})
        widget.on_event(21, {})
        widget.on_event(5, {"token": 6, "error": 0, "entry": 10})
        assert widget._current_entry is None and not widget.has_video_frame()
        widget.on_event(5, {"token": 7, "error": 0, "entry": 11})
        assert widget._current_entry is None
        widget.on_event(6, {"entry": 11})
        widget.on_event(8, {})
        widget.on_event(21, {})
        assert widget._current_entry == 11 and widget.has_video_frame()
        assert widget._want_autoplay and ("set", "pause", False) in widget.engine.calls
    finally:
        dispose(widget)


def test_readiness_before_reply_is_replayed_only_for_matching_target(qapp):
    widget = fake_player(qapp)
    try:
        widget.on_event(6, {"entry": 25})
        widget.on_event(8, {})
        widget.on_event(21, {})
        assert not widget.has_video_frame()
        widget.on_event(5, {"token": 7, "error": 0, "entry": 25})
        assert widget.has_video_frame()
        assert widget.player.mediaStatus() == QMediaPlayer.MediaStatus.LoadedMedia
    finally:
        dispose(widget)


def test_release_mutes_and_late_events_cannot_restart_video(qapp):
    widget = fake_player(qapp)
    try:
        engine = widget.engine
        widget.release()
        before = list(engine.calls)
        assert ("set", "mute", True) in before and ("command", "stop") in before
        for kind, data in [(21, {}), (6, {"entry": 99}),
                           (5, {"token": 7, "error": 0, "entry": 99}),
                           (22, {"name": "eof-reached", "value": False})]:
            widget.on_event(kind, data)
        assert engine.calls == before and widget.player is None and not widget.has_video_frame()
    finally:
        dispose(widget)


def test_failed_next_file_stops_retired_native_video_even_without_facade(qapp):
    widget = fake_player(qapp)
    try:
        engine = widget.engine
        widget.player.deleteLater()
        widget.player = None
        widget.fail("视频不可访问")
        assert widget.failed and not widget._want_autoplay
        assert ("set", "mute", True) in engine.calls and ("command", "stop") in engine.calls
        before = list(engine.calls)
        widget.on_event(21, {})
        widget.toggle()
        assert engine.calls == before
    finally:
        dispose(widget)


def test_load_reply_node_is_copied_and_wrong_types_are_ignored():
    values = (client.Node * 2)()
    values[0].format, values[0].u.int64 = 4, 12345
    values[1].format, values[1].u.int64 = 4, 99
    keys = (C.c_char_p * 2)(b"playlist_entry_id", b"other")
    entries = client.NodeList(2, values, keys)
    node = client.Node()
    node.format, node.u.list = 8, C.pointer(entries)
    copied = client.command_entry(C.byref(node))
    values[0].u.int64 = 777
    assert copied == 12345 and client.command_entry(C.byref(node)) == 777
    values[0].format = 5
    assert client.command_entry(C.byref(node)) is None
    assert client.command_entry(None) is None


def test_native_prefetch_is_included_in_graceful_shutdown(qapp, monkeypatch):
    entered, release = Event(), Event()
    def slow_library():
        entered.set()
        assert release.wait(5)
    monkeypatch.setattr(client, '_prefetch_thread', None)
    monkeypatch.setattr(client, 'load_library', slow_library)
    client.prefetch_library()
    try:
        wait_until(qapp, entered.is_set)
        assert client.pending_shutdowns()
    finally:
        release.set()
        wait_until(qapp, lambda: not client.pending_shutdowns())


@pytest.mark.parametrize("failure", ["observe", "bindings"])
def test_setup_failure_releases_tracked_native_handle_asynchronously(qapp, monkeypatch, failure):
    entered, release = Event(), Event()

    class Library:
        def mpv_create(self): return 123
        def mpv_set_option_string(self, *args): return 0
        def mpv_initialize(self, *args): return 0
        def mpv_observe_property(self, *args): return -3 if failure == "observe" else 0
        def mpv_request_log_messages(self, *args): return 0
        def mpv_command_async(self, *args): return -3 if failure == "bindings" else 0
        def mpv_error_string(self, *args): return b"injected setup failure"
        def mpv_terminate_destroy(self, handle):
            assert handle == 123
            entered.set()
            assert release.wait(5)

    monkeypatch.setattr(client, "load_library", lambda: Library())
    try:
        with pytest.raises(client.MpvError):
            client.MpvClient(0)
        wait_until(qapp, entered.is_set)
        assert client.pending_shutdowns()
        # Constructor error returned to the GUI before native destruction finished.
        release.set()
        wait_until(qapp, lambda: not client.pending_shutdowns())
    finally:
        release.set()
        wait_until(qapp, lambda: not client.pending_shutdowns())

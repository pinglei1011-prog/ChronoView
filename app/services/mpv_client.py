"""Small libmpv C API binding. No Python callbacks run on native media threads.

ABI reference: mpv 0.42.0 include/mpv/client.h (ISC header; LGPL core).
All returned event data is copied before the next mpv_wait_event call.
"""
import ctypes as C
from concurrent.futures import ThreadPoolExecutor
import locale
import logging
import os
from pathlib import Path
import sys
import threading

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication


class MpvError(RuntimeError):
    pass


class Event(C.Structure):
    _fields_ = [("event_id", C.c_int), ("error", C.c_int),
                ("userdata", C.c_uint64), ("data", C.c_void_p)]


class Property(C.Structure):
    _fields_ = [("name", C.c_char_p), ("format", C.c_int), ("data", C.c_void_p)]


class EndFile(C.Structure):
    _fields_ = [("reason", C.c_int), ("error", C.c_int), ("entry", C.c_int64),
                ("insert_id", C.c_int64), ("insert_count", C.c_int)]


class Message(C.Structure):
    _fields_ = [("num_args", C.c_int), ("args", C.POINTER(C.c_char_p))]


class LogMessage(C.Structure):
    _fields_ = [("prefix", C.c_char_p), ("level", C.c_char_p), ("text", C.c_char_p), ("log_level", C.c_int)]


class Node(C.Structure):
    pass


class NodeList(C.Structure):
    pass


class NodeValue(C.Union):
    _fields_ = [("string", C.c_char_p), ("flag", C.c_int), ("int64", C.c_int64),
                ("double", C.c_double), ("list", C.POINTER(NodeList)), ("bytes", C.c_void_p)]


Node._fields_ = [("u", NodeValue), ("format", C.c_int)]
NodeList._fields_ = [("num", C.c_int), ("values", C.POINTER(Node)), ("keys", C.POINTER(C.c_char_p))]


def command_entry(pointer):
    """Copy only the documented loadfile result before mpv reuses event memory."""
    if not pointer:
        return None
    node = C.cast(pointer, C.POINTER(Node)).contents
    if node.format == 8 and node.u.list:
        entries = node.u.list.contents
        if 0 <= entries.num <= 64 and entries.keys and entries.values:
            for i in range(entries.num):
                if entries.keys[i] == b"playlist_entry_id" and entries.values[i].format == 4:
                    return entries.values[i].u.int64
    return None


_library = None
_dll_directory = None
_engines = set()
_shutdown_connected = False
_load_lock = threading.Lock()
_destroy_executor = None
_prefetch_thread = None


def library_path():
    override = os.environ.get("CHRONOVIEW_MPV_LIBRARY")
    if override:
        return Path(override).resolve()
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / "vendor" / "libmpv" / "libmpv-2.dll"


def load_library():
    with _load_lock:
        return _load_library()


def prefetch_library():
    global _prefetch_thread
    if _prefetch_thread is not None:
        return
    def prepare():
        try:
            load_library()
        except (OSError, MpvError, AttributeError) as exc:
            logging.warning("libmpv preload unavailable: %s", exc)
    _prefetch_thread = threading.Thread(target=prepare, name="libmpv-preload", daemon=False)
    _prefetch_thread.start()


def _load_library():
    global _library, _dll_directory
    if _library is not None:
        return _library
    path = library_path()
    if not path.is_file():
        raise MpvError("缺少 libmpv 播放库，请完整解压程序包或重新安装，保留 _internal 文件夹。")
    locale.setlocale(locale.LC_NUMERIC, "C")
    if os.name == "nt":
        _dll_directory = os.add_dll_directory(str(path.parent))
    dll = C.CDLL(str(path))
    specs = {
        "mpv_client_api_version": (C.c_ulong, []),
        "mpv_create": (C.c_void_p, []),
        "mpv_initialize": (C.c_int, [C.c_void_p]),
        "mpv_terminate_destroy": (None, [C.c_void_p]),
        "mpv_set_option_string": (C.c_int, [C.c_void_p, C.c_char_p, C.c_char_p]),
        "mpv_set_property_async": (C.c_int, [C.c_void_p, C.c_uint64, C.c_char_p, C.c_int, C.c_void_p]),
        "mpv_get_property": (C.c_int, [C.c_void_p, C.c_char_p, C.c_int, C.c_void_p]),
        "mpv_get_property_string": (C.c_void_p, [C.c_void_p, C.c_char_p]),
        "mpv_free": (None, [C.c_void_p]),
        "mpv_command_async": (C.c_int, [C.c_void_p, C.c_uint64, C.POINTER(C.c_char_p)]),
        "mpv_observe_property": (C.c_int, [C.c_void_p, C.c_uint64, C.c_char_p, C.c_int]),
        "mpv_wait_event": (C.POINTER(Event), [C.c_void_p, C.c_double]),
        "mpv_error_string": (C.c_char_p, [C.c_int]),
        "mpv_request_log_messages": (C.c_int, [C.c_void_p, C.c_char_p]),
    }
    for name, (result, args) in specs.items():
        fn = getattr(dll, name)
        fn.restype, fn.argtypes = result, args
    if dll.mpv_client_api_version() >> 16 != 2:
        raise MpvError("libmpv API 版本不兼容，需要 API 2。")
    _library = dll
    return dll


def shutdown_all():
    for engine in list(_engines):
        engine.close()


def pending_shutdowns():
    return bool(_engines or (_prefetch_thread is not None and _prefetch_thread.is_alive()))


class MpvClient(QObject):
    event = Signal(int, object)
    disposed = Signal()

    def __init__(self, window_id, parent=None):
        super().__init__(parent)
        global _shutdown_connected
        self.lib = load_library()
        self.handle = self.lib.mpv_create()
        self.closing = False
        self._destroy_future = None
        self._destroy_done = threading.Event()
        self.values = {}
        self.logs = []
        self.active_entry = None
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self.poll)
        if not self.handle:
            raise MpvError("无法创建 libmpv 播放器。")
        # From the first owned native handle onward, failure must follow the
        # same asynchronous cleanup path as a normal close. Registration and
        # binding failures must not leak an untracked initialized player.
        self.disposed.connect(self._finished)
        _engines.add(self)
        if not _shutdown_connected:
            QApplication.instance().aboutToQuit.connect(shutdown_all)
            _shutdown_connected = True
        options = {"profile": os.environ.get("CHRONOVIEW_MPV_PROFILE", "fast"),
                   "config": "no", "load-scripts": "no", "terminal": "no", "osc": "no",
                   "load-stats-overlay": "no", "load-console": "no", "load-select": "no",
                   "load-positioning": "no", "load-commands": "no", "load-context-menu": "no",
                   "load-auto-profiles": "no", "autoload-files": "no", "cover-art-auto": "no",
                   "resume-playback": "no", "ordered-chapters": "no",
                   "input-default-bindings": "no", "input-vo-keyboard": "yes", "input-terminal": "no",
                   "osd-level": "0", "idle": "yes", "keep-open": "yes", "keep-open-pause": "yes",
                   "save-position-on-quit": "no", "audio-file-auto": "no", "sub-auto": "no",
                   "ytdl": "no", "wid": str(window_id), "vo": os.environ.get("CHRONOVIEW_MPV_VO", "gpu-next"), "gpu-api": "d3d11",
                   "gpu-context": "d3d11", "hwdec": "auto-safe", "force-window": "yes"}
        options["video-sync"] = os.environ.get("CHRONOVIEW_MPV_VIDEO_SYNC", "audio")
        try:
            for name, value in options.items():
                if name == "profile" and not value:
                    continue
                result = self.lib.mpv_set_option_string(self.handle, name.encode(), value.encode())
                # Our fixed-source release compiles Lua/JS out. Options for
                # absent built-in scripts need no runtime disabling in that
                # build; all other missing/invalid options remain errors.
                script_option = name in {"osc", "ytdl", "load-scripts", "load-stats-overlay", "load-console",
                                         "load-select", "load-positioning", "load-commands", "load-context-menu",
                                         "load-auto-profiles"}
                if result == -5 and script_option:
                    continue
                self.check(result)
            self.check(self.lib.mpv_initialize(self.handle))
            for name, fmt in {"time-pos": 5, "duration": 5, "pause": 3, "eof-reached": 3,
                              "seekable": 3, "video-params/w": 4, "video-params/h": 4,
                              "estimated-vf-fps": 5, "hwdec-current": 1, "vo-configured": 3}.items():
                self.check(self.lib.mpv_observe_property(self.handle, 0, name.encode(), fmt))
            self.check(self.lib.mpv_request_log_messages(self.handle, b"warn"))
            bindings = "\n".join(f"{key} script-message chronoview-{action}" for key, action in [
                ("MBTN_LEFT", "click"), ("MBTN_LEFT_DBL", "double"), ("SPACE", "toggle"),
                ("LEFT", "previous"), ("RIGHT", "next"), ("F11", "fullscreen"),
                ("ESC", "escape"), ("Ctrl+l", "privacy")])
            self.command("define-section", "chronoview", bindings, "force")
            self.command("enable-section", "chronoview", "allow-hide-cursor")
        except Exception:
            self.close()
            raise
        self.timer.start()

    def check(self, result):
        if result < 0:
            raise MpvError(self.lib.mpv_error_string(result).decode("utf-8", "replace"))
        return result

    def command(self, *args, token=0):
        if self.handle and not self.closing:
            argv = (C.c_char_p * (len(args) + 1))(*(str(a).encode("utf-8") for a in args), None)
            self.check(self.lib.mpv_command_async(self.handle, token, argv))

    def set(self, name, value):
        if not self.handle or self.closing:
            return
        fmt, data = (3, C.c_int(int(value))) if isinstance(value, bool) else (5, C.c_double(value))
        self.check(self.lib.mpv_set_property_async(self.handle, 0, name.encode(), fmt, C.byref(data)))

    def get_number(self, name, default=None):
        if not self.handle or self.closing:
            return default
        value = C.c_double()
        result = self.lib.mpv_get_property(self.handle, name.encode(), 5, C.byref(value))
        return value.value if result >= 0 else default

    def get_text(self, name):
        if not self.handle or self.closing:
            return None
        value = self.lib.mpv_get_property_string(self.handle, name.encode())
        if not value:
            return None
        try:
            return C.string_at(value).decode("utf-8", "replace")
        finally:
            self.lib.mpv_free(value)

    def poll(self):
        if not self.handle or self.closing:
            return
        for _ in range(256):
            e = self.lib.mpv_wait_event(self.handle, 0).contents
            if e.event_id == 0:
                break
            kind, data = e.event_id, {"error": e.error, "token": e.userdata}
            if kind == 5 and e.data and e.error >= 0:
                data["entry"] = command_entry(e.data)
            elif kind == 22 and e.data:
                p = C.cast(e.data, C.POINTER(Property)).contents
                value = None
                if p.data:
                    if p.format == 1:
                        raw = C.cast(p.data, C.POINTER(C.c_char_p)).contents.value
                        value = raw.decode("utf-8", "replace") if raw else None
                    elif p.format in (3, 4, 5):
                        t = {3: C.c_int, 4: C.c_int64, 5: C.c_double}[p.format]
                        value = C.cast(p.data, C.POINTER(t)).contents.value
                name = p.name.decode()
                self.values[name] = value
                data.update(name=name, value=value)
            elif kind == 6 and e.data:
                self.active_entry = C.cast(e.data, C.POINTER(C.c_int64)).contents.value
                data["entry"] = self.active_entry
            elif kind == 7 and e.data:
                end = C.cast(e.data, C.POINTER(EndFile)).contents
                data.update(reason=end.reason, error=end.error, entry=end.entry)
            elif kind == 16 and e.data:
                message = C.cast(e.data, C.POINTER(Message)).contents
                data["args"] = [message.args[i].decode("utf-8", "replace") for i in range(message.num_args)]
            elif kind == 2 and e.data:
                log = C.cast(e.data, C.POINTER(LogMessage)).contents
                self.logs.append((log.text or b"").decode("utf-8", "replace").strip())
                self.logs = self.logs[-30:]
            self.event.emit(kind, data)
            if not self.handle or self.closing:
                break

    def close(self):
        global _destroy_executor
        if self.closing or not self.handle:
            return
        self.closing = True
        self.timer.stop()
        handle, self.handle = self.handle, None
        # mpv destruction can wait for its Win32 window thread. Keep the GUI
        # pumping messages and never execute Python on a media worker callback.
        self.setParent(QApplication.instance())
        def destroy():
            try:
                self.lib.mpv_terminate_destroy(handle)
            finally:
                # Never emit through a QObject from a native cleanup thread:
                # Qt's application may already be exiting in a standalone probe.
                self._destroy_done.set()
        # Bound native teardown concurrency without blocking the GUI. Python
        # joins the executor during normal interpreter shutdown.
        if _destroy_executor is None:
            _destroy_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="libmpv-cleanup")
        self._destroy_future = _destroy_executor.submit(destroy)
        self.cleanup_timer = QTimer(self)
        self.cleanup_timer.setInterval(20)
        self.cleanup_timer.timeout.connect(self._check_destroyed)
        self.cleanup_timer.start()

    def _check_destroyed(self):
        if self._destroy_done.is_set() and self._destroy_future.done():
            self.cleanup_timer.stop()
            self.disposed.emit()

    def _finished(self):
        _engines.discard(self)
        self.deleteLater()

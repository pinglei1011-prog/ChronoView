"""500 mixed switches / 100 native viewer cycles, generated media only.

The script never accepts a user library. Run it in a separate process and
check its normal exit in addition to the JSON resource/SHA report.
"""
import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "windows"
os.environ["CHRONOVIEW_VIDEO_BACKEND"] = "mpv"
from app.playback_config import configure_playback_environment
configure_playback_environment()
from PIL import Image
from PySide6.QtCore import QCoreApplication, QEvent, QStandardPaths, QTimer
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app.core.scanner import scan_library
from app.services.mpv_client import _engines, shutdown_all
from app.ui.photo_viewer import PhotoViewer, cancel_pending_decodes, has_pending_decodes
from scripts.media_fixtures import make_video


class ProcessCounters(C.Structure):
    _fields_ = [("cb", C.c_ulong), ("faults", C.c_ulong)] + [
        (name, C.c_size_t) for name in ("peak_working", "working", "peak_paged", "paged",
                                      "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile", "private")]


def resources():
    C.windll.kernel32.GetCurrentProcess.restype = C.c_void_p
    handle = C.windll.kernel32.GetCurrentProcess()
    C.windll.psapi.GetProcessMemoryInfo.argtypes = [C.c_void_p, C.POINTER(ProcessCounters), C.c_ulong]
    info = ProcessCounters()
    info.cb = C.sizeof(info)
    assert C.windll.psapi.GetProcessMemoryInfo(handle, C.byref(info), C.sizeof(info))
    handles = C.c_ulong()
    C.windll.kernel32.GetProcessHandleCount.argtypes = [C.c_void_p, C.POINTER(C.c_ulong)]
    assert C.windll.kernel32.GetProcessHandleCount(handle, C.byref(handles))
    C.windll.user32.GetGuiResources.argtypes = [C.c_void_p, C.c_ulong]
    return dict(working_bytes=info.working, peak_working_bytes=info.peak_working,
                private_bytes=info.private, handles=handles.value,
                gdi_objects=C.windll.user32.GetGuiResources(handle, 0),
                python_threads=threading.active_count(), live_mpv_engines=len(_engines))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--switches", type=int, default=500)
    parser.add_argument("--cycles", type=int, default=100)
    args = parser.parse_args()
    assert args.switches > 0 and args.cycles > 0
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    fixture = output / "generated-media"
    fixture.mkdir(exist_ok=False)
    names = ["IMG20260101100000.jpg", "VID20260102100000.mp4",
             "IMG20260103100000.png", "VID20260104100000.mov"]
    Image.new("RGB", (1200, 800), "#a8bbcd").save(fixture / names[0])
    Image.new("RGB", (800, 1200), "#cfac90").save(fixture / names[2])
    make_video(fixture / names[1], seconds=2)
    make_video(fixture / names[3], "hevc", seconds=2)
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in fixture.iterdir()}
    by_name = {item.path.name: item for item in scan_library(fixture).items}
    items = [by_name[name] for name in names]
    app = QApplication([])
    app.setOrganizationName("ChronoViewStabilityTest")
    app.setApplicationName("IsolatedPlayerStress")
    app.setQuitOnLastWindowClosed(False)
    QStandardPaths.setTestModeEnabled(True)
    heartbeat = []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: heartbeat.append(time.perf_counter()))
    timer.start()
    samples, video_checks = [], []
    viewer = None

    def wait(condition, seconds=15):
        until = time.monotonic() + seconds
        while not condition():
            if time.monotonic() >= until:
                raise TimeoutError("原生播放压力测试等待超时")
            app.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            QTest.qWait(10)
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def drain():
        wait(lambda: not _engines and not has_pending_decodes())

    def new_viewer(position):
        widget = PhotoViewer(items, 0)
        widget.resize(900, 600)
        widget.video.audio.setMuted(True)
        widget.show()
        widget.position = position
        widget.load()
        return widget

    def ready(widget):
        wait(lambda: widget.video.failed or (widget.video.has_video_frame() and widget.video.player.position() > 30))
        assert not widget.video.failed, widget.video.status.text()

    started = time.monotonic()
    try:
        for position in (1, 3):
            viewer = new_viewer(position)
            ready(viewer)
            video_checks.append(dict(codec="H.264" if position == 1 else "H.265",
                                     hwdec=viewer.video.engine.values.get("hwdec-current")))
            viewer.close()
            viewer.deleteLater()
            viewer = None
            drain()
        samples.append(dict(stage="warmed_baseline", **resources()))
        viewer = new_viewer(0)
        viewer.retain_video_engine = True
        for index in range(args.switches):
            viewer.position = (index + 1) % 4
            viewer.load()
            QTest.qWait(5)
            if index % 50 == 0:
                if items[viewer.position].kind == "video":
                    ready(viewer)
                print(json.dumps(dict(stage="mixed_switch", completed=index + 1)), flush=True)
        viewer.position = 0
        viewer.load()
        wait(lambda: viewer.pages.currentWidget() is viewer.view and not has_pending_decodes())
        viewer.close()
        wait(lambda: not has_pending_decodes())
        samples.append(dict(stage="after_mixed_switches", **resources()))
        for cycle in range(args.cycles):
            # Exercise the same viewer/engine reuse policy as MainWindow.
            viewer.reopen(items, 1 if cycle % 2 == 0 else 3)
            viewer.show()
            ready(viewer)
            if cycle % 10 == 0:
                viewer.toggle_fullscreen()
                QTest.qWait(20)
                viewer.toggle_fullscreen()
                for ms in range(100, 1100, 100):
                    viewer.video.player.setPosition(ms)
                wait(lambda: viewer.video.player.position() >= 900)
            if cycle % 25 == 0:
                viewer.video.player.setPosition(1900)
                wait(lambda: viewer.video.player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia)
                viewer.video.toggle()
                wait(lambda: viewer.video.player.position() < 800 and viewer.video._want_autoplay)
            viewer.close()
            assert viewer.video.player is None and viewer.video.engine is not None
            assert not viewer.items and not viewer.isVisible()
            wait(lambda: not has_pending_decodes())
            assert len(_engines) == 1
            if (cycle + 1) % 10 == 0:
                samples.append(dict(stage="open_close", completed=cycle + 1, **resources()))
                print(json.dumps(samples[-1]), flush=True)
        viewer.dispose()
        viewer.deleteLater()
        viewer = None
        drain()
        samples.append(dict(stage="fully_disposed", **resources()))
        steady = [s['handles'] for s in samples if s.get('stage') == 'open_close' and s.get('completed', 0) >= 50]
        if len(steady) > 1:
            assert max(steady) - min(steady) < 24, 'Native handles kept increasing after warmup'
        assert all(hashlib.sha256(p.read_bytes()).hexdigest() == hashes[p.name] for p in fixture.iterdir())
        assert not _engines and not has_pending_decodes()
        assert not any(t.name == "libmpv-shutdown" for t in threading.enumerate())
        gaps = [(b - a) * 1000 for a, b in zip(heartbeat, heartbeat[1:])]
        result = dict(success=True, mixed_switches=args.switches, viewer_open_close_cycles=args.cycles,
                      viewer_engine_reuse=True,
                      fixture_sha256=hashes, original_sha256_unchanged=True,
                      elapsed_seconds=time.monotonic() - started, video_checks=video_checks,
                      resources=samples, ui_gap_max_ms=max(gaps, default=0),
                      live_engines_at_end=len(_engines), pending_image_decodes_at_end=has_pending_decodes(),
                      vram_measurement="未测量显存；不能以工作集/句柄稳定代替显存证明",
                      limits="本机原生窗口与合成短片；不代表物理断盘、驱动故障或数小时运行验证")
        (output / "summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(dict(success=True, elapsed_seconds=result["elapsed_seconds"])), flush=True)
    finally:
        if viewer is not None:
            viewer.close()
        cancel_pending_decodes()
        shutdown_all()
        drain()
        timer.stop()


if __name__ == "__main__":
    main()

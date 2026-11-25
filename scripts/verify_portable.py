"""Exercise the bundled EXE outside its directory without Python on PATH.

This is a local packaging smoke test, not a substitute for a clean Windows VM.
"""
import os
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QCoreApplication, QSettings, QStandardPaths


root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from app.core.scanner import scan_library
from app.services.thumbnail_service import cache_key
from scripts.media_fixtures import make_video
from app import __version__

parser = argparse.ArgumentParser()
parser.add_argument("--executable", type=Path, default=root / "dist" / f"ChronoView-{__version__}" / "ChronoView.exe")
parser.add_argument("--backend", choices=["mpv", "qt"], default="mpv")
args = parser.parse_args()
exe = args.executable.resolve()
if not exe.is_file():
    raise SystemExit("Build the EXE first.")
cwd = root / "work" / "独立启动目录 with spaces"
cwd.mkdir(parents=True, exist_ok=True)
env = os.environ.copy()
env.pop("PYTHONHOME", None)
env.pop("PYTHONPATH", None)
for name in ["QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH", "QML_IMPORT_PATH"]:
    env.pop(name, None)
env["QT_MEDIA_BACKEND"] = "ffmpeg"
env["CHRONOVIEW_VIDEO_BACKEND"] = args.backend
env["QT_QPA_PLATFORM"] = "windows"
env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
app = QCoreApplication([])
app.setOrganizationName("ChronoView")
app.setApplicationName("ChronoView")
cache = Path(QStandardPaths.writableLocation(QStandardPaths.CacheLocation)) / "thumbnails"
with tempfile.TemporaryDirectory(prefix="packaged-smoke-", dir=cwd) as temp:
    test_dir = Path(temp)
    library = test_dir / "相册 & [素材]" / "错误年份 2025"
    library.mkdir(parents=True)
    Image.new("RGB", (90, 60), "#f39966").save(library / "IMG20261124120000.jpg")
    Image.new("RGB", (60, 90), "#6688ee").save(library / "IMG20260101000000.png")
    make_video(library / "VID20260101003000.mp4")
    make_video(library / "VID20260201003000.mov", "hevc")
    make_video(library / "VID20260301003000.mkv")
    entries = scan_library(library.parent).items
    settings_path = test_dir / "packaged-smoke.ini"
    report_path = root / "work" / f"packaged-{__version__}-media.json"
    result = subprocess.run([str(exe), "--library", str(library.parent), "--settings-file", str(settings_path),
                             "--verify-media", str(report_path)], cwd=cwd, env=env, timeout=60)
    assert result.returncode == 0, f"Packaged app exit code: {result.returncode}"
    import json
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["success"], report
    assert report["video_backend"] == ("libmpv" if args.backend == "mpv" else "qt"), report
    assert "startup_main_privacy_before_loading" in report["steps"], report
    assert all(f"autoplay_ignores_opening_release_video_{i}" in report["steps"] for i in range(3)), report
    settings = QSettings(str(settings_path), QSettings.Format.IniFormat)
    assert settings.value("library") == str(library.parent), "Packaged app did not finish scanning the library"
    for item in entries:
        assert (cache / f"{cache_key(item)}.png").is_file(), "Packaged decoder/cache did not complete"
    # Regression: restore the saved index after source files changed. A stale
    # fingerprint must never turn an otherwise readable file into an error tile.
    for item in entries:
        if item.kind == "image":
            Image.new("RGB", (110, 70), "blue").save(item.path)
        os.utime(item.path, ns=(item.mtime_ns + 2_000_000_000, item.mtime_ns + 2_000_000_000))
    stale_report = root / "work" / f"packaged-{__version__}-stale-index.json"
    result = subprocess.run([str(exe), "--settings-file", str(settings_path),
                             "--verify-media", str(stale_report)], cwd=cwd, env=env, timeout=60)
    assert result.returncode == 0, f"Stale-index regression exit code: {result.returncode}"
    report = json.loads(stale_report.read_text(encoding="utf-8"))
    assert report["success"], report
    assert "startup_main_privacy_before_loading" in report["steps"], report
    assert all(f"autoplay_ignores_opening_release_video_{i}" in report["steps"] for i in range(3)), report
    current_entries = scan_library(library.parent).items
    for item in current_entries:
        assert (cache / f"{cache_key(item)}.png").is_file(), "Changed files must use current cache fingerprints"
print("PASS: Packaged H.264 MP4 / H.265 MOV / H.264 MKV covers, playback, pause, seek, volume, fullscreen; photo decoding and year/month navigation. Unicode cwd, stripped PATH.")
print("PASS: Changed photos/videos remain readable after restoring a stale SQLite index, without manual refresh.")
print("PASS: MP4/MOV/MKV autoplay keeps playing after the opening gesture's stray mouse release.")

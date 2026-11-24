"""Exercise the bundled EXE outside its directory without Python on PATH.

This is a local packaging smoke test, not a substitute for a clean Windows VM.
"""
import os
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

exe = root / "dist" / "ChronoView" / "ChronoView.exe"
if not exe.is_file():
    raise SystemExit("Build the EXE first.")
cwd = root / "work" / "独立启动目录 with spaces"
cwd.mkdir(parents=True, exist_ok=True)
env = os.environ.copy()
env.pop("PYTHONHOME", None)
env.pop("PYTHONPATH", None)
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
    (library / "VID20260101003000.mp4").write_bytes(b"placeholder")
    entries = scan_library(library.parent).items
    settings_path = test_dir / "packaged-smoke.ini"
    result = subprocess.run([str(exe), "--library", str(library.parent), "--settings-file", str(settings_path),
                             "--smoke-test"], cwd=cwd, env=env, timeout=30)
    assert result.returncode == 0, f"Packaged app exit code: {result.returncode}"
    settings = QSettings(str(settings_path), QSettings.Format.IniFormat)
    assert settings.value("library") == str(library.parent), "Packaged app did not finish scanning the library"
    for item in entries:
        if item.kind == "image":
            assert (cache / f"{cache_key(item)}.png").is_file(), "Packaged image decoder/cache did not complete"
print("PASS: EXE launched with stripped PATH from a Unicode/spaced working directory; recursive scan and JPEG/PNG thumbnails verified.")

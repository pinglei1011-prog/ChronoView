"""Read-only real-file playback checks using the bundled EXE, with no Python PATH."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from app import __version__
from app.core.scanner import scan_library

parser = argparse.ArgumentParser()
parser.add_argument("library", type=Path)
parser.add_argument("--seconds", type=float, default=8)
parser.add_argument("--limit", type=int, default=12)
args = parser.parse_args()
if args.seconds <= 0 or args.limit <= 0:
    parser.error("Use positive seconds and file limit")
entries = sorted((item for item in scan_library(args.library).items if item.kind == "video"), key=lambda x: str(x.path))
assert entries, "No videos found"
exe = root / "dist" / f"ChronoView-{__version__}" / "ChronoView.exe"
assert exe.is_file(), "Build the current version first"
work = root / "work" / f"packaged-{__version__}-playback"
work.mkdir(parents=True, exist_ok=True)
cwd = work / "独立启动目录 with spaces"
cwd.mkdir(exist_ok=True)
env = os.environ.copy()
for name in ["PYTHONHOME", "PYTHONPATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH", "QML_IMPORT_PATH"]:
    env.pop(name, None)
env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
env["QT_QPA_PLATFORM"] = "windows"
env["QT_MEDIA_BACKEND"] = "ffmpeg"
results = []
for number, item in enumerate(entries[:args.limit]):
    before = item.path.stat()
    report = work / f"{number:02d}-{item.path.stem}.json"
    result = subprocess.run([str(exe), "--measure-video", str(item.path), "--measurement-report", str(report),
                             "--measurement-seconds", str(args.seconds)], cwd=cwd, env=env,
                            timeout=args.seconds + 20, capture_output=True)
    assert result.returncode == 0, f"Playback exited {result.returncode}: {item.path}"
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["success"] and data["version"] == __version__, data
    assert Path(data["executable"]).resolve() == exe.resolve(), data
    assert data["presentation"] == "frame-driven", data
    assert data["submitted_frames"] == data["delivered_frames"] > 0, data
    after = item.path.stat()
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns), "Source metadata changed"
    results.append(data)
    print(f"PASS {item.path.name}: {data['delivered_frames']} delivered / {data['submitted_frames']} submitted, "
          f"{data['native_submission_fps']:.2f} native submissions/s", flush=True)
(work / "summary.json").write_text(json.dumps({"total_videos": len(entries), "tested": len(results),
    "seconds_limit": args.seconds, "results": results}, indent=2, ensure_ascii=False), encoding="utf-8")

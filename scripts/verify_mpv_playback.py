"""Read-only libmpv full-clip checks; keep native statistics distinct from Qt's."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from app.core.scanner import scan_library

parser = argparse.ArgumentParser()
parser.add_argument("library", type=Path)
parser.add_argument("--executable", type=Path)
parser.add_argument("--rounds", type=int, default=2)
parser.add_argument("--seconds", type=float, default=35)
parser.add_argument("--output", type=Path, default=root / "work/mpv-real-playback")
args = parser.parse_args()
assert args.rounds > 0 and args.seconds > 0
args.output.mkdir(parents=True, exist_ok=True)
entries = sorted((i for i in scan_library(args.library).items if i.kind == "video"), key=lambda i: str(i.path))
assert entries, "No videos found"
command = [str(args.executable.resolve())] if args.executable else [sys.executable, str(root / "main.py")]
env = os.environ.copy()
env["QT_QPA_PLATFORM"] = "windows"
env["CHRONOVIEW_VIDEO_BACKEND"] = "mpv"
env.pop("QT_FFMPEG_DECODING_HW_DEVICE_TYPES", None)
rows = []
for round_number in range(1, args.rounds + 1):
    for i, item in enumerate(entries):
        report = args.output / f"round-{round_number}-{i}.json"
        before = item.path.stat()
        with report.with_suffix('.log').open('wb') as output:
            result = subprocess.run(command + ["--measure-video", str(item.path), "--measurement-report", str(report),
                                               "--measurement-seconds", str(args.seconds)],
                                    env=env, stdout=output, stderr=output, timeout=args.seconds + 20)
        data = json.loads(report.read_text(encoding='utf-8')) if report.exists() else {}
        after = item.path.stat()
        unchanged = (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
        properties = data.get("properties", {})
        estimated_frames = (properties.get("duration") or 0) * (properties.get("estimated-vf-fps") or 0)
        drops = data.get("render_drop_frames")
        performance = drops is not None and estimated_frames > 0 and drops <= estimated_frames * .05
        row = dict(round=round_number, file=item.path.name, exit=result.returncode,
                   success=bool(data.get("success") and data.get("reached_end") and result.returncode == 0 and unchanged),
                   performance_pass=performance, render_drop_frames=drops,
                   decoder_drop_frames=data.get("decoder_drop_frames"), hwdec=properties.get("hwdec-current"),
                   first_video_s=data.get("first_video_s"), ui_gap_max_ms=data.get("ui_gap_max_ms"),
                   original_file_unchanged=unchanged)
        rows.append(row)
        print(json.dumps(row), flush=True)
        summary = dict(stability_pass=all(r["success"] for r in rows),
                       performance_pass=all(r["performance_pass"] for r in rows), results=rows)
        (args.output / "summary.json").write_text(json.dumps(summary, indent=2), encoding='utf-8')
sys.exit(0 if summary["stability_pass"] and summary["performance_pass"] else 1)

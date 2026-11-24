"""Generate small real videos using a development-only FFmpeg executable.

imageio-ffmpeg is not imported by the application or bundled into the release.
"""
import subprocess
from pathlib import Path

import imageio_ffmpeg


def make_video(path: Path, codec="h264", seconds=3):
    path.parent.mkdir(parents=True, exist_ok=True)
    encoder = "libx265" if codec == "hevc" else "libx264"
    args = [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=12",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
            "-t", str(seconds), "-c:v", encoder, "-threads", "2", "-pix_fmt", "yuv420p",
            "-c:a", "aac"]
    if codec == "hevc":
        args += ["-x265-params", "pools=1:frame-threads=1:log-level=error", "-tag:v", "hvc1"]
    subprocess.run(args + [str(path)], check=True, capture_output=True, timeout=30,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return path


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1] / "work" / "视频测试素材"
    for filename, codec in [("VID20260101103000.mp4", "h264"),
                            ("VID20260201103000.mov", "hevc"),
                            ("VID20260301103000.mkv", "h264")]:
        print(make_video(root / filename, codec))

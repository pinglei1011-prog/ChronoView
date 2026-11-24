"""Package the tested one-folder build and its LGPL source companion."""
import hashlib
import json
import sys
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from app import __version__
dist = root / "dist"
runtime = dist / f"ChronoView-{__version__}"
sources = dist / f"ChronoView-{__version__}-third-party-sources"
assert (runtime / "ChronoView.exe").is_file()
assert (runtime / "_internal/PySide6/avcodec-61.dll").is_file()
assert (runtime / "licenses/LGPL-2.1.txt").is_file()
assert (sources / "sources.json").is_file(), "Run prepare_sources.py first"
for entry in json.loads((sources / "sources.json").read_text(encoding="utf-8")):
    assert hashlib.sha256((sources / entry["name"]).read_bytes()).hexdigest() == entry["sha256"]

outputs = []
for directory, filename, compression in [
    (runtime, f"ChronoView-{__version__}-portable-win64.zip", zipfile.ZIP_DEFLATED),
    (sources, f"ChronoView-{__version__}-third-party-sources.zip", zipfile.ZIP_STORED),
]:
    destination = dist / filename
    if directory == runtime or not destination.exists():
        with zipfile.ZipFile(destination, "w", compression=compression) as archive:
            for path in sorted(directory.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(dist))
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert not any("imageio_ffmpeg" in name or name.lower().endswith("ffmpeg.exe") for name in archive.namelist())
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    outputs.append(f"{digest}  {filename}")
    print(f"Verified: {filename} ({destination.stat().st_size / 1024 / 1024:.1f} MiB)", flush=True)
(dist / f"ChronoView-{__version__}-SHA256SUMS.txt").write_text("\n".join(outputs) + "\n", encoding="ascii")

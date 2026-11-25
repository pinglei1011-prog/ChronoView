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
native = json.loads((runtime / "_internal/vendor/libmpv/manifest.json").read_text(encoding="utf-8"))
assert native["distribution_status"] == "release"
assert hashlib.sha256((runtime / "_internal/vendor/libmpv/libmpv-2.dll").read_bytes()).hexdigest() == native["dll_sha256"]
assert (sources / "native/relink/lib").is_dir(), "Native relinking kit missing"
assert (sources / "native/metadata/sources.lock.json").is_file()
native_sources = json.loads((sources / "native/metadata/sources.lock.json").read_text())
for entry in native_sources["sources"]:
    assert hashlib.sha256((sources / "native/sources" / entry["archive"]).read_bytes()).hexdigest() == entry["sha256"]
for entry in json.loads((sources / "native/metadata/linked-archives.json").read_text()):
    assert hashlib.sha256((sources / "native/relink/lib" / entry["name"]).read_bytes()).hexdigest() == entry["sha256"]
assert (sources / "sources.json").is_file(), "Run prepare_sources.py first"
for entry in json.loads((sources / "sources.json").read_text(encoding="utf-8")):
    assert hashlib.sha256((sources / entry["name"]).read_bytes()).hexdigest() == entry["sha256"]

outputs = []
for directory, filename, compression in [
    (runtime, f"ChronoView-{__version__}-portable-win64.zip", zipfile.ZIP_DEFLATED),
    (sources, f"ChronoView-{__version__}-third-party-sources.zip", zipfile.ZIP_DEFLATED),
]:
    destination = dist / filename
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
installer = dist / f"ChronoView-{__version__}-setup-win64.exe"
assert installer.is_file(), "Run build_installer.ps1 first"
outputs.append(f"{hashlib.sha256(installer.read_bytes()).hexdigest()}  {installer.name}")
(dist / f"ChronoView-{__version__}-SHA256SUMS.txt").write_text("\n".join(outputs) + "\n", encoding="ascii")

"""Fetch version-matched upstream source archives for the LGPL companion bundle."""
import concurrent.futures
import hashlib
import json
import shutil
import sys
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from app import __version__
target = root / "dist" / f"ChronoView-{__version__}-third-party-sources"
target.mkdir(parents=True, exist_ok=True)
urls = {"ffmpeg-7.1.3.tar.xz": "https://ffmpeg.org/releases/ffmpeg-7.1.3.tar.xz"}
for module in ["qtbase", "qtmultimedia", "qtimageformats", "qtsvg"]:
    filename = f"{module}-everywhere-src-6.10.3.tar.xz"
    urls[filename] = "https://download.qt.io/archive/qt/6.10/6.10.3/submodules/" + filename
filename = "pyside-setup-everywhere-src-6.10.3.tar.xz"
urls[filename] = "https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.10.3-src/" + filename


def fetch(entry):
    name, url = entry
    destination = target / name
    if not destination.exists():
        temp = destination.with_suffix('.part')
        with urllib.request.urlopen(url, timeout=30) as response, temp.open('wb') as stream:
            shutil.copyfileobj(response, stream)
        assert temp.read_bytes()[:6] == b'\xfd7zXZ\x00', "Source download was not an XZ archive"
        temp.replace(destination)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    print(f"Source ready: {name} ({destination.stat().st_size // 1024} KiB)", flush=True)
    return {"name": name, "url": url, "size": destination.stat().st_size, "sha256": digest}


with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    manifest = list(pool.map(fetch, urls.items()))
(target / "sources.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
shutil.copyfile(root / "assets/licenses/ffmpeg-build.json", target / "ffmpeg-build.json")
shutil.copyfile(root / "assets/licenses/README.md", target / "README.md")
print("Source companion complete.")

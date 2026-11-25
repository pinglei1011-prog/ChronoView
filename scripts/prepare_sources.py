"""Fetch version-matched upstream source archives for the LGPL companion bundle."""
import concurrent.futures
import hashlib
import json
import shutil
import sys
import urllib.request
import zipfile
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
source_lock = {entry["name"]: entry for entry in json.loads((root / "packaging/qt-sources.lock.json").read_text(encoding="utf-8"))}


def fetch(entry):
    name, url = entry
    destination = target / name
    previous = root / "dist/ChronoView-1.0.0-third-party-sources" / name
    if not destination.exists() and previous.exists():
        shutil.copyfile(previous, destination)
    if not destination.exists():
        temp = destination.with_suffix('.part')
        with urllib.request.urlopen(url, timeout=30) as response, temp.open('wb') as stream:
            shutil.copyfileobj(response, stream)
        assert temp.read_bytes()[:6] == b'\xfd7zXZ\x00', "Source download was not an XZ archive"
        temp.replace(destination)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    assert digest == source_lock[name]["sha256"], f"Source checksum mismatch: {name}"
    print(f"Source ready: {name} ({destination.stat().st_size // 1024} KiB)", flush=True)
    return {"name": name, "url": url, "size": destination.stat().st_size, "sha256": digest}


with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    manifest = list(pool.map(fetch, urls.items()))
(target / "sources.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
shutil.copyfile(root / "assets/licenses/ffmpeg-build.json", target / "ffmpeg-build.json")
shutil.copyfile(root / "assets/licenses/README.md", target / "README.md")
native = target / "native"
native.mkdir(exist_ok=True)
kit = root / "work/release-1.1/chronoview-native-player.zip"
if kit.exists():
    with zipfile.ZipFile(kit) as source:
        for name in source.namelist():
            path = Path(name)
            assert not path.is_absolute() and ".." not in path.parts
            # Retain headers used by this minimal player; the toolchain also
            # contains unrelated libraries that are not part of the runtime.
            if name.startswith("relink/include/") and len(path.parts) == 3:
                continue
            if name != "libmpv-2.dll":
                source.extract(name, native)
else:
    assert (native / "metadata/sources.lock.json").exists(), "Download the native source/relinking kit from this release first"
lock = json.loads((native / "metadata/sources.lock.json").read_text())
for entry in lock["sources"]:
    assert hashlib.sha256((native / "sources" / entry["archive"]).read_bytes()).hexdigest() == entry["sha256"]
shutil.copytree(root / "assets/licenses", target / "notices", dirs_exist_ok=True)
shutil.copytree(root / "scripts/native", native / "build-scripts", dirs_exist_ok=True)
shutil.copyfile(root / ".github/workflows/native-player.yml", native / "build-scripts/native-player.yml")
(native / "README.txt").write_text('''ChronoView native player source and relinking companion

Protected library sources are unmodified and hash-locked in metadata/sources.lock.json.
See metadata/linked-archives.json and native-link.map for the exact static link inputs.
relink/lib contains those archives; relink/include and relink/pkgconfig retain headers
and dependency metadata. Runtime copyright notices are in the top-level notices folder.

The native CI workflow and build scripts are also in the ChronoView V1.1.0 source tag.
The fixed cross-toolchain container is identified by immutable digest in the lock.
On a Linux Docker host, mount the project at /src and use that container:
  docker run --rm -v "$PWD:/src" -w /src <container-from-lock> bash scripts/native/build.sh

For an offline source build inside the same container, first copy this bundle's
sources directory to native-output/sources in the project. The release fetcher
verifies and reuses those archives. Its output is native-output/libmpv-2.dll.
If recreating the dependency prefix, copy relink/lib to /opt/ffbuild/lib and
relink/include to /opt/ffbuild/include, and restore pkgconfig metadata under lib.
FFmpeg, libplacebo, FriBidi, libass and mpv are rebuilt by build.sh. No source
patches are applied. The accompanying protected sources may be modified and rebuilt.
Use a compatible MinGW-w64 C/C++ toolchain; the original compiler is identified
in metadata/compiler.txt. Relinking material does not include a Windows OS/SDK.

Replace the application's _internal/vendor/libmpv/libmpv-2.dll with the new DLL,
or set CHRONOVIEW_MPV_LIBRARY to the replacement absolute path before launching.
This companion is for native playback; Qt/PySide6 and Qt's FFmpeg sources are in
the parent folder. See notices/README.md for their dynamic library replacement.
''', encoding="utf-8")
print("Source companion complete.")

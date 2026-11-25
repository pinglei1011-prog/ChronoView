"""Verify our pinned LGPL runtime, or bootstrap it from the matching release."""
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "vendor/libmpv"


def prepare():
    manifest = json.loads((TARGET / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["distribution_status"] == "release", "Unreviewed native runtime"
    expected = manifest["dll_sha256"]
    destination = TARGET / "libmpv-2.dll"
    if not destination.exists():
        cache = ROOT / "work/libmpv"
        cache.mkdir(parents=True, exist_ok=True)
        archive = cache / "release-runtime.zip"
        with urllib.request.urlopen(manifest["runtime_archive"], timeout=120) as response, archive.open("wb") as out:
            shutil.copyfileobj(response, out)
        with zipfile.ZipFile(archive) as source:
            names = [n for n in source.namelist() if n.endswith("/_internal/vendor/libmpv/libmpv-2.dll")]
            assert len(names) == 1
            dll_bytes = source.read(names[0])
            assert hashlib.sha256(dll_bytes).hexdigest() == expected, "Native DLL checksum mismatch"
            destination.write_bytes(dll_bytes)
    assert hashlib.sha256(destination.read_bytes()).hexdigest() == expected, "Native DLL checksum mismatch"
    print("Verified fixed-source LGPL libmpv", manifest["version"])


if __name__ == "__main__":
    prepare()

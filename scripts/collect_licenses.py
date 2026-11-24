"""Copy distributor-provided notices and record the exact runtime FFmpeg build."""
import ctypes
import importlib.metadata
import json
import shutil
import sys
from pathlib import Path

import PySide6


root = Path(__file__).resolve().parents[1]
target = root / "assets" / "licenses"
target.mkdir(parents=True, exist_ok=True)
for package in ["PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6", "Pillow"]:
    dist = importlib.metadata.distribution(package)
    for item in dist.files:
        if "licenses/" in str(item).lower():
            source = Path(dist.locate_file(item))
            shutil.copyfile(source, target / f"{package}-{source.name}")
python_license = Path(sys.base_prefix) / "LICENSE.txt"
if python_license.exists():
    shutil.copyfile(python_license, target / "Python-LICENSE.txt")
qt = Path(PySide6.__file__).parent
library = ctypes.CDLL(str(qt / "avcodec-61.dll"))
record = {}
for function in ["avcodec_license", "avcodec_configuration"]:
    getattr(library, function).restype = ctypes.c_char_p
    record[function] = getattr(library, function)().decode()
assert "LGPL" in record["avcodec_license"]
assert "--enable-gpl" not in record["avcodec_configuration"]
assert "--enable-nonfree" not in record["avcodec_configuration"]
(target / "ffmpeg-build.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
print("Runtime notices copied; FFmpeg LGPL configuration verified.")

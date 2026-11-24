"""Measure metadata enumeration and cached startup on synthetic local fixtures."""
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.scanner import scan_library
from app.storage.index import LibraryIndex

root = Path(__file__).resolve().parents[1]
library = root / "work" / "benchmark-20000"
library.mkdir(parents=True, exist_ok=True)
base = datetime(2026, 1, 1)
for i in range(20000):
    path = library / ("IMG" + (base + timedelta(seconds=i)).strftime("%Y%m%d%H%M%S") + ".jpg")
    if not path.exists():
        path.touch()
started = time.perf_counter()
result = scan_library(library)
scan_seconds = time.perf_counter() - started
index = LibraryIndex(root / "work" / "benchmark.sqlite3")
started = time.perf_counter()
index.save(library, result.items)
save_seconds = time.perf_counter() - started
started = time.perf_counter()
cached = index.load(library)
load_seconds = time.perf_counter() - started
assert len(cached) == 20000
record = {"files": len(cached), "metadata_scan_seconds": round(scan_seconds, 3),
          "index_reconcile_seconds": round(save_seconds, 3), "index_load_seconds": round(load_seconds, 3),
          "scope": "Synthetic zero-byte JPG metadata on local development disk, not real-photo rendering or SATA SSD throughput."}
(root / "work/performance.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
print(json.dumps(record))

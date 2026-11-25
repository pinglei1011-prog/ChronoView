"""Scan 10k/100k/500k simulated directory entries without touching originals."""
import argparse
from datetime import datetime, timedelta
import gc
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('--source', type=Path, default=ROOT)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
sys.path.insert(0, str(a.source))
from app.core.scanner import scan_library


class Entry:
    def __init__(self, name, root): self.name, self.path = name, str(root / name)
    def is_symlink(self): return False
    def is_dir(self, **kw): return False
    def is_file(self, **kw): return True
    def stat(self, **kw): return SimpleNamespace(st_size=1024, st_mtime_ns=1)


class Directory:
    def __init__(self, names, root): self.names, self.root = names, root
    def __enter__(self): return (Entry(n, self.root) for n in self.names)
    def __exit__(self, *args): pass


rows = []
with tempfile.TemporaryDirectory(prefix='cv-simulated-scan-') as tmp:
    root = Path(tmp)
    for count in (10000, 100000, 500000):
        names = [f'IMG{datetime(2020, 1, 1)+timedelta(seconds=i):%Y%m%d%H%M%S}.jpg' for i in range(count)]
        with patch('app.core.scanner.os.scandir', lambda p: Directory(names, root)), \
             patch('app.core.scanner.os.path.isjunction', lambda p: False):
            started = time.perf_counter()
            result = scan_library(root)
            elapsed = time.perf_counter() - started
        assert len(result.items) == count and not result.error_count
        rows.append(dict(records=count, simulated_scan_s=elapsed))
        print(json.dumps(rows[-1]), flush=True)
        del result, names
        gc.collect()
a.output.parent.mkdir(parents=True, exist_ok=True)
a.output.write_text(json.dumps(dict(results=rows, scope='Mock directory entries/stat, real parser/scanner. '
    'Includes Python entry creation overhead; excludes filesystem enumeration, device I/O, and media decoding.'), indent=2), encoding='utf-8')

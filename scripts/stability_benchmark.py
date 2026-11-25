"""Reproducible synthetic metadata benchmarks; never opens a user library."""
import argparse
import ctypes as C
from datetime import datetime, timedelta
import inspect
import json
import os
from pathlib import Path
import sys
import tempfile
import time

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
sys.path.insert(0, str(args.source))
os.environ.setdefault('QT_QPA_PLATFORM', 'windows')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings, QStandardPaths
from app.core.library import MediaItem, sort_items, filter_items
from app.core.scanner import scan_library
from app.storage.index import LibraryIndex
from app.ui.main_window import MainWindow


class Memory(C.Structure):
    _fields_ = [('cb', C.c_ulong), ('faults', C.c_ulong)] + [(n, C.c_size_t) for n in
                ('peak', 'rss', 'qpeak', 'q', 'ppeak', 'p', 'pagefile', 'peakpagefile')]


def rss():
    C.windll.kernel32.GetCurrentProcess.restype = C.c_void_p
    C.windll.psapi.GetProcessMemoryInfo.argtypes = [C.c_void_p, C.POINTER(Memory), C.c_ulong]
    value = Memory(); value.cb = C.sizeof(value)
    assert C.windll.psapi.GetProcessMemoryInfo(C.windll.kernel32.GetCurrentProcess(), C.byref(value), value.cb)
    return round(value.rss / 1048576, 1)


def measure(fn):
    started = time.perf_counter(); value = fn()
    return value, round(time.perf_counter() - started, 4)


app = QApplication([])
app.setOrganizationName('ChronoViewStability')
app.setApplicationName('SyntheticMetadata')
app.setQuitOnLastWindowClosed(False)
QStandardPaths.setTestModeEnabled(True)
rows = []
with tempfile.TemporaryDirectory(prefix='cv-stability-metadata-') as tmp:
    root = Path(tmp) / 'media'; root.mkdir()
    for n in (10000, 100000, 500000):
        base = datetime(2020, 1, 1)
        items, generated = measure(lambda: [MediaItem(root / f'IMG{(base+timedelta(minutes=i)):%Y%m%d%H%M%S}.jpg',
                                  'image', base+timedelta(minutes=i), 0, i) for i in range(n)])
        index = LibraryIndex(Path(tmp) / f'index-{n}.sqlite3')
        _, saved = measure(lambda: index.save(root, items))
        load_args = {'validate': False} if 'validate' in inspect.signature(index.load).parameters else {}
        loaded, restored = measure(lambda: index.load(root, **load_args))
        assert len(loaded) == n
        ordered, sorted_s = measure(lambda: sort_items(items, False))
        subset, filtered = measure(lambda: filter_items(items, year=2020, month=2))
        window = MainWindow(QSettings(str(Path(tmp) / 'ui.ini'), QSettings.Format.IniFormat), auto_load=False)
        window.thumbnails.set_paused(True)
        window.items = items
        _, navigation = measure(window.rebuild_navigation)
        _, view = measure(window.update_view)
        window.show(); app.processEvents()
        gaps = []
        for step in range(30):
            started = time.perf_counter()
            window.grid.verticalScrollBar().setValue(int(window.grid.verticalScrollBar().maximum() * step / 29))
            app.processEvents()
            gaps.append((time.perf_counter() - started) * 1000)
        rows.append(dict(n=n, generate_s=generated, index_save_s=saved, index_load_s=restored,
                         sort_s=sorted_s, filter_s=filtered, navigation_s=navigation, view_s=view,
                         scroll_p95_ms=round(sorted(gaps)[28], 2), scroll_max_ms=round(max(gaps), 2), rss_MiB=rss()))
        print(json.dumps(rows[-1]), flush=True)
        window.close()
        until = time.monotonic() + 20
        while hasattr(window, '_close_ready') and not window._close_ready and time.monotonic() < until:
            app.processEvents(); time.sleep(.005)
        if hasattr(window, '_close_ready'): assert window._close_ready
        app.processEvents()
    # Separate real filesystem enumeration sample; zero-byte fixtures only.
    for item in items[:10000]: item.path.touch()
    scanned, scan_s = measure(lambda: scan_library(root))
    assert len(scanned.items) == 10000
    online = LibraryIndex(Path(tmp) / 'online.sqlite3')
    online.save(root, scanned.items)
    actual, validated_s = measure(lambda: online.load(root))
    assert len(actual) == 10000
    result = dict(records=rows, real_empty_file_scan=dict(n=10000, scan_s=scan_s, validated_load_s=validated_s),
                  scope='Metadata records, no photo/video rendering; scrollbar timings are GUI dispatch latency, not optical FPS. '
                        '10k scan uses real zero-byte files on the local development disk; not external SSD throughput.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')

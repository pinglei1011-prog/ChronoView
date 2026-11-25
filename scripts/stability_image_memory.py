"""Compare full/preview raster RSS in fresh processes using a generated 24MP JPEG."""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, default=ROOT)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--child', type=Path)
parser.add_argument('--edge', type=int)
args = parser.parse_args()
sys.path.insert(0, str(args.source))
if args.child:
    from app.services.images import read_image
    class Memory(C.Structure):
        _fields_ = [('cb', C.c_ulong), ('faults', C.c_ulong)] + [(n, C.c_size_t) for n in
                    ('peak', 'rss', 'qpeak', 'q', 'ppeak', 'p', 'pagefile', 'peakpagefile')]
    start = time.perf_counter(); image = read_image(args.child, args.edge)
    value = Memory(); value.cb = C.sizeof(value)
    C.windll.kernel32.GetCurrentProcess.restype = C.c_void_p
    C.windll.psapi.GetProcessMemoryInfo.argtypes = [C.c_void_p, C.POINTER(Memory), C.c_ulong]
    assert C.windll.psapi.GetProcessMemoryInfo(C.windll.kernel32.GetCurrentProcess(), C.byref(value), value.cb)
    print(json.dumps(dict(edge=args.edge, width=image.width(), height=image.height(), seconds=time.perf_counter()-start,
                          rss_bytes=value.rss, peak_rss_bytes=value.peak)))
    sys.exit(0)
from PIL import Image
args.output.parent.mkdir(parents=True, exist_ok=True)
rows = []
with tempfile.TemporaryDirectory(prefix='cv-raster-memory-') as tmp:
    photo = Path(tmp) / 'synthetic-24MP.jpg'
    image = Image.new('RGB', (6000, 4000), '#8395ad'); image.save(photo); image.close()
    digest = hashlib.sha256(photo.read_bytes()).hexdigest()
    for edge in (None, 2048):
        cmd = [sys.executable, __file__, '--source', str(args.source), '--output', str(args.output), '--child', str(photo)]
        if edge: cmd += ['--edge', str(edge)]
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30)
        rows.append(json.loads(result.stdout))
        assert hashlib.sha256(photo.read_bytes()).hexdigest() == digest
args.output.write_text(json.dumps(dict(results=rows, media_sha256_unchanged=True), indent=2), encoding='utf-8')
print(json.dumps(rows))

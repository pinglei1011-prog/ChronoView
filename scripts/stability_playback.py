"""Isolated native playback metrics on generated fixtures; no user library input."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--source', type=Path, default=ROOT)
parser.add_argument('--child', type=Path)
parser.add_argument('--report', type=Path)
parser.add_argument('--software', action='store_true')
args = parser.parse_args()
sys.path.insert(0, str(args.source))
os.environ['QT_QPA_PLATFORM'] = 'windows'
os.environ['CHRONOVIEW_VIDEO_BACKEND'] = 'mpv'
os.environ['CHRONOVIEW_MPV_LIBRARY'] = str(ROOT / 'vendor/libmpv/libmpv-2.dll')

if args.child:
    # Asset root and native runtime stay identical for before/after source probes.
    sys._MEIPASS = str(ROOT)
    from app.playback_config import configure_playback_environment
    configure_playback_environment()
    from PySide6.QtWidgets import QApplication
    from app.mpv_diagnostics import MpvPlaybackMeasurement
    if args.software:
        import app.services.mpv_client as client
        native = client.load_library()
        class SoftwareOnly:
            def __getattr__(self, name): return getattr(native, name)
            def mpv_set_option_string(self, handle, name, value):
                return native.mpv_set_option_string(handle, name, b'no' if name == b'hwdec' else value)
        client._library = SoftwareOnly()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    probe = MpvPlaybackMeasurement(args.child, args.report, 15)
    sys.exit(app.exec())

import imageio_ffmpeg
args.output.mkdir(parents=True, exist_ok=True)
media = args.output / 'generated-playback'
media.mkdir(exist_ok=True)
definitions = [('H264-1080p60.mp4', '1920x1080', 60, 'libx264', 'yuv420p'),
               ('H265-4k30-main10.mp4', '3840x2160', 30, 'libx265', 'yuv420p10le')]
records = []
for name, size, fps, codec, pixel in definitions:
    path = media / name
    if not path.exists():
        command = [imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-loglevel', 'error', '-nostdin',
                   '-f', 'lavfi', '-i', f'testsrc2=size={size}:rate={fps}', '-f', 'lavfi', '-i',
                   'sine=frequency=440:sample_rate=44100', '-t', '6', '-c:v', codec, '-preset', 'ultrafast',
                   '-threads', '2', '-pix_fmt', pixel, '-c:a', 'aac']
        if codec == 'libx265':
            command += ['-x265-params', 'pools=1:frame-threads=1:log-level=error', '-tag:v', 'hvc1']
        subprocess.run(command + [str(path)], check=True, capture_output=True, timeout=180,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    for software in ([False, True] if codec == 'libx264' else [False]):
        report = args.output / (path.stem + ('-software' if software else '') + '.json')
        command = [sys.executable, __file__, '--output', str(args.output), '--source', str(args.source),
                   '--child', str(path), '--report', str(report)] + (['--software'] if software else [])
        with report.with_suffix('.log').open('wb') as output:
            run = subprocess.run(command, stdout=output, stderr=output, timeout=35)
        value = json.loads(report.read_text(encoding='utf-8')) if report.exists() else {}
        assert run.returncode == 0 and value.get('success') and value.get('reached_end'), (run.returncode, value)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before
        props = value.get('properties', {})
        records.append(dict(file=name, software=software, source_sha256=before, source_unchanged=True,
                            first_video_s=value.get('first_video_s'), hwdec=props.get('hwdec-current'),
                            render_drops=value.get('render_drop_frames'), decode_drops=value.get('decoder_drop_frames'),
                            ui_p95_ms=value.get('ui_gap_p95_ms'), ui_max_ms=value.get('ui_gap_max_ms'),
                            video_output=value.get('video_output'), reached_end=True, child_exit=run.returncode))
        print(json.dumps(records[-1]), flush=True)
(args.output / 'summary.json').write_text(json.dumps(dict(success=True, results=records,
    scope='Generated 6s clips; mpv counters, not optical FPS or perceptual A/V synchronization. '
          'Software row disables hardware decoding in the test proxy only; not a real driver fault.'), indent=2), encoding='utf-8')

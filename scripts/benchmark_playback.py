"""Read-only native playback probe (development tool, not bundled).

Measures QVideoSink delivery and GUI timer gaps, not monitor presentation FPS.
--context recreates cold album cover contention; --suspend-covers applies the
viewer priority policy. Reuse --cache-name to measure the warm cache separately.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_MEDIA_BACKEND', 'ffmpeg')
os.environ.setdefault('QT_QPA_PLATFORM', 'windows')
os.environ.setdefault('QT_LOGGING_RULES', 'qt.multimedia.ffmpeg.*=true;qt.multimedia.*.debug=true')

from PySide6.QtCore import QObject, QTimer, Slot, QEvent, qInstallMessageHandler
from PySide6.QtMultimedia import QMediaPlayer, QVideoFrame, QMediaMetaData
from PySide6.QtWidgets import QApplication
from app.ui.video_player import VideoPlayer

parser = argparse.ArgumentParser()
parser.add_argument('source', type=Path)
parser.add_argument('report', type=Path)
parser.add_argument('--seconds', type=float, default=9)
parser.add_argument('--context', action='store_true')
parser.add_argument('--suspend-covers', action='store_true')
parser.add_argument('--cache-name', help='Reuse this isolated benchmark cache')
parser.add_argument('--fullscreen', action='store_true')
parser.add_argument('--once', action='store_true')
parser.add_argument('--legacy-presentation', action='store_true', help='Compare original Qt frame scheduling')
args = parser.parse_args()
args.source = args.source.resolve(strict=True)
args.report.parent.mkdir(parents=True,exist_ok=True)
if args.seconds <= 0 or (args.suspend_covers and not args.context):
    parser.error('Use positive --seconds and --context with --suspend-covers')
messages = []
if args.legacy_presentation:
    os.environ['CHRONOVIEW_VIDEO_PRESENTATION'] = 'qt'
qInstallMessageHandler(lambda kind, context, message: messages.append(f'{context.category}: {message}'))
app = QApplication([])
app.setOrganizationName('ChronoViewPlaybackBench')
app.setApplicationName(args.cache_name or args.report.stem)
app.setQuitOnLastWindowClosed(False)
main_window = viewer = None
if args.context:
    from PySide6.QtCore import QSettings
    from app.core.scanner import scan_library
    from app.ui.main_window import MainWindow
    from app.ui.photo_viewer import PhotoViewer
    main_window = MainWindow(QSettings(str(args.report.with_suffix('.ini')),QSettings.Format.IniFormat),auto_load=False)
    main_window.items = scan_library(args.source.parent).items
    item = next(i for i in main_window.items if i.path == args.source)
    if not item.taken_at:
        parser.error('--context requires a filename with a recognized date')
    main_window.select_route(('month',item.taken_at.year,item.taken_at.month))
    main_window.show()
    entries = main_window.grid.media_model.items
    if args.suspend_covers:
        main_window.thumbnails.set_paused(True)
    viewer = PhotoViewer(entries,entries.index(item),main_window)
    window = viewer.video
    viewer.show()
else:
    window = VideoPlayer()
window.setWindowTitle('ChronoView playback measurement (muted)')
window.resize(1080, 650)
window.show()
window.audio.setMuted(True)
if args.fullscreen:
    (viewer or window).showFullScreen()
frames, ticks, renders = [], [], []
started, cpu_started = time.perf_counter(), time.process_time()

class Observer(QObject):
    @Slot()
    def swapped(self):
        frame = window.surface.videoSink().videoFrame()
        if frame.isValid():
            renders.append((time.perf_counter(), frame.startTime()))

    def eventFilter(self, obj, event):
        if (not window.surface.frame_driven and event.type() == QEvent.Type.UpdateRequest
                and obj.metaObject().className() == 'QVideoWindow'):
            renders.append((time.perf_counter(), frames[-1][1] if frames else -1))
        return False

    @Slot(QVideoFrame)
    def frame(self, frame):
        if frame.isValid():
            frames.append((time.perf_counter(), frame.startTime(), frame.pixelFormat().name))

observer = Observer()
app.installEventFilter(observer)
if window.surface.frame_driven:
    window.surface.frame_presented.connect(observer.swapped)
window.surface.videoSink().videoFrameChanged.connect(observer.frame)
timer = QTimer()
timer.setInterval(10)
timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
timer.start()
if not args.context:
    window.load(args.source)
if not args.once:
    window.player.setLoops(QMediaPlayer.Loops.Infinite)

def complete():
    elapsed = time.perf_counter() - started
    gaps = [b[0]-a[0] for a,b in zip(frames,frames[1:])]
    tick_gaps = [b-a for a,b in zip(ticks,ticks[1:])]
    result = dict(source=str(args.source), elapsed_s=elapsed,
        cpu_s=time.process_time()-cpu_started, frames=len(frames),
        delivered_fps=(len(frames)-1)/(frames[-1][0]-frames[0][0]) if len(frames)>1 else 0,
        first_frame_s=frames[0][0]-started if frames else None,
        frame_gap_max_ms=max(gaps,default=0)*1000,
        frame_gap_p95_ms=sorted(gaps)[int(len(gaps)*.95)]*1000 if gaps else None,
        ui_gap_max_ms=max(tick_gaps,default=0)*1000,
        pixel_formats=sorted(set(f[2] for f in frames)),
        duration_ms=window.player.duration(),
        expected_fps=window.player.metaData().value(QMediaMetaData.Key.VideoFrameRate),
        status=window.status.text(), environment={k:v for k,v in os.environ.items() if k.startswith(('QT_','QSG_'))})
    result['context'] = args.context
    result['suspend_covers'] = args.suspend_covers
    render_gaps = [b[0]-a[0] for a,b in zip(renders,renders[1:])]
    result['render_requests'] = len(renders)
    result['render_request_fps'] = (len(renders)-1)/(renders[-1][0]-renders[0][0]) if len(renders)>1 else 0
    result['render_gap_p95_ms'] = sorted(render_gaps)[int(len(render_gaps)*.95)]*1000 if render_gaps else None
    result['render_unique_pts'] = len(set(x[1] for x in renders))
    result['presentation'] = 'frame-driven' if window.surface.frame_driven else 'qt-default'
    result['render_measurement'] = 'completed native submissions' if window.surface.frame_driven else 'native update requests'
    args.report.write_text(json.dumps(result,indent=2), encoding='utf-8')
    args.report.with_suffix('.log').write_text('\n'.join(messages),encoding='utf-8')
    print(json.dumps(result), flush=True)
    window.release()
    if viewer:
        viewer.close()
        main_window.close()
    else:
        window.close()
    QTimer.singleShot(150,app.quit)

if args.once:
    window.player.mediaStatusChanged.connect(lambda status: QTimer.singleShot(0,complete)
        if status == QMediaPlayer.MediaStatus.EndOfMedia else None)
QTimer.singleShot(int(args.seconds*1000),complete)
if viewer:
    QTimer.singleShot(0,viewer.exec)
app.exec()

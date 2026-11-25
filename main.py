from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Apply backend configuration before Qt initializes its media integration.
from app.playback_config import configure_playback_environment
configure_playback_environment()
os.environ.setdefault("CHRONOVIEW_VIDEO_BACKEND", "mpv")

from PySide6.QtCore import QSettings, QStandardPaths, QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from app.ui.main_window import MainWindow
from app import __version__

def main() -> int:
    parser = argparse.ArgumentParser(description="ChronoView 本地照片浏览器")
    parser.add_argument("--library", type=Path, help="首次打开的照片库路径")
    parser.add_argument("--settings-file", type=Path, help="使用独立设置文件（测试用）")
    parser.add_argument("--smoke-test", action="store_true", help="启动两秒后退出（测试用）")
    parser.add_argument("--verify-media", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--verify-local-data", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--measure-video", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--measurement-report", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--measurement-seconds", type=float, default=8, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.measure_video and (not args.measurement_report or args.measurement_seconds <= 0
                              or args.measure_video.resolve() == args.measurement_report.resolve()):
        parser.error("Video measurement requires a separate report path and positive duration")
    app = QApplication(sys.argv[:1])
    app.setOrganizationName("ChronoView")
    app.setApplicationName("ChronoView")
    app.setApplicationVersion(__version__)
    app.setFont(QFont("Segoe UI", 10))
    asset_root = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    icon = QIcon(str(asset_root / "assets" / "chronoview.svg"))
    app.setWindowIcon(icon)
    log_dir = (args.settings_file.absolute().parent / "logs" if args.settings_file else
               Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)))
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        from app.services.local_logs import configure_logs
        configure_logs(log_dir)
    except OSError:
        logging.basicConfig(level=logging.INFO)

    def show_error(exc_type, value, traceback):
        logging.error("Unhandled UI exception", exc_info=(exc_type, value, traceback))
        QMessageBox.critical(None, "ChronoView", f"发生错误：{value}\n\n可尝试刷新照片库或重新启动。")

    sys.excepthook = show_error
    if os.environ.get("CHRONOVIEW_VIDEO_BACKEND") == "mpv":
        from app.services.mpv_client import prefetch_library
        prefetch_library()
    if args.measure_video:
        if os.environ.get("CHRONOVIEW_VIDEO_BACKEND") == "mpv":
            from app.mpv_diagnostics import MpvPlaybackMeasurement as PlaybackMeasurement
        else:
            from app.playback_diagnostics import PlaybackMeasurement
        app.setQuitOnLastWindowClosed(False)
        app.measurement = PlaybackMeasurement(args.measure_video, args.measurement_report, args.measurement_seconds)
        return app.exec()
    settings = QSettings(str(args.settings_file), QSettings.Format.IniFormat) if args.settings_file else None
    window = MainWindow(settings=settings, initial_library=args.library)
    window.show()
    if args.verify_media:
        from app.diagnostics import MediaVerification
        window.verification = MediaVerification(window, args.verify_media, args.verify_local_data)
    if args.smoke_test:
        QTimer.singleShot(2000, window.close)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

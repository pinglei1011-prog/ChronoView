from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from app.ui.main_window import MainWindow


def main() -> int:
    parser = argparse.ArgumentParser(description="ChronoView 本地照片浏览器")
    parser.add_argument("--library", type=Path, help="首次打开的照片库路径")
    parser.add_argument("--settings-file", type=Path, help="使用独立设置文件（测试用）")
    parser.add_argument("--smoke-test", action="store_true", help="启动两秒后退出（测试用）")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setOrganizationName("ChronoView")
    app.setApplicationName("ChronoView")
    app.setApplicationVersion("0.1.0")
    app.setFont(QFont("Segoe UI", 10))
    asset_root = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    icon = QIcon(str(asset_root / "assets" / "chronoview.svg"))
    app.setWindowIcon(icon)
    log_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        from logging.handlers import RotatingFileHandler
        handler = RotatingFileHandler(log_dir / "chronoview.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        logging.basicConfig(level=logging.INFO, handlers=[handler])
    except OSError:
        logging.basicConfig(level=logging.INFO)

    def show_error(exc_type, value, traceback):
        logging.error("Unhandled UI exception", exc_info=(exc_type, value, traceback))
        QMessageBox.critical(None, "ChronoView", f"发生错误：{value}\n\n可尝试刷新照片库或重新启动。")

    sys.excepthook = show_error
    settings = QSettings(str(args.settings_file), QSettings.Format.IniFormat) if args.settings_file else None
    window = MainWindow(settings=settings, initial_library=args.library)
    window.show()
    if args.smoke_test:
        QTimer.singleShot(2000, window.close)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

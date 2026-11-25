"""Per-instance logs with path redaction; never log raw media identifiers by default."""
import faulthandler
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re

_native = None
_directory = None
_owned = re.compile(r"(?:chronoview(?:-\d+)?\.log(?:\.[12])?|native-crash(?:-\d+)?\.log)$")


class PrivateFormatter(logging.Formatter):
    def format(self, record):
        text = super().format(record)
        lines = []
        for line in text.splitlines():
            # Decoder errors can contain unquoted names with spaces. Hide the
            # entire detail line rather than leaving part of a private name.
            if re.search(r"\.(?:jpg|jpeg|png|webp|bmp|heic|heif|mp4|mov|mkv|avi)\b", line, re.I):
                line = "[媒体详情已隐藏]"
            else:
                line = re.sub(r"(?:[A-Za-z]:[\\/]|\\\\)[^\r\n]*", "[本地路径已隐藏]", line)
            lines.append(line)
        return "\n".join(lines)


def configure_logs(directory):
    global _native, _directory
    _directory = Path(directory).absolute()
    _directory.mkdir(parents=True, exist_ok=True)
    # Bound inactive per-process logs across repeated application launches.
    total = 0
    candidates = sorted((p for p in _directory.iterdir() if p.is_file() and not p.is_symlink()
                         and _owned.fullmatch(p.name)), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            total += path.stat().st_size
            if total > 32 * 1024 ** 2:
                path.unlink()  # Windows refuses removal of another open instance's log.
        except OSError:
            pass
    handler = RotatingFileHandler(_directory / f"chronoview-{os.getpid()}.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(PrivateFormatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    _native = (_directory / f"native-crash-{os.getpid()}.log").open("a", encoding="utf-8")
    faulthandler.enable(file=_native, all_threads=True)


def clear_logs():
    """Truncate active own logs and remove inactive logs using an exact filename allowlist."""
    if _directory is None:
        return
    active = set()
    for handler in logging.getLogger().handlers:
        if (isinstance(handler, RotatingFileHandler)
                and Path(handler.baseFilename).parent == _directory.absolute()
                and _owned.fullmatch(Path(handler.baseFilename).name)):
            handler.acquire()
            try:
                handler.flush()
                handler.stream.seek(0)
                handler.stream.truncate()
                active.add(Path(handler.baseFilename))
            finally:
                handler.release()
    if _native:
        _native.seek(0)
        _native.truncate()
        _native.flush()
        active.add(Path(_native.name))
    for path in _directory.iterdir():
        if path.is_file() and not path.is_symlink() and _owned.fullmatch(path.name) and path not in active:
            path.unlink()  # Report partial cleanup when another instance still owns a log.

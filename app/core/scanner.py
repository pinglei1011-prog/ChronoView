from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Callable

from app.core.filename_parser import parse_filename
from app.core.library import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, MediaItem


@dataclass
class ScanResult:
    items: list[MediaItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    error_count: int = 0
    cancelled: bool = False
    unavailable: bool = False
    directories: int = 0

    def add_error(self, path: Path, exc: OSError) -> None:
        self.error_count += 1
        if len(self.errors) < 30:
            self.errors.append(f"{path}: {exc}")


def scan_library(root: Path, cancel: Event | None = None,
                 progress: Callable[[int, int], None] | None = None,
                 batch: Callable[[list[MediaItem]], None] | None = None) -> ScanResult:
    """Iterative, read-only traversal; never follow directory links or junctions.

    This function has no GUI dependency. Call it on a worker thread.
    A failed/cancelled result is provisional: callers must preserve their old library.
    """
    root = Path(os.path.abspath(root))
    result = ScanResult()
    cancel = cancel or Event()
    if not root.is_dir():
        result.unavailable = True
        result.add_error(root, OSError("照片库不可访问，请检查硬盘连接或重新选择文件夹"))
        return result
    stack = [root]
    pending: list[MediaItem] = []
    while stack:
        if cancel.is_set():
            result.cancelled = True
            break
        directory = stack.pop()
        try:
            with os.scandir(directory) as entries:
                result.directories += 1
                for entry in entries:
                    if cancel.is_set():
                        result.cancelled = True
                        break
                    try:
                        # isjunction is available on the supported Python 3.12+.
                        if entry.is_symlink() or os.path.isjunction(entry.path):
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                            continue
                        suffix = Path(entry.name).suffix.lower()
                        if suffix not in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        stat = entry.stat(follow_symlinks=False)
                        path = Path(entry.path)
                        item = MediaItem(path, "video" if suffix in VIDEO_EXTENSIONS else "image",
                                         parse_filename(path), stat.st_size, stat.st_mtime_ns)
                        result.items.append(item)
                        pending.append(item)
                        if len(pending) >= 256:
                            if batch:
                                batch(pending)
                            pending = []
                            if progress:
                                progress(len(result.items), result.directories)
                    except OSError as exc:
                        result.add_error(Path(entry.path), exc)
            if progress:
                progress(len(result.items), result.directories)
        except OSError as exc:
            result.add_error(directory, exc)
            if directory == root:
                result.unavailable = True
    if pending and batch and not result.cancelled:
        batch(pending)
    # Root disappearing mid-scan must never replace a previously loaded snapshot.
    if not root.is_dir():
        result.unavailable = True
    return result

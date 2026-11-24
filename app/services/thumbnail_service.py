from __future__ import annotations

import hashlib
import os
import threading
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Qt
from PySide6.QtGui import QImage, QPixmap

from app.core.library import MediaItem
from app.services.images import read_image


def cache_key(item: MediaItem) -> str:
    # Changing the thumbnail algorithm requires changing the version below.
    return hashlib.sha256(f"v1|{item.path}|{item.size}|{item.mtime_ns}".encode("utf-8")).hexdigest()


class TaskSignals(QObject):
    done = Signal(str, QImage, str)


class ThumbnailTask(QRunnable):
    def __init__(self, item: MediaItem, key: str, cache: Path, cancel: threading.Event):
        super().__init__()
        self.item, self.key, self.cache, self.cancel = item, key, cache, cancel
        self.signals = TaskSignals()

    def run(self):
        image, error = QImage(), ""
        try:
            if self.cancel.is_set():
                return
            stat = self.item.path.stat()
            if (stat.st_size, stat.st_mtime_ns) != (self.item.size, self.item.mtime_ns):
                raise ValueError("文件已更改，请刷新照片库")
            target = self.cache / f"{self.key}.png"
            if target.exists():
                image = QImage(str(target))
            if image.isNull():
                image = read_image(self.item.path, 512)
                # Cache failures must not prevent viewing an otherwise valid image.
                try:
                    self.cache.mkdir(parents=True, exist_ok=True)
                    temp = target.with_suffix(f".{threading.get_ident()}.tmp")
                    if image.save(str(temp), "PNG"):
                        os.replace(temp, target)
                except OSError:
                    pass
        except Exception as exc:
            error = str(exc)
        finally:
            self.signals.done.emit(self.key, image, error)


class ThumbnailService(QObject):
    updated = Signal(str)

    def __init__(self, cache: Path, parent=None):
        super().__init__(parent)
        self.cache = cache
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(3)
        self.cancel = threading.Event()
        self.memory: OrderedDict[str, tuple[QPixmap, str]] = OrderedDict()
        self.pending: dict[str, ThumbnailTask] = {}

    def get(self, item: MediaItem) -> tuple[QPixmap | None, str]:
        key = cache_key(item)
        if key in self.memory:
            self.memory.move_to_end(key)
            return self.memory[key]
        if item.kind == "video":
            return None, "第一阶段：视频仅参与分类与排序，播放将在第二阶段加入"
        if key not in self.pending and len(self.pending) < 48 and not self.cancel.is_set():
            task = ThumbnailTask(item, key, self.cache, self.cancel)
            task.signals.done.connect(self._done, Qt.ConnectionType.QueuedConnection)
            self.pending[key] = task
            self.pool.start(task)
        return None, ""

    def _done(self, key: str, image: QImage, error: str):
        self.pending.pop(key, None)
        self.memory[key] = (QPixmap.fromImage(image), error)
        while len(self.memory) > 192:
            self.memory.popitem(last=False)
        self.updated.emit(key)

    def shutdown(self):
        self.cancel.set()
        self.pool.clear()
        self.pool.waitForDone()

    def clear_errors(self):
        """A reconnect/refresh may make previously unreadable files readable again."""
        for key in list(self.memory):
            if self.memory[key][1]:
                del self.memory[key]

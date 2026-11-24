from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from collections import OrderedDict, deque
from pathlib import Path
from dataclasses import replace

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QObject, QRunnable, QThreadPool, Signal, Qt
from PySide6.QtGui import QImage, QPixmap

from app.core.library import MediaItem
from app.services.images import read_image, image_error_message
from app.services.video_thumbnail import VideoThumbnailJob


def cache_key(item: MediaItem) -> str:
    # Changing the thumbnail algorithm requires changing the version below.
    version = "video-v2" if item.kind == "video" else "v1"
    return hashlib.sha256(f"{version}|{item.path}|{item.size}|{item.mtime_ns}".encode("utf-8")).hexdigest()


class TaskSignals(QObject):
    done = Signal(str, QImage, str, float)
    video_needed = Signal(str, object)


class ThumbnailTask(QRunnable):
    def __init__(self, item: MediaItem, key: str, cache: Path, cancel: threading.Event,
                 supplied_image: QImage | None = None, duration: float = 0):
        super().__init__()
        self.item, self.key, self.cache, self.cancel = item, key, cache, cancel
        self.signals = TaskSignals()
        self.supplied_image, self.duration = supplied_image, duration

    def run(self):
        image, error = QImage(), ""
        video_needed = False
        try:
            if self.cancel.is_set():
                return
            stat = self.item.path.stat()
            if (stat.st_size, stat.st_mtime_ns) != (self.item.size, self.item.mtime_ns):
                # The index is a startup snapshot, not proof that a readable file
                # has become invalid. Resolve current metadata in this worker.
                self.item = replace(self.item, size=stat.st_size, mtime_ns=stat.st_mtime_ns)
                # A video frame decoded before this change cannot represent the new file.
                self.supplied_image = None
                self.duration = 0
            # Keep the request key for the model's pending/memory entry, but write
            # disk cache using the *actual* source fingerprint, never the stale one.
            target = self.cache / f"{cache_key(self.item)}.png"
            if self.supplied_image is not None:
                image = self.supplied_image
            elif target.exists():
                image = QImage(str(target))
                try:
                    self.duration = float(json.loads(target.with_suffix('.json').read_text()).get('duration', 0))
                except (OSError, ValueError, TypeError):
                    pass
            if image.isNull():
                if self.item.kind == "video":
                    video_needed = True
                    self.signals.video_needed.emit(self.key, self.item)
                    return
                image = read_image(self.item.path, 512)
            if self.supplied_image is not None or not target.exists() or QImage(str(target)).isNull():
                # Cache failures must not prevent viewing an otherwise valid image.
                try:
                    self.cache.mkdir(parents=True, exist_ok=True)
                    temp = target.with_suffix(f".{threading.get_ident()}.tmp")
                    if image.save(str(temp), "PNG"):
                        os.replace(temp, target)
                        if self.item.kind == "video":
                            meta_temp = temp.with_suffix('.json.tmp')
                            meta_temp.write_text(json.dumps({'duration': self.duration}), encoding='utf-8')
                            os.replace(meta_temp, target.with_suffix('.json'))
                except OSError:
                    pass
        except Exception as exc:
            error = image_error_message(exc) if self.item.kind == "image" else str(exc)
            logging.warning("Thumbnail failed for %s: %s", self.item.path, exc)
        finally:
            if not video_needed:
                self.signals.done.emit(self.key, image, error, self.duration)


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
        self.durations: dict[str, float] = {}
        self.video_queue = deque()
        self.video_jobs = {}
        self.paused = False

    def get(self, item: MediaItem) -> tuple[QPixmap | None, str]:
        key = cache_key(item)
        if key in self.memory:
            self.memory.move_to_end(key)
            return self.memory[key]
        if key not in self.pending and len(self.pending) < 48 and not self.cancel.is_set() and not self.paused:
            task = ThumbnailTask(item, key, self.cache, self.cancel)
            task.signals.done.connect(self._done, Qt.ConnectionType.QueuedConnection)
            task.signals.video_needed.connect(self._queue_video, Qt.ConnectionType.QueuedConnection)
            self.pending[key] = task
            self.pool.start(task)
        return None, ""

    def _done(self, key: str, image: QImage, error: str, duration: float = 0):
        self.pending.pop(key, None)
        self.memory[key] = (QPixmap.fromImage(image), error)
        if duration > 0:
            self.durations[key] = duration
        while len(self.memory) > 192:
            old_key, _ = self.memory.popitem(last=False)
            self.durations.pop(old_key, None)
        self.updated.emit(key)

    def duration(self, item: MediaItem) -> float:
        return self.durations.get(cache_key(item), 0)

    def _queue_video(self, key, item):
        if self.cancel.is_set():
            return
        self.video_queue.append((key, item))
        self._start_videos()

    def _start_videos(self):
        while self.video_queue and len(self.video_jobs) < 2 and not self.cancel.is_set() and not self.paused:
            key, item = self.video_queue.popleft()
            job = VideoThumbnailJob(item, self)
            self.video_jobs[key] = job
            job.finished.connect(lambda image, error, duration, k=key, i=item:
                                 self._video_done(k, i, image, error, duration))
            job.start()

    def set_paused(self, paused: bool):
        """Prioritize the viewer over background cover decoders and new requests."""
        if self.paused == paused:
            return
        self.paused = paused
        if paused:
            jobs = list(self.video_jobs.items())
            self.video_jobs.clear()
            for key, job in reversed(jobs):
                # Completed guards discard already queued frames before toImage()
                # can download/convert a full-resolution GPU frame on the GUI thread.
                job.cancel()
                self.video_queue.appendleft((key, job.item))
                job.deleteLater()
            if jobs and QCoreApplication.instance():
                QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        else:
            self._start_videos()
            # Visible uncached cells skipped during playback may request work again.
            self.updated.emit("")

    def _video_done(self, key, item, image, error, duration):
        job = self.video_jobs.pop(key, None)
        if job:
            job.deleteLater()
        if error or image.isNull():
            self._done(key, image, error or "无法读取视频封面", duration)
        else:
            task = ThumbnailTask(item, key, self.cache, self.cancel, image, duration)
            task.signals.done.connect(self._done, Qt.ConnectionType.QueuedConnection)
            self.pending[key] = task
            self.pool.start(task)
        self._start_videos()

    def shutdown(self):
        self.cancel.set()
        self.video_queue.clear()
        for job in self.video_jobs.values():
            job.cancel()
            job.deleteLater()
        self.video_jobs.clear()
        self.pool.clear()
        self.pool.waitForDone()
        # Complete native stop/deferred-delete events before this service (the
        # players' QObject parent) can be destroyed or another library starts.
        if QCoreApplication.instance():
            QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def clear_errors(self):
        """A reconnect/refresh may make previously unreadable files readable again."""
        for key in list(self.memory):
            if self.memory[key][1]:
                del self.memory[key]

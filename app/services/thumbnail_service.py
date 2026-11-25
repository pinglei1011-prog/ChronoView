from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections import OrderedDict, deque
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, QThreadPool, QTimer, Signal, Qt
from PySide6.QtGui import QImage, QPixmap

from app.core.library import MediaItem
from app.services.disk_cache import DiskThumbnailCache, DEFAULT_LIMIT
from app.services.images import read_image, image_error_message
from app.services.video_thumbnail import VideoThumbnailJob

_retiring_services = set()


def cache_key(item: MediaItem) -> str:
    version = "video-v3" if item.kind == "video" else "v2"
    identity = getattr(item, "library_key", "")
    return hashlib.sha256(f"{version}|{identity}|{item.path}|{item.size}|{item.mtime_ns}".encode("utf-8")).hexdigest()


class TaskSignals(QObject):
    done = Signal(object, str, QImage, str, float)
    video_needed = Signal(object, str, object)
    maintenance = Signal(object, str, object)


class ThumbnailTask:
    def __init__(self, item, key, cache, cancel, signals, generation, supplied_image=None, duration=0):
        self.item, self.key, self.disk, self.cancel = item, key, cache, cancel
        self.signals, self.generation = signals, generation
        self.supplied_image, self.duration = supplied_image, duration
        self.finished = threading.Event()
        self.delivered = False

    def run(self):
        image, error, video_needed = QImage(), "", False
        try:
            if self.cancel.is_set():
                return
            self.disk._prepare()
            epoch = self.disk.epoch
            stat = self.item.path.stat()
            if (stat.st_size, stat.st_mtime_ns) != (self.item.size, self.item.mtime_ns):
                self.item = replace(self.item, size=stat.st_size, mtime_ns=stat.st_mtime_ns)
                self.supplied_image, self.duration = None, 0
            actual_key = cache_key(self.item)
            cached = False
            if self.supplied_image is not None:
                image = self.supplied_image
            else:
                image, duration = self.disk.read(actual_key)
                cached = not image.isNull()
                if duration > 0:
                    self.duration = duration
            if self.cancel.is_set():
                return
            if image.isNull():
                if self.item.kind == "video":
                    video_needed = True
                    self.signals.video_needed.emit(self, self.key, self.item)
                    return
                image = read_image(self.item.path, 512)
            if not cached and not self.cancel.is_set():
                identity = getattr(self.item, 'library_key', '')
                source_id = hashlib.sha256(f'{identity}|{os.path.normcase(str(self.item.path))}'.encode('utf-8')).hexdigest()
                self.disk.write(actual_key, image, self.duration, source_id, epoch)
        except Exception as exc:
            error = image_error_message(exc) if self.item.kind == "image" else "无法读取视频，请检查文件或硬盘连接。"
            logging.warning("Thumbnail read failed (%s)", type(exc).__name__)
        finally:
            if not video_needed:
                self.signals.done.emit(self, self.key, image, error, self.duration)
            self.finished.set()


class CacheTask:
    def __init__(self, disk, action, signals):
        self.disk, self.action = disk, action
        self.signals = signals
        self.finished = threading.Event()
        self.delivered = False

    def run(self):
        try:
            try:
                result = self.disk.clear() if self.action == 'clear' else self.disk.info()
            except Exception as exc:
                logging.warning('Cache operation failed (%s)', type(exc).__name__)
                result = (False, '缓存操作失败，请检查本地磁盘或权限') if self.action == 'clear' else dict(bytes=0, entries=0, limit_bytes=self.disk.limit_bytes, enabled=False)
            self.signals.maintenance.emit(self, self.action, result)
        finally:
            self.finished.set()


class ThumbnailService(QObject):
    updated = Signal(str)
    shutdown_finished = Signal()
    cache_cleared = Signal(bool, str)
    cache_info_ready = Signal(object)

    def __init__(self, cache: Path, parent=None, cache_limit_bytes=DEFAULT_LIMIT):
        super().__init__(parent)
        self.cache = cache
        self.disk = DiskThumbnailCache(cache, limit_bytes=cache_limit_bytes)
        # The pool must outlive windows while a non-interruptible OS read finishes.
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(3)
        self.maintenance_pool = QThreadPool()
        self.maintenance_pool.setMaxThreadCount(1)
        self.cancel = threading.Event()
        self.memory = OrderedDict()
        self.pending = {}
        self.durations = {}
        self._validated = {}
        self.video_queue = deque()
        self.video_jobs = {}
        self._retiring_jobs = set()
        self.paused = False
        self.closing = False
        self.generation = 0
        self._maintenance_task = None
        self._inflight = set()
        # One GUI-owned emitter survives every callable, including pool.clear().
        self._signals = TaskSignals(self)
        self._signals.done.connect(self._task_done, Qt.ConnectionType.QueuedConnection)
        self._signals.video_needed.connect(self._task_video, Qt.ConnectionType.QueuedConnection)
        self._signals.maintenance.connect(self._maintenance_done, Qt.ConnectionType.QueuedConnection)
        self._cache_info = dict(bytes=0, entries=0, limit_bytes=cache_limit_bytes, enabled=True)
        self._shutdown_timer = QTimer(self)
        self._shutdown_timer.setInterval(20)
        self._shutdown_timer.timeout.connect(self._poll_shutdown)
        self._collect_timer = QTimer(self)
        self._collect_timer.setInterval(20)
        self._collect_timer.timeout.connect(self._collect_tasks)

    def _request(self, item, key, image=None, duration=0):
        task = ThumbnailTask(item, key, self.disk, self.cancel, self._signals, self.generation, image, duration)
        self.pending[key] = task
        self._inflight.add(task)
        self._collect_timer.start()
        self.pool.start(task.run)

    def _collect_tasks(self):
        pool_idle = self.pool is None or self.pool.activeThreadCount() == 0
        maintenance_idle = self.maintenance_pool is None or self.maintenance_pool.activeThreadCount() == 0
        for task in list(self._inflight):
            cancelled = isinstance(task, ThumbnailTask) and task.cancel.is_set()
            idle = pool_idle if isinstance(task, ThumbnailTask) else maintenance_idle
            if (task.finished.is_set() and task.delivered) or (idle and cancelled):
                self._inflight.discard(task)
        if not self._inflight:
            self._collect_timer.stop()

    def _task_done(self, task, key, image, error, duration):
        task.delivered = True
        if task.generation == self.generation:
            self._done(key, image, error, duration)

    def _task_video(self, task, key, item):
        task.delivered = True
        if task.generation == self.generation:
            self._queue_video(key, item)

    def get(self, item):
        key = cache_key(item)
        if key in self.memory:
            self.memory.move_to_end(key)
            # Revalidate off the GUI thread, even when a stale index still supplies the same key.
            if time.monotonic() - self._validated.get(key, 0) > 2:
                if key not in self.pending and len(self.pending) < 48 and not self.closing and not self.paused:
                    self._request(item, key)
            return self.memory[key]
        if key not in self.pending and len(self.pending) < 48 and not self.closing and not self.paused:
            self._request(item, key)
        return None, ""

    def _done(self, key, image, error, duration=0):
        self.pending.pop(key, None)
        if self.closing:
            return
        self.memory[key] = (QPixmap.fromImage(image), error)
        self._validated[key] = time.monotonic()
        if duration > 0:
            self.durations[key] = duration
        while len(self.memory) > 192:
            old, _ = self.memory.popitem(last=False)
            self.durations.pop(old, None)
            self._validated.pop(old, None)
        if not self.paused:
            self.updated.emit(key)

    def duration(self, item):
        return self.durations.get(cache_key(item), 0)

    def _queue_video(self, key, item):
        if self.closing or self.paused:
            self.pending.pop(key, None)
            return
        self.video_queue.append((key, item))
        self._start_videos()

    def _start_videos(self):
        while (self.video_queue and len(self.video_jobs) + len(self._retiring_jobs) < 2
               and not self.closing and not self.paused):
            key, item = self.video_queue.popleft()
            job = VideoThumbnailJob(item, self)
            self.video_jobs[key] = job
            generation = self.generation
            job.finished.connect(lambda image, error, duration, k=key, i=item, g=generation:
                                 self._video_done(k, i, image, error, duration) if g == self.generation else None)
            job.start()

    def _retire(self, job):
        self._retiring_jobs.add(job)
        job.destroyed.connect(lambda _=None, j=job: self._retired(j))
        job.dispose()

    def _retired(self, job):
        self._retiring_jobs.discard(job)
        self._start_videos()

    def _cancel_requests(self):
        self.cancel.set()
        self.generation += 1
        self.cancel = threading.Event()
        self.pool.clear()
        self.pending.clear()
        self.video_queue.clear()
        jobs, self.video_jobs = self.video_jobs, {}
        for job in jobs.values():
            self._retire(job)

    def set_paused(self, paused):
        if self.paused == paused or self.closing:
            return
        self.paused = paused
        if paused:
            self._cancel_requests()
        else:
            self.updated.emit("")

    def _video_done(self, key, item, image, error, duration):
        job = self.video_jobs.pop(key, None)
        if job:
            self._retire(job)
        if self.closing or self.paused:
            return
        if error or image.isNull():
            self._done(key, image, error or "无法读取视频封面", duration)
        else:
            self._request(item, key, image, duration)
        self._start_videos()

    def is_idle(self):
        return ((self.pool is None or self.pool.activeThreadCount() == 0)
                and (self.maintenance_pool is None or self.maintenance_pool.activeThreadCount() == 0)
                and self._maintenance_task is None and not self._retiring_jobs and not self.video_jobs)

    def shutdown(self):
        if self.closing:
            return
        self.closing = True
        self.paused = True
        self._cancel_requests()
        self.cancel.set()
        self.memory.clear()
        self.durations.clear()
        self._validated.clear()
        app = QCoreApplication.instance()
        if app:
            self.setParent(app)
        _retiring_services.add(self)
        self._shutdown_timer.start()

    def _poll_shutdown(self):
        if self.is_idle():
            self._shutdown_timer.stop()
            self._collect_tasks()
            for pool in (self.pool, self.maintenance_pool):
                if pool is not None:
                    pool.deleteLater()
            self.pool = self.maintenance_pool = None
            self.setParent(None)
            _retiring_services.discard(self)
            self.shutdown_finished.emit()

    def cache_info(self):
        return dict(self._cache_info)

    def request_cache_info(self):
        return self._run_maintenance('info')

    def clear_cache(self):
        if self.closing or self._maintenance_task is not None:
            self.cache_cleared.emit(False, "缓存正在处理，请稍后重试")
            return False
        self._cancel_requests()
        self.memory.clear()
        self.durations.clear()
        self._validated.clear()
        return self._run_maintenance('clear')

    def _run_maintenance(self, action):
        if self.closing or self._maintenance_task is not None:
            return False
        task = CacheTask(self.disk, action, self._signals)
        self._maintenance_task = task
        self._inflight.add(task)
        self._collect_timer.start()
        self.maintenance_pool.start(task.run)
        return True

    def _maintenance_done(self, task, action, result):
        task.delivered = True
        self._maintenance_task = None
        if self.closing:
            return
        if action == 'clear':
            if result[0]:
                self._cache_info.update(bytes=0, entries=0)
            self.cache_cleared.emit(*result)
            if not self.paused:
                self.updated.emit("")
        else:
            self._cache_info = result
            self.cache_info_ready.emit(result)

    def clear_errors(self):
        # An explicit refresh also invalidates previously successful in-memory snapshots.
        self.memory.clear()
        self.durations.clear()
        self._validated.clear()

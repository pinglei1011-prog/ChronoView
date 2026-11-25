"""Disposable cache and media fixtures only. Never use a user's photo library."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import threading
import time

from PIL import Image
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QSignalSpy
import pytest

from app.core.scanner import scan_library
from app.services.disk_cache import DiskThumbnailCache, DEFAULT_LIMIT
from app.services.thumbnail_service import ThumbnailService, cache_key
from tests.test_images import wait_until


def key(number):
    return hashlib.sha256(str(number).encode()).hexdigest()


def image():
    value = QImage(96, 96, QImage.Format.Format_RGB32)
    value.fill(QColor('#6ca0c4'))
    return value


def test_cache_default_capacity_lru_and_modified_source_eviction(tmp_path):
    cache = DiskThumbnailCache(tmp_path / 'cache')
    assert cache.limit_bytes == DEFAULT_LIMIT == 5 * 1024 ** 3
    for i in range(3):
        assert cache.write(key(i), image(), source_id=str(i))
    limit = cache.info()['bytes']
    cache.limit_bytes = limit
    assert not cache.read(key(0))[0].isNull()
    assert cache.write(key(3), image(), source_id='3')
    assert (cache.root / (key(0) + '.png')).exists()
    assert not (cache.root / (key(1) + '.png')).exists()
    assert cache.info()['bytes'] <= limit
    cache.limit_bytes = DEFAULT_LIMIT
    assert cache.write(key(4), image(), source_id='0')
    assert not (cache.root / (key(0) + '.png')).exists()
    assert (cache.root / (key(4) + '.png')).exists()


def test_age_corrupt_entries_orphans_and_abandoned_temporary_files(tmp_path):
    cache = DiskThumbnailCache(tmp_path / 'cache', max_age_days=1)
    assert cache.write(key(0), image())
    old = time.time() - 2 * 86400
    os.utime(cache.root / (key(0) + '.png'), (old, old))
    corrupt = cache.root / (key(1) + '.png')
    corrupt.write_bytes(b'not a PNG')
    orphan = cache.root / (key(2) + '.json')
    orphan.write_text('{"duration": 2}')
    abandoned = cache.root / (key(3) + '.old.tmp')
    abandoned.write_bytes(b'partial PNG')
    os.utime(abandoned, (old, old))
    recent = cache.root / (key(4) + '.recent.tmp')
    recent.write_bytes(b'active write')
    cache._initialized = False
    assert cache.info()['entries'] == 0
    assert not (cache.root / (key(0) + '.png')).exists()
    assert not corrupt.exists() and not orphan.exists() and not abandoned.exists()
    assert recent.exists()


def test_clear_epoch_prevents_late_writes_and_preserves_unmanaged_files(tmp_path):
    cache = DiskThumbnailCache(tmp_path / 'cache')
    assert cache.write(key(0), image())
    old_epoch = cache.epoch
    source = tmp_path / 'original.png'
    Image.new('RGB', (20, 20), '#6ca0c4').save(source)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    nested = cache.root / 'not-owned'
    nested.mkdir()
    nested_original = nested / 'original.png'
    nested_original.write_bytes(source.read_bytes())
    user_file = cache.root / 'user-notes.txt'
    user_file.write_text('not cache data')
    assert cache.clear()[0]
    assert not cache.write(key(1), image(), epoch=old_epoch)
    assert cache.info()['bytes'] == 0
    assert source.exists() and hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert nested_original.exists() and user_file.read_text() == 'not cache data'


def test_arbitrary_media_directory_and_linked_root_are_never_claimed(tmp_path, monkeypatch):
    originals = tmp_path / 'originals'
    originals.mkdir()
    photo = originals / 'IMG20260101120000.png'
    Image.new('RGB', (20, 20), '#6ca0c4').save(photo)
    before = photo.read_bytes()
    cache = DiskThumbnailCache(originals)
    assert not cache.clear()[0]
    assert not cache.enabled and photo.read_bytes() == before
    linked = tmp_path / 'linked-cache'
    original_check = Path.is_junction
    monkeypatch.setattr(Path, 'is_junction', lambda p: p == linked or original_check(p))
    blocked = DiskThumbnailCache(linked)
    assert not blocked.clear()[0]
    assert not linked.exists()


def test_claimed_cache_root_replaced_by_junction_is_not_cleared(tmp_path, monkeypatch):
    cache = DiskThumbnailCache(tmp_path / 'cache')
    assert cache.write(key(0), image())
    original = Path.is_junction
    monkeypatch.setattr(Path, 'is_junction', lambda p: p == cache.root or original(p))
    assert not cache.clear()[0]
    assert (cache.root / (key(0) + '.png')).exists()


def test_identical_fingerprint_on_different_disks_has_distinct_cache_key(tmp_path):
    from dataclasses import replace
    source = tmp_path / 'IMG20260101120000.png'
    Image.new('RGB', (40, 20), '#6ca0c4').save(source)
    item = scan_library(tmp_path).items[0]
    a, b = replace(item, library_key='disk-a'), replace(item, library_key='disk-b')
    assert cache_key(a) != cache_key(b)


def test_low_disk_space_degrades_to_memory_without_touching_media(tmp_path, qapp, monkeypatch):
    import app.services.disk_cache as module
    from collections import namedtuple
    usage = namedtuple('Usage', 'total used free')
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda p: usage(1024, 1024, 0))
    originals = tmp_path / 'originals'
    originals.mkdir()
    photo = originals / 'IMG20260101120000.png'
    Image.new('RGB', (60, 40), '#6ca0c4').save(photo)
    before = hashlib.sha256(photo.read_bytes()).hexdigest()
    item = scan_library(originals).items[0]
    service = ThumbnailService(tmp_path / 'cache')
    try:
        service.get(item)
        wait_until(qapp, lambda: cache_key(item) in service.memory)
        pixmap, error = service.get(item)
        assert not error and not pixmap.isNull()
        assert not (service.cache / (cache_key(item) + '.png')).exists()
        assert hashlib.sha256(photo.read_bytes()).hexdigest() == before
    finally:
        service.shutdown()
        wait_until(qapp, service.is_idle)


def test_concurrent_cache_instances_write_atomically(tmp_path):
    root = tmp_path / 'cache'
    caches = [DiskThumbnailCache(root), DiskThumbnailCache(root)]
    # Claim once before concurrency; other instances safely adopt the ownership marker.
    caches[0].info()
    def work(i):
        cache = caches[i % 2]
        return cache.write(key(i), image(), duration=2.5, source_id=str(i))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(work, range(16)))
    assert all(results)
    assert caches[0].info()['entries'] == 16
    for i in range(16):
        decoded, duration = caches[0].read(key(i))
        assert not decoded.isNull() and duration == 2.5
    assert not list(root.glob('*.tmp'))


def test_cache_index_corruption_rebuilds_from_valid_payload(tmp_path):
    cache = DiskThumbnailCache(tmp_path / 'cache')
    assert cache.write(key(0), image(), duration=2.5)
    (cache.root / '.cache-index.sqlite3').write_bytes(b'not a sqlite database')
    # First access falls back; the next opens a fresh disposable index.
    cache.read(key(0))
    decoded, duration = cache.read(key(0))
    assert not decoded.isNull() and duration == 2.5
    assert cache.info()['entries'] == 1


def test_shutdown_never_waits_for_a_blocked_reader_or_destroys_its_signals(tmp_path, qapp, monkeypatch):
    import app.services.thumbnail_service as module
    source = tmp_path / 'IMG20260101120000.png'
    Image.new('RGB', (40, 20), '#6ca0c4').save(source)
    item = scan_library(tmp_path).items[0]
    entered, release = threading.Event(), threading.Event()
    real_read = module.read_image
    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(5), 'Test did not release its simulated slow device'
        return real_read(*args, **kwargs)
    monkeypatch.setattr(module, 'read_image', delayed)
    service = ThumbnailService(tmp_path / 'cache')
    updates = QSignalSpy(service.updated)
    service.get(item)
    wait_until(qapp, entered.is_set)
    started = time.monotonic()
    service.shutdown()
    assert time.monotonic() - started < .2
    assert not service.is_idle()
    release.set()
    wait_until(qapp, service.is_idle)
    qapp.processEvents()
    assert not service.memory and updates.count() == 0


def test_manual_clear_cancels_pending_work_and_reports_completion(tmp_path, qapp, monkeypatch):
    source = tmp_path / 'IMG20260101120000.png'
    Image.new('RGB', (40, 20), '#6ca0c4').save(source)
    item = scan_library(tmp_path).items[0]
    service = ThumbnailService(tmp_path / 'cache')
    spy = QSignalSpy(service.cache_cleared)
    try:
        service.get(item)
        wait_until(qapp, lambda: cache_key(item) in service.memory)
        service.set_paused(True)
        assert service.clear_cache()
        wait_until(qapp, lambda: spy.count() == 1)
        assert spy.at(0)[0] is True
        assert not service.memory and not list(service.cache.glob('*.png'))
    finally:
        service.shutdown()
        wait_until(qapp, service.is_idle)

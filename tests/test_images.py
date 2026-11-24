from pathlib import Path

from PIL import Image
from PySide6.QtCore import QEventLoop, QTimer

from app.core.scanner import scan_library
from app.services.images import read_image
from app.services.thumbnail_service import ThumbnailService, cache_key


def wait_until(qapp, predicate, timeout=10000):
    from time import monotonic
    from PySide6.QtTest import QTest
    deadline = monotonic() + timeout / 1000
    while not predicate() and monotonic() < deadline:
        qapp.processEvents()
        QTest.qWait(10)
    qapp.processEvents()
    assert predicate(), "Timed out waiting for Qt worker"


def test_exif_orientation_and_aspect_ratio(tmp_path):
    image = Image.new("RGB", (80, 40), "red")
    exif = Image.Exif()
    exif[274] = 6
    path = tmp_path / "IMG20260101000000.jpg"
    image.save(path, exif=exif)
    decoded = read_image(path)
    assert (decoded.width(), decoded.height()) == (40, 80)
    thumbnail = read_image(path, 20)
    assert (thumbnail.width(), thumbnail.height()) == (10, 20)


def test_cached_thumbnail_and_invalidation(tmp_path, qapp, monkeypatch):
    original = tmp_path / "originals"
    original.mkdir()
    path = original / "IMG20260101000000.jpg"
    Image.new("RGB", (160, 80), "red").save(path)
    entry = scan_library(original).items[0]
    cache = tmp_path / "cache"
    service = ThumbnailService(cache)
    try:
        assert service.get(entry)[0] is None
        wait_until(qapp, lambda: cache_key(entry) in service.memory)
        pixmap, error = service.get(entry)
        assert not error and not pixmap.isNull()
        assert (cache / f"{cache_key(entry)}.png").is_file()
        assert len(list(original.iterdir())) == 1
        # Prove a new service uses the disk cache without decoding the original again.
        import app.services.thumbnail_service as module
        monkeypatch.setattr(module, "read_image", lambda *args: (_ for _ in ()).throw(AssertionError("cache miss")))
        other = ThumbnailService(cache)
        try:
            other.get(entry)
            wait_until(qapp, lambda: cache_key(entry) in other.memory)
            assert not other.get(entry)[1]
        finally:
            other.shutdown()
        Image.new("RGB", (200, 100), "blue").save(path)
        updated = scan_library(original).items[0]
        assert cache_key(updated) != cache_key(entry)
    finally:
        service.shutdown()


def test_corrupt_photo_is_reported_without_stopping_others(tmp_path, qapp):
    (tmp_path / "broken.jpg").write_bytes(b"broken")
    Image.new("RGB", (40, 20), "blue").save(tmp_path / "IMG20260101000000.png")
    items = scan_library(tmp_path).items
    service = ThumbnailService(tmp_path / "cache")
    try:
        for item in items:
            service.get(item)
        wait_until(qapp, lambda: len(service.memory) == 2)
        for item in items:
            pixmap, error = service.get(item)
            assert bool(error) == (item.path.name == "broken.jpg")
    finally:
        service.shutdown()


def test_disconnect_thumbnail_error(tmp_path, qapp):
    path = tmp_path / "IMG20260101000000.jpg"
    Image.new("RGB", (40, 20), "blue").save(path)
    item = scan_library(tmp_path).items[0]
    path.unlink()
    service = ThumbnailService(tmp_path / "cache")
    try:
        service.get(item)
        wait_until(qapp, lambda: cache_key(item) in service.memory)
        assert service.get(item)[1]
    finally:
        service.shutdown()


def test_corrupt_disk_cache_is_rebuilt(tmp_path, qapp):
    path = tmp_path / "IMG20260101000000.jpg"
    Image.new("RGB", (60, 30), "green").save(path)
    item = scan_library(tmp_path).items[0]
    cache = tmp_path / "cache"
    cache.mkdir()
    target = cache / f"{cache_key(item)}.png"
    target.write_bytes(b"corrupt cached data")
    service = ThumbnailService(cache)
    try:
        service.get(item)
        wait_until(qapp, lambda: cache_key(item) in service.memory)
        assert not service.get(item)[1]
        assert target.read_bytes().startswith(b"\x89PNG")
    finally:
        service.shutdown()


def test_refresh_can_retry_previously_missing_photo(tmp_path, qapp):
    path = tmp_path / "IMG20260101000000.jpg"
    Image.new("RGB", (60, 30), "green").save(path)
    item = scan_library(tmp_path).items[0]
    data = path.read_bytes()
    path.unlink()
    service = ThumbnailService(tmp_path / "cache")
    try:
        service.get(item)
        wait_until(qapp, lambda: cache_key(item) in service.memory)
        assert service.get(item)[1]
        path.write_bytes(data)
        import os
        os.utime(path, ns=(item.mtime_ns, item.mtime_ns))
        service.clear_errors()
        service.get(item)
        wait_until(qapp, lambda: cache_key(item) in service.memory)
        assert not service.get(item)[1]
    finally:
        service.shutdown()


def test_stale_index_uses_current_photo_and_current_disk_cache(tmp_path, qapp):
    import hashlib
    import os
    original = tmp_path / "originals"
    original.mkdir()
    path = original / "IMG20261016103000.jpg"
    Image.new("RGB", (120, 60), "red").save(path)
    stale = scan_library(original).items[0]
    cache = tmp_path / "cache"
    service = ThumbnailService(cache)
    service.get(stale)
    wait_until(qapp, lambda: cache_key(stale) in service.memory)
    service.shutdown()
    Image.new("RGB", (160, 80), "blue").save(path)
    os.utime(path, ns=(stale.mtime_ns + 2_000_000_000, stale.mtime_ns + 2_000_000_000))
    current = scan_library(original).items[0]
    before = (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
    service = ThumbnailService(cache)
    try:
        service.get(stale)
        wait_until(qapp, lambda: cache_key(stale) in service.memory)
        pixmap, error = service.get(stale)
        assert not error and not pixmap.isNull()
        pixel = pixmap.toImage().pixelColor(10, 10)
        assert pixel.blue() > 200 and pixel.red() < 30
        assert (cache / f"{cache_key(current)}.png").is_file()
        assert cache_key(current) != cache_key(stale)
        assert (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()) == before
    finally:
        service.shutdown()

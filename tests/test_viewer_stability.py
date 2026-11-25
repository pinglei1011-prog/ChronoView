"""Independent synthetic data: cancellation, raster lifetime and full-detail loading."""
import gc
import hashlib
from pathlib import Path
from threading import Event
from time import monotonic

from PIL import Image
from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage

from app.core.scanner import scan_library
from app.services.images import ImageReadCancelled, read_image
from app.ui.photo_viewer import PhotoViewer, has_pending_decodes, image_decoder
from tests.test_images import wait_until


def make_photos(folder):
    folder.mkdir()
    for i, color in enumerate(("#de9b6e", "#70a5cb"), start=1):
        Image.new("RGB", (180, 120), color).save(folder / f"IMG2026010{i}100000.png")
    return scan_library(folder).items


def test_cancelled_read_and_owned_rgb_buffer(tmp_path):
    path = tmp_path / "odd-width.png"
    Image.new("RGB", (7, 11), "#137bce").save(path)
    stopped = Event()
    stopped.set()
    import pytest
    with pytest.raises(ImageReadCancelled):
        read_image(path, cancel=stopped)
    image = read_image(path)
    gc.collect()
    garbage = [bytes(10000) for _ in range(100)]
    assert image.format() == QImage.Format.Format_RGB888
    assert image.pixelColor(6, 10).name() == "#137bce"
    assert len(garbage) == 100


def test_extension_mismatch_alpha_and_exif_preview(tmp_path):
    wrong_extension = tmp_path / "actually-png.heic"
    Image.new("RGBA", (35, 21), (16, 32, 64, 99)).save(wrong_extension, format="PNG")
    assert read_image(wrong_extension).pixelColor(5, 5).alpha() == 99
    photo = tmp_path / "oriented.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (80, 40), "blue").save(photo, exif=exif)
    preview = read_image(photo, 20)
    assert (preview.width(), preview.height()) == (10, 20)
    assert (preview.text("chronoview.original_width"), preview.text("chronoview.original_height")) == ("40", "80")


def test_slow_decode_close_is_nonblocking_and_old_results_do_not_revive_viewer(tmp_path, qapp, monkeypatch):
    import app.ui.photo_viewer as module
    items = make_photos(tmp_path / "photos")
    entered, release = Event(), Event()
    original = module.read_image

    def delayed(path, edge=None, cancel=None):
        entered.set()
        assert release.wait(5), "Test decoder release timed out"
        return original(path, edge, cancel=cancel)

    monkeypatch.setattr(module, "read_image", delayed)
    viewer = PhotoViewer(items, 0)
    viewer.show()
    try:
        wait_until(qapp, entered.is_set)
        ticked = []
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: ticked.append(True))
        timer.start(10)
        started = monotonic()
        viewer.close()
        assert monotonic() - started < .2
        wait_until(qapp, lambda: bool(ticked))
        assert has_pending_decodes()
        assert not viewer.isVisible() and not viewer.view.scene().items()
        release.set()
        wait_until(qapp, lambda: not has_pending_decodes())
        assert not viewer.isVisible() and not viewer.view.scene().items()
    finally:
        release.set()
        viewer.close()
        wait_until(qapp, lambda: not has_pending_decodes())


def test_500_switches_coalesce_while_decode_is_blocked(tmp_path, qapp, monkeypatch):
    import app.ui.photo_viewer as module
    items = make_photos(tmp_path / "photos")
    entered, release = Event(), Event()
    calls = []
    original = module.read_image

    def delayed(path, edge=None, cancel=None):
        calls.append(path)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        return original(path, edge, cancel=cancel)

    monkeypatch.setattr(module, "read_image", delayed)
    viewer = PhotoViewer(items, 0)
    viewer.show()
    try:
        wait_until(qapp, entered.is_set)
        for index in range(500):
            viewer.position = index % 2
            viewer.load()
        assert image_decoder().pool.maxThreadCount() == 1
        assert len(image_decoder().pending) == 1 and len(viewer.jobs) == 1
        release.set()
        wait_until(qapp, lambda: viewer.pages.currentWidget() is viewer.view and not has_pending_decodes())
        assert len(calls) == 2, "Superseded photos must not be decoded"
        color = viewer.view.scene().items()[0].pixmap().toImage().pixelColor(10, 10)
        assert color.name() == "#70a5cb"
    finally:
        release.set()
        viewer.close()
        wait_until(qapp, lambda: not has_pending_decodes())


def test_100_viewer_cycles_share_one_decoder_without_pending_owner_leaks(tmp_path, qapp, monkeypatch):
    import app.ui.photo_viewer as module
    items = make_photos(tmp_path / "photos")
    entered, release = Event(), Event()
    original = module.read_image

    def delayed(path, edge=None, cancel=None):
        entered.set()
        assert release.wait(10)
        return original(path, edge, cancel=cancel)

    monkeypatch.setattr(module, "read_image", delayed)
    first = PhotoViewer(items, 0)
    first.show()
    try:
        wait_until(qapp, entered.is_set)
        first.close()
        for _ in range(100):
            viewer = PhotoViewer(items, 1)
            viewer.show()
            viewer.close()
            viewer.deleteLater()
            qapp.processEvents()
        assert not image_decoder().pending
        release.set()
        wait_until(qapp, lambda: not has_pending_decodes())
    finally:
        release.set()
        first.close()
        wait_until(qapp, lambda: not has_pending_decodes())


def test_high_resolution_preview_then_original_retains_details_and_hash(tmp_path, qapp):
    path = tmp_path / "IMG20260101100000.jpg"
    image = Image.new("RGB", (6000, 4000), "#8395ad")
    image.putpixel((3000, 2000), (255, 0, 0))
    image.save(path, quality=95)
    image.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    viewer = PhotoViewer(scan_library(tmp_path).items, 0)
    viewer.show()
    try:
        wait_until(qapp, lambda: viewer.pages.currentWidget() is viewer.view and not has_pending_decodes())
        assert not viewer._is_full
        preview = viewer.view.scene().items()[0].pixmap()
        assert max(preview.width(), preview.height()) <= viewer._preview_edge
        assert viewer.view.sceneRect().width() == 6000
        viewer.view.actual()
        wait_until(qapp, lambda: viewer._is_full and not has_pending_decodes())
        full = viewer.view.scene().items()[0].pixmap()
        assert (full.width(), full.height()) == (6000, 4000)
        assert viewer.view.transform().m11() == 1
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    finally:
        viewer.close()
        wait_until(qapp, lambda: not has_pending_decodes())

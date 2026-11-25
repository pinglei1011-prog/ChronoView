from __future__ import annotations

from pathlib import Path
from threading import Event

from PIL import Image, ImageOps, UnidentifiedImageError
from PySide6.QtGui import QImage


try:
    import pillow_heif
except ImportError:
    HEIF_AVAILABLE = False
else:
    pillow_heif.register_heif_opener()
    HEIF_AVAILABLE = True


class ImageReadCancelled(Exception):
    """A superseded decode; never present cancellation as a corrupt photo."""


def read_image(path: Path, edge: int | None = None, cancel: Event | None = None) -> QImage:
    def check_cancel():
        if cancel is not None and cancel.is_set():
            raise ImageReadCancelled()

    check_cancel()
    # Pillow opens originals read-only; no metadata is ever saved back.
    try:
        source = Image.open(path)
    except UnidentifiedImageError as exc:
        if path.suffix.lower() in {".heic", ".heif"} and not HEIF_AVAILABLE:
            raise ValueError("HEIC / HEIF 需要可选的 pillow-heif 解码器，详见 README。") from exc
        raise
    with source:
        original_width, original_height = source.size
        orientation = source.getexif().get(274, 1)
        if orientation in (5, 6, 7, 8):
            original_width, original_height = original_height, original_width
        if edge:
            scale = min(1.0, edge / max(source.size))
            draft_size = tuple(max(1, int(dimension * scale)) for dimension in source.size)
            source.draft("RGB", draft_size)
        check_cancel()
        # Downsample before EXIF transpose: transpose otherwise duplicates the
        # full decoded raster even when the user only needs a screen preview.
        if edge:
            source.thumbnail((edge, edge), Image.Resampling.LANCZOS)
        check_cancel()
        ImageOps.exif_transpose(source, in_place=True)
        check_cancel()
        mode = "RGBA" if "A" in source.getbands() or "transparency" in source.info else "RGB"
        image = source if source.mode == mode else source.convert(mode)
        try:
            channels = 4 if mode == "RGBA" else 3
            fmt = QImage.Format.Format_RGBA8888 if channels == 4 else QImage.Format.Format_RGB888
            data = image.tobytes("raw", mode)
            check_cancel()
            # Own the Qt raster independently of Pillow/Python buffers. RGB
            # photos no longer incur a full RGBA conversion or EXIF copy.
            result = QImage(data, image.width, image.height, image.width * channels, fmt).copy()
            result.setText("chronoview.original_width", str(original_width))
            result.setText("chronoview.original_height", str(original_height))
            check_cancel()
            return result
        finally:
            if image is not source:
                image.close()


def image_error_message(error: Exception) -> str:
    if isinstance(error, MemoryError):
        return "照片过大，当前可用内存不足。请关闭其他查看器后重试。"
    if isinstance(error, Image.DecompressionBombError):
        return "照片尺寸超出安全解码范围，无法在当前环境中读取。"
    if isinstance(error, FileNotFoundError):
        return "原文件不存在或移动硬盘未连接。请检查硬盘，盘符变化后重新选择文件夹。"
    if isinstance(error, PermissionError):
        return "没有读取此文件的权限，或文件正被其他程序占用。"
    if isinstance(error, UnidentifiedImageError):
        return "无法识别此照片的内容，文件可能损坏或实际格式不受支持。"
    return str(error)

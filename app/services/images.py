from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from PySide6.QtGui import QImage


try:
    import pillow_heif
except ImportError:
    HEIF_AVAILABLE = False
else:
    pillow_heif.register_heif_opener()
    HEIF_AVAILABLE = True


def read_image(path: Path, edge: int | None = None) -> QImage:
    if path.suffix.lower() in {".heic", ".heif"} and not HEIF_AVAILABLE:
        raise ValueError("HEIC / HEIF 需要可选的 pillow-heif 解码器，详见 README。")
    # Pillow opens originals read-only; no metadata is ever saved back.
    with Image.open(path) as source:
        if edge:
            source.draft("RGB", (edge, edge))
        image = ImageOps.exif_transpose(source)
        if edge:
            image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
        image = image.convert("RGBA")
        data = image.tobytes("raw", "RGBA")
        return QImage(data, image.width, image.height, image.width * 4,
                      QImage.Format.Format_RGBA8888).copy()


def image_error_message(error: Exception) -> str:
    if isinstance(error, FileNotFoundError):
        return "原文件不存在或移动硬盘未连接。请检查硬盘，盘符变化后重新选择文件夹。"
    if isinstance(error, PermissionError):
        return "没有读取此文件的权限，或文件正被其他程序占用。"
    if isinstance(error, UnidentifiedImageError):
        return "无法识别此照片的内容，文件可能损坏或实际格式不受支持。"
    return str(error)

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps
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

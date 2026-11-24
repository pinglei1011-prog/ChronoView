from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".heif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}


@dataclass(frozen=True, slots=True)
class MediaItem:
    path: Path
    kind: str
    taken_at: datetime | None
    size: int
    mtime_ns: int

    @property
    def date_label(self) -> str:
        return self.taken_at.strftime("%Y年%m月%d日  %H:%M:%S") if self.taken_at else "未识别日期"


def sort_items(items: list[MediaItem], newest_first: bool = True) -> list[MediaItem]:
    # Unknown dates stay at the end in both directions. Ties always use full paths.
    ordered = sorted(items, key=lambda item: (str(item.path).casefold(), str(item.path)))
    known = [item for item in ordered if item.taken_at is not None]
    unknown = [item for item in ordered if item.taken_at is None]
    return sorted(known, key=lambda item: item.taken_at, reverse=newest_first) + unknown


def filter_items(items: list[MediaItem], year: int | None = None,
                 month: int | None = None, unknown: bool = False) -> list[MediaItem]:
    if unknown:
        return [item for item in items if item.taken_at is None]
    return [item for item in items if
            (year is None or (item.taken_at is not None and item.taken_at.year == year))
            and (month is None or (item.taken_at is not None and item.taken_at.month == month))]


def calendar_counts(items: list[MediaItem]) -> Counter[tuple[int, int]]:
    return Counter((item.taken_at.year, item.taken_at.month)
                   for item in items if item.taken_at is not None)

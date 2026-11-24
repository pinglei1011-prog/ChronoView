"""Calendar albums derived solely from filename dates, without reading media."""
from dataclasses import dataclass

from app.core.library import MediaItem


@dataclass(frozen=True, slots=True)
class Album:
    route: tuple
    title: str
    photos: int
    videos: int
    months: int = 0

    @property
    def subtitle(self):
        return f"{self.photos:,} 张照片 · {self.videos:,} 个视频"


def calendar_albums(items: list[MediaItem], year: int | None = None) -> list[Album]:
    groups: dict[int | None, list[MediaItem]] = {}
    for item in items:
        date = item.taken_at
        if year is not None and (date is None or date.year != year):
            continue
        key = (date.year if year is None else date.month) if date else None
        groups.setdefault(key, []).append(item)
    keys = sorted(key for key in groups if key is not None)
    if None in groups:
        keys.append(None)
    albums = []
    for key in keys:
        group = groups[key]
        photos = sum(item.kind == "image" for item in group)
        route = ("unknown",) if key is None else (("year", key) if year is None else ("month", year, key))
        title = "未识别日期" if key is None else (f"{key}年" if year is None else f"{key}月")
        months = len({item.taken_at.month for item in group if item.taken_at})
        albums.append(Album(route, title, photos, len(group) - photos, months))
    return albums

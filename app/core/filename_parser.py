import re
from datetime import datetime
from pathlib import Path


_PATTERN = re.compile(r"(?:IMG|VID)([0-9]{14})", re.IGNORECASE | re.ASCII)


def parse_filename(path: str | Path) -> datetime | None:
    """Strict IMG/VID + 14 digits; neither folder names nor filesystem times count."""
    match = _PATTERN.fullmatch(Path(path).stem)
    if match is None:
        return None
    try:
        return datetime.strptime(match[1], "%Y%m%d%H%M%S")
    except ValueError:
        return None

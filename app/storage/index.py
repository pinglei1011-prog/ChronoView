"""Atomic, per-library local snapshots. Never store a database on the source SSD."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from app.core.library import MediaItem


class LibraryIndex:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE IF NOT EXISTS libraries (root TEXT PRIMARY KEY, scanned_at TEXT NOT NULL)")
        db.execute("""CREATE TABLE IF NOT EXISTS media (
            root TEXT NOT NULL, path TEXT NOT NULL, kind TEXT NOT NULL,
            taken_at TEXT, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
            PRIMARY KEY(root, path))""")
        try:
            with db:
                yield db
        finally:
            db.close()

    def load(self, root: Path) -> list[MediaItem] | None:
        if not self.path.exists():
            return None
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM libraries WHERE root=?", (str(root),)).fetchone():
                return None
            return [MediaItem(Path(path), kind, datetime.fromisoformat(date) if date else None, size, mtime)
                    for path, kind, date, size, mtime in db.execute(
                        "SELECT path,kind,taken_at,size,mtime_ns FROM media WHERE root=?", (str(root),))]

    def save(self, root: Path, items: list[MediaItem]):
        # Reconcile only after a complete successful traversal. No partial/cancelled replacement.
        with self.connect() as db:
            db.execute("CREATE TEMP TABLE seen (path TEXT PRIMARY KEY)")
            db.executemany("INSERT INTO seen VALUES (?)", ((str(item.path),) for item in items))
            db.executemany("""INSERT INTO media VALUES (?,?,?,?,?,?)
                ON CONFLICT(root,path) DO UPDATE SET kind=excluded.kind,
                taken_at=excluded.taken_at,size=excluded.size,mtime_ns=excluded.mtime_ns
                WHERE media.kind!=excluded.kind OR media.taken_at IS NOT excluded.taken_at
                   OR media.size!=excluded.size OR media.mtime_ns!=excluded.mtime_ns""",
                ((str(root), str(item.path), item.kind, item.taken_at.isoformat() if item.taken_at else None,
                  item.size, item.mtime_ns) for item in items))
            db.execute("DELETE FROM media WHERE root=? AND path NOT IN (SELECT path FROM seen)", (str(root),))
            db.execute("INSERT OR REPLACE INTO libraries VALUES (?,?)", (str(root), datetime.now().isoformat()))

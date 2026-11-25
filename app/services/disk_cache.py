"""Owned, bounded thumbnail cache. Only hash-named files inside this directory are managed."""
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import threading
import time
import uuid

from PySide6.QtCore import QLockFile
from PySide6.QtGui import QImage

KEY = re.compile(r"^[0-9a-f]{64}$")
MANAGED = re.compile(r"^([0-9a-f]{64})\.(png|json)$")
TEMP = re.compile(r"^[0-9a-f]{64}\.[A-Za-z0-9.-]+\.tmp$")
MARKER_TEMP = re.compile(r"^\.chronoview-marker\.[0-9a-f]{32}\.tmp$")
DEFAULT_LIMIT = 5 * 1024 ** 3


class DiskThumbnailCache:
    def __init__(self, root: Path, limit_bytes=DEFAULT_LIMIT, max_age_days=90, reserve_bytes=64 * 1024 ** 2):
        self.root = Path(root).absolute()
        self.limit_bytes = max(0, int(limit_bytes))
        self.max_age = max_age_days * 86400
        self.reserve_bytes = reserve_bytes
        self._mutex = threading.RLock()
        self._initialized = False
        self._last_sweep = 0.0
        self._owned = False
        self.enabled = True
        self.epoch = uuid.uuid4().hex
        self.last_error = ""

    def _prepare(self):
        if self._owned or not self.enabled:
            return self.enabled
        try:
            if self.root.is_symlink() or self.root.is_junction():
                raise OSError("缓存目录不能是符号链接或目录联接")
            self.root.mkdir(parents=True, exist_ok=True)
            self.root = self.root.resolve()
            with self._locked() as acquired:
                if not acquired:
                    return
                marker = self.root / ".chronoview-cache.json"
                if not marker.exists():
                    # Adopt legacy hash-only thumbnail directories, never an arbitrary photo directory.
                    if any(not self._recognized(p.name) for p in self.root.iterdir()):
                        raise OSError("缓存目录包含非缓存文件，已禁用磁盘缓存")
                    self.epoch = uuid.uuid4().hex
                    self._write_marker()
                self._read_marker()
                self._owned = True
                return True
        except (OSError, ValueError, RuntimeError) as exc:
            self.enabled = False
            self.last_error = str(exc)
            return False

    @staticmethod
    def _recognized(name):
        return bool(MANAGED.fullmatch(name) or TEMP.fullmatch(name) or MARKER_TEMP.fullmatch(name) or name in
                    {".chronoview-cache.lock", ".chronoview-cache.json", ".cache-index.sqlite3",
                     ".cache-index.sqlite3-wal", ".cache-index.sqlite3-shm"})

    def _safe(self, path):
        return path.parent == self.root and not path.is_symlink() and not path.is_junction()

    @contextmanager
    def _locked(self):
        with self._mutex:
            if self.root.is_symlink() or self.root.is_junction():
                raise OSError("缓存目录已被替换为链接，已停止缓存操作")
            lock = QLockFile(str(self.root / ".chronoview-cache.lock"))
            lock.setStaleLockTime(30000)
            acquired = lock.tryLock(100)
            try:
                yield acquired
            finally:
                if acquired:
                    lock.unlock()

    def _read_marker(self):
        marker = self.root / ".chronoview-cache.json"
        if not self._safe(marker):
            raise OSError("缓存所有权标记不可访问")
        value = json.loads(marker.read_text(encoding="utf-8"))
        if (not isinstance(value, dict) or value.get("owner") != "ChronoView thumbnails"
                or value.get("schema") != 1 or not re.fullmatch(r'[0-9a-f]{32}', str(value.get('epoch', '')))):
            raise OSError("缓存目录所有权标记无效")
        self.epoch = value["epoch"]

    def _write_marker(self):
        temporary = self.root / f'.chronoview-marker.{uuid.uuid4().hex}.tmp'
        marker = self.root / '.chronoview-cache.json'
        if not self._safe(temporary) or not self._safe(marker):
            raise OSError('缓存标记路径无效')
        try:
            with temporary.open('w', encoding='utf-8') as output:
                json.dump(dict(owner='ChronoView thumbnails', schema=1, epoch=self.epoch), output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, marker)
        finally:
            temporary.unlink(missing_ok=True)

    @contextmanager
    def _db(self):
        path = self.root / ".cache-index.sqlite3"
        if not self._safe(path):
            raise OSError("缓存索引路径无效")
        db = sqlite3.connect(path, timeout=.2)
        try:
            db.execute('PRAGMA secure_delete=ON')
            db.executescript("""CREATE TABLE IF NOT EXISTS entries (
                key TEXT PRIMARY KEY, size INTEGER NOT NULL, accessed REAL NOT NULL, source_id TEXT);
                CREATE INDEX IF NOT EXISTS cache_lru ON entries(accessed);
                CREATE INDEX IF NOT EXISTS cache_source ON entries(source_id);
                CREATE TABLE IF NOT EXISTS totals (id INTEGER PRIMARY KEY, bytes INTEGER NOT NULL);
                INSERT OR IGNORE INTO totals VALUES (1,0);
                CREATE TRIGGER IF NOT EXISTS cache_added AFTER INSERT ON entries BEGIN
                  UPDATE totals SET bytes=bytes+new.size WHERE id=1; END;
                CREATE TRIGGER IF NOT EXISTS cache_removed AFTER DELETE ON entries BEGIN
                  UPDATE totals SET bytes=bytes-old.size WHERE id=1; END;
                CREATE TRIGGER IF NOT EXISTS cache_resized AFTER UPDATE OF size ON entries BEGIN
                  UPDATE totals SET bytes=bytes+new.size-old.size WHERE id=1; END;""")
            with db:
                yield db
        except sqlite3.DatabaseError as exc:
            code = getattr(exc, 'sqlite_errorcode', 0) & 0xff
            if code in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB):
                db.close()
                db = None
                for suffix in ('', '-wal', '-shm', '-journal'):
                    candidate = self.root / ('.cache-index.sqlite3' + suffix)
                    if self._safe(candidate):
                        candidate.unlink(missing_ok=True)
                self._initialized = False
                self._last_sweep = 0
            raise
        finally:
            if db is not None:
                db.close()

    def _remove(self, key, db):
        for suffix in (".png", ".json"):
            p = self.root / (key + suffix)
            if self._safe(p):
                p.unlink(missing_ok=True)
        db.execute("DELETE FROM entries WHERE key=?", (key,))

    def _sweep(self, db, force=False):
        now = time.time()
        if self._initialized and not force and time.monotonic() - self._last_sweep < 300:
            return
        self._last_sweep = time.monotonic()
        # Reconcile interrupted writes, legacy entries and externally removed cache files.
        seen = set()
        for p in self.root.iterdir():
            if not self._safe(p) or not p.is_file():
                continue
            match = MANAGED.fullmatch(p.name)
            if TEMP.fullmatch(p.name) or MARKER_TEMP.fullmatch(p.name):
                if now - p.stat().st_mtime > 3600:
                    p.unlink(missing_ok=True)
            elif match and match[2] == "png":
                key = match[1]
                try:
                    with p.open("rb") as f:
                        valid = f.read(8) == b"\x89PNG\r\n\x1a\n"
                    if not valid or now - p.stat().st_mtime > self.max_age:
                        self._remove(key, db)
                        continue
                    size = p.stat().st_size
                    meta = p.with_suffix('.json')
                    source_id = None
                    if meta.is_file() and self._safe(meta):
                        try:
                            value = json.loads(meta.read_text(encoding='utf-8'))
                            if not isinstance(value, dict):
                                raise ValueError('Invalid cache metadata')
                            source_id = value.get('source_id')
                            if source_id is not None and not isinstance(source_id, str):
                                source_id = None
                            size += meta.stat().st_size
                        except (OSError, ValueError, TypeError):
                            meta.unlink(missing_ok=True)
                    seen.add(key)
                    db.execute("INSERT INTO entries VALUES (?,?,?,?) ON CONFLICT(key) DO UPDATE SET size=excluded.size",
                               (key, size, p.stat().st_mtime, source_id))
                except OSError:
                    continue
            elif match and match[2] == "json" and not p.with_suffix('.png').exists():
                p.unlink(missing_ok=True)
        for (key,) in list(db.execute("SELECT key FROM entries")):
            if key not in seen:
                db.execute("DELETE FROM entries WHERE key=?", (key,))
        self._initialized = True

    def _prune(self, db, leave_bytes=None):
        maximum = self.limit_bytes if leave_bytes is None else max(0, leave_bytes)
        total = db.execute("SELECT bytes FROM totals WHERE id=1").fetchone()[0]
        if total <= maximum:
            return
        for key, size in list(db.execute("SELECT key,size FROM entries ORDER BY accessed")):
            self._remove(key, db)
            total -= size
            if total <= maximum:
                break

    def read(self, key):
        if not KEY.fullmatch(key) or not self._prepare():
            return QImage(), 0.0
        try:
            with self._locked() as acquired:
                if not acquired:
                    return QImage(), 0.0
                self._read_marker()
                with self._db() as db:
                    self._sweep(db)
                    p = self.root / (key + ".png")
                    image = QImage(str(p)) if self._safe(p) and p.exists() else QImage()
                    if image.isNull():
                        self._remove(key, db)
                        return image, 0.0
                    now = time.time()
                    db.execute("UPDATE entries SET accessed=? WHERE key=?", (now, key))
                    if now - p.stat().st_mtime > 30:
                        os.utime(p, (now, now))
                    duration = 0.0
                    meta = p.with_suffix('.json')
                    if self._safe(meta) and meta.exists():
                        try:
                            value = json.loads(meta.read_text(encoding='utf-8'))
                            if not isinstance(value, dict): raise ValueError('Invalid cache metadata')
                            duration = float(value.get('duration', 0))
                            if not math.isfinite(duration) or duration < 0: duration = 0.0
                        except (OSError, ValueError, TypeError): pass
                    self._prune(db)
                    return image, duration
        except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
            self.last_error = str(exc)
            return QImage(), 0.0

    def write(self, key, image, duration=0.0, source_id=None, epoch=None):
        if self.limit_bytes <= 0 or not KEY.fullmatch(key) or image.isNull() or not self._prepare():
            return False
        temporary = []
        try:
            with self._locked() as acquired:
                if not acquired:
                    return False
                self._read_marker()
                if epoch is not None and epoch != self.epoch:
                    return False
                with self._db() as db:
                    self._sweep(db)
                    if shutil.disk_usage(self.root).free < self.reserve_bytes:
                        self._prune(db, 0)
                        if shutil.disk_usage(self.root).free < self.reserve_bytes:
                            return False
                    nonce = uuid.uuid4().hex
                    png = self.root / (key + ".png")
                    meta = png.with_suffix('.json')
                    temporary = [self.root / f"{key}.{nonce}.tmp", self.root / f"{key}.{nonce}.json.tmp"]
                    if not self._safe(png) or not self._safe(meta):
                        return False
                    if not image.save(str(temporary[0]), 'PNG'):
                        return False
                    temporary[1].write_text(json.dumps(dict(duration=float(duration), source_id=source_id)), encoding='utf-8')
                    if source_id:
                        for (old,) in list(db.execute("SELECT key FROM entries WHERE source_id=? AND key!=?", (source_id, key))):
                            self._remove(old, db)
                    os.replace(temporary[0], png)
                    os.replace(temporary[1], meta)
                    size = png.stat().st_size + meta.stat().st_size
                    db.execute("INSERT INTO entries VALUES (?,?,?,?) ON CONFLICT(key) DO UPDATE SET size=excluded.size,accessed=excluded.accessed,source_id=excluded.source_id",
                               (key, size, time.time(), source_id))
                    self._prune(db)
                    return png.exists()
        except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
            self.last_error = str(exc)
            return False
        finally:
            for p in temporary:
                if self._safe(p):
                    try: p.unlink(missing_ok=True)
                    except OSError: pass

    def clear(self):
        if not self._prepare():
            return False, "缓存目录不可用，未执行清理"
        try:
            with self._locked() as acquired:
                if not acquired:
                    return False, "缓存正在使用，请稍后重试"
                self._read_marker()
                self.epoch = uuid.uuid4().hex
                self._write_marker()
                with self._db() as db:
                    for p in self.root.iterdir():
                        if self._safe(p) and p.is_file() and (MANAGED.fullmatch(p.name) or TEMP.fullmatch(p.name) or MARKER_TEMP.fullmatch(p.name)):
                            p.unlink(missing_ok=True)
                    db.execute('DELETE FROM entries')
                    db.commit()
                    db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                return True, "缩略图缓存已清除"
        except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
            self.last_error = str(exc)
            return False, "缓存清理失败，请检查磁盘空间或权限"

    def info(self):
        result = dict(bytes=0, entries=0, limit_bytes=self.limit_bytes, enabled=self.enabled)
        if not self._prepare():
            result['enabled'] = False
            return result
        try:
            with self._locked() as acquired:
                if acquired:
                    self._read_marker()
                    with self._db() as db:
                        self._sweep(db)
                        self._prune(db)
                        result['bytes'], result['entries'] = db.execute('SELECT COALESCE(SUM(size),0),COUNT(*) FROM entries').fetchone()
        except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
            self.last_error = str(exc)
        return result

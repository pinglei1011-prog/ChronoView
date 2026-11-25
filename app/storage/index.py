"""Transactional, volume-aware snapshots stored only in the application's data area."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import Event
import json
import os
import re
import sqlite3
import stat
import uuid

from app.core.library import MediaItem
from app.storage.identity import LibraryIdentity, library_identity, normalized_root


class IndexGenerationChanged(RuntimeError):
    pass


class LibraryIdentityChanged(RuntimeError):
    pass


class IndexSchemaError(RuntimeError):
    pass


_UNSET = object()


class LibraryIndex:
    def __init__(self, path: Path, identity_provider=None):
        self.path = Path(path)
        self.identity_provider = identity_provider or library_identity
        self.warning = ""
        self.loaded_identity = None

    @contextmanager
    def _gate(self):
        # A separate SQLite lock survives neither process termination nor a
        # crash. It serializes schema/recovery/clear across current instances.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        gate = sqlite3.connect(str(self.path) + ".gate.sqlite3", timeout=2)
        try:
            gate.execute("CREATE TABLE IF NOT EXISTS gate (id INTEGER PRIMARY KEY)")
            gate.execute("BEGIN IMMEDIATE")
            yield
        except sqlite3.OperationalError as exc:
            if getattr(exc, "sqlite_errorcode", 0) & 255 in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise RuntimeError("本地索引正在被其他窗口使用，请稍后重试。") from exc
            raise
        finally:
            gate.rollback()
            gate.close()

    def _migrate(self, db):
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version > 2:
            raise RuntimeError("本地索引由更高版本创建，请使用对应版本或清除本地索引。")
        if version == 2:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"libraries", "media", "libraries_v2", "media_v2", "aliases_v2", "metadata_v2"} <= tables:
                raise IndexSchemaError("本地索引表不完整。")
            return
        db.execute("BEGIN IMMEDIATE")
        try:
            # Preserve v1 tables without guessing which physical disk owns old
            # absolute paths. The first complete online scan safely imports them.
            db.execute("CREATE TABLE IF NOT EXISTS libraries (root TEXT PRIMARY KEY, scanned_at TEXT NOT NULL)")
            db.execute("""CREATE TABLE IF NOT EXISTS media (
                root TEXT NOT NULL,path TEXT NOT NULL,kind TEXT NOT NULL,taken_at TEXT,
                size INTEGER NOT NULL,mtime_ns INTEGER NOT NULL,PRIMARY KEY(root,path))""")
            db.execute("""CREATE TABLE libraries_v2 (
                id INTEGER PRIMARY KEY,identity_key TEXT UNIQUE NOT NULL,
                identity_json TEXT,root TEXT NOT NULL,scanned_at TEXT NOT NULL)""")
            db.execute("""CREATE TABLE media_v2 (
                library_id INTEGER NOT NULL,path TEXT NOT NULL,kind TEXT NOT NULL,
                taken_at TEXT,size INTEGER NOT NULL,mtime_ns INTEGER NOT NULL,
                PRIMARY KEY(library_id,path)) WITHOUT ROWID""")
            db.execute("CREATE TABLE aliases_v2 (root TEXT PRIMARY KEY,library_id INTEGER NOT NULL)")
            db.execute("CREATE TABLE metadata_v2 (key TEXT PRIMARY KEY,value TEXT NOT NULL)")
            db.execute("INSERT INTO metadata_v2 VALUES ('generation',?)", (uuid.uuid4().hex,))
            db.execute("PRAGMA user_version=2")
            db.commit()
        except BaseException:
            db.rollback()
            raise

    def _open(self):
        for attempt in range(2):
            db = None
            try:
                db = sqlite3.connect(self.path, timeout=2)
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("PRAGMA synchronous=FULL")
                self._migrate(db)
                return db
            except BaseException as exc:
                if db is not None:
                    db.close()
                if attempt or not self._is_corrupt(exc):
                    raise
                # The cross-instance gate is held. Preserve the original bad
                # bytes for recovery; never reinterpret arbitrary media as SQL.
                self._quarantine()
        raise RuntimeError("无法打开本地索引。")

    @staticmethod
    def _is_corrupt(exc):
        return (getattr(exc, "sqlite_errorcode", 0) & 255) in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB) or isinstance(exc, IndexSchemaError)

    def _quarantine(self):
        backup = self.path.with_name(self.path.name + ".corrupt-" + uuid.uuid4().hex)
        self.path.replace(backup)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(self.path) + suffix)
            if sidecar.exists():
                sidecar.replace(Path(str(backup) + suffix))
        self.warning = "本地索引损坏，已隔离原数据库并建立新索引；原始照片和视频未受影响。"

    @contextmanager
    def connect(self):
        with self._gate():
            db = self._open()
            corrupt = False
            try:
                with db:
                    yield db
            except BaseException as exc:
                corrupt = self._is_corrupt(exc)
                raise
            finally:
                db.close()
                if corrupt:
                    self._quarantine()

    def generation(self):
        with self.connect() as db:
            return db.execute("SELECT value FROM metadata_v2 WHERE key='generation'").fetchone()[0]

    @staticmethod
    def _relative(root, path):
        root_text = os.path.abspath(root)
        path_text = os.path.abspath(path)
        prefix = root_text.rstrip("\\/") + os.sep
        if not os.path.normcase(path_text).startswith(os.path.normcase(prefix)):
            raise ValueError("拒绝把照片库之外的文件写入该库的索引。")
        return path_text[len(prefix):].replace("\\", "/")

    def load(self, root: Path, cancel: Event | None = None, validate=True) -> list[MediaItem] | None:
        self.loaded_identity = None
        if cancel is not None and cancel.is_set():
            return None
        if not self.path.exists():
            return None
        root = Path(os.path.abspath(root))
        root_prefix = str(root).rstrip("\\/") + os.sep
        identity = self.identity_provider(root)
        with self.connect() as db:
            if identity is not None:
                row = db.execute("SELECT id,identity_json,identity_key FROM libraries_v2 WHERE identity_key=?", (identity.key,)).fetchone()
            else:
                # Unknown identity on an accessible disk must rescan. Offline
                # aliases are explicit last-known snapshots, not disk matches.
                if root.is_dir():
                    return None
                row = db.execute("SELECT l.id,l.identity_json,l.identity_key FROM aliases_v2 a "
                                 "JOIN libraries_v2 l ON l.id=a.library_id WHERE a.root=?", (normalized_root(root),)).fetchone()
            if row is None:
                if db.execute("SELECT 1 FROM libraries WHERE root=?", (str(root),)).fetchone():
                    self.warning = "旧版索引尚无硬盘身份，正在重新扫描以安全升级。"
                return None
            library_id = row[0]
            stored_identity = LibraryIdentity(**json.loads(row[1])) if row[1] else None
            namespace = row[2]
            items = []
            changed, missing = [], []
            online = root.is_dir()
            for relative, kind, date, size, mtime in db.execute(
                    "SELECT path,kind,taken_at,size,mtime_ns FROM media_v2 WHERE library_id=?", (library_id,)):
                if cancel is not None and cancel.is_set():
                    return None
                if (not relative or relative.startswith(("/", "\\"))
                        or (os.name == "nt" and ":" in relative)
                        or ".." in relative.replace("\\", "/").split("/")
                        or kind not in ("image", "video") or size < 0):
                    self.warning = "本地索引包含无效记录，正在重新扫描。"
                    return None
                try:
                    taken_at = datetime.fromisoformat(date) if date else None
                except ValueError:
                    self.warning = "本地索引日期记录无效，正在重新扫描。"
                    return None
                item = MediaItem(Path(root_prefix + relative), kind, taken_at, size, mtime, library_key=namespace)
                items.append(item)
                if validate and online:
                    try:
                        info = item.path.stat()
                        if not stat.S_ISREG(info.st_mode):
                            missing.append(relative)
                        elif (info.st_size, info.st_mtime_ns) != (size, mtime):
                            changed.append((info.st_size, info.st_mtime_ns, library_id, relative))
                    except (FileNotFoundError, NotADirectoryError):
                        missing.append(relative)
                    except OSError:
                        pass  # Preserve inaccessible records for a friendly tile error.
            if cancel is not None and cancel.is_set():
                return None
            # A disconnect is not mass deletion. A replacement disk is not the
            # same snapshot, even if it reused exactly the same drive/path.
            current = self.identity_provider(root)
            if identity is not None and current is not None and current != identity:
                return None
            if not root.is_dir():
                self.loaded_identity = stored_identity
                return items
            if identity is not None and current is None:
                return None
            if missing:
                db.executemany("DELETE FROM media_v2 WHERE library_id=? AND path=?", ((library_id, p) for p in missing))
            if changed:
                db.executemany("UPDATE media_v2 SET size=?,mtime_ns=? WHERE library_id=? AND path=?", changed)
            if missing or changed:
                gone = set(missing)
                updates = {p: (size, mtime) for size, mtime, _, p in changed}
                items = [MediaItem(i.path, i.kind, i.taken_at, *updates[i.path.relative_to(root).as_posix()], library_key=i.library_key)
                         if i.path.relative_to(root).as_posix() in updates else i
                         for i in items if i.path.relative_to(root).as_posix() not in gone]
            db.execute("INSERT OR REPLACE INTO aliases_v2 VALUES (?,?)", (normalized_root(root), library_id))
            self.loaded_identity = stored_identity
            return items

    def save(self, root: Path, items: list[MediaItem], expected_identity=_UNSET,
             expected_generation=None, cancel: Event | None = None):
        if cancel is not None and cancel.is_set():
            raise IndexGenerationChanged("扫描已取消，未覆盖原有索引。")
        root = Path(os.path.abspath(root))
        root_prefix = str(root).rstrip("\\/") + os.sep
        normalized_prefix = os.path.normcase(root_prefix)
        def relative(path):
            value = os.path.abspath(path)
            if not os.path.normcase(value).startswith(normalized_prefix):
                raise ValueError("拒绝把照片库之外的文件写入该库的索引。")
            return value[len(root_prefix):].replace("\\", "/")
        identity = self.identity_provider(root)
        if expected_identity is not _UNSET and identity != expected_identity:
            raise LibraryIdentityChanged("扫描期间硬盘身份发生变化，未覆盖旧索引，请重新选择照片库。")
        if identity is not None:
            key = identity.key
        else:
            namespaces = {item.library_key for item in items}
            key = (next(iter(namespaces)) if len(namespaces) == 1 and next(iter(namespaces)).startswith("unverified:")
                   else "unverified:" + uuid.uuid4().hex)
        identity_json = json.dumps(dict(volume_guid=identity.volume_guid,volume_serial=identity.volume_serial,
                                        relative_root=identity.relative_root,quality=identity.quality)) if identity else None
        with self.connect() as db:
            generation = db.execute("SELECT value FROM metadata_v2 WHERE key='generation'").fetchone()[0]
            if expected_generation is not None and generation != expected_generation:
                raise IndexGenerationChanged("本地记录已清理，已丢弃此前开始的索引写入。")
            db.execute("INSERT INTO libraries_v2(identity_key,identity_json,root,scanned_at) VALUES (?,?,?,?) "
                       "ON CONFLICT(identity_key) DO UPDATE SET root=excluded.root,scanned_at=excluded.scanned_at",
                       (key,identity_json,str(root),datetime.now().isoformat()))
            library_id = db.execute("SELECT id FROM libraries_v2 WHERE identity_key=?", (key,)).fetchone()[0]
            db.execute("CREATE TEMP TABLE seen (path TEXT PRIMARY KEY) WITHOUT ROWID")
            def values():
                for item in items:
                    if cancel is not None and cancel.is_set():
                        raise IndexGenerationChanged("扫描已取消，未覆盖原有索引。")
                    item_relative = relative(item.path)
                    if identity is not None and item.library_key and item.library_key != key:
                        raise LibraryIdentityChanged("媒体记录属于另一块硬盘，未覆盖原有索引。")
                    yield (library_id,item_relative,item.kind,item.taken_at.isoformat() if item.taken_at else None,
                           item.size,item.mtime_ns)
            db.executemany("""INSERT INTO media_v2 VALUES (?,?,?,?,?,?)
                ON CONFLICT(library_id,path) DO UPDATE SET kind=excluded.kind,taken_at=excluded.taken_at,
                size=excluded.size,mtime_ns=excluded.mtime_ns
                WHERE media_v2.kind!=excluded.kind OR media_v2.taken_at IS NOT excluded.taken_at
                OR media_v2.size!=excluded.size OR media_v2.mtime_ns!=excluded.mtime_ns""", values())
            db.executemany("INSERT INTO seen VALUES (?)", ((relative(i.path),) for i in items))
            if cancel is not None and cancel.is_set():
                raise IndexGenerationChanged("扫描已取消，未覆盖原有索引。")
            if self.identity_provider(root) != identity:
                raise LibraryIdentityChanged("索引提交前硬盘身份发生变化，已保留旧索引。")
            db.execute("DELETE FROM media_v2 WHERE library_id=? AND path NOT IN (SELECT path FROM seen)", (library_id,))
            db.execute("INSERT OR REPLACE INTO aliases_v2 VALUES (?,?)", (normalized_root(root),library_id))
            # Retire this root's unverified v1 snapshot only after successful v2 commit.
            db.execute("DELETE FROM media WHERE root=?", (str(root),))
            db.execute("DELETE FROM libraries WHERE root=?", (str(root),))

    def clear(self):
        """Clear only owned local SQL records; stale scans must carry generation()."""
        with self.connect() as db:
            db.execute("PRAGMA secure_delete=ON")
            for table in ("media_v2", "libraries_v2", "aliases_v2", "media", "libraries"):
                db.execute("DELETE FROM " + table)
            db.execute("UPDATE metadata_v2 SET value=? WHERE key='generation'", (uuid.uuid4().hex,))
            db.commit()
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            for path in self.path.parent.iterdir():
                if (re.fullmatch(re.escape(self.path.name) + r"\.corrupt-[0-9a-f]{32}(?:-wal|-shm)?", path.name)
                        and path.is_file() and not path.is_symlink()):
                    path.unlink()

from datetime import datetime
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from threading import Event

import pytest

from app.core.library import MediaItem
from app.core.scanner import scan_library
from app.storage.identity import LibraryIdentity
from app.storage.index import IndexGenerationChanged, LibraryIdentityChanged, LibraryIndex


def volume(name="disk-a", serial="1234", relative="photos"):
    return LibraryIdentity(name, serial, relative)


def media(root, name="IMG20260101100000.jpg", size=3, mtime=1):
    return MediaItem(root / name, "image", datetime(2026, 1, 1, 10), size, mtime)


def test_same_path_different_disk_never_restores_other_volume(tmp_path):
    root = tmp_path / "mounted" / "photos"
    root.mkdir(parents=True)
    active = [volume()]
    index = LibraryIndex(tmp_path / "cache.sqlite3", lambda root: active[0])
    a = media(root, "A.jpg")
    b = media(root, "B.jpg")
    index.save(root, [a])
    active[0] = volume("disk-b")
    assert index.load(root, validate=False) is None
    index.save(root, [b])
    assert index.load(root, validate=False) == [b]
    active[0] = volume()
    assert index.load(root, validate=False) == [a]
    active[0] = volume(serial="different-serial")
    assert index.load(root, validate=False) is None


def test_same_disk_new_mount_remaps_relative_paths_and_separates_libraries(tmp_path):
    first, second = tmp_path / "drive-old" / "photos", tmp_path / "drive-new" / "photos"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    index = LibraryIndex(tmp_path / "cache.sqlite3", lambda root: volume())
    index.save(first, [media(first, "sub/file.jpg")])
    restored = index.load(second, validate=False)
    assert restored == [media(second, "sub/file.jpg")]
    with index.connect() as db:
        assert db.execute("SELECT path FROM media_v2").fetchall() == [("sub/file.jpg",)]
    different = LibraryIndex(index.path, lambda root: volume(relative="other/photos"))
    assert different.load(second, validate=False) is None


def test_unverified_online_volume_cannot_use_path_alias(tmp_path, monkeypatch):
    root = tmp_path / "photos"
    root.mkdir()
    active = [volume()]
    index = LibraryIndex(tmp_path / "cache.sqlite3", lambda root: active[0])
    item = media(root)
    index.save(root, [item])
    active[0] = None
    assert index.load(root, validate=False) is None
    original = Path.is_dir
    monkeypatch.setattr(Path, "is_dir", lambda p: False if p == root else original(p))
    assert index.load(root, validate=False) == [item]


def test_refresh_rejects_foreign_paths_and_preserves_transaction(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    index = LibraryIndex(tmp_path / "cache.sqlite3", lambda root: volume())
    item = media(root)
    index.save(root, [item])
    with pytest.raises(ValueError, match="之外"):
        index.save(root, [media(tmp_path / "another")])
    assert index.load(root, validate=False) == [item]


def test_modified_and_deleted_files_are_reconciled_on_online_restore(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    deleted, changed = root / "IMG20260101100000.jpg", root / "IMG20260102100000.jpg"
    deleted.write_bytes(b"delete fixture")
    changed.write_bytes(b"old fixture")
    index = LibraryIndex(tmp_path / "cache.sqlite3")
    index.save(root, scan_library(root).items)
    deleted.unlink()
    changed.write_bytes(b"changed fixture, independent test data")
    before = hashlib.sha256(changed.read_bytes()).digest()
    restored = index.load(root)
    assert len(restored) == 1 and restored[0].path == changed
    assert restored[0].size == changed.stat().st_size
    assert restored[0].mtime_ns == changed.stat().st_mtime_ns
    assert hashlib.sha256(changed.read_bytes()).digest() == before
    assert index.load(root, validate=False) == restored


def test_cancelled_online_validation_does_not_commit_partial_deletions(tmp_path, monkeypatch):
    root = tmp_path / "photos"
    root.mkdir()
    for i in range(4):
        (root / f"IMG2026010{i+1}100000.jpg").write_bytes(b"fixture")
    index = LibraryIndex(tmp_path / "cache.sqlite3")
    before = scan_library(root).items
    index.save(root, before)
    before[0].path.unlink()
    cancel = Event()
    original = Path.stat
    def stat(p, *args, **kwargs):
        if p == before[1].path:
            cancel.set()
        return original(p, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "stat", stat)
        assert index.load(root, cancel=cancel) is None
    assert set(index.load(root, validate=False)) == set(before)


def test_scan_rejects_replaced_volume_and_observes_late_cancel(tmp_path, monkeypatch):
    root = tmp_path / "photos"
    root.mkdir()
    (root / "IMG20260101100000.jpg").touch()
    identities = iter([volume(), volume("replacement")])
    monkeypatch.setattr("app.core.scanner.library_identity", lambda root: next(identities))
    result = scan_library(root)
    assert result.unavailable and result.identity_changed
    assert "身份" in result.errors[-1]
    monkeypatch.setattr("app.core.scanner.library_identity", lambda root: volume())
    cancel = Event()
    original = Path.is_dir
    def is_dir(p):
        if cancel.is_set():
            pytest.fail("Cancellation must not initiate another blocking root check")
        return original(p)
    monkeypatch.setattr(Path, "is_dir", is_dir)
    result = scan_library(root, cancel=cancel, batch=lambda items: cancel.set())
    assert result.cancelled


def test_save_rejects_changed_identity_and_clear_rejects_stale_scans(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    index = LibraryIndex(tmp_path / "cache.sqlite3", lambda root: volume())
    item = media(root)
    with pytest.raises(LibraryIdentityChanged):
        index.save(root, [item], expected_identity=volume("other"))
    token = index.generation()
    index.save(root, [item], expected_identity=volume(), expected_generation=token)
    other_instance = LibraryIndex(index.path, lambda root: volume())
    other_instance.clear()
    assert other_instance.generation() != token
    with pytest.raises(IndexGenerationChanged):
        index.save(root, [item], expected_generation=token)
    assert index.load(root, validate=False) is None


def test_cancelled_save_rolls_back_previous_snapshot(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    index = LibraryIndex(tmp_path / "cache.sqlite3", lambda root: volume())
    index.save(root, [media(root)])
    cancel = Event()
    cancel.set()
    with pytest.raises(IndexGenerationChanged):
        index.save(root, [], cancel=cancel)
    assert index.load(root, validate=False) == [media(root)]


def legacy_database(path, root):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE libraries(root TEXT PRIMARY KEY, scanned_at TEXT NOT NULL)")
        db.execute("CREATE TABLE media(root TEXT,path TEXT,kind TEXT,taken_at TEXT,size INTEGER,mtime_ns INTEGER,PRIMARY KEY(root,path))")
        db.execute("INSERT INTO libraries VALUES (?,?)", (str(root), "2026-01-01"))
        db.execute("INSERT INTO media VALUES (?,?,?,?,?,?)", (str(root), str(root / "legacy.jpg"), "image", None, 3, 1))


def test_legacy_schema_migrates_without_guessing_its_disk(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    path = tmp_path / "cache.sqlite3"
    legacy_database(path, root)
    index = LibraryIndex(path, lambda root: volume())
    assert index.load(root, validate=False) is None
    assert "旧版" in index.warning
    with index.connect() as db:
        assert db.execute("SELECT count(*) FROM media").fetchone()[0] == 1
    index.save(root, [media(root)])
    assert index.load(root, validate=False) == [media(root)]
    with index.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM media").fetchone()[0] == 0


def test_migration_failure_rolls_back_schema_and_retains_legacy_data(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    path = tmp_path / "cache.sqlite3"
    legacy_database(path, root)
    class FailingMigration(LibraryIndex):
        def _migrate(self, db):
            db.set_authorizer(lambda action, arg1, *args:
                              sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_CREATE_TABLE and arg1 == "aliases_v2" else sqlite3.SQLITE_OK)
            return super()._migrate(db)
    with pytest.raises(sqlite3.DatabaseError):
        FailingMigration(path).generation()
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM media").fetchone()[0] == 1
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='libraries_v2'").fetchall()
    assert not list(tmp_path.glob("*.corrupt-*"))
    assert LibraryIndex(path).generation()


def test_corrupt_database_is_preserved_and_clear_only_removes_owned_metadata(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    original = root / "IMG20260101100000.jpg"
    original.write_bytes(b"original media fixture")
    digest = hashlib.sha256(original.read_bytes()).digest()
    path = tmp_path / "cache.sqlite3"
    broken = b"invalid SQLite fixture\x00"
    path.write_bytes(broken)
    index = LibraryIndex(path, lambda root: volume())
    assert index.load(root) is None
    backups = list(tmp_path.glob("cache.sqlite3.corrupt-*"))
    assert backups and backups[0].read_bytes() == broken
    assert "损坏" in index.warning and "隔离" in index.warning
    index.save(root, [media(root)])
    unrelated = tmp_path / 'cache.sqlite3.corrupt-original.jpg'
    unrelated.write_bytes(b'Unmanaged user file must survive record cleanup')
    index.clear()
    assert list(tmp_path.glob("cache.sqlite3.corrupt-*")) == [unrelated]
    assert unrelated.read_bytes() == b'Unmanaged user file must survive record cleanup'
    assert hashlib.sha256(original.read_bytes()).digest() == digest


def test_multiple_processes_serialize_metadata_without_losing_other_libraries(tmp_path):
    path = tmp_path / "cache.sqlite3"
    script = """from pathlib import Path
from app.core.library import MediaItem
from app.storage.index import LibraryIndex
import sys
root=Path(sys.argv[2]); root.mkdir(exist_ok=True)
LibraryIndex(Path(sys.argv[1])).save(root,[MediaItem(root/f'photo{i}.jpg','image',None,3,1) for i in range(100)])
"""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    processes = [subprocess.Popen([sys.executable, "-c", script, str(path), str(tmp_path / f"library-{i}")],
                                  env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(4)]
    for process in processes:
        _, error = process.communicate(timeout=20)
        assert process.returncode == 0, error.decode(errors="replace")
    index = LibraryIndex(path)
    for i in range(4):
        assert len(index.load(tmp_path / f"library-{i}", validate=False)) == 100


@pytest.mark.parametrize("outcome", ["cancelled", "unavailable", "partial", "swapped_mid_scan", "unverified"])
def test_main_window_cannot_restore_or_merge_disk_a_after_same_path_becomes_disk_b(tmp_path, qapp, outcome):
    from PySide6.QtCore import QObject, QSettings
    from app.core.scanner import ScanResult
    from app.ui.main_window import MainWindow
    root = tmp_path / "mounted" / "photos"
    root.mkdir(parents=True)
    a, b = media(root, "A.jpg"), media(root, "B.jpg")
    window = MainWindow(QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat), auto_load=False)
    window.root = window.snapshot_root = window.scan_root = root
    window.library_identity = window.snapshot_identity = volume()
    window.snapshot = [a]
    window.snapshot_route = ("all",)
    window.items = [b]
    window.scan = QObject(window)
    window.scan_result = ScanResult(items=[b],library_identity=None if outcome == "unverified" else volume("disk-b"),
                                    cancelled=outcome in ("cancelled", "unverified"),unavailable=outcome in ("unavailable","swapped_mid_scan"),
                                    identity_changed=outcome == "swapped_mid_scan",error_count=1 if outcome == "partial" else 0,
                                    errors=["simulated independent scan failure"])
    try:
        window.finish_scan()
        assert a not in window.items
        assert window.items == ([b] if outcome == "partial" else [])
        assert "身份" in window.banner.text() or "未合并" in window.banner.text()
    finally:
        window.close()
        qapp.processEvents()


def test_main_window_partial_merge_requires_verified_same_identity(tmp_path, qapp):
    from PySide6.QtCore import QObject, QSettings
    from app.core.scanner import ScanResult
    from app.ui.main_window import MainWindow
    root = tmp_path / "photos"
    root.mkdir()
    a, b = media(root, "A.jpg"), media(root, "B.jpg")
    window = MainWindow(QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat), auto_load=False)
    window.root = window.snapshot_root = window.scan_root = root
    window.library_identity = window.snapshot_identity = volume()
    window.snapshot,window.items,window.snapshot_route = [a],[b],("all",)
    window.scan = QObject(window)
    window.scan_result = ScanResult(items=[b],library_identity=volume(),error_count=1,errors=["simulated permission denial"])
    try:
        window.finish_scan()
        assert set(window.items) == {a,b}
        assert "原有未读到" in window.banner.text()
    finally:
        window.close()
        qapp.processEvents()


def test_unknown_identity_uses_fresh_cache_namespace_per_scan(tmp_path, monkeypatch):
    root=tmp_path/'photos'
    root.mkdir()
    (root/'IMG20260101100000.jpg').touch()
    monkeypatch.setattr('app.core.scanner.library_identity',lambda root:None)
    first,second=scan_library(root),scan_library(root)
    assert first.items[0].library_key and first.items[0].library_key!=second.items[0].library_key
    index=LibraryIndex(tmp_path/'cache.sqlite3',lambda root:None)
    index.save(root,first.items)
    original=Path.is_dir
    monkeypatch.setattr(Path,'is_dir',lambda p:False if p==root else original(p))
    restored=index.load(root)
    assert restored[0].library_key==first.items[0].library_key

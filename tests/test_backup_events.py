"""测试 7-8：备份/恢复/完整性/checksum；测试 13：事件不可变（DB 触发器）+ correction。"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import select

from database.invariants import verify_event_immutability
from services.backup_service import (backup_sqlite, integrity_check,
                                     pre_migration_backup, restore_from_backup)
from services.repositories import EventRepository

W = "W"


def _seed_event(factory):
    with factory() as s:
        e = EventRepository(s).append(world_id=W, event_type="RESOURCE_DECLINE",
                                      source="SIM", blessed_tick=10_000_000,
                                      real_time=datetime.now(timezone.utc),
                                      cause={"region": "EAST_LAKE"})
        s.commit()
        return e.event_uid


def _seed_junk(migrated_db):
    """事故模拟：向非事件表写垃圾数据（world_events 的 DELETE 已被 DB 触发器禁止）。"""
    with migrated_db["engine"].begin() as c:
        c.execute(sa.text(
            "INSERT INTO system_configuration (key, kind, value, updated_at) "
            "VALUES ('junk-key', 'SYSTEM', '{}', '2000-01-01 00:00:00+00:00')"))


def _logical_dump_hash(db_path: str) -> str:
    """SQLite 逻辑内容摘要（文件字节级比较对 SQLite 无效：文件头 change counter 不同）。"""
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        h = hashlib.sha256()
        for t in tables:
            h.update(t.encode("utf-8"))
            for row in conn.execute(f'SELECT * FROM "{t}" ORDER BY rowid'):
                h.update(repr(row).encode("utf-8"))
        return h.hexdigest()
    finally:
        conn.close()


def test_backup_restore(migrated_db, seeded_session_factory, tmp_path):
    _seed_event(seeded_session_factory)
    rec = backup_sqlite(migrated_db["engine"], tmp_path / "bk" / "world.db",
                        meta={"kind": "TEST"})
    assert (tmp_path / "bk" / "backup_manifest.jsonl").exists()
    # 事故：写入垃圾数据
    _seed_junk(migrated_db)
    # 恢复（restore_from_backup 内部处理引擎释放与 -wal/-shm 副产物）
    restore_from_backup(migrated_db["engine"], Path(rec["path"]))
    engine2 = sa.create_engine(migrated_db["url"])
    with engine2.connect() as c:
        n = c.execute(sa.text("SELECT COUNT(*) FROM world_events")).scalar()
        junk = c.execute(sa.text(
            "SELECT COUNT(*) FROM system_configuration")).scalar()
        assert c.execute(sa.text("PRAGMA integrity_check")).scalar() == "ok"
    engine2.dispose()
    assert n == 1
    assert junk == 0


def test_backup_restore_with_wal_active(migrated_db, seeded_session_factory, tmp_path):
    """Windows + WAL 状态下恢复：备份含 WAL 内容，恢复后一致。"""
    _seed_event(seeded_session_factory)  # WAL 活跃（未 checkpoint）
    rec = backup_sqlite(migrated_db["engine"], tmp_path / "bk" / "world.db")
    _seed_junk(migrated_db)
    restore_from_backup(migrated_db["engine"], Path(rec["path"]))
    engine2 = sa.create_engine(migrated_db["url"])
    with engine2.connect() as c:
        assert c.execute(sa.text("SELECT COUNT(*) FROM world_events")).scalar() == 1
        assert c.execute(sa.text(
            "SELECT COUNT(*) FROM system_configuration")).scalar() == 0
        assert c.execute(sa.text("PRAGMA integrity_check")).scalar() == "ok"
    engine2.dispose()


def test_backup_checksum_matches_live_after_checkpoint(migrated_db,
                                                       seeded_session_factory, tmp_path):
    _seed_event(seeded_session_factory)
    with migrated_db["engine"].connect() as c:
        c.execute(sa.text("PRAGMA wal_checkpoint(FULL)"))
    rec = backup_sqlite(migrated_db["engine"], tmp_path / "bk" / "w.db")
    main_path = migrated_db["url"].replace("sqlite:///", "")
    assert _logical_dump_hash(main_path) == _logical_dump_hash(rec["path"])


def test_backup_integrity(migrated_db, tmp_path):
    rec = backup_sqlite(migrated_db["engine"], tmp_path / "b2" / "w.db")
    import sqlite3
    conn = sqlite3.connect(rec["path"])
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def test_pre_migration_backup(migrated_db, tmp_path):
    rec = pre_migration_backup(migrated_db["engine"], tmp_path)
    assert rec["kind"] == "PRE_MIGRATION"
    import sqlite3
    conn = sqlite3.connect(rec["path"])
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def test_integrity_check_helper(migrated_db):
    assert integrity_check(migrated_db["engine"]) == "ok"


def test_event_immutability_triggers_present(migrated_db):
    """DB 层触发器真实存在（不是代码约定）。"""
    verify_event_immutability(migrated_db["engine"])


def test_event_db_level_immutable(migrated_db, seeded_session_factory):
    """数据库层拒绝 Committed Event 原地 UPDATE / DELETE。"""
    eid = _seed_event(seeded_session_factory)
    with pytest.raises(sa.exc.IntegrityError):
        with migrated_db["engine"].begin() as c:
            c.execute(sa.text("UPDATE world_events SET severity = 999.0 "
                              "WHERE event_uid = :e"), {"e": eid})
    with pytest.raises(sa.exc.IntegrityError):
        with migrated_db["engine"].begin() as c:
            c.execute(sa.text("DELETE FROM world_events WHERE event_uid = :e"),
                      {"e": eid})
    with seeded_session_factory() as s:
        assert EventRepository(s).get(eid) is not None


def test_event_immutable_and_correction(seeded_session_factory):
    eid = _seed_event(seeded_session_factory)
    with seeded_session_factory() as s:
        repo = EventRepository(s)
        orig = repo.get(eid)
        corr = repo.append_correction(
            original_event_id=eid, world_id=W, event_type="RESOURCE_CORRECTION",
            source="OWNER_CONFIRM", blessed_tick=11_000_000, real_time=orig.real_time,
            cause={"fix": "severity 校正"})
        s.commit()
        orig2 = repo.get(eid)
        assert orig2.cause == {"region": "EAST_LAKE"}  # 原事件未被修改
        assert corr.supersedes_event_id == eid
        assert corr.correction_reason == "CORRECTION"


def test_event_causal_chain(seeded_session_factory):
    with seeded_session_factory() as s:
        repo = EventRepository(s)
        e3 = repo.append(world_id=W, event_type="C", source="SIM",
                         blessed_tick=3_000_000, parent_event_ref=None)
        e2 = repo.append(world_id=W, event_type="B", source="SIM",
                         blessed_tick=2_000_000, parent_event_ref=e3.event_uid)
        e1 = repo.append(world_id=W, event_type="A", source="SIM",
                         blessed_tick=1_000_000, parent_event_ref=e2.event_uid)
        s.commit()
        chain = repo.chain_of(e1.event_uid)
        assert [c.event_type for c in chain] == ["A", "B", "C"]

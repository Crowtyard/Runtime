"""测试 7-8：备份/恢复/完整性；测试 13：事件不可变与 correction。"""
from __future__ import annotations

import shutil
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import select

from services.backup_service import (backup_sqlite, integrity_check,
                                     pre_migration_backup)
from services.repositories import EventRepository

W = "W"


def _seed_event(factory):
    with factory() as s:
        e = EventRepository(s).append(world_id=W, event_type="RESOURCE_DECLINE",
                                      source="SIM", blessed_time=10,
                                      real_time=datetime.now(timezone.utc),
                                      cause={"region": "EAST_LAKE"})
        s.commit()
        return e.event_uid


def test_backup_restore(migrated_db, seeded_session_factory, tmp_path):
    _seed_event(seeded_session_factory)
    rec = backup_sqlite(migrated_db["engine"], tmp_path / "bk" / "world.db",
                        meta={"kind": "TEST"})
    assert (tmp_path / "bk" / "backup_manifest.jsonl").exists()
    # 事故：清空事件表
    with migrated_db["engine"].begin() as c:
        c.execute(sa.text("DELETE FROM world_events WHERE 1=1"))
    # 恢复（先释放引擎连接，避免 Windows 文件占用）
    migrated_db["engine"].dispose()
    main_path = migrated_db["url"].replace("sqlite:///", "")
    shutil.copy(rec["path"], main_path)
    engine2 = sa.create_engine(migrated_db["url"])
    with engine2.connect() as c:
        n = c.execute(sa.text("SELECT COUNT(*) FROM world_events")).scalar()
    engine2.dispose()
    assert n == 1


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


def test_integrity_check_helper(migrated_db):
    assert integrity_check(migrated_db["engine"]) == "ok"


def test_event_immutable_and_correction(seeded_session_factory):
    eid = _seed_event(seeded_session_factory)
    with seeded_session_factory() as s:
        repo = EventRepository(s)
        orig = repo.get(eid)
        corr = repo.append_correction(
            original_event_id=eid, world_id=W, event_type="RESOURCE_CORRECTION",
            source="OWNER_CONFIRM", blessed_time=11, real_time=orig.real_time,
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
                         blessed_time=3, real_time=None, parent_event_ref=None)
        s.flush()
        e2 = repo.append(world_id=W, event_type="B", source="SIM",
                         blessed_time=2, real_time=None, parent_event_ref=e3.id)
        s.flush()
        e1 = repo.append(world_id=W, event_type="A", source="SIM",
                         blessed_time=1, real_time=None, parent_event_ref=e2.id)
        s.commit()
        chain = repo.chain_of(e1.id)
        assert [c.event_type for c in chain] == ["A", "B", "C"]

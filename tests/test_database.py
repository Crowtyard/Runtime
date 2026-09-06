"""测试 1-4：migration / transaction / atomic tick rollback / single writer / retry 幂等。"""
from __future__ import annotations

import pytest
from sqlalchemy import select, text

from database.base import Base
from database.models_core import SimulationRun, WorldEvent
from database.models_world import Settlement
from domain.errors import WriterLockConflict
from services.atomic_tick import run_atomic_tick
from services.repositories import EventRepository
from services.writer_lock import WriterLease, world_writer

W = "W"


def test_migration_creates_schema(migrated_db):
    with migrated_db["engine"].connect() as c:
        rows = c.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'alembic%'"
        )).fetchall()
        assert len(rows) == 20
        assert {r[0] for r in rows} == set(Base.metadata.tables)


def test_migration_schema_version_present(migrated_db):
    with migrated_db["engine"].connect() as c:
        v = c.execute(text("SELECT version_num FROM alembic_version")).fetchone()
        assert v is not None and v[0]


def test_sqlite_pragmas(migrated_db):
    with migrated_db["engine"].connect() as c:
        assert c.execute(text("PRAGMA foreign_keys")).scalar() == 1
        mode = c.execute(text("PRAGMA journal_mode")).scalar()
        assert str(mode).upper() == "WAL"


def test_session_rollback_on_error(seeded_session_factory):
    with pytest.raises(RuntimeError):
        with seeded_session_factory() as s:
            with s.begin():
                s.add(Settlement(world_id=W, working_name="测试聚落",
                                 settlement_type="MAIN"))
                raise RuntimeError("boom")
    with seeded_session_factory() as s:
        assert s.execute(select(Settlement)).scalars().all() == []


def test_atomic_tick_rollback(seeded_session_factory):
    def bad_fn(session):
        EventRepository(session).append(world_id=W, event_type="X",
                                        source="SIM", blessed_time=1)
        raise RuntimeError("tick failed")

    with pytest.raises(RuntimeError):
        run_atomic_tick(seeded_session_factory, world_id=W,
                        target_blessed_time=1, simulate_fn=bad_fn)
    with seeded_session_factory() as s:
        assert s.execute(select(WorldEvent)).scalars().all() == []
        assert s.execute(select(SimulationRun)).scalars().all() == []


def test_single_writer_exclusive(seeded_session_factory):
    # writer1 取得租约并提交（锁持久可见）
    with seeded_session_factory() as s1:
        lease = WriterLease(s1, W, 120)
        lease.acquire()
        s1.commit()
        try:
            # writer2 探测到未过期锁 → 拒绝（不等待、不抢注）
            with pytest.raises(WriterLockConflict):
                with seeded_session_factory() as s2:
                    with world_writer(s2, W):
                        pass
        finally:
            lease.release()
            s1.commit()
    # 释放后可再获取
    with seeded_session_factory() as s3:
        with world_writer(s3, W):
            pass


def test_retry_idempotency_skip(seeded_session_factory):
    calls = []

    def fn(session):
        calls.append(1)
        EventRepository(session).append(world_id=W, event_type="E",
                                        source="SIM", blessed_time=5)

    r1 = run_atomic_tick(seeded_session_factory, world_id=W,
                         target_blessed_time=5, simulate_fn=fn)
    assert r1.skipped is False
    r2 = run_atomic_tick(seeded_session_factory, world_id=W,
                         target_blessed_time=5, simulate_fn=fn)
    assert r2.skipped is True
    assert len(calls) == 1
    with seeded_session_factory() as s:
        assert len(s.execute(select(WorldEvent)).scalars().all()) == 1

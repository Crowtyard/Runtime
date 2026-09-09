"""测试 1-4：migration / transaction / atomic tick rollback / single writer / retry 幂等。"""
from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text

from XiaoguangBlessedLandRuntime.database.base import Base
from XiaoguangBlessedLandRuntime.database.models_core import SimulationRun, WorldEvent
from XiaoguangBlessedLandRuntime.database.models_world import Settlement
from XiaoguangBlessedLandRuntime.domain.constants import SimulationVersion
from XiaoguangBlessedLandRuntime.domain.errors import WriterLockConflict, WorldNotActivated
from XiaoguangBlessedLandRuntime.services.atomic_tick import run_atomic_tick
from XiaoguangBlessedLandRuntime.services.repositories import EventRepository
from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease, world_writer

from tests.conftest import HEAD_REVISION, PROJECT_ROOT, W


def test_migration_creates_schema(migrated_db):
    with migrated_db["engine"].connect() as c:
        rows = c.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'alembic%'"
        )).fetchall()
        assert len(rows) == 31  # M0 20 + M2b 5 + M2c 3 + M2d 3
        assert {r[0] for r in rows} == set(Base.metadata.tables)


def test_migration_at_head(migrated_db):
    with migrated_db["engine"].connect() as c:
        v = c.execute(text("SELECT version_num FROM alembic_version")).fetchone()
        assert v is not None and v[0] == HEAD_REVISION


def test_migration_downgrade_upgrade_cycle(migrated_db):
    """M1 迁移基本验证：downgrade base → upgrade head 全链路可逆。"""
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "database" / "alembic"))
    cfg.set_main_option("sqlalchemy.url", migrated_db["url"])
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    with migrated_db["engine"].connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() \
            == HEAD_REVISION
        triggers = c.execute(text(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND "
            "tbl_name='world_events'")).fetchall()
        assert len(triggers) == 2  # 不可变触发器随 upgrade 重建


def test_canonical_tick_columns(migrated_db):
    """blessed 时间列 = 整数 canonical tick（BigInteger）；旧 String/年语义列不得残留。"""
    expect = {
        "world_runtime": "current_blessed_tick",
        "time_ratio_history": "blessed_effective_from_tick",
        "simulation_run": "target_blessed_tick",
        "simulation_run": "committed_until_tick",
        "world_events": "blessed_tick",
        "persons": "birth_blessed_tick",
        "tribulations": "start_blessed_tick",
        "timeline_entries": "blessed_tick",
    }
    with migrated_db["engine"].connect() as c:
        for table, col in expect.items():
            info = {r[1]: r[2] for r in c.execute(text(f"PRAGMA table_info({table})"))}
            assert col in info, f"{table}.{col} 缺失"
            assert "INT" in info[col].upper(), f"{table}.{col} 非整数类型: {info[col]}"
        persons = {r[1] for r in c.execute(text("PRAGMA table_info(persons)"))}
        assert "birth_blessed_time" not in persons  # 旧列名不得残留


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


def test_atomic_tick_rollback(activated_session_factory, lease_helper):
    """失败事务不推进 committed_until_tick：0 事件 0 run。"""
    s, lease = lease_helper()
    try:
        def bad_fn(session):
            EventRepository(session).append(world_id=W, event_type="X",
                                            source="SIM", blessed_tick=1)
            raise RuntimeError("tick failed")

        with pytest.raises(RuntimeError):
            run_atomic_tick(activated_session_factory, world_id=W,
                            target_blessed_tick=1, simulate_fn=bad_fn,
                            writer_id=lease.owner,
                            fencing_token=lease.token)
        with activated_session_factory() as sess:
            assert sess.execute(select(WorldEvent)).scalars().all() == []
            assert sess.execute(select(SimulationRun)).scalars().all() == []
    finally:
        lease.release()
        s.close()


def test_atomic_tick_requires_activation(seeded_session_factory):
    """simulate_tick 在未激活世界必须失败（WORLD_NOT_ACTIVATED，先于 fencing）。"""
    with pytest.raises(WorldNotActivated):
        run_atomic_tick(seeded_session_factory, world_id=W,
                        target_blessed_tick=1, simulate_fn=lambda s: None,
                        writer_id="w", fencing_token="t")
    with seeded_session_factory() as s:
        assert s.execute(select(SimulationRun)).scalars().all() == []


def test_single_writer_exclusive(seeded_session_factory):
    # writer1 取得租约（acquire 立即提交，跨会话可见）
    with seeded_session_factory() as s1:
        lease = WriterLease(s1, W, 120)
        lease.acquire()
        try:
            # writer2 探测到未过期锁 → 拒绝（不等待、不抢注）
            with pytest.raises(WriterLockConflict):
                with seeded_session_factory() as s2:
                    with world_writer(s2, W):
                        pass
        finally:
            lease.release()
    # 释放后可再获取
    with seeded_session_factory() as s3:
        with world_writer(s3, W):
            pass


def test_retry_idempotency_skip(activated_session_factory, lease_helper):
    """TICK_IDENTITY：同 world + 同 simulation_version 同 target → skip；run_id 稳定。"""
    s, lease = lease_helper()
    try:
        calls = []

        def fn(session):
            calls.append(1)
            EventRepository(session).append(world_id=W, event_type="E",
                                            source="SIM", blessed_tick=5_000_000)

        r1 = run_atomic_tick(activated_session_factory, world_id=W,
                             target_blessed_tick=5_000_000, simulate_fn=fn,
                             writer_id=lease.owner, fencing_token=lease.token)
        assert r1.skipped is False and r1.run_id is not None
        r2 = run_atomic_tick(activated_session_factory, world_id=W,
                             target_blessed_tick=5_000_000, simulate_fn=fn,
                             writer_id=lease.owner, fencing_token=lease.token)
        assert r2.skipped is True
        assert r2.run_id == r1.run_id
        assert len(calls) == 1
        with activated_session_factory() as sess:
            assert len(sess.execute(select(WorldEvent)).scalars().all()) == 1
            run = sess.execute(select(SimulationRun)).scalar_one()
            assert run.committed_until_tick == 5_000_000
            assert run.target_blessed_tick == 5_000_000
            assert run.simulation_version == SimulationVersion.CURRENT
    finally:
        lease.release()
        s.close()


def test_idempotency_scoped_to_simulation_version(activated_session_factory,
                                                  lease_helper):
    """旧 simulation_version 的 committed_until_tick 不得阻止新版合法推进。"""
    s, lease = lease_helper()
    try:
        with activated_session_factory() as sess:
            sess.add(SimulationRun(
                run_id="LEGACY-RUN-1", world_id=W,
                simulation_version="0.0.1-legacy",
                status="COMMITTED", committed_until_tick=100_000_000,
                target_blessed_tick=100_000_000, seed_context={}))
            sess.commit()
        result = run_atomic_tick(activated_session_factory, world_id=W,
                                 target_blessed_tick=5_000_000,
                                 simulate_fn=lambda s: None,
                                 writer_id=lease.owner,
                                 fencing_token=lease.token)
        assert result.skipped is False
        assert result.committed_until_tick == 5_000_000
    finally:
        lease.release()
        s.close()

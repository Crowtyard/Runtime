# -*- coding: utf-8 -*-
"""PRE-M6 PG-001：权威恢复 checkpoint 查询的方言可移植性。

三层证据：
1. **SQLite 行为不变**：混合 checkpoint 集合（含更新的 CATCHUP 行、
   complete=False 行、缺键行）下仍选中最新 complete WORLD_COMMITTED；
2. **跨方言编译等价**：PostgreSQL 编译结果不含 SQLite JSON 函数、使用 ``->>``、
   布尔列用 ``IS true``；SQLite 编译结果不含 ``->>``（JSON 函数由 SQLAlchemy
   方言适配器生成，源码中不出现）；
3. **PG 集成入口**：真实 PostgreSQL 集成测试（环境建设后启用），默认跳过，
   且对非 test 库名 / 非 PG DSN fail-closed。
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import delete
from sqlalchemy.dialects import postgresql, sqlite

import XiaoguangBlessedLandRuntime.services.simulation.recovery as recovery_mod
from XiaoguangBlessedLandRuntime.database.models_core import (
    SimulationCheckpoint, WorldRuntime)
from XiaoguangBlessedLandRuntime.services.simulation.recovery import (
    WORLD_COMMITTED_KIND, authoritative_checkpoint_statement,
    checkpoint_count_statement, count_checkpoints_by_kind,
    latest_authoritative_world_checkpoint)

from tests.conftest import W

PG_DSN_ENV = "BLR_TEST_PG_DSN"
PG_ALLOW_ENV = "BLR_TEST_PG_ALLOW"


def _add(session, *, world_id=W, tick, meta_key, meta_value, complete=True):
    session.add(SimulationCheckpoint(world_id=world_id,
                                     checkpoint_blessed_tick=tick,
                                     world_state_hash=f"hash-{tick}",
                                     complete=complete,
                                     meta={meta_key: meta_value}))
    return tick


@pytest.fixture()
def mixed_checkpoints(seeded_session_factory):
    """混合 checkpoint 集合：CATCHUP 行更新，incomplete 行 tick 最大。"""
    with seeded_session_factory() as s:
        _add(s, tick=100, meta_key="kind", meta_value="CATCHUP")
        _add(s, tick=50, meta_key="checkpoint_kind",
             meta_value=WORLD_COMMITTED_KIND)
        _add(s, tick=80, meta_key="checkpoint_kind",
             meta_value=WORLD_COMMITTED_KIND)
        _add(s, tick=200, meta_key="checkpoint_kind",
             meta_value=WORLD_COMMITTED_KIND, complete=False)
        _add(s, tick=150, meta_key="kind", meta_value="CATCHUP")
        s.commit()
    return seeded_session_factory


def test_authoritative_pick_ignores_newer_catchup_and_incomplete(
        mixed_checkpoints):
    with mixed_checkpoints() as s:
        got = latest_authoritative_world_checkpoint(s, W)
    assert got is not None
    # 非 200（incomplete）、非 150/100（CATCHUP，无 checkpoint_kind）
    assert got.checkpoint_blessed_tick == 80
    assert got.meta["checkpoint_kind"] == WORLD_COMMITTED_KIND


def test_authoritative_pick_none_when_no_world_committed(seeded_session_factory):
    with seeded_session_factory() as s:
        _add(s, tick=10, meta_key="kind", meta_value="CATCHUP")
        s.commit()
    with seeded_session_factory() as s:
        assert latest_authoritative_world_checkpoint(s, W) is None


def test_count_checkpoints_by_kind_matches_mixed_set(mixed_checkpoints):
    with mixed_checkpoints() as s:
        assert count_checkpoints_by_kind(s, W) == {"time_committed": 2,
                                                   "world_committed": 2}


def test_authoritative_pick_is_world_scoped(mixed_checkpoints):
    with mixed_checkpoints() as s:
        assert latest_authoritative_world_checkpoint(s, "OTHER-WORLD") is None


def _sql(stmt, dialect) -> str:
    return str(stmt.compile(dialect=dialect,
                            compile_kwargs={"literal_binds": True}))


def test_postgres_compilation_has_no_sqlite_json_function():
    pg = _sql(authoritative_checkpoint_statement(W), postgresql.dialect())
    assert "json_extract" not in pg.lower()
    assert "->>" in pg            # meta ->> 'checkpoint_kind'
    assert "IS true" in pg        # 布尔列不写成 = 1
    cnt = _sql(checkpoint_count_statement(W, "kind", "CATCHUP"),
               postgresql.dialect())
    assert "->>" in cnt
    assert "json_extract" not in cnt.lower()


def test_sqlite_compilation_is_dialect_native():
    lite = _sql(authoritative_checkpoint_statement(W), sqlite.dialect())
    # SQLite 侧的 JSON 函数由 SQLAlchemy 方言适配器生成（源码无手写函数名）
    assert "json_extract" in lite.lower()
    assert "->>" not in lite
    assert "IS 1" in lite


def test_recovery_module_source_has_no_sqlite_json_function():
    """源码层（排除 docstring 说明文字）不得手写 json_extract 调用。"""
    source = open(recovery_mod.__file__, encoding="utf-8").read()
    assert "json_extract(meta" not in source
    assert "json_extract(SimulationCheckpoint" not in source


def test_sqlite_runtime_executes_portable_predicate(mixed_checkpoints):
    with mixed_checkpoints() as s:
        rows = s.execute(authoritative_checkpoint_statement(W)).scalars().all()
    assert [r.checkpoint_blessed_tick for r in rows] == [80]


# --------------------------------------------------------------- PG 集成入口
def _pg_dsn_or_skip() -> str:
    dsn = os.environ.get(PG_DSN_ENV, "").strip()
    if not dsn or os.environ.get(PG_ALLOW_ENV) != "1":
        pytest.skip("PG 集成测试需 BLR_TEST_PG_DSN + BLR_TEST_PG_ALLOW=1"
                    "（PRE-M6 PostgreSQL 环境建设后启用）")
    assert "sqlite" not in dsn.lower(), "本测试只接受 PostgreSQL DSN"
    db_name = dsn.rsplit("/", 1)[-1].split("?")[0]
    if "test" not in db_name.lower():
        pytest.fail(f"拒绝在非测试库上执行 PG 集成测试（fail-closed）: {db_name!r}")
    return dsn


def _purge_world(factory, world_id: str) -> None:
    """删除合成 world 的全部痕迹（先 checkpoint，再 world_runtime 行）。

    必须彻底且可重复：只删 checkpoint 会留下 world_runtime 行，
    使下一次运行在 uq_world_runtime_world_id 上失败（即入口不可重跑）。
    """
    with factory() as s:
        s.execute(delete(SimulationCheckpoint).where(
            SimulationCheckpoint.world_id == world_id))
        s.execute(delete(WorldRuntime).where(WorldRuntime.world_id == world_id))
        s.commit()


def test_pg_recovery_integration_entrypoint():
    """POSTGRES_RECOVERY_INTEGRATION：合成 world + 合成 checkpoint，用后清理。

    仅当 BLR_TEST_PG_DSN（库名必须含 "test"）+ BLR_TEST_PG_ALLOW=1 时执行；
    不触碰任何正式世界 / 正式库 / live plugin_data。
    """
    dsn = _pg_dsn_or_skip()
    from XiaoguangBlessedLandRuntime.database.db import (
        create_db_engine, make_session_factory)
    from XiaoguangBlessedLandRuntime.services.db_lifecycle import (
        migrate_database)
    from XiaoguangBlessedLandRuntime.services.repositories import (
        RuntimeRepository)

    from tests.conftest import PROJECT_ROOT

    migrate_database(dsn, project_root=PROJECT_ROOT)
    engine = create_db_engine(dsn)
    factory = make_session_factory(engine)
    world_id = "PG-TEST-RECOVERY-0001"
    try:
        _purge_world(factory, world_id)     # 幂等：清理上次中断运行的残留
        with factory() as s:
            RuntimeRepository(s).create_not_activated(
                world_id=world_id, world_bible_version="1.0",
                simulation_version="0.1.0-dev",
                world_bible_manifest_hash="pghash")
            s.commit()
        with factory() as s:
            _add(s, world_id=world_id, tick=50, meta_key="checkpoint_kind",
                 meta_value=WORLD_COMMITTED_KIND)
            _add(s, world_id=world_id, tick=90, meta_key="checkpoint_kind",
                 meta_value=WORLD_COMMITTED_KIND)
            _add(s, world_id=world_id, tick=120, meta_key="kind",
                 meta_value="CATCHUP")
            s.commit()
        with factory() as s:
            got = latest_authoritative_world_checkpoint(s, world_id)
            counts = count_checkpoints_by_kind(s, world_id)
        assert got is not None and got.checkpoint_blessed_tick == 90
        assert counts == {"time_committed": 1, "world_committed": 2}
    finally:
        _purge_world(factory, world_id)
        engine.dispose()


def test_pg_dsn_guard_rejects_formal_database(monkeypatch):
    """守卫自证：非 test 库名必须 fail-closed（防止误连正式库）。"""
    monkeypatch.setenv(PG_DSN_ENV,
                       "postgresql+psycopg://u:p@localhost:5432/blr_formal")
    monkeypatch.setenv(PG_ALLOW_ENV, "1")
    with pytest.raises(pytest.fail.Exception) as exc:
        _pg_dsn_or_skip()
    assert "非测试库" in str(exc.value)


def test_pg_dsn_guard_rejects_sqlite(monkeypatch):
    monkeypatch.setenv(PG_DSN_ENV, "sqlite:///tmp/x.db")
    monkeypatch.setenv(PG_ALLOW_ENV, "1")
    with pytest.raises(AssertionError):
        _pg_dsn_or_skip()

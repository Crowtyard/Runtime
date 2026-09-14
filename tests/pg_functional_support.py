# -*- coding: utf-8 -*-
"""PRE-M6 PostgreSQL FUNCTIONAL GATE —— 支持模块（TEST ONLY）。

职责：
- 在隔离测试容器内创建/销毁**专用合成** PostgreSQL 测试库（库名含 ``test``，
  满足门禁守卫的 fail-closed 规则）；
- 构建与 `tests/test_m3_integrated_long._fresh_m3` **同构**的 ACTIVE 合成世界
  （同一 mini world、同一 TEST 速率、同一 world_id 约定）——唯一差别是 DB 后端；
- 复用既有冻结 helper（`_hashes` / `_hist_coordinator`）以保证语义一致；
- 以**独立 OS 进程**方式运行 worker（文件 IPC，不使用管道）。

安全边界：只连隔离容器中的 ``blr_pg_*_test`` 库；绝不触碰正式
``blessed_land.sqlite`` / live ``plugin_data`` / World Seed / 正式 world_id。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKER_MODULE = "tests.pg_functional_worker"

#: 本阶段允许的测试库名前缀（库名必须含 "test" → 门禁守卫 fail-closed 语义）
TEST_DB_PREFIX = "blr_pg_functional_test"

DEFAULT_WORKER_TIMEOUT = 1800.0


def base_dsn_or_skip() -> str:
    """复用单一来源的 PG gated 守卫（缺变量 → skip；库名不含 test → fail-closed）。"""
    from tests.test_pg_recovery_checkpoint_portability import _pg_dsn_or_skip
    return _pg_dsn_or_skip()


def psycopg_dsn(dsn: str) -> str:
    """SQLAlchemy DSN → psycopg 直连 DSN。"""
    url = make_url(dsn)
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def admin_dsn(dsn: str) -> str:
    url = make_url(dsn)
    return url.set(database="postgres").set(
        drivername="postgresql").render_as_string(hide_password=False)


def dsn_for_database(dsn: str, name: str) -> str:
    return make_url(dsn).set(database=name).render_as_string(hide_password=False)


def database_name(dsn: str) -> str:
    return make_url(dsn).database or ""


def _admin_execute(sql: str) -> None:
    import psycopg
    from tests.pg_functional_support import base_dsn_or_skip as _guard  # noqa: F401
    with psycopg.connect(admin_dsn(base_dsn_or_skip()),
                         autocommit=True) as conn:
        conn.execute(sql)


def reset_database(name: str, *, base: str | None = None) -> str:
    """DROP（含 FORCE）+ CREATE 专用测试库；返回该库的 DSN。"""
    base = base or base_dsn_or_skip()
    if "test" not in name.lower():
        raise AssertionError(f"拒绝在非测试库名上操作（fail-closed）: {name!r}")
    import psycopg
    with psycopg.connect(admin_dsn(base), autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{name}"')
    return dsn_for_database(base, name)


def drop_database(name: str, *, base: str | None = None) -> None:
    base = base or base_dsn_or_skip()
    import psycopg
    with psycopg.connect(admin_dsn(base), autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def fresh_env(index: int, world_id: str, *, seed: bool = True) -> dict:
    """合成 ACTIVE 世界 + 已迁移 schema（PG 版 `_fresh_m3`）。

    seed=True 时播种 mini world（生态/社会/灾劫全开），与 SQLite 侧完全同构。
    """
    from XiaoguangBlessedLandRuntime.database.db import (
        create_db_engine, make_session_factory)
    from XiaoguangBlessedLandRuntime.database.models_core import WorldRuntime
    from XiaoguangBlessedLandRuntime.domain.constants import RuntimeStatus
    from XiaoguangBlessedLandRuntime.services.db_lifecycle import migrate_database
    from XiaoguangBlessedLandRuntime.services.repositories import (
        RuntimeRepository, TimeRatioRepository)
    from XiaoguangBlessedLandRuntime.services.simulation.mini_world import (
        seed_mini_world)
    from XiaoguangBlessedLandRuntime.services.simulation.tribulation import (
        M3A_SIMULATION_VERSION)

    from tests.conftest import EPOCH0, EPOCH0_US

    name = f"{TEST_DB_PREFIX}_{index}"
    dsn = reset_database(name)
    migrate_database(dsn, project_root=PROJECT_ROOT)
    engine = create_db_engine(dsn)
    factory = make_session_factory(engine)
    with factory() as s:
        RuntimeRepository(s).create_not_activated(
            world_id=world_id, world_bible_version="1.0",
            simulation_version=M3A_SIMULATION_VERSION,
            world_bible_manifest_hash="pg-functional")
        row = s.execute(select(WorldRuntime)).scalar_one()
        row.runtime_status = RuntimeStatus.ACTIVE
        row.world_seed_version = "PG-FUNCTIONAL-TEST-SEED"
        row.current_blessed_tick = 0
        row.last_committed_real_us = EPOCH0_US
        row.time_rate_remainder = 0
        rate = TimeRatioRepository(s).add(
            world_id=world_id, real_effective_from=EPOCH0,
            rate_numerator=1_000_000, rate_denominator=86_400_000_000,
            reason="TEST", source="TEST")
        row.current_time_ratio_id = rate.ratio_id
        if seed:
            seed_mini_world(s, with_ecology=True, with_social=True,
                            with_tribulation=True, world_id=world_id)
        s.commit()
    return {"dsn": dsn, "engine": engine, "factory": factory,
            "world_id": world_id, "db_name": name}


def hashes(env) -> dict:
    """复用冻结的三哈希口径（world / event stream / causal history）。"""
    from tests.test_m3_integrated_long import _hashes
    return _hashes(env)


def m3_run(env, *, years: int, start_year: int = 0,
           restart_every_years: int | None = None):
    """PG 上的 direct 仿真（与 SQLite 侧同一 runner / 同一 coordinator）。"""
    from XiaoguangBlessedLandRuntime.services.simulation.m3a_runner import (
        run_m3a_world)
    from tests.test_m3b_history import _hist_coordinator
    return run_m3a_world(env["factory"], coordinator=_hist_coordinator(),
                         world_id=env["world_id"], years=years,
                         start_year=start_year,
                         restart_every_years=restart_every_years)


def scheduler_to(env, *, budget_years: int, target_years: int, state_dir: Path):
    """按 budget 分块推进（chunk equivalence 的 PG 侧入口）。"""
    from tests.test_scheduler_catchup import run_scheduler_to
    return run_scheduler_to(
        env, budget_ticks=budget_years * 1_000_000,
        target_years=target_years, provider_years=target_years,
        state_dir=state_dir)


def counts(env) -> dict:
    from sqlalchemy import text
    with env["factory"]() as s:
        out = {}
        for table in ("world_events", "simulation_checkpoints", "simulation_run",
                      "world_runtime", "runtime_lock"):
            out[table] = s.execute(
                text(f"SELECT COUNT(*) FROM {table}")).scalar()
        out["current_blessed_tick"] = s.execute(text(
            "SELECT current_blessed_tick FROM world_runtime")).scalar()
    return out


def live_lease_rows(env) -> int:
    """当前**未过期**租约行数（MAX_AUTHORITATIVE_WRITERS 的 DB 侧证据）。"""
    from sqlalchemy import text
    with env["factory"]() as s:
        return int(s.execute(text(
            "SELECT COUNT(*) FROM runtime_lock WHERE expires_at > now()")
        ).scalar() or 0)


# ---------------------------------------------------------------- 进程级 worker
def spawn_worker(job: dict, out_path: Path, *,
                 python: str | None = None) -> subprocess.Popen:
    """启动独立 OS 进程 worker（stdout/stderr 丢弃，结果经文件回传）。"""
    job_path = out_path.with_suffix(".job.json")
    job_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    return subprocess.Popen(
        [python or sys.executable, "-m", WORKER_MODULE,
         str(job_path), str(out_path)],
        cwd=str(PROJECT_ROOT), stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_worker(proc: subprocess.Popen, out_path: Path, *,
                timeout: float = DEFAULT_WORKER_TIMEOUT) -> dict:
    """等待 worker 结果文件；超时 → 只结束该 PID（绝不按名字批量杀）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if out_path.exists():
            try:
                return json.loads(out_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        if proc.poll() is not None and out_path.exists():
            return json.loads(out_path.read_text(encoding="utf-8"))
        time.sleep(0.2)
    proc.terminate()          # 仅该 PID
    raise AssertionError(f"worker 超时（{timeout}s）: {out_path}")

# -*- coding: utf-8 -*-
"""PRE-M6 PG COMMIT AMBIGUITY GATE —— 支持模块（TEST ONLY）。

设计依据：docs/pre_m6_pg_commit_ambiguity_audit.md（§5 harness 要求）。
原则：
- **只复用生产机制**：`catch_up` / `run_blessed_year` / `WriterLease` /
  `WorldMutationContext` / `SimulationRunRepository.committed_for_interval` /
  `latest_authoritative_world_checkpoint` / `HistoryService.history_integrity_audit`；
  不新设计 commit protocol。
- **durable truth 只来自 PostgreSQL**（§15）；内存态与本地文件一律不作真值。
- **BLIND_RETRY_COUNT 可断言**（§16）：恢复驱动必须先查 durable truth 再决定提交。
- 专用合成库 `blr_pg_commit_ambiguity_test`、world id `PGAMB-*`、synthetic 速率；
  绝不触碰正式库 / live / StayOps / functional gate 的库。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import text

from tests.pg_functional_support import (admin_dsn, base_dsn_or_skip,
                                        database_name, dsn_for_database,
                                        psycopg_dsn, spawn_worker as _spawn,
                                        wait_worker as _wait)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AMBIGUITY_DB = "blr_pg_commit_ambiguity_test"
REFERENCE_DB = "blr_pg_commit_ambiguity_ref_test"
WORKER_MODULE = "tests.pg_ambiguity_worker"
CONTAINER = "blr-pre-m6-postgres"
EPOCH0_US_DEFAULT = None  # 运行时由 tests.conftest 提供

#: durable outcome 分类
ALREADY_COMMITTED = "ALREADY_COMMITTED"
NOT_COMMITTED = "NOT_COMMITTED"
RUNNING_STALE = "RUNNING_STALE"      # 阶段 1 残留（设计内，可安全重做）


def ambiguity_dsn() -> str:
    """专用合成库 DSN（库名含 test → 门禁守卫允许）。"""
    return dsn_for_database(base_dsn_or_skip(), AMBIGUITY_DB)


def reference_dsn() -> str:
    """无故障 direct 参照库 DSN（同一 world_id、同一 synthetic seed）。"""
    return dsn_for_database(base_dsn_or_skip(), REFERENCE_DB)


def _admin(sql: str) -> None:
    import psycopg
    with psycopg.connect(admin_dsn(base_dsn_or_skip()), autocommit=True) as c:
        c.execute(sql)


def reset_db(name: str) -> str:
    """DROP（FORCE）+ CREATE + 迁移；返回该库 DSN。"""
    if "test" not in name.lower():
        raise AssertionError(f"拒绝在非测试库名上操作（fail-closed）: {name!r}")
    _admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    _admin(f'CREATE DATABASE "{name}"')
    dsn = dsn_for_database(base_dsn_or_skip(), name)
    from XiaoguangBlessedLandRuntime.services.db_lifecycle import migrate_database
    migrate_database(dsn, project_root=PROJECT_ROOT)
    return dsn


def reset_ambiguity_db() -> str:
    return reset_db(AMBIGUITY_DB)


def reset_reference_db() -> str:
    return reset_db(REFERENCE_DB)


def drop_ambiguity_db() -> None:
    _admin(f'DROP DATABASE IF EXISTS "{AMBIGUITY_DB}" WITH (FORCE)')


def seed_world(dsn: str, world_id: str, *, active: bool = True) -> dict:
    """合成 ACTIVE 世界 + mini world（与 SQLite 参照同构；synthetic seed）。"""
    from sqlalchemy import select

    from XiaoguangBlessedLandRuntime.database.db import (
        create_db_engine, make_session_factory)
    from XiaoguangBlessedLandRuntime.database.models_core import WorldRuntime
    from XiaoguangBlessedLandRuntime.domain.constants import RuntimeStatus
    from XiaoguangBlessedLandRuntime.services.repositories import (
        RuntimeRepository, TimeRatioRepository)
    from XiaoguangBlessedLandRuntime.services.simulation.mini_world import (
        seed_mini_world)
    from XiaoguangBlessedLandRuntime.services.simulation.tribulation import (
        M3A_SIMULATION_VERSION)

    from tests.conftest import EPOCH0, EPOCH0_US

    engine = create_db_engine(dsn)
    factory = make_session_factory(engine)
    with factory() as s:
        RuntimeRepository(s).create_not_activated(
            world_id=world_id, world_bible_version="1.0",
            simulation_version=M3A_SIMULATION_VERSION,
            world_bible_manifest_hash="pg-ambiguity")
        row = s.execute(select(WorldRuntime).where(
            WorldRuntime.world_id == world_id)).scalar_one()
        if active:
            row.runtime_status = RuntimeStatus.ACTIVE
            row.world_seed_version = "M3-LONG-TEST-SEED-001"
            row.current_blessed_tick = 0
            row.last_committed_real_us = EPOCH0_US
            row.time_rate_remainder = 0
            rate = TimeRatioRepository(s).add(
                world_id=world_id, real_effective_from=EPOCH0,
                rate_numerator=1_000_000, rate_denominator=86_400_000_000,
                reason="TEST", source="TEST")
            row.current_time_ratio_id = rate.ratio_id
            seed_mini_world(s, with_ecology=True, with_social=True,
                            with_tribulation=True, world_id=world_id)
        s.commit()
    return {"dsn": dsn, "engine": engine, "factory": factory,
            "world_id": world_id}


# --------------------------------------------------------------- durable truth
def durable_tick(factory, world_id: str) -> int | None:
    with factory() as s:
        return s.execute(text(
            "SELECT current_blessed_tick FROM world_runtime WHERE world_id = :w"),
            {"w": world_id}).scalar()


def durable_real_cursor(factory, world_id: str) -> int | None:
    with factory() as s:
        return s.execute(text(
            "SELECT last_committed_real_us FROM world_runtime WHERE world_id = :w"),
            {"w": world_id}).scalar()


def committed_run_for_interval(factory, world_id: str, start_us: int,
                               end_us: int, simulation_version: str):
    """生产查找路径：同区间已 COMMITTED 的 run（幂等命中）。"""
    from XiaoguangBlessedLandRuntime.services.run_lifecycle import (
        SimulationRunRepository)
    with factory() as s:
        return SimulationRunRepository(s).committed_for_interval(
            world_id, simulation_version, start_us, end_us)


def stale_running_runs(factory, world_id: str) -> int:
    with factory() as s:
        return int(s.execute(text(
            "SELECT COUNT(*) FROM simulation_run WHERE world_id = :w "
            "AND status = 'RUNNING'"), {"w": world_id}).scalar() or 0)


def lease_live(factory, world_id: str) -> bool:
    """durable 租约是否仍未过期（等待自然过期用；**不修改 DB**）。"""
    with factory() as s:
        n = s.execute(text(
            "SELECT COUNT(*) FROM runtime_lock WHERE world_id = :w "
            "AND expires_at > now()"), {"w": world_id}).scalar()
    return bool(n)


def wait_lease_expiry(factory, world_id: str, *, timeout: float = 300.0,
                      poll: float = 1.0) -> float:
    """等待被杀 writer 的租约**自然过期**（生产 STALE_WRITER_RECOVERY 语义）。

    绝不手工 UPDATE runtime_lock —— 接管必须由生产 CAS 路径完成。
    """
    started = time.time()
    while time.time() - started < timeout:
        if not lease_live(factory, world_id):
            return time.time() - started
        time.sleep(poll)
    raise AssertionError(f"租约在 {timeout}s 内未过期（world={world_id}）")


def authoritative_hashes(factory, world_id: str) -> dict:
    from tests.test_m3_integrated_long import _hashes
    return _hashes({"factory": factory, "world_id": world_id})


def history_audit(factory, world_id: str) -> dict:
    from XiaoguangBlessedLandRuntime.services.history.service import (
        HistoryService)
    return HistoryService(factory).history_integrity_audit(world_id=world_id)


# ------------------------------------------------------- 恢复驱动（BLIND_RETRY）
@dataclass
class RecoveryDriver:
    """先查 durable truth、再决定是否提交的恢复驱动（§15/§16）。"""

    factory: object
    world_id: str
    epoch0_us: int
    simulation_version: str
    blind_retry_count: int = 0
    blind_retry_probes: int = 0
    lookups: int = 0
    _looked_up: set = field(default_factory=set)

    def year_interval(self, year_index: int) -> tuple[int, int]:
        from XiaoguangBlessedLandRuntime.services.simulation.harness import (
            YEAR_US)
        return (self.epoch0_us + year_index * YEAR_US,
                self.epoch0_us + (year_index + 1) * YEAR_US)

    def classify(self, year_index: int) -> dict:
        """**只读** durable truth → COMMITTED / NOT_COMMITTED（+ 证据）。"""
        from XiaoguangBlessedLandRuntime.services.simulation.harness import (
            YEAR_US)
        self.lookups += 1
        self._looked_up.add(year_index)
        start_us, end_us = self.year_interval(year_index)
        year_end_tick = (year_index + 1) * 1_000_000
        tick = durable_tick(self.factory, self.world_id)
        cursor = durable_real_cursor(self.factory, self.world_id)
        run = committed_run_for_interval(self.factory, self.world_id,
                                         start_us, end_us,
                                         self.simulation_version)
        stale = stale_running_runs(self.factory, self.world_id)
        if (tick is not None and tick >= year_end_tick) or run is not None:
            outcome = ALREADY_COMMITTED
        elif stale:
            outcome = RUNNING_STALE
        else:
            outcome = NOT_COMMITTED
        return {"outcome": outcome, "durable_tick": tick,
                "durable_cursor_us": cursor, "interval": (start_us, end_us),
                "committed_run_id": run.run_id if run is not None else None,
                "stale_running_runs": stale,
                "expected_year_end_tick": year_end_tick}

    def submit_year(self, year_index: int, *, owner: str, token: str,
                    coordinator=None) -> dict:
        """经生产 `run_blessed_year` 提交一年（**必须先 classify**）。"""
        if year_index not in self._looked_up:
            self.blind_retry_count += 1
        return run_year(self.factory, self.world_id, year_index,
                        owner=owner, token=token, coordinator=coordinator,
                        epoch0_us=self.epoch0_us)

    def blind_probe(self, year_index: int, *, owner: str, token: str,
                    coordinator=None) -> dict:
        """CA-06 受控实验：**故意**不查 durable truth 直接重提（计为 probe）。"""
        self.blind_retry_probes += 1
        return run_year(self.factory, self.world_id, year_index,
                        owner=owner, token=token, coordinator=coordinator,
                        epoch0_us=self.epoch0_us)


def run_year(factory, world_id: str, year_index: int, *, owner: str, token: str,
             coordinator=None, epoch0_us: int) -> dict:
    """生产路径的一年推进（`run_blessed_year` → `catch_up`）。"""
    from XiaoguangBlessedLandRuntime.services.scheduler.adapter import (
        run_blessed_year)
    from XiaoguangBlessedLandRuntime.services.simulation.tribulation import (
        M3A_SIMULATION_VERSION)

    class _Lease:
        pass
    lease = _Lease()
    lease.owner = owner
    lease.token = token
    try:
        run_blessed_year(factory, world_id=world_id, year_index=year_index,
                         coordinator=coordinator, lease=lease,
                         epoch0_us=epoch0_us,
                         simulation_version=M3A_SIMULATION_VERSION)
        return {"client_outcome": "SUCCESS", "error_type": None,
                "error": None}
    except BaseException as exc:  # noqa: BLE001
        return {"client_outcome": "ERROR", "error_type": type(exc).__name__,
                "error": str(exc)[:400]}


# ------------------------------------------------------------------ invariants
def invariants(factory, world_id: str, *, expected_years: int,
               stale_token: str | None = None,
               takeover_at=None) -> dict:
    """§17 硬指标（全部来自 durable state）。"""
    with factory() as s:
        dup_intervals = s.execute(text(
            "SELECT real_interval_start_us, real_interval_end_us, COUNT(*) c "
            "FROM simulation_run WHERE world_id = :w AND status = 'COMMITTED' "
            "GROUP BY 1,2 HAVING COUNT(*) > 1"), {"w": world_id}).fetchall()
        dup_checkpoints = s.execute(text(
            "SELECT checkpoint_blessed_tick, COUNT(*) c FROM "
            "simulation_checkpoints WHERE world_id = :w AND complete = true "
            "AND meta ->> 'checkpoint_kind' = 'WORLD_COMMITTED' "
            "GROUP BY 1 HAVING COUNT(*) > 1"), {"w": world_id}).fetchall()
        forked = s.execute(text(
            "SELECT checkpoint_blessed_tick, "
            "(meta ->> 'checkpoint_kind') kind, "
            "COUNT(DISTINCT world_state_hash) c "
            "FROM simulation_checkpoints WHERE world_id = :w AND complete = true "
            "GROUP BY 1, 2 HAVING COUNT(DISTINCT world_state_hash) > 1"),
            {"w": world_id}).fetchall()
        dup_events = s.execute(text(
            "SELECT event_uid, COUNT(*) c FROM world_events WHERE world_id = :w "
            "GROUP BY 1 HAVING COUNT(*) > 1"), {"w": world_id}).fetchall()
        dup_links = s.execute(text(
            "SELECT link_id, COUNT(*) c FROM causal_history_links "
            "WHERE world_id = :w GROUP BY 1 HAVING COUNT(*) > 1"),
            {"w": world_id}).fetchall()
        committed_ticks = [r[0] for r in s.execute(text(
            "SELECT DISTINCT committed_until_tick FROM simulation_run "
            "WHERE world_id = :w AND status = 'COMMITTED' AND "
            "committed_until_tick IS NOT NULL"), {"w": world_id}).fetchall()]
        tick = s.execute(text(
            "SELECT current_blessed_tick FROM world_runtime WHERE world_id = :w"),
            {"w": world_id}).scalar()
        stale_mutations = 0
        if stale_token is not None:
            stale_mutations = int(s.execute(text(
                "SELECT COUNT(*) FROM simulation_run WHERE world_id = :w AND "
                "fencing_token = :t"), {"w": world_id, "t": stale_token}).scalar()
                or 0)
            if takeover_at is not None:
                stale_mutations = int(s.execute(text(
                    "SELECT COUNT(*) FROM simulation_run WHERE world_id = :w "
                    "AND fencing_token = :t AND started_at > :ts"),
                    {"w": world_id, "t": stale_token,
                     "ts": takeover_at}).scalar() or 0)

    expected = {y * 1_000_000 for y in range(1, expected_years + 1)}
    have = set(committed_ticks)
    audit = history_audit(factory, world_id)
    return {
        "duplicate_ticks": len(dup_intervals) + len(dup_checkpoints),
        "duplicate_interval_samples": [tuple(r) for r in dup_intervals],
        "duplicate_checkpoint_samples": [tuple(r) for r in dup_checkpoints],
        "duplicate_history_events": len(dup_events) + len(dup_links),
        "duplicate_event_samples": [tuple(r) for r in dup_events],
        "duplicate_link_samples": [tuple(r) for r in dup_links],
        "lost_ticks": len(expected - have),
        "lost_tick_samples": sorted(expected - have)[:10],
        "forked_history": len(forked),
        "forked_samples": [tuple(r) for r in forked],
        "stale_writer_mutations": stale_mutations,
        "final_tick": tick,
        "history_orphan_links": audit["orphan_links"],
        "history_causal_cycles": audit["cycle_count"],
        "history_invalid_refs": len(audit["invalid_relations"])
                                + audit["tick_paradox_links"],
        "history_clean": audit["clean"],
    }


# ------------------------------------------------------------- fault injection
def backend_pid_of(dsn_psycopg: str) -> int:
    import psycopg
    with psycopg.connect(dsn_psycopg) as c:
        return int(c.execute("SELECT pg_backend_pid()").fetchone()[0])


def terminate_backend(pid: int) -> bool:
    """真实 PG backend 终止（控制连接执行，模拟 COMMIT 期连接故障）。"""
    import psycopg
    with psycopg.connect(psycopg_dsn(ambiguity_dsn()), autocommit=True) as c:
        return bool(c.execute("SELECT pg_terminate_backend(%s)", (pid,))
                    .fetchone()[0])


def container_restart() -> None:
    """仅重启本阶段测试容器（绝不碰 stayops-postgres / live）。"""
    subprocess.run(["docker", "restart", CONTAINER], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_pg_healthy(timeout: float = 120.0) -> str:
    deadline = time.time() + timeout
    status = "unknown"
    while time.time() < deadline:
        out = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Health.Status}}",
             CONTAINER], capture_output=True, text=True)
        status = (out.stdout or "").strip() or "unknown"
        if status == "healthy":
            return status
        time.sleep(2)
    return status


# ------------------------------------------------------------- 进程编排封装
def sentinel_paths(out_path: Path) -> dict[str, Path]:
    """worker 阶段通报文件（IPC；单一来源，worker 与 controller 共用）。

    - ``inside_tx`` ：事务已开始（run_step 入口）
    - ``pre_commit``：本步工作已就绪、即将返回 → mutation context 立即 COMMIT
                      （在此 kill 可与 COMMIT 真实竞速）
    - ``committed`` ：durable commit 已完成、应用确认尚未写出
    """
    base = str(out_path.with_suffix(""))
    return {"started": Path(base + ".started.json"),
            "inside_tx": Path(base + ".inside_tx.json"),
            "pre_commit": Path(base + ".pre_commit.json"),
            "committed": Path(base + ".committed.json")}


def spawn(job: dict, out_path: Path):
    """独立 OS 进程 worker（stdout/stderr 丢弃，结果文件回传）。"""
    job2 = dict(job)
    job2.setdefault("dsn", ambiguity_dsn())
    job_path = out_path.with_suffix(".job.json")
    job_path.write_text(json.dumps(job2, ensure_ascii=False), encoding="utf-8")
    return subprocess.Popen(
        [sys.executable, "-m", WORKER_MODULE, str(job_path), str(out_path)],
        cwd=str(PROJECT_ROOT), stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_sentinel(path: Path, *, timeout: float = 120.0,
                  poll: float = 0.05) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        time.sleep(poll)
    raise AssertionError(f"sentinel 超时: {path}")


def wait_result(path: Path, *, timeout: float = 600.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        time.sleep(0.1)
    raise AssertionError(f"worker 结果超时: {path}")


def kill_worker(proc, *, pid: int | None = None, timeout: float = 60.0) -> None:
    """按**显式 PID** 终止 worker（Windows venv 启动器下 Popen.pid 只是 stub）。

    只使用显式 PID 的强制终止形式（``taskkill /F /PID``）——满足仓库
    PROCESS_KILL_SCOPE 契约（tests/test_process_kill_scope.py），
    绝不按进程名批量 kill（owner §10）。
    """
    import subprocess

    for p in [x for x in (pid, proc.pid) if x]:
        subprocess.run(["taskkill", "/F", "/PID", str(p)],
                       capture_output=True)
    try:
        proc.wait(timeout=timeout)
    except Exception:  # noqa: BLE001
        pass

# -*- coding: utf-8 -*-
"""PRE-M6 PG COMMIT AMBIGUITY GATE —— 独立 OS 进程 worker（TEST ONLY）。

用法：python -m tests.pg_ambiguity_worker <job.json> <out.json>

actions：
- ``advance_year``     ：真实生产年推进（WriterLease + run_blessed_year → catch_up）。
                         支持 in-transaction 慢点（扩大故障窗口）与
                         "durable commit 后阻塞不得写应用确认"（ACK lost 窗口）。
                         通过 sentinel 文件向 controller 通报阶段（IPC，不写 DB 结果）。
- ``scheduler_cycle``  ：完整生产调度器一轮（RuntimeScheduler.start + run_cycle）。
- ``recover_continue`` ：生产 recovery 路径（先查 durable truth，仅在 NOT_COMMITTED/
                         RUNNING_STALE 时才提交；统计 BLIND_RETRY_COUNT）。
- ``stale_retry``      ：旧 token/owner 尝试重提（必须被 fencing 拒绝）。
- ``dump``             ：输出计数与三哈希。

sentinel（与 tests/pg_ambiguity_support.sentinel_paths 一致）：
  <out 去扩展名>.started.json   {pid, backend_pid, phase}
  <out 去扩展名>.inside_tx.json {backend_pid, year_index, phase}
  <out 去扩展名>.committed.json {year_index, phase}   ← durable commit 后、应用确认前
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ sentinels
from tests.pg_ambiguity_support import sentinel_paths  # noqa: E402  (单一来源)


def write_sentinel(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def clear_sentinels(out_path: Path) -> None:
    for p in sentinel_paths(out_path).values():
        p.unlink(missing_ok=True)


# ------------------------------------------------------------------- factories
def engine_factory(dsn: str):
    from XiaoguangBlessedLandRuntime.database.db import (
        create_db_engine, make_session_factory)
    engine = create_db_engine(dsn)
    return engine, make_session_factory(engine)


def _epoch0_us() -> int:
    from tests.conftest import EPOCH0_US
    return EPOCH0_US


def release_with_token(dsn: str, world_id: str, token: str | None) -> bool:
    """用生产 `WriterLease.release()`（token 匹配才删）释放租约。

    必须使用**全新 engine**：backend 被终止后，原连接池中的连接已损坏，
    复用会导致释放失败并残留租约（进而阻塞后续接管）。
    """
    if not token:
        return False
    from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease
    try:
        engine, factory = engine_factory(dsn)
        session = factory()
        lease = WriterLease(session, world_id, 120)
        lease.token = token
        lease.release()
        session.close()
        engine.dispose()
        return True
    except Exception:  # noqa: BLE001
        return False


class SlowCoordinator:
    """在事务内写入 inside_tx sentinel 并可注入可控延时（生产公开扩展点）。"""

    def __init__(self, inner, *, out_path: Path, slow_ms: int):
        self.inner = inner
        self.out_path = out_path
        self.slow_ms = slow_ms
        self._signalled = False
        self._pre_commit_signalled = False

    def run_step(self, session, **kwargs):
        if not self._signalled:
            self._signalled = True
            backend = int(session.execute(
                text("SELECT pg_backend_pid()")).scalar())
            write_sentinel(sentinel_paths(self.out_path)["inside_tx"],
                           {"phase": "INSIDE_TX", "backend_pid": backend,
                            "pid": os.getpid(), "at": time.time()})
        if self.slow_ms > 0:
            session.execute(text("SELECT pg_sleep(:s)"),
                            {"s": self.slow_ms / 1000.0})
        result = self.inner.run_step(session, **kwargs)
        # 本步工作已就绪，返回后 mutation context 立即执行 COMMIT：
        # 在此刻通知 controller 可与 COMMIT 真实竞速（harness 侧 IPC，不改生产语义）
        if not self._pre_commit_signalled:
            self._pre_commit_signalled = True
            backend = int(session.execute(
                text("SELECT pg_backend_pid()")).scalar())
            write_sentinel(sentinel_paths(self.out_path)["pre_commit"],
                           {"phase": "PRE_COMMIT", "backend_pid": backend,
                            "pid": os.getpid(), "at": time.time()})
        return result


# -------------------------------------------------------------------- actions
def action_advance_year(job: dict, out_path: Path) -> dict:
    """真实年推进；写 started/inside_tx/committed sentinel；可选 commit 后阻塞。"""
    from XiaoguangBlessedLandRuntime.services.scheduler.adapter import (
        run_blessed_year)
    from XiaoguangBlessedLandRuntime.services.simulation.tribulation import (
        M3A_SIMULATION_VERSION)
    from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease

    clear_sentinels(out_path)
    engine, factory = engine_factory(job["dsn"])
    world_id = job["world_id"]
    year_index = int(job["year_index"])
    epoch0 = _epoch0_us()

    session = factory()
    lease = WriterLease(session, world_id, int(job.get("lease_seconds", 60)),
                        owner=job.get("owner"))
    try:
        lease.acquire()
    except Exception as exc:  # noqa: BLE001
        write_sentinel(sentinel_paths(out_path)["started"],
                       {"phase": "LEASE_REJECTED", "error": str(exc)[:200]})
        session.close()
        engine.dispose()
        return {"lease": "REJECTED", "error": repr(exc)}

    with factory() as s:
        backend = int(s.execute(text("SELECT pg_backend_pid()")).scalar())
    write_sentinel(sentinel_paths(out_path)["started"],
                   {"phase": "LEASED", "pid": os.getpid(),
                    "backend_pid": backend, "year_index": year_index,
                    "owner": lease.owner, "token": lease.token})

    from tests.test_m3b_history import _hist_coordinator
    inner = _hist_coordinator()
    coordinator = SlowCoordinator(inner, out_path=out_path,
                                  slow_ms=int(job.get("slow_ms", 0)))

    result: dict[str, Any] = {"year_index": year_index, "owner": lease.owner,
                              "token": lease.token, "pid": os.getpid(),
                              "backend_pid": backend}
    try:
        run_blessed_year(factory, world_id=world_id, year_index=year_index,
                         coordinator=coordinator, lease=lease,
                         epoch0_us=epoch0, simulation_version=M3A_SIMULATION_VERSION)
        result["client_outcome"] = "SUCCESS"
    except BaseException as exc:  # noqa: BLE001
        result["client_outcome"] = "ERROR"
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)[:400]
        write_sentinel(sentinel_paths(out_path)["committed"],
                       {"phase": "CLIENT_ERROR_BEFORE_ACK", "error_type":
                        result["error_type"]})
        if job.get("release_on_error", True):
            # 生产 release 路径（token 匹配才删；被接管则不动）——"writer 自行释放"
            result["released"] = release_with_token(job["dsn"], world_id,
                                                    lease.token)
        session.close()
        engine.dispose()
        return result

    # durable commit 已完成；**应用确认尚未写出** → 通知 controller 后阻塞
    write_sentinel(sentinel_paths(out_path)["committed"],
                   {"phase": "COMMITTED_UNACKED", "year_index": year_index,
                    "pid": os.getpid(), "at": time.time()})
    block = float(job.get("block_after_commit_seconds", 0) or 0)
    wrote_ack = False
    if block:
        time.sleep(block)
    if job.get("ack_after_block"):
        # 仅用于"无故障 direct 参照"：模拟应用确认
        wrote_ack = True
    if job.get("release_on_exit", True):
        # 用**新 session** 做 token 匹配释放：原 session 可能已被 backend 终止而损坏
        result["released"] = release_with_token(job["dsn"], world_id, lease.token)
    result["app_ack_written"] = wrote_ack
    session.close()
    engine.dispose()
    return result


def action_scheduler_cycle(job: dict, out_path: Path) -> dict:
    """生产调度器一轮（真实 commit → 真实 checkpoint 写；供 ACK lost / CA-08 用例）。

    记录：run_cycle 是否抛出、抛出类型、以及抛出**之后**的调度器状态
    （用于检验「连接故障是否进入 durable-truth 核对 / fail-closed」）。
    """
    from XiaoguangBlessedLandRuntime.services.scheduler import (
        RuntimeScheduler, SchedulerConfig)
    from XiaoguangBlessedLandRuntime.services.simulation.harness import YEAR_US

    clear_sentinels(out_path)
    engine, factory = engine_factory(job["dsn"])
    world_id = job["world_id"]
    epoch0 = _epoch0_us()
    state_dir = Path(job["state_dir"])
    state_dir.mkdir(parents=True, exist_ok=True)
    target_years = int(job.get("target_years", 1))
    slow_ms = int(job.get("slow_ms", 0))

    def provider():
        inner = _hist_coordinator_ref()
        if slow_ms <= 0:
            return inner
        return SlowCoordinator(inner, out_path=out_path, slow_ms=slow_ms)

    sched = RuntimeScheduler(
        session_factory=factory, world_id=world_id,
        config=SchedulerConfig(catch_up_max_ticks_per_cycle=target_years * 1_000_000),
        real_now_us_provider=lambda: epoch0 + target_years * YEAR_US,
        epoch0_us=epoch0, coordinator_provider=provider,
        state_dir=state_dir)
    sched.start()
    write_sentinel(sentinel_paths(out_path)["started"],
                   {"phase": "SCHEDULER_STARTED", "pid": os.getpid(),
                    "year_index": target_years - 1})
    error = None
    try:
        snap = sched.run_cycle().as_dict()
    except BaseException as exc:  # noqa: BLE001
        import traceback
        snap = None
        error = {"type": type(exc).__name__, "msg": str(exc)[:300],
                 "traceback": traceback.format_exc()[-800:]}
    status = sched.get_scheduler_status()
    state_file = state_dir / "scheduler_state.json"
    result = {"cycle": (snap or {}).get("cycle"),
              "durable_current_tick": (snap or {}).get("durable_current_tick"),
              "scheduler_state": (snap or {}).get("scheduler_state"),
              "error": error,
              "status_after_error": status,
              "state_file_exists": state_file.exists(),
              "pid": os.getpid()}
    write_sentinel(sentinel_paths(out_path)["committed"],
                   {"phase": "SCHEDULER_CYCLE_DONE",
                    "durable_current_tick": result["durable_current_tick"],
                    "error": error})
    engine.dispose()
    return result


def _hist_coordinator_ref():
    from tests.test_m3b_history import _hist_coordinator
    return _hist_coordinator()


def acquire_with_expiry_wait(factory, world_id: str, *, seconds: int = 120,
                             timeout: float = 500.0):
    """获取租约；若仍被上一 writer 持有则**等待自然过期**后重试（生产接管语义）。

    绝不手工 UPDATE runtime_lock —— 接管只能由生产 CAS 路径完成。
    """
    from XiaoguangBlessedLandRuntime.domain.errors import WriterLockConflict
    from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease
    deadline = time.time() + timeout
    while True:
        session = factory()
        lease = WriterLease(session, world_id, seconds)
        try:
            lease.acquire()
            return session, lease
        except WriterLockConflict:
            session.close()
            if time.time() > deadline:
                raise
            time.sleep(2.0)


def action_recover_continue(job: dict, out_path: Path) -> dict:
    """生产 recovery 路径 + 可继续推进；输出 BLIND_RETRY_COUNT 与不变量。"""
    from tests.pg_ambiguity_support import RecoveryDriver
    from XiaoguangBlessedLandRuntime.services.simulation.tribulation import (
        M3A_SIMULATION_VERSION)

    engine, factory = engine_factory(job["dsn"])
    world_id = job["world_id"]
    epoch0 = _epoch0_us()
    driver = RecoveryDriver(factory=factory, world_id=world_id,
                            epoch0_us=epoch0,
                            simulation_version=M3A_SIMULATION_VERSION)
    years = [int(y) for y in job.get("years", [])]
    classifications = []
    submissions = []
    coordinator = _hist_coordinator_ref()
    lease_session = None
    lease = None
    for year_index in years:
        info = driver.classify(year_index)
        classifications.append({"year_index": year_index,
                                "outcome": info["outcome"],
                                "durable_tick": info["durable_tick"]})
        if info["outcome"] == "ALREADY_COMMITTED":
            continue                     # 绝不重试
        # NOT_COMMITTED / RUNNING_STALE → 经生产路径提交
        # （必要时等待上一 writer 的租约**自然过期**后由生产 CAS 接管）
        if lease is None:
            lease_session, lease = acquire_with_expiry_wait(factory, world_id)
        submissions.append({"year_index": year_index,
                            "result": driver.submit_year(
                                year_index, owner=lease.owner,
                                token=lease.token, coordinator=coordinator)})
    if lease is not None:
        try:
            lease.release()
        except Exception:  # noqa: BLE001
            pass
        lease_session.close()

    from tests.pg_ambiguity_support import authoritative_hashes
    result = {"classifications": classifications, "submissions": submissions,
              "blind_retry_count": driver.blind_retry_count,
              "blind_retry_probes": driver.blind_retry_probes,
              "lookups": driver.lookups,
              "hashes": authoritative_hashes(factory, world_id)}
    engine.dispose()
    return result


def action_stale_retry(job: dict, out_path: Path) -> dict:
    """旧 token/owner 尝试提交（必须被 fencing 拒绝，零写入）。"""
    from tests.pg_ambiguity_support import run_year, durable_tick
    engine, factory = engine_factory(job["dsn"])
    world_id = job["world_id"]
    before = durable_tick(factory, world_id)
    outcome = run_year(factory, world_id, int(job["year_index"]),
                       owner=job["owner"], token=job["token"],
                       coordinator=_hist_coordinator_ref(),
                       epoch0_us=_epoch0_us())
    after = durable_tick(factory, world_id)
    engine.dispose()
    return {"outcome": outcome, "durable_tick_before": before,
            "durable_tick_after": after,
            "mutated": before != after}


def action_dump(job: dict, out_path: Path) -> dict:
    from tests.pg_ambiguity_support import authoritative_hashes, durable_tick
    engine, factory = engine_factory(job["dsn"])
    out = {"durable_tick": durable_tick(factory, job["world_id"]),
           "hashes": authoritative_hashes(factory, job["world_id"])}
    engine.dispose()
    return out


ACTIONS = {
    "advance_year": action_advance_year,
    "scheduler_cycle": action_scheduler_cycle,
    "recover_continue": action_recover_continue,
    "stale_retry": action_stale_retry,
    "dump": action_dump,
}


def main() -> int:
    job_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    job = json.loads(job_path.read_text(encoding="utf-8"))
    payload: dict
    try:
        payload = {"ok": True, "action": job["action"],
                   "result": ACTIONS[job["action"]](job, out_path)}
    except BaseException as exc:  # noqa: BLE001
        import traceback
        payload = {"ok": False, "action": job.get("action"),
                   "error": f"{type(exc).__name__}: {exc}",
                   "traceback": traceback.format_exc()[-1500:]}
    out_path.write_text(json.dumps(payload, ensure_ascii=False, default=str),
                        encoding="utf-8")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""PRE-M6 PG FUNCTIONAL GATE —— 独立 OS 进程 worker（TEST ONLY）。

用法：python -m tests.pg_functional_worker <job.json> <out.json>

为什么存在：owner §10 要求至少一组 writer contention 必须由**两个真实 OS 进程**
完成（独立 engine / 独立连接 / 独立进程状态），而不是两个 Python 对象或协程。
本 worker 以文件回传结果（不使用管道），父进程只以显式 PID 控制它。

支持的 action：
- ``acquire``         获取租约（可选 ``start_at_ms`` 做真实竞态、``hold_seconds`` 持锁）
- ``renew``           以给定 token 续约
- ``stale_mutation``  以给定（可能已 stale 的）token 尝试世界/history/checkpoint 写入
- ``run_years``       从 durable 状态推进 N 年（restart equivalence 的一侧）
- ``scheduler_budget`` 以 budget 分块推进到目标年（chunk equivalence 的一侧）
- ``dump``            输出当前计数与哈希

job 字段：dsn / world_id / action / years / start_year / budget_years /
target_years / state_dir / token / owner / lease_seconds / hold_seconds /
start_at_ms / release_on_exit
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _engine_factory(dsn: str):
    from XiaoguangBlessedLandRuntime.database.db import (
        create_db_engine, make_session_factory)
    engine = create_db_engine(dsn)
    return engine, make_session_factory(engine)


def _counts(factory, world_id: str) -> dict:
    from sqlalchemy import text
    with factory() as s:
        out = {}
        for table in ("world_events", "simulation_checkpoints", "simulation_run",
                      "world_runtime", "runtime_lock"):
            out[table] = s.execute(
                text(f"SELECT COUNT(*) FROM {table}")).scalar()
        out["current_blessed_tick"] = s.execute(text(
            "SELECT current_blessed_tick FROM world_runtime WHERE world_id = :w"),
            {"w": world_id}).scalar()
    return out


def _hashes(factory, world_id: str) -> dict:
    from tests.test_m3_integrated_long import _hashes
    return _hashes({"factory": factory, "world_id": world_id})


def _do_acquire(job: dict) -> dict:
    from XiaoguangBlessedLandRuntime.domain.errors import WriterLockConflict
    from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease
    start_at_ms = job.get("start_at_ms")
    if start_at_ms is not None:
        while time.time() * 1000 < start_at_ms:
            time.sleep(0.001)
    engine, factory = _engine_factory(job["dsn"])
    session = factory()
    lease = WriterLease(session, job["world_id"],
                        int(job.get("lease_seconds", 120)),
                        owner=job.get("owner"))
    out: dict = {"owner": lease.owner, "pid": None}
    import os
    out["pid"] = os.getpid()
    try:
        lease.acquire()
    except WriterLockConflict as exc:
        out.update(result="REJECTED", detail=str(exc))
        session.close()
        engine.dispose()
        return out
    out.update(result="ACQUIRED", token=lease.token)
    hold = float(job.get("hold_seconds") or 0)
    if hold:
        time.sleep(hold)
    if job.get("release_on_exit", True):
        try:
            lease.release()
        except Exception as exc:  # noqa: BLE001
            out["release_error"] = repr(exc)
    session.close()
    engine.dispose()
    return out


def _do_renew(job: dict) -> dict:
    from XiaoguangBlessedLandRuntime.domain.errors import WriterLockConflict
    from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease
    engine, factory = _engine_factory(job["dsn"])
    session = factory()
    lease = WriterLease(session, job["world_id"], int(job.get("lease_seconds", 120)))
    lease.token = job.get("token")
    try:
        lease.renew()
        result = "RENEWED"
    except WriterLockConflict as exc:
        result = "REJECTED"
        detail = str(exc)
    else:
        detail = ""
    session.close()
    engine.dispose()
    return {"result": result, "detail": detail}


def _do_stale_mutation(job: dict) -> dict:
    """以旧 token 尝试三类 mutation，全部必须被拒且零写入。"""
    from sqlalchemy import text

    from XiaoguangBlessedLandRuntime.domain.errors import FencingViolation
    from XiaoguangBlessedLandRuntime.services.fencing import WorldMutationContext
    from XiaoguangBlessedLandRuntime.services.repositories import EventRepository

    engine, factory = _engine_factory(job["dsn"])
    world_id = job["world_id"]
    before = _counts(factory, world_id)
    attempts: dict = {}

    # (a) world mutation（事件写入）
    with factory() as s:
        try:
            with WorldMutationContext(
                    s, world_id=world_id, writer_id=job["owner"],
                    fencing_token=job["token"]) as ctx:
                EventRepository(s).append(world_id=world_id, event_type="STALE",
                                          source="STALE-WRITER", blessed_tick=1)
                ctx.commit()
            attempts["world_mutation"] = "COMMITTED"
        except FencingViolation as exc:
            attempts["world_mutation"] = f"REJECTED: {exc}"
        except Exception as exc:  # noqa: BLE001
            attempts["world_mutation"] = f"REJECTED_OTHER: {type(exc).__name__}: {exc}"

    # (b) checkpoint / authoritative commit（写入 simulation_checkpoints）
    with factory() as s:
        try:
            with WorldMutationContext(
                    s, world_id=world_id, writer_id=job["owner"],
                    fencing_token=job["token"]) as ctx:
                s.execute(text(
                    "INSERT INTO simulation_checkpoints (world_id, "
                    "checkpoint_blessed_tick, world_state_hash, complete, meta, "
                    "created_at, rate_remainder) VALUES (:w, 1, 'stale', true, "
                    "'{}'::json, now(), 0)"), {"w": world_id})
                ctx.commit()
            attempts["checkpoint_commit"] = "COMMITTED"
        except FencingViolation as exc:
            attempts["checkpoint_commit"] = f"REJECTED: {exc}"
        except Exception as exc:  # noqa: BLE001
            attempts["checkpoint_commit"] = f"REJECTED_OTHER: {type(exc).__name__}: {exc}"

    # (c) history mutation（直接写 causal_history_links + 校验 fence）
    with factory() as s:
        try:
            with WorldMutationContext(
                    s, world_id=world_id, writer_id=job["owner"],
                    fencing_token=job["token"]) as ctx:
                s.execute(text(
                    "INSERT INTO causal_history_links (world_id, link_id, "
                    "relation_type, source_kind, source_id, target_kind, "
                    "target_id, committed_tick, status) VALUES "
                    "(:w, :lid, 'CAUSES', 'EVENT', 'x', 'EVENT', 'y', 1, "
                    "'ACTIVE')"),
                    {"lid": f"STALE-{job['token'][:8]}", "w": world_id})
                ctx.commit()
            attempts["history_mutation"] = "COMMITTED"
        except FencingViolation as exc:
            attempts["history_mutation"] = f"REJECTED: {exc}"
        except Exception as exc:  # noqa: BLE001
            attempts["history_mutation"] = f"REJECTED_OTHER: {type(exc).__name__}: {exc}"

    after = _counts(factory, world_id)
    engine.dispose()
    return {"attempts": attempts, "before": before, "after": after,
            "mutations_applied": sum(
                1 for k, v in after.items() if k in before and v != before[k])}


def _do_run_years(job: dict) -> dict:
    engine, factory = _engine_factory(job["dsn"])
    from XiaoguangBlessedLandRuntime.services.simulation.m3a_runner import (
        run_m3a_world)
    from tests.test_m3b_history import _hist_coordinator
    rep = run_m3a_world(
        factory, coordinator=_hist_coordinator(), world_id=job["world_id"],
        years=int(job["years"]), start_year=int(job.get("start_year", 0)),
        restart_every_years=job.get("restart_every_years"))
    out = {"final_blessed_tick": rep.final_blessed_tick,
           "hashes": _hashes(factory, job["world_id"]),
           "counts": _counts(factory, job["world_id"])}
    engine.dispose()
    return out


def _do_scheduler_budget(job: dict) -> dict:
    engine, factory = _engine_factory(job["dsn"])
    from tests.test_scheduler_catchup import run_scheduler_to
    sched = run_scheduler_to(
        {"factory": factory, "world_id": job["world_id"]},
        budget_ticks=int(job["budget_years"]) * 1_000_000,
        target_years=int(job["target_years"]),
        provider_years=int(job["target_years"]),
        state_dir=Path(job["state_dir"]))
    snap = sched.get_scheduler_status()
    sched.stop()
    out = {"hashes": _hashes(factory, job["world_id"]),
           "durable_current_tick": snap.get("durable_current_tick"),
           "batches_total": snap.get("catchup_batches_total"),
           "counts": _counts(factory, job["world_id"])}
    engine.dispose()
    return out


def _do_dump(job: dict) -> dict:
    engine, factory = _engine_factory(job["dsn"])
    out = {"counts": _counts(factory, job["world_id"]),
           "hashes": _hashes(factory, job["world_id"])}
    engine.dispose()
    return out


ACTIONS = {
    "acquire": _do_acquire,
    "renew": _do_renew,
    "stale_mutation": _do_stale_mutation,
    "run_years": _do_run_years,
    "scheduler_budget": _do_scheduler_budget,
    "dump": _do_dump,
}


def main() -> int:
    job_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    job = json.loads(job_path.read_text(encoding="utf-8"))
    payload: dict
    try:
        result = ACTIONS[job["action"]](job)
        payload = {"ok": True, "action": job["action"], "result": result}
    except Exception as exc:  # noqa: BLE001
        import traceback
        payload = {"ok": False, "action": job.get("action"),
                   "error": f"{type(exc).__name__}: {exc}",
                   "traceback": traceback.format_exc()[-2000:]}
    out_path.write_text(json.dumps(payload, ensure_ascii=False, default=str),
                        encoding="utf-8")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

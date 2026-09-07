"""OFFLINE CATCH-UP（M1）。

catch_up(world_id, last_real_cursor, now_real) 行为：
    计算关闭期间经过的现实时间（权威游标 = DB world_runtime.last_committed_real_us，
    调用方游标仅作校验/日志 —— 防止陈旧调用方重复累计）
    → 读取该期间所有 Rate History → 按真实时间整数边界分段积分
    → 生成 deterministic Simulation Run → 更新 Blessed Time
    → 更新 real cursor 与 remainder → 写 checkpoint → COMMIT。

M1 不生成世界内容：只产生 TIME_ADVANCE / CHECKPOINT / SIMULATION_RUN_METADATA
等基础设施级记录（禁止出生/死亡/居民/产业/灾劫/资源/历史事件/NPC/聚落变化）。

全部写路径经 WorldMutationContext（fencing commit-time enforcement）。
CATCH-UP 不知道 NPC/灾劫：simulate_fn 是留给 M2 的内容推演钩子，M1 恒 None。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..database.models_core import WorldRuntime
from ..domain.blessed_time import TimeRate, epoch_us_to_datetime
from ..domain.constants import (EventSources, RunStatus, SimulationVersion,
                              TickSources)
from ..domain.errors import IntegrityError, WorldNotActivated
from .fencing import WorldMutationContext
from .guard import require_world_activated
from .repositories import (CheckpointRepository, EventRepository,
                                   TimeRatioRepository)
from .run_lifecycle import SimulationRunRepository
from .time_engine import (Integrator, RateWindow, rate_at,
                                  segment_interval)


@dataclass(frozen=True)
class CatchUpResult:
    skipped: bool
    run_id: str | None
    delta_ticks: int
    new_blessed_tick: int | None
    new_cursor_us: int | None
    remainder: int | None


def _clock_state_hash(world_id: str, tick: int, cursor_us: int, rate_id: int,
                      remainder: int, simulation_version: str) -> str:
    """M1 时钟状态哈希（M2 起由真实世界状态哈希替代）。"""
    payload = f"{world_id}|{tick}|{cursor_us}|{rate_id}|{remainder}|{simulation_version}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def catch_up(
    session_factory: sessionmaker[Session],
    *,
    world_id: str,
    now_real_us: int,
    writer_id: str,
    fencing_token: str,
    last_real_cursor_us: int | None = None,
    simulation_version: str = SimulationVersion.CURRENT,
    simulate_fn: Callable[[Session, dict], None] | None = None,
) -> CatchUpResult:
    """Offline Catch-up：把 [DB 游标, now_real_us] 按历史速率分段积分推进时钟。

    - last_real_cursor_us：调用方游标仅供校验/日志；权威游标在 DB。
    - simulate_fn(session, advance_info)：M2 内容推演钩子；M1 必须为 None。
    - 幂等：now_real_us <= 游标 → skip（delta 0）；同区间 COMMITTED run 已存在 → skip。
    - Fencing：run 创建与时钟提交分两个 fenced 事务；commit 前重验 token。
    - 失败：时钟零写入；run 置 FAILED（仅当仍持有 fence，否则留给接管者）。
    """
    # 阶段 0（只读）：激活守卫 + 时钟游标快照
    with session_factory() as s:
        row = require_world_activated(s, "offline_catchup")
        if row.current_blessed_tick is None or row.last_committed_real_us is None:
            raise WorldNotActivated(
                "世界时钟未初始化（blessed tick / real cursor 缺失）",
                detail={"world_id": world_id,
                        "current_blessed_tick": row.current_blessed_tick,
                        "last_committed_real_us": row.last_committed_real_us})
        cursor = row.last_committed_real_us
        tick_before = row.current_blessed_tick
        remainder = row.time_rate_remainder
        if now_real_us <= cursor:
            return CatchUpResult(skipped=True, run_id=None, delta_ticks=0,
                                 new_blessed_tick=tick_before,
                                 new_cursor_us=cursor, remainder=remainder)

    # 阶段 1（fenced）：清理 stale RUNNING + 幂等检查 + 创建 RUNNING run
    with WorldMutationContext(session_factory(), world_id=world_id,
                              writer_id=writer_id,
                              fencing_token=fencing_token) as ctx:
        run_repo = SimulationRunRepository(ctx.session)
        run_repo.fail_stale_running(world_id, fencing_token)
        existing = run_repo.committed_for_interval(
            world_id, simulation_version, cursor, now_real_us)
        if existing is not None:
            ctx.commit()  # 幂等：同区间已提交 → skip（fence 校验后仅提交心跳）
            return CatchUpResult(skipped=True, run_id=existing.run_id,
                                 delta_ticks=0, new_blessed_tick=tick_before,
                                 new_cursor_us=cursor, remainder=0)
        run = run_repo.create_run(
            world_id=world_id, simulation_version=simulation_version,
            real_interval_start_us=cursor, real_interval_end_us=now_real_us,
            blessed_tick_before=tick_before, writer_id=writer_id,
            fencing_token=fencing_token, run_kind=TickSources.CATCHUP)
        ctx.commit()

    # 阶段 2（fenced）：分段积分 + 时钟提交 + run COMMITTED + checkpoint
    try:
        with WorldMutationContext(session_factory(), world_id=world_id,
                                  writer_id=writer_id,
                                  fencing_token=fencing_token) as ctx2:
            result = _advance_and_commit(
                ctx2.session, world_id=world_id, run_id=run.run_id,
                simulation_version=simulation_version,
                now_real_us=now_real_us, writer_id=writer_id,
                fencing_token=fencing_token, simulate_fn=simulate_fn)
            ctx2.commit()
        return result
    except Exception:
        _try_mark_failed(session_factory, world_id, writer_id, fencing_token,
                         run.run_id)
        raise


def _advance_and_commit(
    session: Session, *, world_id: str, run_id: str, simulation_version: str,
    now_real_us: int, writer_id: str, fencing_token: str,
    simulate_fn: Callable[[Session, dict], None] | None,
) -> CatchUpResult:
    runtime = session.execute(
        select(WorldRuntime).where(WorldRuntime.world_id == world_id)
    ).scalar_one()
    cursor = runtime.last_committed_real_us
    tick_before = runtime.current_blessed_tick
    # 防御：本事务持有 fence，游标不可能在此期间被他人推进；若发生 → 单调性破坏
    if cursor is None or tick_before is None or now_real_us <= cursor:
        raise IntegrityError("时钟游标/刻度非法", detail={"cursor": cursor,
                                                          "now": now_real_us})

    run = SimulationRunRepository(session).get(run_id)
    if run is None or run.status != RunStatus.RUNNING:
        raise IntegrityError("run 状态异常（应为 RUNNING）", detail=run_id)

    tr = TimeRatioRepository(session)
    rows = tr.list_effective_up_to(world_id, now_real_us)
    if not rows:
        raise IntegrityError("rate history 为空，无法积分", detail=world_id)
    windows = [RateWindow(real_effective_from_us=r.real_effective_from_us,
                          rate=TimeRate(r.rate_numerator, r.rate_denominator),
                          ratio_id=r.ratio_id, reason=r.reason) for r in rows]

    # remainder 绑定校验：当前生效速率与持久化 remainder 所属速率不一致 → 余数作废
    remainder = runtime.time_rate_remainder
    effective_rate, effective_rid = rate_at(windows, cursor)
    if runtime.current_time_ratio_id != effective_rid:
        remainder = 0

    integrator = Integrator(remainder=remainder, rate=effective_rate,
                            ratio_id=effective_rid)
    for sl in segment_interval(windows, cursor, now_real_us):
        integrator.add_segment(sl.real_start_us, sl.real_end_us, sl.rate,
                               sl.ratio_id)

    delta = integrator.total_ticks
    new_tick = tick_before + delta
    if new_tick < tick_before:  # 单调性（防御，delta 恒 >= 0）
        raise IntegrityError("blessed tick 单调性被破坏",
                             detail={"before": tick_before, "after": new_tick})

    # 世界时钟提交（fenced 事务内）
    runtime.current_blessed_tick = new_tick
    runtime.last_committed_real_us = now_real_us
    runtime.time_rate_remainder = integrator.remainder
    runtime.current_time_ratio_id = integrator.ratio_id
    runtime.last_simulated_real_time = epoch_us_to_datetime(now_real_us)

    # TIME_ADVANCE 基础设施事件（M1 唯一允许的事件类型，不含世界内容）
    EventRepository(session).append(
        world_id=world_id, event_type="TIME_ADVANCE",
        source=EventSources.SIMULATION, blessed_tick=new_tick, scope="WORLD",
        cause={"real_interval_start_us": cursor,
               "real_interval_end_us": now_real_us,
               "elapsed_real_us": integrator.elapsed_real_us},
        effect={"delta_ticks": delta, "remainder": integrator.remainder,
                "rate_id": integrator.ratio_id,
                "simulation_version": simulation_version})

    if simulate_fn is not None:  # M2 内容推演钩子；M1 恒 None
        simulate_fn(session, {
            "world_id": world_id, "delta_ticks": delta,
            "new_blessed_tick": new_tick,
            "real_interval_start_us": cursor,
            "real_interval_end_us": now_real_us,
        })

    SimulationRunRepository(session).commit_run(
        run, blessed_tick_after=new_tick, blessed_tick_delta=delta,
        real_cursor_after_us=now_real_us)

    CheckpointRepository(session).create(
        world_id=world_id, blessed_tick=new_tick,
        world_state_hash=_clock_state_hash(
            world_id, new_tick, now_real_us, integrator.ratio_id,
            integrator.remainder, simulation_version),
        complete=True, meta={"kind": "CATCHUP"},
        last_committed_real_us=now_real_us, rate_id=integrator.ratio_id,
        rate_remainder=integrator.remainder,
        simulation_version=simulation_version,
        last_committed_run_id=run.run_id, writer_id=writer_id,
        fencing_token=fencing_token)

    return CatchUpResult(skipped=False, run_id=run.run_id, delta_ticks=delta,
                         new_blessed_tick=new_tick,
                         new_cursor_us=now_real_us,
                         remainder=integrator.remainder)


def _try_mark_failed(session_factory: sessionmaker[Session], world_id: str,
                     writer_id: str, fencing_token: str, run_id: str) -> None:
    """best effort：仍持有 fence 时把 run 置 FAILED；fence 已失则留给接管者。"""
    try:
        with WorldMutationContext(session_factory(), world_id=world_id,
                                  writer_id=writer_id,
                                  fencing_token=fencing_token) as ctx:
            run = SimulationRunRepository(ctx.session).get(run_id)
            if run is not None and run.status == "RUNNING":
                SimulationRunRepository(ctx.session).fail_run(
                    run, "catch-up phase failed")
            ctx.commit()
    except Exception:  # noqa: BLE001
        pass

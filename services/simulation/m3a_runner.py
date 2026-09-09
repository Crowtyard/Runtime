# -*- coding: utf-8 -*-
"""M3a Runner：Adaptive Time Resolution 驱动（TEST harness 与未来 M3a 集成用）。

- 逐步推进 blessed 年，每步先用 next_tribulation_boundary 拆分
  SimulationInterval（整数 tick）：跨越排期窗口 / 阶段转移边界绝不
  静默跳过 PRECURSOR/PREPARATION/RESPONSE。
- 全部经 M1 catch_up（fencing/幂等/ack-lost 继承）。
- OwnerDecision 显式提交（submit_owner_decision）；离线无决策 →
  DEFAULT_AUTONOMOUS_RESPONSE_POLICY。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session, sessionmaker

from ..catchup import catch_up
from ..writer_lock import WriterLease
from .coordinator import SimulationCoordinator
from .harness import MINI_WORLD_EPOCH0_US, YEAR_US
from .mini_world import MINI_WORLD_ID
from .tribulation import (M3A_SIMULATION_VERSION, next_tribulation_boundary,
                          submit_owner_decision)


@dataclass(frozen=True)
class M3aReport:
    world_id: str
    years: int
    final_blessed_tick: int
    final_state_hash: str
    final_event_stream_hash: str
    metrics: dict = field(default_factory=dict)
    splits: int = 0
    runs: int = 0
    checkpoints: int = 0
    events: int = 0


def run_m3a_world(
    session_factory: sessionmaker[Session],
    *,
    coordinator: SimulationCoordinator,
    world_id: str = MINI_WORLD_ID,
    epoch0_us: int = MINI_WORLD_EPOCH0_US,
    years: int = 300,
    start_year: int = 0,
    restart_every_years: int | None = None,
    owner_decisions: dict | None = None,
) -> M3aReport:
    """运行 M3a 世界 N 年（Adaptive Time Resolution 拆分）。

    owner_decisions：{year_index: dict(episode_id, action,
    effective_before_tick, ...)} —— 该年推进前显式提交决策。
    """
    owner_decisions = owner_decisions or {}
    metrics: dict = {}
    last_hash, last_event_hash = "", ""
    total_splits = 0
    runs_count = 0
    events_count = 0
    checkpoint_count = 0

    for start_year_i in range(0, years, restart_every_years or years):
        lease_session = session_factory()
        lease = WriterLease(lease_session, world_id, 120)
        lease.acquire()
        try:
            for i in range(start_year_i, min(start_year_i + (
                    restart_every_years or years), years)):
                year_index = start_year + i
                from_tick = year_index * 1_000_000
                to_tick = (year_index + 1) * 1_000_000
                now_us = epoch0_us + (year_index + 1) * YEAR_US

                if year_index in owner_decisions:
                    with session_factory() as s:
                        submit_owner_decision(
                            s, world_id=world_id,
                            **owner_decisions[year_index])
                        s.commit()

                # 区间拆分（整数 tick）
                sub_intervals: list[tuple[int, int]] = []
                cursor = from_tick
                while cursor < to_tick:
                    with session_factory() as s:
                        boundary = next_tribulation_boundary(
                            s, world_id=world_id, from_tick=cursor,
                            to_tick=to_tick)
                    if boundary is None:
                        sub_intervals.append((cursor, to_tick))
                        cursor = to_tick
                    else:
                        sub_intervals.append((cursor, boundary))
                        cursor = boundary
                        total_splits += 1

                for (sub_from, sub_to) in sub_intervals:
                    def step_fn(s, info, _f=sub_from, _t=sub_to, _y=year_index):
                        return coordinator.run_step(
                            s, world_id=world_id,
                            blessed_start_tick=_f, blessed_end_tick=_t,
                            real_interval_start_us=info[
                                "real_interval_start_us"],
                            real_interval_end_us=info[
                                "real_interval_end_us"],
                            step_index=_y + 1)

                    res = catch_up(
                        session_factory, world_id=world_id,
                        now_real_us=now_us, writer_id=lease.owner,
                        fencing_token=lease.token,
                        simulation_version=M3A_SIMULATION_VERSION,
                        simulate_fn=step_fn)
                    last_report = res.simulate_result
                    if last_report is not None:
                        for eid, m in last_report.metrics.items():
                            for k, v in m.items():
                                metrics.setdefault(eid, {}).setdefault(k, 0)
                                metrics[eid][k] += v
                        last_hash = last_report.world_state_hash
                        last_event_hash = last_report.event_stream_hash
        finally:
            lease.release()
            lease_session.close()

    from sqlalchemy import select, text
    from ...database.models_core import SimulationCheckpoint
    with session_factory() as s:
        tick = s.execute(text(
            "SELECT current_blessed_tick FROM world_runtime")).scalar()
        checkpoint_count = len(s.execute(
            select(SimulationCheckpoint)).scalars().all())
        runs_count = s.execute(text(
            "SELECT COUNT(*) FROM simulation_run")).scalar()
        events_count = s.execute(text(
            "SELECT COUNT(*) FROM world_events")).scalar()
    return M3aReport(
        world_id=world_id, years=years, final_blessed_tick=tick,
        final_state_hash=last_hash,
        final_event_stream_hash=last_event_hash, metrics=metrics,
        splits=total_splits, runs=runs_count,
        checkpoints=checkpoint_count, events=events_count)

# -*- coding: utf-8 -*-
"""CatchUpPlanner（M4.3）：只读预演，权威转换永远在 catch_up。

- 用冻结 time_engine 原语（rate_at / segment_interval / Integrator）把
  [durable real cursor, now_real_us] 换算为 target blessed tick —— 这只是
  **规划**；任何真实推进都经 catch_up 的 fenced 事务完成。
- 执行后 Scheduler 断言 durable tick 推进量 == 规划值；不一致 → FAILED
  （fail-closed，禁止猜测世界真值）。
- M4 范围不变量（自然速率 + 年锚 = epoch0 + k*YEAR_US）：规划前断言
  durable cursor 恰好落在年锚上；否则 FAILED（速率变更感知锚定留给 M6）。
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ...database.models_core import WorldRuntime
from ...domain.blessed_time import TimeRate
from ..repositories import TimeRatioRepository
from ..simulation.harness import YEAR_US
from ..simulation.tribulation import TICKS_PER_BLESSED_YEAR
from ..time_engine import Integrator, RateWindow, rate_at, segment_interval


@dataclass(frozen=True)
class CatchUpPlan:
    target_tick: int
    due_ticks: int
    batch_years: int            # 本 cycle 实际执行年数（整数年原子粒度）
    year_indices: tuple[int, ...]  # 绝对年序号（epoch0 起）
    planned_delta_ticks: int     # batch_years * TICKS_PER_BLESSED_YEAR
    real_now_us: int
    durable_cursor_us: int
    durable_tick: int


class CatchUpPlanner:
    """只读规划：现实锚 → 目标 tick；batch 只在年边界。"""

    def __init__(self, *, world_id: str, epoch0_us: int):
        self.world_id = world_id
        self.epoch0_us = epoch0_us

    def _read_runtime(self, session: Session) -> WorldRuntime:
        row = session.execute(
            select(WorldRuntime).where(
                WorldRuntime.world_id == self.world_id)).scalar_one_or_none()
        if row is None:
            raise RuntimeError("world_runtime 行缺失（无法规划）")
        return row

    def compute_target_tick(self, session: Session, now_real_us: int) -> int:
        """[cursor, now_real_us] 的冻结积分 → 目标 tick（只读，零写入）。"""
        row = self._read_runtime(session)
        cursor = row.last_committed_real_us
        tick_before = row.current_blessed_tick
        if cursor is None or tick_before is None:
            raise RuntimeError("世界时钟未初始化（tick/real cursor 缺失）")
        if now_real_us <= cursor:
            return tick_before
        tr = TimeRatioRepository(session)
        rows = tr.list_effective_up_to(self.world_id, now_real_us)
        if not rows:
            raise RuntimeError("rate history 为空，无法规划")
        windows = [RateWindow(real_effective_from_us=r.real_effective_from_us,
                              rate=TimeRate(r.rate_numerator,
                                            r.rate_denominator),
                              ratio_id=r.ratio_id, reason=r.reason)
                   for r in rows]
        remainder = row.time_rate_remainder
        effective_rate, effective_rid = rate_at(windows, cursor)
        if row.current_time_ratio_id != effective_rid:
            remainder = 0
        integrator = Integrator(remainder=remainder, rate=effective_rate,
                                ratio_id=effective_rid)
        for sl in segment_interval(windows, cursor, now_real_us):
            integrator.add_segment(sl.real_start_us, sl.real_end_us, sl.rate,
                                   sl.ratio_id)
        return tick_before + integrator.total_ticks

    def plan(self, session: Session, *, now_real_us: int,
             budget_ticks: int) -> CatchUpPlan:
        """规划本 cycle：target/due/batch（年粒度）。只读，零写入。"""
        if budget_ticks < 1:
            raise ValueError("budget_ticks 必须 >= 1")
        row = self._read_runtime(session)
        cursor = row.last_committed_real_us
        tick_before = row.current_blessed_tick
        if cursor is None or tick_before is None:
            raise RuntimeError("世界时钟未初始化（tick/real cursor 缺失）")
        # 年锚不变量（M4 范围）：durable tick 与 real cursor 必须整年对齐
        if tick_before % TICKS_PER_BLESSED_YEAR != 0:
            raise RuntimeError(
                f"durable tick 未整年对齐: {tick_before}（M4 范围外，fail-closed）")
        year_start = tick_before // TICKS_PER_BLESSED_YEAR
        expected_cursor = self.epoch0_us + year_start * YEAR_US
        if cursor != expected_cursor:
            raise RuntimeError(
                "durable real cursor 与年锚不一致（速率变更场景超出 M4 范围，"
                f"fail-closed）: cursor={cursor} expected={expected_cursor}")
        target_tick = self.compute_target_tick(session, now_real_us)
        due_ticks = max(0, target_tick - tick_before)
        batch_ticks = min(due_ticks, budget_ticks)
        batch_years = batch_ticks // TICKS_PER_BLESSED_YEAR
        year_indices = tuple(range(year_start + 1,
                                   year_start + 1 + batch_years))
        return CatchUpPlan(
            target_tick=target_tick, due_ticks=due_ticks,
            batch_years=batch_years, year_indices=year_indices,
            planned_delta_ticks=batch_years * TICKS_PER_BLESSED_YEAR,
            real_now_us=now_real_us, durable_cursor_us=cursor,
            durable_tick=tick_before)

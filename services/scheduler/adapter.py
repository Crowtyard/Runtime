# -*- coding: utf-8 -*-
"""YearStepAdapter（M4.3）：以冻结原语复刻 m3a_runner 的年步执行序列。

- 引擎调用粒度 = 1 福地年/次 coordinator.run_step（冻结合成排期下
  next_tribulation_boundary 边界恒为年边界）；此处仅**编排**，不复制 Engine。
- 每个子区间经 catch_up（幂等 + fencing + run 生命周期）提交；
  simulate_fn 使用与 m3a_runner 完全相同的 blessed 区间与 step_index 约定
  （step_index = 绝对年序号 + 1）→ 与 run_m3a_world 字节等价。
- 现实锚 = epoch0_us + (year_index + 1) * YEAR_US（M4 自然速率范围；
  速率变更感知锚定属 M6）。
"""
from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from ..catchup import catch_up
from ..simulation.harness import YEAR_US
from ..simulation.tribulation import (TICKS_PER_BLESSED_YEAR,
                                      next_tribulation_boundary)
from ..writer_lock import WriterLease


def run_blessed_year(session_factory: sessionmaker, *, world_id: str,
                     year_index: int, coordinator, lease: WriterLease,
                     epoch0_us: int, simulation_version: str) -> None:
    """推进一个福地年（与 m3a_runner 等价的子区间序列）。"""
    now_us = epoch0_us + (year_index + 1) * YEAR_US
    from_tick = year_index * TICKS_PER_BLESSED_YEAR
    to_tick = (year_index + 1) * TICKS_PER_BLESSED_YEAR

    sub_intervals: list[tuple[int, int]] = []
    cursor = from_tick
    while cursor < to_tick:
        with session_factory() as s:
            boundary = next_tribulation_boundary(
                s, world_id=world_id, from_tick=cursor, to_tick=to_tick)
        if boundary is None:
            sub_intervals.append((cursor, to_tick))
            cursor = to_tick
        else:
            sub_intervals.append((cursor, boundary))
            cursor = boundary

    for (sub_from, sub_to) in sub_intervals:
        def step_fn(s, info, _f=sub_from, _t=sub_to, _y=year_index):
            return coordinator.run_step(
                s, world_id=world_id,
                blessed_start_tick=_f, blessed_end_tick=_t,
                real_interval_start_us=info["real_interval_start_us"],
                real_interval_end_us=info["real_interval_end_us"],
                step_index=_y + 1,
                simulation_run_id=info.get("simulation_run_id"))

        catch_up(session_factory, world_id=world_id, now_real_us=now_us,
                 writer_id=lease.owner, fencing_token=lease.token,
                 simulation_version=simulation_version, simulate_fn=step_fn)

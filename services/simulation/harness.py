# -*- coding: utf-8 -*-
"""120 Blessed Years Harness（M2 Preflight）。

时间粒度（CONFIRMED，04 §2/§3）：默认年度步进 —— 120 年 = 120 个年度
simulation step。wall-clock 永不参与：现实时间输入为合成 EPOCH0 + n 年
（自然态速率 1 现实天 = 1 福地年 → 1 年 = 86,400,000,000 µs）。

管线：逐年度 catch_up(simulate_fn=coordinator.run_step)；
fencing 由 M1 WorldMutationContext 持有；本 harness 只负责租约与调度。
等价性：state 等价 = 最终 world_state_hash v2 + 最终 tick 相等。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from ..catchup import catch_up
from ...database.models_core import SimulationCheckpoint, WorldEvent
from ...database.models_world import (EcologicalRegion, Institution, Lineage,
                                     PopulationGroup, ResourceNode, Settlement)
from ...domain.blessed_time import datetime_to_epoch_us
from ..writer_lock import WriterLease
from .contracts import PREFLIGHT_SIMULATION_VERSION, Engine, NoOpEngine
from .coordinator import SimulationCoordinator, StepReport
from .mini_world import MINI_WORLD_ID

YEAR_US = 86_400_000_000
MINI_WORLD_EPOCH0_US = datetime_to_epoch_us(
    datetime(2026, 1, 1, tzinfo=timezone.utc))


@dataclass(frozen=True)
class MiniWorldReport:
    """120 年 Metrics Schema 聚合（§14：只定义 schema，不预设数值）。"""
    world_id: str
    years: int
    steps: int
    runs: int
    events: int
    checkpoints: int
    final_blessed_tick: int
    final_state_hash: str
    engine_metrics: dict = field(default_factory=dict)
    entity_counts: dict = field(default_factory=dict)
    population: dict = field(default_factory=dict)
    economy: dict = field(default_factory=dict)
    ecology: dict = field(default_factory=dict)
    society: dict = field(default_factory=dict)


def noop_engines() -> list[Engine]:
    return [NoOpEngine(eid) for eid in ("DEMOGRAPHY", "RESOURCE",
                                        "ECONOMY", "ECOLOGY", "SOCIAL")]


def _population_total(session: Session, world_id: str) -> int:
    return sum(
        g.count or 0 for g in session.execute(
            select(PopulationGroup).where(
                PopulationGroup.world_id == world_id)).scalars())


def run_mini_world_120y(
    session_factory: sessionmaker[Session],
    *,
    engines: list[Engine] | None = None,
    world_id: str = MINI_WORLD_ID,
    epoch0_us: int = MINI_WORLD_EPOCH0_US,
    restart_every_years: int | None = None,
    years: int = 120,
    start_year: int = 0,
) -> MiniWorldReport:
    """运行 mini_world N 个福地年（N 个年度 step；可分段重启/续跑）。

    restart_every_years：每 N 年释放租约并重新获取（模拟重启边界），
    默认 None = 全程一次租约。start_year：续跑偏移（DB 游标为准）。
    """
    engines = engines or noop_engines()
    coordinator = SimulationCoordinator(engines)
    chunk = restart_every_years or years

    with session_factory() as s0:
        population_start = _population_total(s0, world_id)

    total_events = 0
    engine_metrics: dict = {e.engine_id: {} for e in engines}
    last_report: StepReport | None = None

    for start_year_i in range(0, years, chunk):
        lease_session = session_factory()
        lease = WriterLease(lease_session, world_id, 120)
        lease.acquire()
        try:
            for i in range(start_year_i, min(start_year_i + chunk, years)):
                year_index = start_year + i
                now_us = epoch0_us + (year_index + 1) * YEAR_US

                def step_fn(session, info, _i=year_index):
                    return coordinator.run_step(
                        session,
                        world_id=world_id,
                        blessed_start_tick=(
                            info["new_blessed_tick"] - info["delta_ticks"]),
                        blessed_end_tick=info["new_blessed_tick"],
                        real_interval_start_us=info["real_interval_start_us"],
                        real_interval_end_us=info["real_interval_end_us"],
                        step_index=_i + 1)

                res = catch_up(
                    session_factory, world_id=world_id, now_real_us=now_us,
                    writer_id=lease.owner, fencing_token=lease.token,
                    simulation_version=PREFLIGHT_SIMULATION_VERSION,
                    simulate_fn=step_fn)
                last_report = res.simulate_result
                total_events += last_report.event_count if last_report else 0
                if last_report:
                    for eid, m in last_report.metrics.items():
                        for k, v in m.items():
                            engine_metrics.setdefault(eid, {}).setdefault(k, 0)
                            engine_metrics[eid][k] += v
        finally:
            lease.release()
            lease_session.close()

    with session_factory() as s:
        runtime_tick = s.execute(text(
            "SELECT current_blessed_tick FROM world_runtime")).scalar()
        counts = {
            "settlements": len(s.execute(select(Settlement)).scalars().all()),
            "population_groups": len(s.execute(
                select(PopulationGroup)).scalars().all()),
            "resource_nodes": len(s.execute(
                select(ResourceNode)).scalars().all()),
            "ecological_regions": len(s.execute(
                select(EcologicalRegion)).scalars().all()),
            "lineages": len(s.execute(select(Lineage)).scalars().all()),
            "institutions": len(s.execute(select(Institution)).scalars().all()),
        }
        events_total = len(s.execute(select(WorldEvent)).scalars().all())
        ckpts = len(s.execute(select(SimulationCheckpoint)).scalars().all())
        runs = s.execute(text("SELECT COUNT(*) FROM simulation_run")).scalar()
        population_end = _population_total(s, world_id)

    return MiniWorldReport(
        world_id=world_id, years=years, steps=years, runs=runs,
        events=events_total, checkpoints=ckpts,
        final_blessed_tick=runtime_tick,
        final_state_hash=last_report.world_state_hash if last_report else "",
        engine_metrics=engine_metrics,
        entity_counts=counts,
        population={"start": population_start, "end": population_end,
                    "births": int(engine_metrics.get("DEMOGRAPHY", {}).get(
                        "births", 0)),
                    "deaths": int(engine_metrics.get("DEMOGRAPHY", {}).get(
                        "deaths", 0)),
                    "migrations": int(engine_metrics.get("DEMOGRAPHY", {}).get(
                        "emigration", 0))},
        economy={"stock": None, "production": None, "consumption": None,
                 "shortages": None},
        ecology={"state": None, "pressure": None},
        society={"households": None, "lineages": counts["lineages"],
                 "institution_events": None},
    )

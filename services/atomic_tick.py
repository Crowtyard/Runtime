"""ATOMIC_TICK 与幂等骨架（11/12/31 节）。

- 一次 Tick 的全部 State Changes + World Events + Metadata 在单一事务提交；
  异常 → 全部回滚（禁止 人口 Year100/经济 Year99）。
- TICK_IDENTITY（M0 DSH QA 修正）：幂等身份 = world_id + simulation_version +
  status=COMMITTED + committed_until_tick；旧 simulation_version 的
  committed_until_tick 不得阻止新版合法推进。
- WORLD_NOT_ACTIVATED：默认强制激活校验（simulate_tick 在未激活世界失败）。
- 失败事务不推进 committed_until_tick（同一事务内回滚）。
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from database.base import utcnow
from database.models_core import SimulationRun
from domain.constants import SimulationVersion, TickSources
from services.guard import require_world_activated


@dataclass(frozen=True)
class TickResult:
    skipped: bool
    run_id: str | None
    committed_until_tick: int | None


def run_atomic_tick(
    session_factory: sessionmaker[Session],
    *,
    world_id: str,
    target_blessed_tick: int,
    simulate_fn: Callable[[Session], None],
    run_kind: str = TickSources.ONLINE,
    real_now: datetime | None = None,
    require_activation: bool = True,
) -> TickResult:
    """执行一次原子 Tick（target = canonical blessed tick）。

    simulate_fn(session) 只做状态变更与事件插入（不得自行 commit）。
    幂等：存在 同 world + 同 simulation_version 的 COMMITTED run 且
    committed_until_tick >= target → skipped=True 直接返回。
    """
    with session_factory() as session:
        with session.begin():
            if require_activation:
                require_world_activated(session, "simulate_tick")
            latest = session.execute(
                select(SimulationRun)
                .where(SimulationRun.world_id == world_id,
                       SimulationRun.simulation_version == SimulationVersion.CURRENT,
                       SimulationRun.status == "COMMITTED")
                .order_by(SimulationRun.committed_until_tick.desc())
                .limit(1)
            ).scalar_one_or_none()
            if latest is not None and latest.committed_until_tick is not None \
                    and latest.committed_until_tick >= target_blessed_tick:
                return TickResult(skipped=True, run_id=latest.run_id,
                                  committed_until_tick=latest.committed_until_tick)

            run = SimulationRun(
                run_id=str(uuid.uuid4()),
                world_id=world_id,
                started_at=real_now or utcnow(),
                target_blessed_tick=target_blessed_tick,
                committed_until_tick=target_blessed_tick,
                status="COMMITTED",
                simulation_version=SimulationVersion.CURRENT,
                seed_context={"kind": run_kind},
            )
            session.add(run)
            simulate_fn(session)
    return TickResult(skipped=False, run_id=run.run_id,
                      committed_until_tick=target_blessed_tick)

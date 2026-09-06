"""ATOMIC_TICK 与幂等骨架（11/12/31 节）。

- 一次 Tick 的全部 State Changes + World Events + Metadata 在单一事务提交；
  异常 → 全部回滚（禁止 人口 Year100/经济 Year99）。
- TICK_IDENTITY：simulation_run 记录 committed_until；同 target 重试 → skip，
  防止 Crash/Retry 重复写入事件。
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
from domain.constants import SimulationVersion


@dataclass(frozen=True)
class TickResult:
    skipped: bool
    run_id: str | None
    committed_until: int | None


def run_atomic_tick(
    session_factory: sessionmaker[Session],
    *,
    world_id: str,
    target_blessed_time: int,
    simulate_fn: Callable[[Session], None],
    run_kind: str = "ONLINE",
    real_now: datetime | None = None,
) -> TickResult:
    """执行一次原子 Tick。

    simulate_fn(session) 只做状态变更与事件插入（不得自行 commit）。
    幂等：若已存在 committed_until >= target 的 run → skipped=True 直接返回。
    """
    with session_factory() as session:
        with session.begin():
            latest = session.execute(
                select(SimulationRun)
                .where(SimulationRun.world_id == world_id)
                .order_by(SimulationRun.committed_until.desc())
                .limit(1)
            ).scalar_one_or_none()
            if latest is not None and latest.committed_until is not None \
                    and latest.committed_until >= target_blessed_time:
                return TickResult(skipped=True, run_id=latest.run_id,
                                  committed_until=latest.committed_until)

            run = SimulationRun(
                run_id=str(uuid.uuid4()),
                world_id=world_id,
                started_at=real_now or utcnow(),
                target_blessed_time=target_blessed_time,
                committed_until=target_blessed_time,
                status="COMMITTED",
                simulation_version=SimulationVersion.CURRENT,
                seed_context={"kind": run_kind},
            )
            session.add(run)
            simulate_fn(session)
    return TickResult(skipped=False, run_id=run.run_id,
                      committed_until=target_blessed_time)

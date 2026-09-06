"""SIMULATION RUN 生命周期（M1）。

生命周期：PENDING → RUNNING → COMMITTED；异常：RUNNING → FAILED。
重试：FAILED / stale RUNNING → 新 run（或由接管者明确置 FAILED 后重试）。

幂等身份：world_id + simulation_version + real_interval_start_us +
real_interval_end_us（COMMITTED 行由部分唯一索引在 DB 层强制，见
migration e6c0f4a1b3d9）→ 同一现实时间区间只允许一个 COMMITTED run，
不可能被累计两次。

RUN LIFECYCLE 不知道 NPC/灾劫：只管理 run 元数据与状态转移。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from database.base import utcnow
from database.models_core import SimulationRun
from domain.constants import RunStatus, TickSources


class SimulationRunRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self, run_id: str) -> SimulationRun | None:
        return self.session.execute(
            select(SimulationRun).where(SimulationRun.run_id == run_id)
        ).scalar_one_or_none()

    def create_run(self, *, world_id: str, simulation_version: str,
                   real_interval_start_us: int, real_interval_end_us: int,
                   blessed_tick_before: int, writer_id: str, fencing_token: str,
                   run_kind: str = TickSources.CATCHUP,
                   status: str = RunStatus.RUNNING) -> SimulationRun:
        """创建 run 行（默认 RUNNING；PENDING 为可选过渡态）。"""
        run = SimulationRun(
            run_id=str(uuid.uuid4()),
            world_id=world_id,
            simulation_version=simulation_version,
            status=status,
            seed_context={"kind": run_kind,
                          "real_interval_start_us": real_interval_start_us,
                          "real_interval_end_us": real_interval_end_us},
            real_interval_start_us=real_interval_start_us,
            real_interval_end_us=real_interval_end_us,
            blessed_tick_before=blessed_tick_before,
            writer_id=writer_id,
            fencing_token=fencing_token,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def commit_run(self, run: SimulationRun, *, blessed_tick_after: int,
                   blessed_tick_delta: int, real_cursor_after_us: int,
                   finished_at: datetime | None = None) -> None:
        run.status = RunStatus.COMMITTED
        run.target_blessed_tick = blessed_tick_after
        run.committed_until_tick = blessed_tick_after
        run.blessed_tick_delta = blessed_tick_delta
        run.real_cursor_after_us = real_cursor_after_us
        run.finished_at = finished_at or utcnow()
        self.session.flush()

    def fail_run(self, run: SimulationRun, reason: str,
                 finished_at: datetime | None = None) -> None:
        run.status = RunStatus.FAILED
        run.finished_at = finished_at or utcnow()
        run.seed_context = {**run.seed_context, "failure_reason": reason}
        self.session.flush()

    def committed_for_interval(self, world_id: str, simulation_version: str,
                               real_interval_start_us: int,
                               real_interval_end_us: int) -> SimulationRun | None:
        """同区间已 COMMITTED 的 run（幂等命中）。"""
        return self.session.execute(
            select(SimulationRun)
            .where(SimulationRun.world_id == world_id,
                   SimulationRun.simulation_version == simulation_version,
                   SimulationRun.status == RunStatus.COMMITTED,
                   SimulationRun.real_interval_start_us == real_interval_start_us,
                   SimulationRun.real_interval_end_us == real_interval_end_us)
            .order_by(SimulationRun.finished_at.desc())
            .limit(1)
        ).scalar_one_or_none()

    def fail_stale_running(self, world_id: str, current_token: str) -> int:
        """把其它（已失效）writer 遗留的 RUNNING run 置 FAILED（Case G 恢复）。"""
        result = self.session.execute(
            update(SimulationRun)
            .where(SimulationRun.world_id == world_id,
                   SimulationRun.status == RunStatus.RUNNING,
                   SimulationRun.fencing_token != current_token)
            .values(status=RunStatus.FAILED, finished_at=utcnow()))
        return result.rowcount

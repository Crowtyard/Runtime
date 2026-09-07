"""WORLD_NOT_ACTIVATED 守卫（28 节）：世界推进的终极安全锁。

- 任何 advance/simulate/catchup/create_event 前必须调用。
- 激活判定 = runtime 行存在 + runtime_status==ACTIVE + world_seed_version 非空。
- 创建 metadata / time rule（world_runtime 行、time_ratio_history 行）绝不等于激活世界。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database.models_core import WorldEvent, WorldRuntime
from ..domain.constants import RuntimeStatus
from ..domain.errors import WorldNotActivated
from .repositories import EventRepository


def get_runtime_row(session: Session) -> WorldRuntime | None:
    return session.execute(select(WorldRuntime).limit(1)).scalar_one_or_none()


def require_world_activated(session: Session, action: str) -> WorldRuntime:
    """任何 advance/simulate/catchup/create_event 前调用。

    未激活（或缺失 runtime 行、或 world_seed 未生效）→ WorldNotActivated。
    即使误运行 Runtime，福地也不会偷偷开始推进。
    """
    row = get_runtime_row(session)
    if (row is None
            or row.runtime_status != RuntimeStatus.ACTIVE
            or row.world_seed_version is None):
        raise WorldNotActivated(
            f"世界未激活，禁止操作: {action}",
            detail={"runtime_status": getattr(row, "runtime_status", None),
                    "world_seed_version": getattr(row, "world_seed_version", None)})
    return row


def create_simulation_event(session: Session, **event_kwargs) -> WorldEvent:
    """模拟事件创建入口：未激活世界一律拒绝（WORLD_NOT_ACTIVATED）。

    这是"simulation event creation 在未激活状态下必须失败"的唯一受保护入口；
    M1 引擎事件写入必须经此（或先自行调用 require_world_activated）。
    """
    require_world_activated(session, "create_world_event_from_simulation")
    return EventRepository(session).append(**event_kwargs)

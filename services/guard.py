"""WORLD_NOT_ACTIVATED 守卫（28 节）：世界推进的终极安全锁。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models_core import WorldRuntime
from domain.constants import RuntimeStatus
from domain.errors import WorldNotActivated


def get_runtime_row(session: Session) -> WorldRuntime | None:
    return session.execute(select(WorldRuntime).limit(1)).scalar_one_or_none()


def require_world_activated(session: Session, action: str) -> WorldRuntime:
    """任何 advance/simulate/catchup/create_event 前调用。

    未激活（或缺失 runtime 行）→ WorldNotActivated。即使误运行 Runtime，
    福地也不会偷偷开始推进。
    """
    row = get_runtime_row(session)
    if row is None or row.runtime_status != RuntimeStatus.ACTIVE:
        raise WorldNotActivated(
            f"世界未激活，禁止操作: {action}",
            detail={"runtime_status": getattr(row, "runtime_status", None),
                    "world_seed_version": getattr(row, "world_seed_version", None)})
    return row

"""SINGLE_WORLD_WRITER（14 节）：runtime_lock 租约。

同一 World 同一时间只能有一个推进者；客户端可并发读，不能并发写。
第二个 writer 尝试进入 → WRITER_LOCK_CONFLICT（不等待不抢注，除非过期）。
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import ContextManager

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.base import utcnow
from database.models_core import RuntimeLock
from domain.errors import WriterLockConflict


class WriterLease:
    def __init__(self, session: Session, world_id: str, lease_seconds: int):
        self.session = session
        self.world_id = world_id
        self.lease_seconds = lease_seconds
        self.token: str | None = None

    def acquire(self) -> None:
        row = self.session.execute(
            select(RuntimeLock).where(RuntimeLock.world_id == self.world_id)
        ).scalar_one_or_none()
        now = utcnow()
        if row is not None and row.expires_at > now:
            raise WriterLockConflict(
                "另一 Runtime 正在推进该世界",
                detail={"expires_at": str(row.expires_at), "owner": row.owner})
        token = secrets.token_hex(16)
        if row is None:
            row = RuntimeLock(world_id=self.world_id, lease_token=token, owner="runtime",
                              acquired_at=now,
                              expires_at=now + timedelta(seconds=self.lease_seconds))
            self.session.add(row)
        else:
            row.lease_token = token
            row.owner = "runtime"
            row.acquired_at = now
            row.expires_at = now + timedelta(seconds=self.lease_seconds)
        self.session.flush()
        self.token = token

    def release(self) -> None:
        if self.token is None:
            return
        row = self.session.execute(
            select(RuntimeLock).where(RuntimeLock.world_id == self.world_id)
        ).scalar_one_or_none()
        if row is not None and row.lease_token == self.token:
            self.session.delete(row)
            self.session.flush()
        self.token = None


class world_writer(ContextManager[WriterLease]):
    """用法: with world_writer(session, world_id) as lease: ...（事务提交后释放由 with 完成）。

    说明：租约行与 tick 事务同库——writer 进入时 flush；释放 delete。
    """

    def __init__(self, session: Session, world_id: str, lease_seconds: int = 120):
        self.session = session
        self.lease = WriterLease(session, world_id, lease_seconds)

    def __enter__(self) -> WriterLease:
        self.lease.acquire()
        return self.lease

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
        try:
            self.lease.release()
        finally:
            if exc_type is not None:
                self.session.rollback()
            else:
                self.session.commit()
        return False

"""FENCING TOKEN —— 统一 Mutation Guard（M1 第一硬门槛）。

任何会修改 World State 的 Mutation Transaction 必须经 WorldMutationContext：

1. __enter__：verify + refresh 心跳（UPDATE runtime_lock WHERE
   lease_token=本事务 token AND owner=本 writer AND expires_at>now → 延长
   expires_at）。该写操作立即取得数据库写锁 → 同一世界同一时刻只有一个
   mutation 事务在途；verify 失败 → FENCING_VIOLATION（零写入）。
2. 事务内做任意世界状态写入。
3. commit()：COMMIT 前再次 assert_current_fence()（DB 中当前 token 必须仍等于
   本事务持有的 token 且未过期）——这是最终写入授权，不是事务开始的一次性检查。
4. 未显式 commit 或异常 → __exit__ 回滚（绝不裸提交）。

被接管的旧 Writer（token 已失效）即使恢复执行，其 mutation 事务在 __enter__
或 commit() 任一环节都会失败，不允许写入任何世界状态。
FENCING 不知道人口/NPC/灾劫：它是纯写入授权门禁。
"""
from __future__ import annotations

from datetime import timedelta
from typing import ContextManager

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from config.settings import Settings
from database.base import utcnow
from database.models_core import RuntimeLock
from domain.errors import FencingViolation


class WorldMutationContext(ContextManager["WorldMutationContext"]):
    """统一 Mutation Guard：所有世界状态写入的唯一受保护事务入口。"""

    def __init__(self, session: Session, *, world_id: str, writer_id: str,
                 fencing_token: str, lease_seconds: int | None = None):
        self.session = session
        self.world_id = world_id
        self.writer_id = writer_id
        self.fencing_token = fencing_token
        self.lease_seconds = lease_seconds or Settings().writer_lease_seconds
        self._committed = False

    def __enter__(self) -> "WorldMutationContext":
        now = utcnow()
        expires = now + timedelta(seconds=self.lease_seconds)
        result = self.session.execute(
            update(RuntimeLock)
            .where(RuntimeLock.world_id == self.world_id,
                   RuntimeLock.lease_token == self.fencing_token,
                   RuntimeLock.owner == self.writer_id,
                   RuntimeLock.expires_at > now)
            .values(expires_at=expires))
        if result.rowcount != 1:
            self.session.rollback()
            raise FencingViolation(
                "fencing 校验失败：token/owner 与 DB 不一致或租约已过期",
                detail={"world_id": self.world_id,
                        "writer_id": self.writer_id})
        return self

    def assert_current_fence(self) -> None:
        """COMMIT 前最终验证：DB 中当前 fencing token 必须仍等于本事务 token。"""
        now = utcnow()
        row = self.session.execute(
            select(RuntimeLock)
            .where(RuntimeLock.world_id == self.world_id)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if (row is None or row.lease_token != self.fencing_token
                or row.owner != self.writer_id or row.expires_at <= now):
            raise FencingViolation(
                "commit 前 fencing 校验失败：token 已 stale",
                detail={"world_id": self.world_id,
                        "writer_id": self.writer_id,
                        "db_token": getattr(row, "lease_token", None)})

    def commit(self) -> None:
        self.assert_current_fence()  # COMMIT 前最终验证（不是开始时的检查）
        self.session.commit()
        self._committed = True

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
        if exc_type is not None or not self._committed:
            self.session.rollback()
        return False

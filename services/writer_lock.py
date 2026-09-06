"""SINGLE_WORLD_WRITER（14 节）+ STALE_WRITER_RECOVERY（M0 DSH QA 修正）。

租约模型（runtime_lock 表）：
- acquire 立即提交 → 租约跨进程可见（修正前序实现"租约直到 with 退出才提交"的
  跨进程空洞）。
- select-first 竞争协议：先读行 → 无行则 INSERT（PK 冲突 → 重读重判）；
  有行且未过期 → WRITER_LOCK_CONFLICT；已过期 → CAS 接管
  （UPDATE ... WHERE expires_at <= now，行数为 0 即被他人抢先，不抢注）。
- owner identity：host:pid:process_run_id 记录于 owner 列；lease_token 随机。
- renew：长任务续约（仅同一 token 可续）。
- release：仅当 token 匹配才删除（fencing），绝不误删他人租约；
  释放失败不吞锁 —— 租约自然过期后下一 writer 接管。
- STALE_WRITER_RECOVERY：进程异常退出 / 机器重启 / 僵尸进程只留下过期租约，
  最坏阻塞 lease_seconds；过期即 stale，世界不会永久锁死。
- 边界说明（M1 硬性门禁，World Seed Activation 前必须 PASS）：接管只校验"租约已过期"；
  M1 所有世界 Mutation Transaction 提交前必须校验当前 fencing token —— 旧 Writer 被
  接管后即使恢复执行也不得提交任何世界状态（强 fencing）。本模块的 lease_token 即
  fencing token 的载体；M1 在原子 tick 提交路径接入校验。M0 未激活世界无写负载。
"""
from __future__ import annotations

import os
import secrets
import socket
import uuid
from datetime import timedelta
from typing import ContextManager

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config.settings import Settings
from database.base import utcnow
from database.models_core import RuntimeLock
from domain.errors import WriterLockConflict
from services.logging_setup import get_logger

log = get_logger("LOCK")

_PROCESS_RUN_ID = uuid.uuid4().hex[:8]


def default_owner_id() -> str:
    try:
        host = socket.gethostname()
    except OSError:
        host = "unknown"
    return f"{host}:{os.getpid()}:{_PROCESS_RUN_ID}"


class WriterLease:
    def __init__(self, session: Session, world_id: str, lease_seconds: int = 120,
                 owner: str | None = None):
        self.session = session
        self.world_id = world_id
        self.lease_seconds = lease_seconds
        self.owner = owner or default_owner_id()
        self.token: str | None = None

    def _load(self) -> RuntimeLock | None:
        return self.session.execute(
            select(RuntimeLock).where(RuntimeLock.world_id == self.world_id)
        ).scalar_one_or_none()

    def _cas_takeover(self, row: RuntimeLock, now, token: str, expires) -> None:
        """过期租约 CAS 接管；并发下失败（rowcount=0）→ 冲突，不抢注。"""
        result = self.session.execute(
            update(RuntimeLock)
            .where(RuntimeLock.world_id == self.world_id,
                   RuntimeLock.expires_at <= now)
            .values(lease_token=token, owner=self.owner,
                    acquired_at=now, expires_at=expires))
        if result.rowcount != 1:
            raise WriterLockConflict(
                "租约刚被其他 writer 接管",
                detail={"world_id": self.world_id})
        # 同步身份映射中的实例，避免后续 release/renew 读到陈旧 token
        row.lease_token = token
        row.owner = self.owner
        row.acquired_at = now
        row.expires_at = expires

    def acquire(self) -> None:
        """获取或接管租约；成功即 commit（跨进程可见）。"""
        now = utcnow()
        token = secrets.token_hex(16)
        expires = now + timedelta(seconds=self.lease_seconds)
        row = self._load()
        if row is not None and row.expires_at > now:
            raise WriterLockConflict(
                "另一 Runtime 正在推进该世界",
                detail={"owner": row.owner, "expires_at": str(row.expires_at)})
        if row is None:
            try:
                self.session.add(RuntimeLock(
                    world_id=self.world_id, lease_token=token, owner=self.owner,
                    acquired_at=now, expires_at=expires))
                self.session.flush()
            except IntegrityError:
                # 并发插入竞争：回滚后重读重判
                self.session.rollback()
                row = self._load()
                if row is None:
                    raise WriterLockConflict(
                        "租约竞争：锁定行在竞争期间消失",
                        detail={"world_id": self.world_id})
                if row.expires_at > now:
                    raise WriterLockConflict(
                        "另一 Runtime 正在推进该世界",
                        detail={"owner": row.owner, "expires_at": str(row.expires_at)})
                self._cas_takeover(row, now, token, expires)
        else:
            # 行存在且已过期 → STALE_WRITER_RECOVERY：CAS 接管
            self._cas_takeover(row, now, token, expires)
        self.session.commit()  # 立即提交：租约跨进程可见
        self.token = token

    def renew(self) -> None:
        """长任务续约：仅同一 token 可续；被接管后续约失败。"""
        if self.token is None:
            raise WriterLockConflict("未持有租约，无法续约")
        now = utcnow()
        result = self.session.execute(
            update(RuntimeLock)
            .where(RuntimeLock.world_id == self.world_id,
                   RuntimeLock.lease_token == self.token)
            .values(expires_at=now + timedelta(seconds=self.lease_seconds)))
        self.session.commit()
        if result.rowcount != 1:
            raise WriterLockConflict("租约已被接管或释放，无法续约",
                                     detail={"world_id": self.world_id})

    def release(self) -> None:
        """释放租约：仅当 token 匹配（fencing）；token 不匹配不动他人租约。"""
        if self.token is None:
            return
        row = self.session.execute(
            select(RuntimeLock)
            .where(RuntimeLock.world_id == self.world_id)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if row is not None and row.lease_token == self.token:
            self.session.delete(row)
            self.session.flush()
            self.session.commit()
        self.token = None


class world_writer(ContextManager[WriterLease]):
    """用法: with world_writer(session, world_id) as lease: ...（M1 推进入口组合模式）。"""

    def __init__(self, session: Session, world_id: str,
                 lease_seconds: int | None = None):
        if lease_seconds is None:
            lease_seconds = Settings().writer_lease_seconds
        self.session = session
        self.lease = WriterLease(session, world_id, lease_seconds)

    def __enter__(self) -> WriterLease:
        self.lease.acquire()
        return self.lease

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
        error: BaseException | None = exc
        if exc_type is None:
            try:
                self.session.commit()
            except Exception as commit_exc:  # noqa: BLE001
                error = commit_exc
                try:
                    self.session.rollback()
                except Exception:  # noqa: BLE001
                    pass
        else:
            try:
                self.session.rollback()
            except Exception:  # noqa: BLE001
                pass
        try:
            self.lease.release()
        except Exception as release_exc:  # noqa: BLE001
            # 释放失败不吞世界锁：租约自然过期后由 STALE_WRITER_RECOVERY 接管
            log.error("释放租约失败（将由过期机制兜底）world=%s err=%s",
                      self.lease.world_id, release_exc)
        return False

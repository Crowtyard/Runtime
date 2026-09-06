"""Repository 层（5 节 POSTGRESQL_MIGRATION_READY：业务只经 Repository/ORM 访问）。

事件不可变：EventRepository 只提供 insert / query，无 update/delete；
DB 触发器（migration b2d4e8f9a6c3）在数据库层阻止 UPDATE/DELETE；
纠错通过新事件（supersedes/reverses + correction_reason，17 节）。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from database.models_core import (
    SimulationCheckpoint,
    TimeRatioHistory,
    WorldEvent,
    WorldRuntime,
)
from domain.blessed_time import datetime_to_epoch_us
from domain.errors import IntegrityError


def _current_schema_version(session: Session) -> str:
    row = session.execute(
        text("SELECT version_num FROM alembic_version LIMIT 1")).fetchone()
    return row[0] if row else "0000"


class RuntimeRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self) -> WorldRuntime | None:
        return self.session.execute(select(WorldRuntime).limit(1)).scalar_one_or_none()

    def create_not_activated(self, *, world_id: str, world_bible_version: str,
                             simulation_version: str,
                             world_bible_manifest_hash: str | None = None) -> WorldRuntime:
        """创建 NOT_ACTIVATED 运行时行（绝不激活世界）。"""
        world = WorldRuntime(
            world_id=world_id,
            world_bible_version=world_bible_version,
            simulation_version=simulation_version,
            schema_version=_current_schema_version(self.session),
            world_seed_version=None,
            current_blessed_tick=None,
            last_simulated_real_time=None,
            current_time_ratio_id=None,
            runtime_status="NOT_ACTIVATED",
            world_bible_manifest_hash=world_bible_manifest_hash or "",
        )
        self.session.add(world)
        self.session.flush()  # 立即落库：后续同事务插入依赖 FK 时可确定可见
        return world

    def sync_schema_version(self) -> None:
        """把 runtime 行的 schema_version 校正为当前 alembic head（版本锁三要素之一）。"""
        row = self.get()
        if row is None:
            return
        current = _current_schema_version(self.session)
        if row.schema_version != current:
            row.schema_version = current


class TimeRatioRepository:
    """TIME_RATIO_HISTORY（9 节）：effective-dated 有理速率，禁止只存当前值。

    速率 = rate_numerator [blessed ticks] / rate_denominator [real µs]，
    从 DB 起就是整数分子/分母（无 float 倍率真值，可审计、可复现）。
    """

    def __init__(self, session: Session):
        self.session = session

    def add(self, *, world_id: str, real_effective_from: datetime,
            rate_numerator: int, rate_denominator: int, reason: str, source: str,
            blessed_effective_from_tick: int | None = None) -> TimeRatioHistory:
        if rate_numerator <= 0 or rate_denominator <= 0:
            raise ValueError("速率分子/分母必须为正整数")
        row = TimeRatioHistory(
            world_id=world_id,
            real_effective_from=real_effective_from,
            real_effective_from_us=datetime_to_epoch_us(real_effective_from),
            blessed_effective_from_tick=blessed_effective_from_tick,
            rate_numerator=rate_numerator,
            rate_denominator=rate_denominator,
            reason=reason,
            source=source,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def list_all(self) -> list[TimeRatioHistory]:
        return list(self.session.execute(
            select(TimeRatioHistory).order_by(TimeRatioHistory.real_effective_from_us)
        ).scalars())

    def list_effective_up_to(self, world_id: str, real_end_us: int) -> list[TimeRatioHistory]:
        """所有 real_effective_from_us <= real_end_us 的速率行（分段积分的候选窗口集）。"""
        return list(self.session.execute(
            select(TimeRatioHistory)
            .where(TimeRatioHistory.world_id == world_id,
                   TimeRatioHistory.real_effective_from_us <= real_end_us)
            .order_by(TimeRatioHistory.real_effective_from_us)
        ).scalars())


class EventRepository:
    """只追加事件库：无 update/delete 方法（结构上杜绝历史篡改，DB 触发器兜底）。"""

    def __init__(self, session: Session):
        self.session = session

    def append(self, *, world_id: str, event_type: str, source: str,
               blessed_tick: int | None, real_time: datetime | None = None,
               severity: float = 0.0, scope: str = "AMBIENT",
               cause: dict | None = None, effect: dict | None = None,
               participants: list | None = None,
               state_changes: list | None = None,
               simulation_seed: int | None = None,
               parent_event_ref: str | None = None,
               supersedes_event_id: str | None = None,
               reverses_event_id: str | None = None,
               correction_reason: str | None = None) -> WorldEvent:
        from database.base import utcnow as _utcnow
        if real_time is None:
            real_time = _utcnow()
        event = WorldEvent(
            event_uid=str(uuid.uuid4())[:12],
            world_id=world_id,
            event_type=event_type,
            source=source,
            blessed_tick=blessed_tick,
            real_time=real_time,
            severity=severity,
            scope=scope,
            cause=cause or {},
            effect=effect or {},
            participants=participants or [],
            state_changes=state_changes or [],
            simulation_seed=simulation_seed,
            parent_event_ref=parent_event_ref,
            supersedes_event_id=supersedes_event_id,
            reverses_event_id=reverses_event_id,
            correction_reason=correction_reason,
        )
        self.session.add(event)
        self.session.flush()
        return event

    def append_correction(self, *, original_event_id: str, **kw) -> WorldEvent:
        """纠错=新事件（17 节）；原事件永不修改。"""
        original = self.session.execute(
            select(WorldEvent).where(WorldEvent.event_uid == original_event_id)
        ).scalar_one_or_none()
        if original is None:
            raise IntegrityError("correction 指向不存在的事件", detail=original_event_id)
        kw.setdefault("supersedes_event_id", original_event_id)
        kw.setdefault("correction_reason", "CORRECTION")
        return self.append(**kw)

    def get(self, event_uid: str) -> WorldEvent | None:
        return self.session.execute(
            select(WorldEvent).where(WorldEvent.event_uid == event_uid)
        ).scalar_one_or_none()

    def chain_of(self, event_uid: str, *, limit: int = 32) -> list[WorldEvent]:
        """沿 parent_event_ref（event_uid 引用）回溯因果链（M3 历史服务的基础查询）。"""
        chain: list[WorldEvent] = []
        cur = self.get(event_uid)
        while cur is not None and len(chain) < limit:
            chain.append(cur)
            cur = self.get(cur.parent_event_ref) if cur.parent_event_ref else None
        return chain


class CheckpointRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, *, world_id: str, blessed_tick: int,
               world_state_hash: str, meta: dict | None = None,
               complete: bool = True,
               last_committed_real_us: int | None = None,
               rate_id: int | None = None,
               rate_remainder: int = 0,
               simulation_version: str | None = None,
               last_committed_run_id: str | None = None,
               writer_id: str | None = None,
               fencing_token: str | None = None) -> SimulationCheckpoint:
        """持久化 checkpoint：crash 后仅依赖 DB 即可恢复时钟状态。"""
        row = SimulationCheckpoint(
            world_id=world_id,
            checkpoint_blessed_tick=blessed_tick,
            world_state_hash=world_state_hash,
            complete=complete, meta=meta or {},
            last_committed_real_us=last_committed_real_us,
            rate_id=rate_id,
            rate_remainder=rate_remainder,
            simulation_version=simulation_version,
            last_committed_run_id=last_committed_run_id,
            writer_id=writer_id,
            fencing_token=fencing_token,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def latest_complete(self, world_id: str) -> SimulationCheckpoint | None:
        return self.session.execute(
            select(SimulationCheckpoint)
            .where(SimulationCheckpoint.world_id == world_id,
                   SimulationCheckpoint.complete.is_(True))
            .order_by(SimulationCheckpoint.checkpoint_blessed_tick.desc())
            .limit(1)
        ).scalar_one_or_none()

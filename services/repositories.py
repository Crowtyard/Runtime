"""Repository 层（5 节 POSTGRESQL_MIGRATION_READY：业务只经 Repository/ORM 访问）。

事件不可变：EventRepository 只提供 insert / query，无 update/delete；
纠错通过新事件（supersedes/reverses + correction_reason，17 节）。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models_core import (
    SimulationCheckpoint,
    TimeRatioHistory,
    WorldEvent,
    WorldRuntime,
)
from domain.errors import IntegrityError


class RuntimeRepository:
    def __init__(self, session: Session):
        self.session = session

    def get(self) -> WorldRuntime | None:
        return self.session.execute(select(WorldRuntime).limit(1)).scalar_one_or_none()

    def create_not_activated(self, *, world_id: str, world_bible_version: str,
                             simulation_version: str,
                             world_bible_manifest_hash: str | None = None) -> WorldRuntime:
        from sqlalchemy import text as _text
        row = self.session.execute(_text(
            "SELECT version_num FROM alembic_version ORDER BY version_num DESC LIMIT 1"
        )).fetchone()
        schema_version = row[0] if row else "0000"
        world = WorldRuntime(
            world_id=world_id,
            world_bible_version=world_bible_version,
            simulation_version=simulation_version,
            schema_version=schema_version,
            world_seed_version=None,
            current_blessed_time=None,
            last_simulated_real_time=None,
            current_time_ratio_id=None,
            runtime_status="NOT_ACTIVATED",
            world_bible_manifest_hash=world_bible_manifest_hash,
        )
        self.session.add(world)
        self.session.flush()  # 立即落库：后续同事务插入依赖 FK 时可确定可见
        return world


class TimeRatioRepository:
    """TIME_RATIO_HISTORY（9 节）：effective-dated，禁止只存当前值。"""

    def __init__(self, session: Session):
        self.session = session

    def add(self, *, world_id: str, real_effective_from: datetime,
            ratio_value: float, reason: str, source: str,
            blessed_effective_from: int | None = None) -> TimeRatioHistory:
        row = TimeRatioHistory(
            world_id=world_id,
            real_effective_from=real_effective_from,
            blessed_effective_from=blessed_effective_from,
            ratio_value=ratio_value,
            reason=reason,
            source=source,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def list_all(self) -> list[TimeRatioHistory]:
        return list(self.session.execute(
            select(TimeRatioHistory).order_by(TimeRatioHistory.real_effective_from)
        ).scalars())


class EventRepository:
    """只追加事件库：无 update/delete 方法（结构上杜绝历史篡改）。"""

    def __init__(self, session: Session):
        self.session = session

    def append(self, *, world_id: str, event_type: str, source: str,
               blessed_time: int | None, real_time: datetime | None = None,
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
            blessed_time=blessed_time,
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

    def get(self, event_id: str) -> WorldEvent | None:
        return self.session.execute(
            select(WorldEvent).where(WorldEvent.event_uid == event_id)
        ).scalar_one_or_none()

    def chain_of(self, event_id: str, *, limit: int = 32) -> list[WorldEvent]:
        """沿 parent_event_ref 回溯因果链（M3 历史服务的基础查询）。"""
        chain: list[WorldEvent] = []
        cur = self.session.get(WorldEvent, event_id)
        while cur is not None and len(chain) < limit:
            chain.append(cur)
            cur = self.session.get(WorldEvent, cur.parent_event_ref) \
                if cur.parent_event_ref else None
        return chain


class CheckpointRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, *, world_id: str, blessed_time: int,
               world_state_hash: str, meta: dict | None = None,
               complete: bool = True) -> SimulationCheckpoint:
        row = SimulationCheckpoint(world_id=world_id,
                                   checkpoint_blessed_time=blessed_time,
                                   world_state_hash=world_state_hash,
                                   complete=complete, meta=meta or {})
        self.session.add(row)
        self.session.flush()
        return row

    def latest_complete(self, world_id: str) -> SimulationCheckpoint | None:
        return self.session.execute(
            select(SimulationCheckpoint)
            .where(SimulationCheckpoint.world_id == world_id,
                   SimulationCheckpoint.complete.is_(True))
            .order_by(SimulationCheckpoint.checkpoint_blessed_time.desc())
            .limit(1)
        ).scalar_one_or_none()

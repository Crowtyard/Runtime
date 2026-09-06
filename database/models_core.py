"""核心表模型（M0）：world_runtime / 版本 / 时间 / 运行 / 事件 / 叙事 / 锁 / 配置。

时间列约定（M0 DSH QA 修正）：
- 一切 blessed 时间坐标 = CANONICAL_BLESSED_TICK（整数 µy，见 domain/blessed_time），
  列名以 ``*_tick`` 结尾、BigInteger（SQLite 64-bit INTEGER / PostgreSQL BIGINT）。
- 一切现实时间 = aware UTC（UtcDateTime）。
事件表 immutable：DB 触发器阻止 UPDATE/DELETE（migration b2d4e8f9a6c3），
Repository 层同样只提供 INSERT。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (JSON, BigInteger, Boolean, ForeignKey, Integer, String,
                        Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, UtcDateTime, utcnow


class WorldRuntime(Base):
    __tablename__ = "world_runtime"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    world_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)  # 'BL-0001'
    world_bible_version: Mapped[str] = mapped_column(String(16), nullable=False)  # '1.0'
    world_bible_manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    simulation_version: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    world_seed_version: Mapped[str | None] = mapped_column(String(32), nullable=True)  # NULL=未激活
    runtime_status: Mapped[str] = mapped_column(String(24), nullable=False,
                                                default="NOT_ACTIVATED")
    last_simulated_real_time: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    current_blessed_tick: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    current_time_ratio_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow,
                                                 nullable=False)


class TimeRatioHistory(Base):
    """TIME_RATIO_HISTORY（9 节）：effective-dated；离线补算按区间分段积分。

    ratio 语义：现实 1 天 = ratio_value 福地年。
    blessed_effective_from_tick = NULL 表示"尚未开始计"（世界未激活）；
    非空时表示该 ratio 从该 canonical tick 起对福地时间生效。
    """
    __tablename__ = "time_ratio_history"

    ratio_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    world_id: Mapped[str] = mapped_column(String(64), ForeignKey("world_runtime.world_id"),
                                          nullable=False)
    real_effective_from: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    blessed_effective_from_tick: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ratio_value: Mapped[float] = mapped_column(nullable=False)  # 自然状态 365.0（Bible WS-0201）
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow, nullable=False)


class SimulationRun(Base):
    """SIMULATION_RUN + TICK_IDENTITY（11 节）：防 crash/retry 重复写事件。

    幂等身份 = world_id + simulation_version + status=COMMITTED + committed_until_tick；
    旧 simulation_version 的 committed_until_tick 不得阻止新版合法推进。
    """
    __tablename__ = "simulation_run"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    world_id: Mapped[str] = mapped_column(String(64), ForeignKey("world_runtime.world_id"),
                                          nullable=False)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow, nullable=False)
    target_blessed_tick: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    committed_until_tick: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    simulation_version: Mapped[str] = mapped_column(String(32), nullable=False)
    seed_context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)


class SimulationCheckpoint(Base):
    __tablename__ = "simulation_checkpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    world_id: Mapped[str] = mapped_column(String(64), ForeignKey("world_runtime.world_id"),
                                          nullable=False)
    checkpoint_blessed_tick: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    world_state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    meta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow, nullable=False)


class WorldEvent(Base):
    """不可变事件（17 节）：DB 触发器禁 UPDATE/DELETE；纠错=新事件
    （supersedes/reverses + correction_reason）。"""
    __tablename__ = "world_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_uid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    world_id: Mapped[str] = mapped_column(String(64), ForeignKey("world_runtime.world_id"),
                                          nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    cause: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    effect: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    severity: Mapped[float | None] = mapped_column(nullable=True)
    scope: Mapped[str | None] = mapped_column(String(16), nullable=True)
    participants: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    state_changes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    blessed_tick: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    real_time: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    simulation_seed: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_event_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    supersedes_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reverses_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correction_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("event_uid", name="uq_world_events_event_uid"),
    )


class WorldStateChange(Base):
    __tablename__ = "world_state_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    world_id: Mapped[str] = mapped_column(String(64), ForeignKey("world_runtime.world_id"),
                                          nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    field: Mapped[str] = mapped_column(String(64), nullable=False)
    old_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    event_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    blessed_tick: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    real_time: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)


class NarrativeRecord(Base):
    """叙事与事实分离（19 节）：叙事只读 source events，无状态变更权限。"""
    __tablename__ = "narrative_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    world_id: Mapped[str] = mapped_column(String(64), ForeignKey("world_runtime.world_id"),
                                          nullable=False)
    source_event_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    renderer_version: Mapped[str] = mapped_column(String(32), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow, nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="zh-CN")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class RuntimeLock(Base):
    """SINGLE_WORLD_WRITER（14 节）：同一世界同一时间只有一个推进者。

    STALE_WRITER_RECOVERY：租约到期即 stale，新 writer CAS 接管；
    崩溃/重启/僵尸进程最多阻塞 lease_seconds，不会永久锁死世界。
    """
    __tablename__ = "runtime_lock"

    world_id: Mapped[str] = mapped_column(String(64), ForeignKey("world_runtime.world_id"),
                                          primary_key=True)
    lease_token: Mapped[str] = mapped_column(String(64), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    owner: Mapped[str] = mapped_column(String(64), nullable=False)


class SystemConfiguration(Base):
    """system configuration（非世界内容；世界规则引用 Bible，不在此复制）。"""
    __tablename__ = "system_configuration"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)  # SYSTEM | WORLD_RULE_REF
    value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow,
                                                 onupdate=utcnow, nullable=False)

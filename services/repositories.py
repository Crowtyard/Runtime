"""Repository 层（5 节 POSTGRESQL_MIGRATION_READY：业务只经 Repository/ORM 访问）。

事件不可变：EventRepository 只提供 insert / query，无 update/delete；
DB 触发器（migration b2d4e8f9a6c3）在数据库层阻止 UPDATE/DELETE；
纠错通过新事件（supersedes/reverses + correction_reason，17 节）。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..database.models_core import (
    SimulationCheckpoint,
    TimeRatioHistory,
    WorldEvent,
    WorldRuntime,
)
from ..domain.blessed_time import MAX_TICK, MIN_TICK, datetime_to_epoch_us
from ..domain.constants import RuntimeStatus
from ..domain.errors import ActivationRefused, IntegrityError


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

    # ------------------------------------------------------------- M6A 激活原语
    def assert_activatable(self, *, world_id: str) -> WorldRuntime:
        """激活前置条件（fail-closed）：不满足即 ``ActivationRefused``，零写入。

        条件（全部为 durable 行状态，不看进程内状态）：
        - runtime 行存在且 ``world_id`` 与请求一致（世界身份不得漂移）；
        - ``runtime_status == NOT_ACTIVATED``（已 ACTIVE ＝ 已激活 → 拒绝，幂等语义
          由 service 层给出，本原语绝不覆盖既有已激活世界）；
        - ``world_seed_version is None``（seed 未生效）；
        - 时钟三件套仍为未初始化（``current_blessed_tick`` / ``last_committed_real_us``
          为 NULL）—— 激活只能从干净未激活态出发，绝不覆盖半初始化时钟。
        """
        row = self.get()
        if row is None:
            raise ActivationRefused(
                "world_runtime 行缺失（未播种 metadata）",
                detail={"world_id": world_id})
        if row.world_id != world_id:
            raise ActivationRefused(
                "请求 world_id 与 DB 中的正式世界不一致（禁止激活第二个世界）",
                detail={"requested": world_id, "db": row.world_id})
        if row.runtime_status != RuntimeStatus.NOT_ACTIVATED:
            raise ActivationRefused(
                "世界已激活或处于非 NOT_ACTIVATED 状态；禁止二次激活",
                detail={"world_id": row.world_id,
                        "runtime_status": row.runtime_status})
        if row.world_seed_version is not None:
            raise ActivationRefused(
                "world_seed_version 已生效；禁止二次消费 Seed",
                detail={"world_id": row.world_id,
                        "world_seed_version": row.world_seed_version})
        if row.current_blessed_tick is not None or \
                row.last_committed_real_us is not None:
            raise ActivationRefused(
                "世界时钟已初始化（tick/real cursor 非 NULL）；"
                "激活不得覆盖既有时间锚",
                detail={"current_blessed_tick": row.current_blessed_tick,
                        "last_committed_real_us": row.last_committed_real_us})
        return row

    def activate(self, *, world_id: str, world_seed_version: str,
                 initial_blessed_tick: int, activation_real_us: int,
                 current_time_ratio_id: int | None) -> WorldRuntime:
        """把 NOT_ACTIVATED 运行时行转为 ACTIVE（**唯一**受保护的激活原语）。

        本方法**绝不 commit**：commit 由调用方的 ``WorldMutationContext`` 负责，
        因而激活的全部写入（本行 + genesis 事件 + 速率行绑定）落在同一个
        durable 事务里（A4/A5：一次性原子创建，失败整体 rollback，无部分状态）。

        PG-011 教训（POSTGRESQL_COMPATIBILITY_CONTRACT §11）：SQLite 不强制
        ``VARCHAR(N)`` 而 PostgreSQL 强制 —— 入库前显式校验列宽，避免 PG 侧
        ``DataError`` 在提交时炸掉激活事务。
        """
        row = self.assert_activatable(world_id=world_id)
        if not isinstance(world_seed_version, str) or not world_seed_version:
            raise ActivationRefused("world_seed_version 必须为非空字符串")
        if len(world_seed_version) > 32:  # world_runtime.world_seed_version VARCHAR(32)
            raise ActivationRefused(
                "world_seed_version 超出列宽（VARCHAR(32)）；PG 会拒绝该值",
                detail={"length": len(world_seed_version)})
        if isinstance(initial_blessed_tick, bool) or \
                not isinstance(initial_blessed_tick, int):
            raise ActivationRefused("initial_blessed_tick 必须为整数（canonical tick）")
        if not (MIN_TICK <= initial_blessed_tick <= MAX_TICK):
            raise ActivationRefused(
                "initial_blessed_tick 超出 64-bit canonical tick 范围",
                detail={"initial_blessed_tick": initial_blessed_tick})
        if isinstance(activation_real_us, bool) or \
                not isinstance(activation_real_us, int) or activation_real_us <= 0:
            raise ActivationRefused(
                "activation_real_us 必须为正整数（现实 epoch µs）")

        row.runtime_status = RuntimeStatus.ACTIVE
        row.world_seed_version = world_seed_version
        row.current_blessed_tick = initial_blessed_tick
        row.last_committed_real_us = activation_real_us
        row.current_time_ratio_id = current_time_ratio_id
        # 激活即世界时间原点：余数进位从 0 起（不得继承未激活期的任何进位）
        row.time_rate_remainder = 0
        self.session.flush()
        return row


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

    def bind_blessed_start(self, *, ratio_id: int,
                           blessed_effective_from_tick: int) -> TimeRatioHistory:
        """记录"该速率从某 canonical tick 起对福地时间生效"（M6A 激活时调用）。

        ``blessed_effective_from_tick = NULL`` 的语义是"尚未开始计（世界未激活）"
        （见 database/models_core.TimeRatioHistory）；激活即世界时间原点，
        因此该列由 NULL 变为 initial blessed tick。**绝不 commit**（由调用方的
        激活事务统一提交）；已绑定到不同的 tick → 拒绝（禁止二次改写时间原点）。
        """
        row = self.session.execute(
            select(TimeRatioHistory).where(TimeRatioHistory.ratio_id == ratio_id)
        ).scalar_one_or_none()
        if row is None:
            raise ActivationRefused("速率行不存在",
                                    detail={"ratio_id": ratio_id})
        if row.blessed_effective_from_tick is not None and \
                row.blessed_effective_from_tick != blessed_effective_from_tick:
            raise ActivationRefused(
                "速率行已绑定福地起始 tick；禁止改写既有时间原点",
                detail={"ratio_id": ratio_id,
                        "existing": row.blessed_effective_from_tick})
        row.blessed_effective_from_tick = blessed_effective_from_tick
        self.session.flush()
        return row


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
               correction_reason: str | None = None,
               event_uid: str | None = None) -> WorldEvent:
        from ..database.base import utcnow as _utcnow
        if real_time is None:
            real_time = _utcnow()
        if event_uid is None:
            # M2 Review 硬化：确定性 128-bit fallback（无 UUID4/wallclock；
            # M2 路径全部显式传确定性 uid，此 fallback 仅为遗留调用兜底）
            from .identity import deterministic_hex_id
            event_uid = deterministic_hex_id(
                [world_id, event_type, str(blessed_tick), source,
                 repr(cause or {}), repr(effect or {})],
                bits=128, schema="event-uid-fallback-v1")
        event = WorldEvent(
            event_uid=event_uid,
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

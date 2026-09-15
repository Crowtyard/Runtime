# -*- coding: utf-8 -*-
"""DURABLE TRUTH（M6A）：commit 结果未知时**唯一**允许的核对来源。

纪律来源（PG-012 / PRE-M6 commit ambiguity gate，见
``docs/pre_m6_pg_commit_ambiguity_audit.md``）：

```
COMMIT 结果未知
  → 绝不盲重试
  → 先读 durable truth
  → 判定 COMMITTED / NOT_COMMITTED
  → 再行动
  → durable truth 不可读取 ＝ fail-closed（RECOVERING/FAILED）
```

本模块把该纪律提取为**唯一实现**：此前它只存在于 ``RuntimeScheduler`` 的私有方法
（``_read_durable_tick_resilient`` / ``_recover_truth``）中，激活服务若自行再写一份
就成了第二套 commit 协议 —— 明令禁止。Scheduler 与 M6 activation service 共用本模块。

本模块**不接触 World Seed**：它只读正式库的 durable 真值，因此不在
``ACTIVATION_BOUNDARY_GUARD`` 的种子访问 allowlist 内（也不需要）。
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from ..database.models_core import WorldEvent, WorldRuntime
from ..domain.constants import ActivationState, RuntimeStatus

#: genesis 事件类型（canon：12_initial_event_boundary.json 的 activation_event）
#: 定义在本模块是为了让 durable-truth 读取不依赖 activation 包
#: （依赖方向：activation → durable_truth；scheduler → durable_truth）。
GENESIS_EVENT_TYPE = "WORLD_SEED_ACTIVATED"


@dataclass(frozen=True)
class ActivationTruth:
    """激活的 durable 真值快照（只读）。"""

    state: str
    world_id: str | None
    runtime_status: str | None
    world_seed_version: str | None
    current_blessed_tick: int | None
    last_committed_real_us: int | None
    genesis_events: int
    seed_consumption_count: int

    @property
    def committed(self) -> bool:
        return self.state == ActivationState.COMMITTED


def world_id_filter(stmt, world_id: str | None):  # noqa: ANN001
    return stmt if world_id is None else stmt.where(
        WorldRuntime.world_id == world_id)


def read_runtime_row(session: Session, world_id: str | None = None,
                     ) -> WorldRuntime | None:
    """读 durable runtime 行（world_id=None → 唯一行语义）。"""
    return session.execute(
        world_id_filter(select(WorldRuntime), world_id).limit(1)
    ).scalar_one_or_none()


def read_durable_tick_resilient(session_factory: sessionmaker[Session], *,
                                world_id: str | None = None,
                                attempts: int = 2) -> int | None:
    """读取 durable tick；连接故障时重试（失效连接会被连接池回收）。

    仍失败则**抛出** —— 调用方必须 fail-closed（durable truth 不可判定时
    绝不允许继续推进或重试）。语义与 M4 ``RuntimeScheduler`` 原私有实现逐字一致
    （fresh session / 仅对 DBAPIError 重试 / 耗尽后抛出）。
    """
    last_exc: Exception | None = None
    for _ in range(max(1, attempts)):
        try:
            with session_factory() as s:
                row = read_runtime_row(s, world_id)
                return row.current_blessed_tick if row is not None else None
        except DBAPIError as exc:  # noqa: PERF203
            last_exc = exc
    raise last_exc if last_exc is not None else RuntimeError("durable tick 读取失败")


def count_genesis_events(session: Session, world_id: str | None = None) -> int:
    """genesis 事件（WORLD_SEED_ACTIVATED）条数 —— seed 消费次数的 durable 证据。"""
    stmt = text("SELECT COUNT(*) FROM world_events WHERE event_type = :t")
    params: dict = {"t": GENESIS_EVENT_TYPE}
    if world_id is not None:
        stmt = text("SELECT COUNT(*) FROM world_events "
                    "WHERE event_type = :t AND world_id = :w")
        params["w"] = world_id
    return int(session.execute(stmt, params).scalar() or 0)


def count_events(session: Session, world_id: str | None = None) -> int:
    """正式事件总条数（A2/A10：未激活世界的官方历史必须为空）。"""
    if world_id is None:
        return int(session.execute(
            text("SELECT COUNT(*) FROM world_events")).scalar() or 0)
    return int(session.execute(
        text("SELECT COUNT(*) FROM world_events WHERE world_id = :w"),
        {"w": world_id}).scalar() or 0)


def read_world_epoch_anchor(session_factory: sessionmaker[Session], *,
                            world_id: str | None = None) -> int | None:
    """读回**激活时确立的世界年锚** ``epoch0_us``（durable truth）。

    年锚是激活事务写下的权威事实（记录在 genesis 事件的 ``effect`` 内），
    它不是"派生量"：Runtime 的 planner 必须用**同一个**年锚校验
    ``cursor == epoch0 + year_start*YEAR_US``（services/scheduler/planner.py:97-102），
    否则已激活世界永远无法推进。本读取器是该事实的唯一读法。

    未激活（无 genesis 事件）→ None。
    """
    with session_factory() as s:
        ev = s.execute(
            select(WorldEvent)
            .where(WorldEvent.event_type == GENESIS_EVENT_TYPE,
                   *(([WorldEvent.world_id == world_id]) if world_id else []))
            .order_by(WorldEvent.id).limit(1)).scalar_one_or_none()
    if ev is None:
        return None
    value = (ev.effect or {}).get("epoch0_us")
    return int(value) if isinstance(value, int) and not isinstance(value, bool) \
        else None


def read_activation_truth(session_factory: sessionmaker[Session], *,
                          world_id: str | None = None) -> ActivationTruth:
    """从 durable truth 判定激活状态（绝不看进程内状态）。

    判定（与 ``guard.require_world_activated`` / scheduler ``_activated`` 同口径）：
    ``runtime_status == ACTIVE`` **且** ``world_seed_version`` 非空 → COMMITTED。
    同时读取 genesis 事件条数作为 seed 消费次数的 durable 证据。
    """
    with session_factory() as s:
        row = read_runtime_row(s, world_id)
        genesis = count_genesis_events(s, world_id)
    if row is None:
        return ActivationTruth(state=ActivationState.NOT_STARTED, world_id=None,
                               runtime_status=None, world_seed_version=None,
                               current_blessed_tick=None,
                               last_committed_real_us=None,
                               genesis_events=genesis,
                               seed_consumption_count=genesis)
    committed = (row.runtime_status == RuntimeStatus.ACTIVE
                 and row.world_seed_version is not None)
    return ActivationTruth(
        state=(ActivationState.COMMITTED if committed
               else ActivationState.NOT_STARTED),
        world_id=row.world_id,
        runtime_status=row.runtime_status,
        world_seed_version=row.world_seed_version,
        current_blessed_tick=row.current_blessed_tick,
        last_committed_real_us=row.last_committed_real_us,
        genesis_events=genesis,
        seed_consumption_count=genesis,
    )

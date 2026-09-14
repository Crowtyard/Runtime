# -*- coding: utf-8 -*-
"""权威恢复 checkpoint 规则（M2 Preflight Hardening）。

checkpoint_kind 语义（冻结）：
- M1 CATCHUP（TIME_COMMITTED 层）：时间引擎 checkpoint —— 恢复现实游标/
  进位的最低限度（快速时钟恢复）。
- M2_PREFLIGHT（WORLD_COMMITTED 层，checkpoint_kind="WORLD_COMMITTED"，
  phase="COMMITTED"）：世界语义 checkpoint —— world_state_hash v2 +
  event_stream_hash + 引擎版本 —— **crash recovery 的权威 checkpoint**。

规则：每 1 个 committed simulation step 严格产生 1+1 个 checkpoint；
恢复一律以 complete=True 且 checkpoint_kind=WORLD_COMMITTED 的最新
M2 checkpoint 为准（CATCHUP 行不参与世界语义恢复）。

方言可移植性（PRE-M6 / PG-001，冻结约束）：
本模块处于**权威恢复路径**（services/simulation/coordinator.py 直接调用），
因此 meta JSON 键比较一律使用 SQLAlchemy 可移植表达式
（``SimulationCheckpoint.meta["k"].as_string()``）：SQLite 侧由 SQLAlchemy
方言编译为 ``JSON_EXTRACT``，PostgreSQL 侧编译为 ``->>``。
生产代码**不得**出现 SQLite 私有函数（json_extract/json_each 等）、
``sqlite_master``、``PRAGMA``，也不得依赖 ``complete = 1`` 这类隐式布尔
比较（PG 布尔列不接受与整数字面量比较），一律用 ``.is_(True)``。
静态门禁：tests/pg_portability_scan.py（全生产路径扫描，PG-002）。
"""
from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from ...database.models_core import SimulationCheckpoint

WORLD_COMMITTED_KIND = "WORLD_COMMITTED"
_M2_KIND = "M2_PREFLIGHT"
_M1_CATCHUP_KIND = "CATCHUP"


def _meta_equals(key: str, value: str):
    """方言可移植的 meta JSON 键等值条件（不写方言专用 SQL）。"""
    return SimulationCheckpoint.meta[key].as_string() == value


def authoritative_checkpoint_statement(world_id: str) -> Select:
    """权威恢复 checkpoint 查询（供执行与跨方言编译测试复用）。"""
    return (
        select(SimulationCheckpoint)
        .where(SimulationCheckpoint.world_id == world_id,
               SimulationCheckpoint.complete.is_(True),
               _meta_equals("checkpoint_kind", WORLD_COMMITTED_KIND))
        .order_by(SimulationCheckpoint.checkpoint_blessed_tick.desc())
        .limit(1)
    )


def checkpoint_count_statement(world_id: str, key: str, value: str) -> Select:
    """按 meta 键计数（time 层 / world 层审计；方言可移植）。"""
    return (
        select(func.count())
        .select_from(SimulationCheckpoint)
        .where(SimulationCheckpoint.world_id == world_id,
               SimulationCheckpoint.complete.is_(True),
               _meta_equals(key, value))
    )


def latest_authoritative_world_checkpoint(
        session: Session, world_id: str) -> SimulationCheckpoint | None:
    """权威恢复 checkpoint：最新 complete WORLD_COMMITTED（M2_PREFLIGHT）。"""
    return session.execute(
        authoritative_checkpoint_statement(world_id)).scalar_one_or_none()


def count_checkpoints_by_kind(session: Session, world_id: str) -> dict:
    """审计计数：time 层 vs world 层（HP7）。"""
    time_n = session.execute(
        checkpoint_count_statement(world_id, "kind", _M1_CATCHUP_KIND)).scalar()
    world_n = session.execute(
        checkpoint_count_statement(world_id, "checkpoint_kind",
                                   WORLD_COMMITTED_KIND)).scalar()
    return {"time_committed": int(time_n or 0),
            "world_committed": int(world_n or 0)}

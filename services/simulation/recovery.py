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
"""
from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ...database.models_core import SimulationCheckpoint

WORLD_COMMITTED_KIND = "WORLD_COMMITTED"
_M2_KIND = "M2_PREFLIGHT"


def latest_authoritative_world_checkpoint(
        session: Session, world_id: str) -> SimulationCheckpoint | None:
    """权威恢复 checkpoint：最新 complete WORLD_COMMITTED（M2_PREFLIGHT）。"""
    return session.execute(
        select(SimulationCheckpoint)
        .where(SimulationCheckpoint.world_id == world_id,
               SimulationCheckpoint.complete.is_(True),
               text("json_extract(meta, '$.checkpoint_kind') = "
                    f"'{WORLD_COMMITTED_KIND}'"))
        .order_by(SimulationCheckpoint.checkpoint_blessed_tick.desc())
        .limit(1)
    ).scalar_one_or_none()


def count_checkpoints_by_kind(session: Session, world_id: str) -> dict:
    """审计计数：time 层 vs world 层（HP7）。"""
    time_n = session.execute(text(
        "SELECT COUNT(*) FROM simulation_checkpoints "
        "WHERE complete = 1 AND json_extract(meta, '$.kind') = 'CATCHUP' "
        "AND world_id = :w"), {"w": world_id}).scalar()
    world_n = session.execute(text(
        "SELECT COUNT(*) FROM simulation_checkpoints "
        "WHERE complete = 1 AND "
        "json_extract(meta, '$.checkpoint_kind') = 'WORLD_COMMITTED' "
        "AND world_id = :w"), {"w": world_id}).scalar()
    return {"time_committed": time_n, "world_committed": world_n}

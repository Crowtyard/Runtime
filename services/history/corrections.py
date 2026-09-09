# -*- coding: utf-8 -*-
"""M3b Correction API：append-only 历史纠错（不原地改旧 event/uid/hash）。

- 新 HISTORY_CORRECTION 事件进入 event stream（确定性 uid）；
- CORRECTS / SUPERSEDES / REVERSES 建立新历史关系（FREE tick 规则，
  显式 retrospective 分类，绝不使用 CAUSES）；
- SUPERSEDES 语义：旧事件出边（ACTIVE links）置 SUPERSEDED；查询默认
  显示当前有效解释，include_superseded=true 查看完整审计链；
- supersede 环防护：已被取代的事件不得再作为取代源（v1 冻结规则：
  每事件至多被取代一次）。
- 经 WorldMutationContext commit-time fencing（stale writer 不得提交）。
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ...database.models_core import WorldEvent, WorldRuntime
from ...database.models_world import CausalHistoryLink
from ...domain.errors import IntegrityError
from ..fencing import WorldMutationContext
from ..repositories import EventRepository
from ..simulation.event_stream import deterministic_event_uid
from ..simulation.tribulation import M3A_SIMULATION_VERSION
from .builder import HistoryLinkBuilder
from .relations import CORRECTS, REVERSES, SUPERSEDES

CORRECTION_RELATIONS = (CORRECTS, SUPERSEDES, REVERSES)


@dataclass(frozen=True)
class HistoryCorrection:
    relation_type: str            # CORRECTS | SUPERSEDES | REVERSES
    target_kind: str              # EVENT | STATE_CHANGE
    target_id: str
    reason: str


def submit_history_correction(
    session_factory: sessionmaker[Session],
    *,
    world_id: str,
    writer_id: str,
    fencing_token: str,
    correction: HistoryCorrection,
    simulation_version: str = M3A_SIMULATION_VERSION,
) -> dict:
    """提交一次历史纠错（fenced；append-only；返回新事件 uid 与 link_id）。"""
    if correction.relation_type not in CORRECTION_RELATIONS:
        raise IntegrityError("非法纠错关系类型",
                             detail=correction.relation_type)
    if correction.target_kind not in ("EVENT", "STATE_CHANGE"):
        raise IntegrityError("纠错目标必须为 EVENT/STATE_CHANGE",
                             detail=correction.target_kind)
    builder = HistoryLinkBuilder()
    with WorldMutationContext(session_factory(), world_id=world_id,
                              writer_id=writer_id,
                              fencing_token=fencing_token) as ctx:
        s = ctx.session
        if not builder._node_exists(s, world_id, correction.target_kind,
                                    correction.target_id):
            raise IntegrityError("纠错目标不存在",
                                 detail={"kind": correction.target_kind,
                                         "id": correction.target_id})
        if correction.relation_type == SUPERSEDES:
            if correction.target_kind != "EVENT":
                raise IntegrityError("SUPERSEDES 目标必须为 EVENT",
                                     detail=correction.target_kind)
            existing = s.execute(select(CausalHistoryLink).where(
                CausalHistoryLink.world_id == world_id,
                CausalHistoryLink.relation_type == SUPERSEDES,
                CausalHistoryLink.target_kind == "EVENT",
                CausalHistoryLink.target_id == correction.target_id,
                CausalHistoryLink.status == "ACTIVE")).first()
            if existing is not None:
                raise IntegrityError("supersede 环被拒绝：目标已被取代",
                                     detail=correction.target_id)
        runtime = s.execute(select(WorldRuntime).where(
            WorldRuntime.world_id == world_id)).scalar_one()
        tick = runtime.current_blessed_tick or 0
        seq = len(s.execute(select(WorldEvent).where(
            WorldEvent.world_id == world_id)).scalars().all())
        uid = deterministic_event_uid(
            world_id=world_id, simulation_version=simulation_version,
            real_start_us=tick, real_end_us=tick, engine_id="HISTORY",
            event_type="HISTORY_CORRECTION", seq=seq)
        EventRepository(s).append(
            world_id=world_id, event_type="HISTORY_CORRECTION",
            source="OWNER_INPUT", blessed_tick=tick, scope="WORLD",
            cause={"relation": correction.relation_type,
                   "target_kind": correction.target_kind,
                   "target_id": correction.target_id},
            effect={"reason": correction.reason,
                    "supersedes_event_id":
                        correction.target_id
                        if correction.relation_type == SUPERSEDES else None},
            event_uid=uid)
        s.flush()
        link_id = builder._add_link(
            s, world_id, relation_type=correction.relation_type,
            source_kind="EVENT", source_id=uid,
            target_kind=correction.target_kind,
            target_id=correction.target_id,
            committed_tick=tick, status="ACTIVE")
        if correction.relation_type == SUPERSEDES:
            # 旧事件的出边（ACTIVE）→ SUPERSEDED（默认查询隐藏）
            for link in s.execute(select(CausalHistoryLink).where(
                    CausalHistoryLink.world_id == world_id,
                    CausalHistoryLink.source_kind == "EVENT",
                    CausalHistoryLink.source_id == correction.target_id,
                    CausalHistoryLink.status == "ACTIVE")).scalars():
                link.status = "SUPERSEDED"
        ctx.commit()
    return {"event_uid": uid, "link_id": link_id,
            "relation": correction.relation_type}

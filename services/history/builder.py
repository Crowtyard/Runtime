# -*- coding: utf-8 -*-
"""M3b HistoryLinkBuilder：在模拟事务内构建因果历史索引。

- 与 Domain Events 同一 WorldMutationContext 原子提交（§29）：事件提交而
  索引缺失的静默间隙不存在；崩溃 → 一起回滚。
- 确定性：迭代顺序冻结（引擎顺序 → 事件 seq → 变更顺序）；link_id 为
  deterministic 128-bit（causal-link-id-v1）；查询全部 ORDER BY 全序。
- 幂等：同 link_id 已存在 → skip（重放/ack-lost 安全）。
- 只写 history 层 5 张新表 + world_state_changes 账本（history 开启时）；
  不改任何模拟表 → world_state_hash / event_stream_hash 不变。
- 0 LLM / 网络 / wall-clock / commit。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...database.models_core import WorldEvent
from ...database.models_world import (CausalHistoryLink,
                                      EntityHistoryIndex,
                                      HistoryEpisodeIndex,
                                      HistoryIndexState,
                                      HistoryStateChange,
                                      ResourceSuccessionCandidate,
                                      TribulationDecision,
                                      TribulationEpisode,
                                      TribulationImpactPlan,
                                      TribulationRecoveryState,
                                      TribulationResidualChange)
from ...domain.errors import IntegrityError
from ..identity import deterministic_hex_id
from ..simulation.contracts import StateChange
from ..simulation.snapshot import WorldSnapshot
from .entities import (BOOKKEEPING_FIELDS, ENTITY_MODELS, SCOPE_KEYS)
from .relations import (CAUSAL_LINK_ID_SCHEMA_VERSION,
                        CYCLE_CHECK_MAX_DEPTH, CYCLE_FORBIDDEN_RELATIONS,
                        HISTORY_SCHEMA_VERSION, RELATION_TYPES,
                        RELATION_TICK_RULES, TICK_BACKWARD, TICK_FORWARD,
                        AFFECTS, CAUSES, CONTINUES, DECIDED_BY,
                        DERIVED_FROM, PART_OF_EPISODE, RECOVERS_FROM,
                        RESULTS_IN)

# 阶段事件类型（CONTINUES 链成员；冻结顺序）
STAGE_EVENT_TYPES = (
    "TRIBULATION_PRECURSOR_STARTED",
    "TRIBULATION_PREPARATION_STARTED",
    "TRIBULATION_IMPACT_STARTED",
    "TRIBULATION_IMPACT_APPLIED",
    "TRIBULATION_STABILIZED",
    "TRIBULATION_RESIDUAL_CHANGE_CREATED",
    "TRIBULATION_NEW_NORMAL_REACHED",
    "TRIBULATION_EPISODE_COMPLETED",
)

# 跨域 CAUSES（state→state，同 Step 前馈）：资源开采 → 生态压力/质量
_CROSS_DOMAIN = [
    (("resource_nodes", ("remaining_reserve", "extraction_carry",
                         "last_extracted_minor")),
     ("ecology_state", ("extraction_pressure", "habitat_quality",
                        "ecological_stress", "depletion_pressure")),
     ("settlement_relation", "region_ref")),
]


def _deep_has(payload: Any, value: str) -> bool:
    if isinstance(payload, dict):
        return any(_deep_has(v, value) for v in payload.values())
    if isinstance(payload, (list, tuple)):
        return any(_deep_has(v, value) for v in payload)
    return str(payload) == str(value)


def _event_episode(event: dict) -> str | None:
    return event.get("cause", {}).get("episode_id") \
        or event.get("effect", {}).get("episode_id")


@dataclass(frozen=True)
class StepHistoryBundle:
    """Coordinator → Builder 的单步历史包（全部已写入当前 fenced session）。"""
    world_id: str
    simulation_run_id: str | None
    blessed_start_tick: int
    blessed_end_tick: int
    step_index: int
    snapshot: WorldSnapshot
    engine_events: tuple[tuple[str, tuple[dict, ...]], ...]
    engine_changes: tuple[tuple[str, tuple[StateChange, ...]], ...]
    adapter_changes: tuple[dict, ...] = ()
    impact_event_uid: str | None = None
    impact_plan: dict | None = None
    episodes_touched: tuple[str, ...] = ()
    plans_created: tuple[dict, ...] = ()
    decisions_created: tuple[dict, ...] = ()
    recovery_created: tuple[dict, ...] = ()
    residual_created: tuple[dict, ...] = ()
    succession_created: tuple[dict, ...] = ()


class HistoryLinkBuilder:
    """历史索引构建器（在协调器 fenced 事务内调用；不 commit）。"""

    def __init__(self) -> None:
        self._tick_cache: dict[tuple[str, str], int | None] = {}
        self._exist_cache: dict[tuple[str, str], bool] = {}
        self._event_type_cache: dict[str, str] = {}

    # ------------------------------------------------------------ public
    def build_step(self, session: Session, bundle: StepHistoryBundle) -> dict:
        metrics = {"links_created": 0, "state_changes_indexed": 0,
                   "entities_indexed": 0, "episodes_synced": 0}
        w = bundle.world_id
        events_by_engine = {eid: evs for eid, evs in bundle.engine_events}
        changes_by_engine = {eid: chs for eid, chs in bundle.engine_changes}
        sc_by_key: dict[tuple[str, str, str], int] = {}

        # ---- 1) 引擎状态变更账本 + provenance + AFFECTS + CONTINUES ----
        for eid in tuple(changes_by_engine):
            evs = events_by_engine.get(eid, ())
            for ch in changes_by_engine[eid]:
                if ch.new_row is not None or ch.entity_id is None:
                    continue
                table = ch.table
                if table not in ENTITY_MODELS or table not in SCOPE_KEYS:
                    continue
                if ch.field in BOOKKEEPING_FIELDS:
                    continue
                row = bundle.snapshot.tables.get(table, {})  # snapshot rows
                row_by_id = {r["id"]: r for r in row}
                entity_row = row_by_id.get(ch.entity_id)
                scope_values = []
                if entity_row is not None:
                    for k in SCOPE_KEYS.get(table, ()):
                        v = entity_row.get(k)
                        if v is not None:
                            scope_values.append(str(v))
                matched = self._match_event(evs, scope_values,
                                            str(ch.entity_id))
                old = ch.old_value
                sc = HistoryStateChange(
                    world_id=w, entity_type=table,
                    entity_id=str(ch.entity_id), field=ch.field,
                    old_value={"v": old}, new_value={"v": ch.new_value},
                    event_ref=matched, blessed_tick=bundle.blessed_end_tick,
                    simulation_run_id=bundle.simulation_run_id,
                    engine_id=eid, trigger_event_id=None, episode_id=None,
                    owner_decision_id=None,
                    semantic_version=HISTORY_SCHEMA_VERSION)
                session.add(sc)
                session.flush()
                sc_by_key[(table, str(ch.entity_id), ch.field)] = sc.id
                metrics["state_changes_indexed"] += 1
                self._tick_cache[("STATE_CHANGE", str(sc.id))] = \
                    bundle.blessed_end_tick
                if matched:
                    self._add_link(
                        session, w, relation_type=AFFECTS,
                        source_kind="EVENT", source_id=matched,
                        target_kind="STATE_CHANGE", target_id=str(sc.id),
                        committed_tick=bundle.blessed_end_tick,
                        entity_scope={"type": table,
                                      "id": str(ch.entity_id)})
                    metrics["links_created"] += 1
                prev = self._latest_change_before(
                    session, w, table, str(ch.entity_id), ch.field, sc.id,
                    bundle.blessed_end_tick)
                if prev is not None:
                    self._add_link(
                        session, w, relation_type=CONTINUES,
                        source_kind="STATE_CHANGE", source_id=str(prev),
                        target_kind="STATE_CHANGE", target_id=str(sc.id),
                        committed_tick=bundle.blessed_end_tick,
                        entity_scope={"type": table,
                                      "id": str(ch.entity_id)})
                    metrics["links_created"] += 1

        # ---- 2) 跨域 CAUSES（同 Step 前馈）----
        self._cross_domain_links(session, bundle, metrics, sc_by_key)

        # ---- 3) 灾劫 Adapter 变更 → M3b 账本 + provenance + AFFECTS ----
        plan = bundle.impact_plan
        ep_ctx = (plan or {}).get("episode_id")
        decision_id = self._active_decision(session, w, ep_ctx) \
            if ep_ctx else None
        for ad in bundle.adapter_changes:
            sc = HistoryStateChange(
                world_id=w, entity_type=ad["entity_type"],
                entity_id=str(ad["entity_id"]), field=ad["field"],
                old_value={"v": ad["old"]}, new_value={"v": ad["new"]},
                event_ref=bundle.impact_event_uid,
                blessed_tick=bundle.blessed_end_tick,
                simulation_run_id=bundle.simulation_run_id,
                engine_id=ad["domain"],
                trigger_event_id=bundle.impact_event_uid,
                episode_id=ep_ctx, owner_decision_id=decision_id,
                semantic_version=HISTORY_SCHEMA_VERSION)
            session.add(sc)
            session.flush()
            metrics["state_changes_indexed"] += 1
            if bundle.impact_event_uid:
                self._add_link(
                    session, w, relation_type=AFFECTS,
                    source_kind="EVENT", source_id=bundle.impact_event_uid,
                    target_kind="STATE_CHANGE",
                    target_id=str(sc.id),
                    committed_tick=bundle.blessed_end_tick,
                    episode_id=ep_ctx,
                    entity_scope={"type": ad["entity_type"],
                                  "id": str(ad["entity_id"])})
                metrics["links_created"] += 1
            prev = self._latest_change_before(
                session, w, ad["entity_type"], str(ad["entity_id"]),
                ad["field"], sc.id, bundle.blessed_end_tick)
            if prev is not None:
                self._add_link(
                    session, w, relation_type=CONTINUES,
                    source_kind="STATE_CHANGE", source_id=str(prev),
                    target_kind="STATE_CHANGE", target_id=str(sc.id),
                    committed_tick=bundle.blessed_end_tick,
                    entity_scope={"type": ad["entity_type"],
                                  "id": str(ad["entity_id"])})
                metrics["links_created"] += 1

        # ---- 4) 灾劫图（事件链/决策/计划/恢复/残留/继承）----
        self._tribulation_links(session, bundle, events_by_engine, metrics)

        # ---- 5) Episode 索引同步 ----
        for ep_id in bundle.episodes_touched:
            self._sync_episode_index(session, w, ep_id,
                                     bundle.blessed_end_tick)
            metrics["episodes_synced"] += 1

        # ---- 6) 水印 ----
        state = session.execute(select(HistoryIndexState).where(
            HistoryIndexState.world_id == w)).scalar_one_or_none()
        if state is None:
            state = HistoryIndexState(world_id=w, indexed_through_tick=0,
                                      links_total=0,
                                      semantic_version=HISTORY_SCHEMA_VERSION)
            session.add(state)
        state.indexed_through_tick = max(
            state.indexed_through_tick or 0, bundle.blessed_end_tick)
        state.links_total = (state.links_total or 0) + \
            metrics["links_created"]
        state.semantic_version = HISTORY_SCHEMA_VERSION
        session.flush()
        return metrics

    # ------------------------------------------------------------ links
    def add_link(self, session: Session, *, world_id: str, relation_type: str,
                 source_kind: str, source_id: str, target_kind: str,
                 target_id: str, committed_tick: int, episode_id: str | None
                 = None, entity_scope: dict | None = None,
                 owner_decision_id: str | None = None,
                 status: str = "ACTIVE") -> dict:
        """公开插入 API（Correction / 测试用；全部校验 + 幂等）。"""
        link_id = self._add_link(
            session, world_id, relation_type=relation_type,
            source_kind=source_kind, source_id=source_id,
            target_kind=target_kind, target_id=target_id,
            committed_tick=committed_tick, episode_id=episode_id,
            entity_scope=entity_scope, owner_decision_id=owner_decision_id,
            status=status)
        return {"link_id": link_id, "created": link_id is not None}

    def _add_link(self, session: Session, world_id: str, *,
                  relation_type: str, source_kind: str, source_id: str,
                  target_kind: str, target_id: str, committed_tick: int,
                  episode_id: str | None = None,
                  entity_scope: dict | None = None,
                  owner_decision_id: str | None = None,
                  status: str = "ACTIVE") -> str | None:
        if relation_type not in RELATION_TYPES:
            raise IntegrityError("非法历史关系类型",
                                 detail={"relation": relation_type})
        if not self._node_exists(session, world_id, source_kind, source_id):
            raise IntegrityError("历史链接源节点不存在（禁止 orphan）",
                                 detail={"kind": source_kind,
                                         "id": source_id})
        if not self._node_exists(session, world_id, target_kind, target_id):
            raise IntegrityError("历史链接目标节点不存在（禁止 orphan）",
                                 detail={"kind": target_kind,
                                         "id": target_id})
        src_tick = self._node_tick(session, world_id, source_kind, source_id)
        dst_tick = self._node_tick(session, world_id, target_kind, target_id)
        rule = RELATION_TICK_RULES[relation_type]
        if rule == TICK_FORWARD and src_tick is not None \
                and dst_tick is not None and src_tick > dst_tick:
            raise IntegrityError("tick paradox：前向因果源晚于目标",
                                 detail={"relation": relation_type,
                                         "src_tick": src_tick,
                                         "dst_tick": dst_tick})
        if rule == TICK_BACKWARD and src_tick is not None \
                and dst_tick is not None and src_tick < dst_tick:
            raise IntegrityError("tick paradox：后向关系源早于目标",
                                 detail={"relation": relation_type,
                                         "src_tick": src_tick,
                                         "dst_tick": dst_tick})
        if relation_type in CYCLE_FORBIDDEN_RELATIONS \
                and self._would_cycle(session, world_id, relation_type,
                                      source_kind, source_id, target_kind,
                                      target_id):
            raise IntegrityError("因果环被拒绝",
                                 detail={"relation": relation_type,
                                         "source": (source_kind, source_id),
                                         "target": (target_kind, target_id)})
        link_id = deterministic_hex_id(
            [world_id, relation_type, source_kind, source_id, target_kind,
             target_id, episode_id or "", HISTORY_SCHEMA_VERSION],
            bits=128, schema=CAUSAL_LINK_ID_SCHEMA_VERSION)
        existing = session.execute(select(CausalHistoryLink).where(
            CausalHistoryLink.world_id == world_id,
            CausalHistoryLink.link_id == link_id)).scalar_one_or_none()
        if existing is not None:
            return None  # 幂等：重放不重复创建
        session.add(CausalHistoryLink(
            world_id=world_id, link_id=link_id, relation_type=relation_type,
            source_kind=source_kind, source_id=source_id,
            target_kind=target_kind, target_id=target_id,
            source_tick=src_tick, target_tick=dst_tick,
            episode_id=episode_id, entity_scope=entity_scope,
            owner_decision_id=owner_decision_id,
            committed_tick=committed_tick, status=status,
            semantic_version=HISTORY_SCHEMA_VERSION))
        if entity_scope is not None:
            self._index_entity(session, world_id, entity_scope["type"],
                               str(entity_scope["id"]), link_id,
                               committed_tick)
        return link_id

    def _index_entity(self, session: Session, world_id: str, entity_type: str,
                      entity_id: str, link_id: str,
                      committed_tick: int) -> None:
        exists = session.execute(select(EntityHistoryIndex).where(
            EntityHistoryIndex.world_id == world_id,
            EntityHistoryIndex.entity_type == entity_type,
            EntityHistoryIndex.entity_id == entity_id,
            EntityHistoryIndex.link_id == link_id)).scalar_one_or_none()
        if exists is None:
            session.add(EntityHistoryIndex(
                world_id=world_id, entity_type=entity_type,
                entity_id=entity_id, link_id=link_id,
                committed_tick=committed_tick,
                semantic_version=HISTORY_SCHEMA_VERSION))

    # ------------------------------------------------------------ 校验
    def _would_cycle(self, session: Session, world_id: str, relation_type: str,
                     s_kind: str, s_id: str, t_kind: str, t_id: str) -> bool:
        """插入时环防御（O(1) 自环 + 反向二环 + EVENT 链深度受限 DFS）。

        完整图环保证由 HISTORY_INTEGRITY_AUDIT 提供（拓扑 DFS）；
        此处只拦截构造层面可能出现的最小环，避免 300y 构建 O(N²)。
        """
        if (s_kind, s_id) == (t_kind, t_id):
            return True  # 自环
        # 反向二环：target → source 已存在禁环关系
        rev = session.execute(select(CausalHistoryLink).where(
            CausalHistoryLink.world_id == world_id,
            CausalHistoryLink.source_kind == t_kind,
            CausalHistoryLink.source_id == t_id,
            CausalHistoryLink.target_kind == s_kind,
            CausalHistoryLink.target_id == s_id,
            CausalHistoryLink.relation_type.in_(CYCLE_FORBIDDEN_RELATIONS),
            CausalHistoryLink.status == "ACTIVE")).first()
        if rev is not None:
            return True
        # EVENT 链（CONTINUES event→event）深度受限 DFS
        if relation_type == CONTINUES and s_kind == "EVENT" \
                and t_kind == "EVENT":
            stack = [(t_kind, t_id)]
            seen = {(t_kind, t_id)}
            for _ in range(CYCLE_CHECK_MAX_DEPTH):
                if not stack:
                    return False
                nxt: list[tuple[str, str]] = []
                for k, i in stack:
                    rows = session.execute(select(CausalHistoryLink).where(
                        CausalHistoryLink.world_id == world_id,
                        CausalHistoryLink.source_kind == k,
                        CausalHistoryLink.source_id == i,
                        CausalHistoryLink.relation_type == CONTINUES,
                        CausalHistoryLink.status == "ACTIVE")).scalars()
                    for row in rows:
                        node = (row.target_kind, row.target_id)
                        if node == (s_kind, s_id):
                            return True
                        if node not in seen:
                            seen.add(node)
                            nxt.append(node)
                stack = nxt
            raise IntegrityError("禁环检测深度超限",
                                 detail={"source": (s_kind, s_id)})
        return False

    # ------------------------------------------------------------ 节点解析
    def _node_tick(self, session: Session, world_id: str, kind: str,
                   node_id: str) -> int | None:
        key = (kind, node_id)
        if key in self._tick_cache:
            return self._tick_cache[key]
        tick: int | None = None
        if kind == "EVENT":
            ev = session.execute(select(WorldEvent).where(
                WorldEvent.event_uid == node_id)).scalar_one_or_none()
            tick = ev.blessed_tick if ev is not None else None
        elif kind == "STATE_CHANGE":
            sc = session.get(HistoryStateChange, int(node_id))
            tick = sc.blessed_tick if sc is not None else None
        elif kind == "EPISODE":
            ep = session.execute(select(TribulationEpisode).where(
                TribulationEpisode.world_id == world_id,
                TribulationEpisode.episode_id == node_id)
            ).scalar_one_or_none()
            tick = ep.entered_tick if ep is not None else None
        elif kind == "RECOVERY_STATE":
            rec = session.execute(select(TribulationRecoveryState).where(
                TribulationRecoveryState.world_id == world_id,
                TribulationRecoveryState.episode_id == node_id)
            ).scalar_one_or_none()
            tick = rec.started_tick if rec is not None else None
        self._tick_cache[key] = tick
        return tick

    def _node_exists(self, session: Session, world_id: str, kind: str,
                     node_id: str) -> bool:
        key = (kind, node_id)
        if key in self._exist_cache:
            return self._exist_cache[key]
        found = False
        if kind == "EVENT":
            found = session.execute(select(WorldEvent.event_uid).where(
                WorldEvent.event_uid == node_id)).scalar_one_or_none() \
                is not None
        elif kind == "STATE_CHANGE":
            found = session.get(HistoryStateChange, int(node_id)) is not None
        elif kind == "EPISODE":
            found = session.execute(select(TribulationEpisode.episode_id)
                                    .where(
                TribulationEpisode.world_id == world_id,
                TribulationEpisode.episode_id == node_id)
            ).scalar_one_or_none() is not None
        elif kind == "PLAN":
            found = session.execute(select(TribulationImpactPlan.plan_id)
                                    .where(
                TribulationImpactPlan.world_id == world_id,
                TribulationImpactPlan.plan_id == node_id)
            ).scalar_one_or_none() is not None
        elif kind == "DECISION":
            found = session.execute(select(TribulationDecision.decision_id)
                                    .where(
                TribulationDecision.world_id == world_id,
                TribulationDecision.decision_id == node_id)
            ).scalar_one_or_none() is not None
        elif kind == "RECOVERY_STATE":
            found = session.execute(select(
                TribulationRecoveryState.episode_id).where(
                TribulationRecoveryState.world_id == world_id,
                TribulationRecoveryState.episode_id == node_id)
            ).scalar_one_or_none() is not None
        elif kind == "RESIDUAL":
            found = session.get(TribulationResidualChange, int(node_id)) \
                is not None
        elif kind == "SUCCESSION":
            found = session.execute(select(
                ResourceSuccessionCandidate.candidate_id).where(
                ResourceSuccessionCandidate.world_id == world_id,
                ResourceSuccessionCandidate.candidate_id == node_id)
            ).scalar_one_or_none() is not None
        elif kind == "ENTITY":
            etype, _, eid = node_id.partition(":")
            model = ENTITY_MODELS.get(etype)
            found = model is not None and session.execute(select(model.id)
                                                          .where(
                model.id == int(eid))).scalar_one_or_none() is not None
        elif kind == "CHECKPOINT":
            from ...database.models_core import SimulationCheckpoint
            found = session.get(SimulationCheckpoint, int(node_id)) \
                is not None
        self._exist_cache[key] = found
        return found

    # ------------------------------------------------------------ 匹配
    @staticmethod
    def _match_event(evs: tuple[dict, ...], scope_values: list[str],
                     entity_id: str) -> str | None:
        if not evs:
            return None
        hits = []
        for ev in evs:
            payload = {"cause": ev.get("cause", {}),
                       "effect": ev.get("effect", {})}
            if any(_deep_has(payload, v) for v in scope_values) \
                    or _deep_has(payload, entity_id):
                hits.append(ev)
        if hits:
            return hits[-1]["event_uid"]  # seq 最后（最具体）命中
        return None  # 无命中 → domain_event_id=NULL（不得伪造归属）

    def _latest_change_before(self, session: Session, world_id: str,
                              entity_type: str, entity_id: str, field: str,
                              exclude_id: int, tick: int) -> str | None:
        row = session.execute(select(HistoryStateChange).where(
            HistoryStateChange.world_id == world_id,
            HistoryStateChange.entity_type == entity_type,
            HistoryStateChange.entity_id == entity_id,
            HistoryStateChange.field == field,
            HistoryStateChange.id != exclude_id,
            HistoryStateChange.blessed_tick <= tick).order_by(
                HistoryStateChange.blessed_tick.desc(),
                HistoryStateChange.id.desc()).limit(1)).scalars().first()
        return str(row.id) if row is not None else None

    # ------------------------------------------------------------ 跨域
    def _cross_domain_links(self, session: Session, bundle: StepHistoryBundle,
                            metrics: dict,
                            sc_by_key: dict[tuple[str, str, str], int]
                            ) -> None:
        w = bundle.world_id
        changes_by_engine = {eid: chs for eid, chs in bundle.engine_changes}
        snap = {t: {r["id"]: r for r in bundle.snapshot.tables.get(t, ())}
                for t in bundle.snapshot.tables}
        for (src_table, src_fields), (dst_table, dst_fields), scope_keys in \
                _CROSS_DOMAIN:
            src_changes = [c for eid in changes_by_engine
                           for c in changes_by_engine[eid]
                           if c.new_row is None and c.entity_id is not None
                           and c.table == src_table and c.field in src_fields]
            dst_changes = [c for eid in changes_by_engine
                           for c in changes_by_engine[eid]
                           if c.new_row is None and c.entity_id is not None
                           and c.table == dst_table and c.field in dst_fields]
            if not src_changes or not dst_changes:
                continue
            for dc in dst_changes:
                drow = snap.get(dst_table, {}).get(dc.entity_id, {})
                zone_ref = drow.get("zone_ref")
                zone = None
                if zone_ref is not None:
                    for z in bundle.snapshot.tables.get("ecology_zones", ()):
                        if z.get("zone_id") == zone_ref:
                            zone = z
                            break
                dscope = []
                if zone is not None:
                    for k in scope_keys:
                        if zone.get(k) is not None:
                            dscope.append(str(zone[k]))
                if not dscope:
                    continue
                for sc2 in src_changes:
                    srow = snap.get(src_table, {}).get(sc2.entity_id, {})
                    if any(srow.get(k) is not None
                           and str(srow[k]) in dscope for k in scope_keys):
                        src_sc_id = sc_by_key.get(
                            (src_table, str(sc2.entity_id), sc2.field))
                        dst_sc_id = sc_by_key.get(
                            (dst_table, str(dc.entity_id), dc.field))
                        if src_sc_id is None or dst_sc_id is None:
                            continue
                        self._add_link(
                            session, w, relation_type=CAUSES,
                            source_kind="STATE_CHANGE",
                            source_id=str(src_sc_id),
                            target_kind="STATE_CHANGE",
                            target_id=str(dst_sc_id),
                            committed_tick=bundle.blessed_end_tick,
                            entity_scope={"type": dst_table,
                                          "id": str(dc.entity_id)})
                        metrics["links_created"] += 1

    # ------------------------------------------------------------ 灾劫图
    def _tribulation_links(self, session: Session, bundle: StepHistoryBundle,
                           events_by_engine: dict, metrics: dict) -> None:
        w = bundle.world_id
        evs = events_by_engine.get("TRIBULATION", ())
        if not evs and not bundle.impact_plan:
            return
        plan = bundle.impact_plan
        ep_created = {}
        changes_by_engine = {eid: chs for eid, chs in bundle.engine_changes}
        for ch in changes_by_engine.get("TRIBULATION", ()):
            if ch.new_row is not None and ch.table == "tribulation_episodes":
                nr = ch.new_row
                ep_created[nr["episode_id"]] = nr
        # SCHEDULED → EPISODE；PART_OF_EPISODE（全部带 episode_id 的事件）
        for ev in evs:
            ep_id = _event_episode(ev)
            if ev["event_type"] == "TRIBULATION_SCHEDULED":
                nr = ep_created.get(ep_id)
                if nr is not None:
                    self._add_link(session, w, relation_type=RESULTS_IN,
                                   source_kind="EVENT",
                                   source_id=ev["event_uid"],
                                   target_kind="EPISODE", target_id=ep_id,
                                   committed_tick=bundle.blessed_end_tick,
                                   episode_id=ep_id)
                    metrics["links_created"] += 1
            if ep_id is not None:
                self._add_link(session, w, relation_type=PART_OF_EPISODE,
                               source_kind="EVENT", source_id=ev["event_uid"],
                               target_kind="EPISODE", target_id=ep_id,
                               committed_tick=bundle.blessed_end_tick,
                               episode_id=ep_id)
                metrics["links_created"] += 1
            if ep_id is not None and ev["event_type"] in STAGE_EVENT_TYPES:
                prev = self._episode_event_before(
                    session, w, ep_id, ev["event_uid"], STAGE_EVENT_TYPES,
                    bundle.blessed_end_tick)
                if prev is not None:
                    self._add_link(session, w, relation_type=CONTINUES,
                                   source_kind="EVENT", source_id=prev,
                                   target_kind="EVENT",
                                   target_id=ev["event_uid"],
                                   committed_tick=bundle.blessed_end_tick,
                                   episode_id=ep_id)
                    metrics["links_created"] += 1
        # Plan → 决策 / Impact 事件（source=解释，target=被解释）
        if plan is not None:
            ep_id = plan["episode_id"]
            decision_id = self._active_decision(session, w, ep_id)
            if decision_id is not None:
                self._add_link(session, w, relation_type=DECIDED_BY,
                               source_kind="DECISION",
                               source_id=decision_id,
                               target_kind="PLAN", target_id=plan["plan_id"],
                               committed_tick=bundle.blessed_end_tick,
                               episode_id=ep_id)
                metrics["links_created"] += 1
            else:
                aut = self._episode_event(session, w, ep_id,
                                          "AUTONOMOUS_RESPONSE_SELECTED")
                if aut is not None:
                    self._add_link(session, w, relation_type=DECIDED_BY,
                                   source_kind="EVENT", source_id=aut,
                                   target_kind="PLAN",
                                   target_id=plan["plan_id"],
                                   committed_tick=bundle.blessed_end_tick,
                                   episode_id=ep_id)
                    metrics["links_created"] += 1
            for etype in ("TRIBULATION_IMPACT_STARTED",
                          "TRIBULATION_IMPACT_APPLIED"):
                for ev in evs:
                    if ev["event_type"] == etype \
                            and _event_episode(ev) == ep_id:
                        self._add_link(session, w, relation_type=RESULTS_IN,
                                       source_kind="PLAN",
                                       source_id=plan["plan_id"],
                                       target_kind="EVENT",
                                       target_id=ev["event_uid"],
                                       committed_tick=bundle.blessed_end_tick,
                                       episode_id=ep_id)
                        metrics["links_created"] += 1
        # 恢复 / 残留 / 继承（source=冲击/源头 → target=被解释）
        impact_uid = bundle.impact_event_uid
        for rec in bundle.recovery_created:
            ep_id = rec["episode_id"]
            imp = impact_uid if plan and plan["episode_id"] == ep_id \
                else self._episode_event(session, w, ep_id,
                                         "TRIBULATION_IMPACT_APPLIED")
            if imp is not None:
                self._add_link(session, w, relation_type=RECOVERS_FROM,
                               source_kind="EVENT", source_id=imp,
                               target_kind="RECOVERY_STATE",
                               target_id=ep_id,
                               committed_tick=bundle.blessed_end_tick,
                               episode_id=ep_id)
                metrics["links_created"] += 1
        for res in bundle.residual_created:
            ep_id = res["episode_id"]
            imp = impact_uid if plan and plan["episode_id"] == ep_id \
                else self._episode_event(session, w, ep_id,
                                         "TRIBULATION_IMPACT_APPLIED")
            if imp is not None:
                self._add_link(session, w, relation_type=DERIVED_FROM,
                               source_kind="EVENT", source_id=imp,
                               target_kind="RESIDUAL",
                               target_id=str(res["id"]),
                               committed_tick=bundle.blessed_end_tick,
                               episode_id=ep_id)
                metrics["links_created"] += 1
        for suc in bundle.succession_created:
            ep_id = suc["episode_id"]
            residual_id = self._episode_residual(session, w, ep_id)
            if residual_id is not None:
                self._add_link(session, w, relation_type=DERIVED_FROM,
                               source_kind="RESIDUAL",
                               source_id=str(residual_id),
                               target_kind="SUCCESSION",
                               target_id=suc["candidate_id"],
                               committed_tick=bundle.blessed_end_tick,
                               episode_id=ep_id)
                metrics["links_created"] += 1

    def _episode_event(self, session: Session, world_id: str, episode_id: str,
                       event_type: str) -> str | None:
        rows = session.execute(select(WorldEvent).join(
            CausalHistoryLink,
            (CausalHistoryLink.source_kind == "EVENT")
            & (CausalHistoryLink.source_id == WorldEvent.event_uid)
            & (CausalHistoryLink.target_kind == "EPISODE")
            & (CausalHistoryLink.target_id == episode_id)
            & (CausalHistoryLink.relation_type == PART_OF_EPISODE)
            & (CausalHistoryLink.world_id == world_id)).where(
                WorldEvent.event_type == event_type).order_by(
                    WorldEvent.blessed_tick.desc(),
                    WorldEvent.id.desc()).limit(1)).scalars().first()
        return rows.event_uid if rows is not None else None

    def _episode_event_before(self, session: Session, world_id: str,
                              episode_id: str, exclude_uid: str,
                              event_types: tuple[str, ...],
                              tick: int) -> str | None:
        rows = session.execute(select(WorldEvent).join(
            CausalHistoryLink,
            (CausalHistoryLink.source_kind == "EVENT")
            & (CausalHistoryLink.source_id == WorldEvent.event_uid)
            & (CausalHistoryLink.target_kind == "EPISODE")
            & (CausalHistoryLink.target_id == episode_id)
            & (CausalHistoryLink.relation_type == PART_OF_EPISODE)
            & (CausalHistoryLink.world_id == world_id)).where(
                WorldEvent.event_type.in_(event_types),
                WorldEvent.event_uid != exclude_uid,
                WorldEvent.blessed_tick <= tick).order_by(
                    WorldEvent.blessed_tick.desc(),
                    WorldEvent.id.desc()).limit(1)).scalars().first()
        return rows.event_uid if rows is not None else None

    def _active_decision(self, session: Session, world_id: str,
                         episode_id: str) -> str | None:
        row = session.execute(select(TribulationDecision).where(
            TribulationDecision.world_id == world_id,
            TribulationDecision.episode_id == episode_id,
            TribulationDecision.status == "ACTIVE").order_by(
                TribulationDecision.submitted_tick.desc(),
                TribulationDecision.decision_id).limit(1)).scalars().first()
        return row.decision_id if row is not None else None

    def _episode_residual(self, session: Session, world_id: str,
                          episode_id: str) -> int | None:
        row = session.execute(select(TribulationResidualChange).where(
            TribulationResidualChange.world_id == world_id,
            TribulationResidualChange.episode_id == episode_id).order_by(
                TribulationResidualChange.id).limit(1)).scalars().first()
        return row.id if row is not None else None

    def _sync_episode_index(self, session: Session, world_id: str,
                            episode_id: str, tick: int) -> None:
        ep = session.execute(select(TribulationEpisode).where(
            TribulationEpisode.world_id == world_id,
            TribulationEpisode.episode_id == episode_id)
        ).scalar_one_or_none()
        if ep is None:
            return
        row = session.execute(select(HistoryEpisodeIndex).where(
            HistoryEpisodeIndex.world_id == world_id,
            HistoryEpisodeIndex.episode_id == episode_id)
        ).scalar_one_or_none()
        if row is None:
            row = HistoryEpisodeIndex(
                world_id=world_id, episode_id=episode_id, kind="TRIBULATION",
                semantic_version=HISTORY_SCHEMA_VERSION)
            session.add(row)
        row.status = "COMPLETED" if ep.status == "COMPLETED" else "ACTIVE"
        row.stage = ep.current_stage
        row.entered_tick = ep.entered_tick
        row.transition_tick = ep.transition_tick
        row.profile_ref = ep.profile_ref
        row.tier = ep.window_tier
        if ep.status == "COMPLETED":
            row.completed_tick = tick
        row.semantic_version = HISTORY_SCHEMA_VERSION

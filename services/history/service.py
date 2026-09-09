# -*- coding: utf-8 -*-
"""M3b HistoryService：只读历史查询 + 完整性审计 + causal_history_hash。

- 0 mutation：所有方法不 commit、不 flush、不写任何表（HB25 用 DB checksum
  实测）。
- Deterministic：全部 ORDER BY 冻结规则（tick → relation priority →
  source/target id → link_id / event_uid），禁止 DB physical row order /
  Python set order / wall-clock。
- 0 LLM / 网络 / wall-clock（性能测量除外——不进确定性输出）。
"""
from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ...database.models_core import WorldEvent
from ...database.models_world import (CausalHistoryLink,
                                      EntityHistoryIndex,
                                      HistoryEpisodeIndex,
                                      HistoryIndexState,
                                      HistoryStateChange,
                                      ResourceSuccessionCandidate,
                                      TribulationCausalLink,
                                      TribulationDecision,
                                      TribulationEpisode,
                                      TribulationImpactPlan,
                                      TribulationProfile,
                                      TribulationRecoveryState,
                                      TribulationResidualChange,
                                      TribulationSchedule)
from .entities import ENTITY_MODELS
from .relations import (CAUSAL_HISTORY_HASH_SCHEMA_VERSION,
                        CYCLE_FORBIDDEN_RELATIONS, RELATION_PRIORITY,
                        RELATION_TYPES, RELATION_TICK_RULES, TICK_BACKWARD,
                        TICK_FORWARD, PART_OF_EPISODE, TRACE_RELATIONS)

# 阶段事件顺序（Episode history 展示用；冻结）
_STAGE_TYPES = ("TRIBULATION_PRECURSOR_STARTED",
                "TRIBULATION_PREPARATION_STARTED",
                "TRIBULATION_IMPACT_STARTED",
                "TRIBULATION_IMPACT_APPLIED",
                "TRIBULATION_STABILIZED",
                "TRIBULATION_RESIDUAL_CHANGE_CREATED",
                "TRIBULATION_RECOVERY_PROGRESS",
                "RESOURCE_SUCCESSION_CANDIDATE_CREATED",
                "TRIBULATION_NEW_NORMAL_REACHED",
                "TRIBULATION_EPISODE_COMPLETED")


class HistoryService:
    """只读 History Query Service（同一 session_factory，绝不 commit）。"""

    def __init__(self, session_factory: sessionmaker[Session]):
        self._factory = session_factory

    # ------------------------------------------------------------ Timeline
    def get_timeline(self, *, world_id: str, start_tick: int | None = None,
                     end_tick: int | None = None,
                     event_types: tuple[str, ...] | None = None,
                     max_items: int = 500) -> list[dict]:
        """按时间看发生了什么（Timeline ≠ History Graph）。"""
        with self._factory() as s:
            q = select(WorldEvent).where(WorldEvent.world_id == world_id)
            if start_tick is not None:
                q = q.where(WorldEvent.blessed_tick >= start_tick)
            if end_tick is not None:
                q = q.where(WorldEvent.blessed_tick <= end_tick)
            if event_types:
                q = q.where(WorldEvent.event_type.in_(event_types))
            q = q.order_by(WorldEvent.blessed_tick, WorldEvent.id) \
                .limit(max_items)
            return [{"event_uid": e.event_uid, "event_type": e.event_type,
                     "blessed_tick": e.blessed_tick, "cause": dict(e.cause),
                     "effect": dict(e.effect), "source": e.source}
                    for e in s.execute(q).scalars()]

    # ------------------------------------------------------------ Entity
    def get_entity_history(self, *, world_id: str, entity_type: str,
                           entity_id: str, start_tick: int | None = None,
                           end_tick: int | None = None,
                           max_items: int = 200) -> dict:
        """实体的直接历史：直接影响它的 state change + 相关事件。"""
        eid = str(entity_id)
        with self._factory() as s:
            q = select(HistoryStateChange).where(
                HistoryStateChange.world_id == world_id,
                HistoryStateChange.entity_type == entity_type,
                HistoryStateChange.entity_id == eid)
            if start_tick is not None:
                q = q.where(HistoryStateChange.blessed_tick >= start_tick)
            if end_tick is not None:
                q = q.where(HistoryStateChange.blessed_tick <= end_tick)
            q = q.order_by(HistoryStateChange.blessed_tick,
                           HistoryStateChange.id).limit(max_items)
            changes = []
            for c in s.execute(q).scalars():
                changes.append({
                    "state_change_id": c.id, "field": c.field,
                    "old_value": c.old_value, "new_value": c.new_value,
                    "event_ref": c.event_ref, "blessed_tick": c.blessed_tick,
                    "engine_id": c.engine_id,
                    "simulation_run_id": c.simulation_run_id,
                    "episode_id": c.episode_id,
                    "owner_decision_id": c.owner_decision_id})
            # 关联事件（entity_history_index → links → EVENT/EPISODE 节点）
            link_ids = [r.link_id for r in s.execute(select(
                EntityHistoryIndex).where(
                    EntityHistoryIndex.world_id == world_id,
                    EntityHistoryIndex.entity_type == entity_type,
                    EntityHistoryIndex.entity_id == eid).order_by(
                        EntityHistoryIndex.committed_tick)).scalars()]
            event_uids: list[str] = []
            for lid in link_ids:
                link = s.execute(select(CausalHistoryLink).where(
                    CausalHistoryLink.world_id == world_id,
                    CausalHistoryLink.link_id == lid)).scalar_one_or_none()
                if link is None:
                    continue
                if link.source_kind == "EVENT" \
                        and link.source_id not in event_uids:
                    event_uids.append(link.source_id)
                if link.target_kind == "EVENT" \
                        and link.target_id not in event_uids:
                    event_uids.append(link.target_id)
            events = []
            for uid in event_uids:
                ev = s.execute(select(WorldEvent).where(
                    WorldEvent.event_uid == uid)).scalar_one_or_none()
                if ev is not None:
                    events.append({"event_uid": ev.event_uid,
                                   "event_type": ev.event_type,
                                   "blessed_tick": ev.blessed_tick,
                                   "cause": dict(ev.cause),
                                   "effect": dict(ev.effect)})
            events.sort(key=lambda e: (e["blessed_tick"] or 0,
                                       e["event_uid"]))
            return {"entity_type": entity_type, "entity_id": eid,
                    "state_changes": changes, "events": events}

    def get_scope_history(self, *, world_id: str, table: str, scope_field: str,
                          scope_value: str, max_items: int = 300) -> dict:
        """按 scope 键聚合实体历史（region/settlement/zone 等）。"""
        model = ENTITY_MODELS.get(table)
        if model is None or not hasattr(model, scope_field):
            return {"scope": {scope_field: scope_value},
                    "entities": [], "events": []}
        with self._factory() as s:
            rows = s.execute(select(model.id).where(
                model.world_id == world_id,
                getattr(model, scope_field) == scope_value)).scalars().all()
        out = {"scope": {scope_field: scope_value}, "entities": [],
               "events": [], "state_changes": 0}
        seen_uids: dict[str, int] = {}
        for rid in rows[:50]:
            hist = self.get_entity_history(
                world_id=world_id, entity_type=table, entity_id=str(rid),
                max_items=max_items)
            if hist["state_changes"] or hist["events"]:
                out["entities"].append({
                    "entity_id": str(rid),
                    "state_change_count": len(hist["state_changes"]),
                    "event_count": len(hist["events"])})
                out["state_changes"] += len(hist["state_changes"])
                for ev in hist["events"]:
                    seen_uids[ev["event_uid"]] = ev["blessed_tick"] or 0
        out["events"] = [{"event_uid": u, "blessed_tick": t}
                         for u, t in sorted(seen_uids.items(),
                                            key=lambda kv: (kv[1], kv[0]))
                         ][:max_items]
        return out

    def get_region_history(self, *, world_id: str, region_id: str,
                           max_items: int = 300) -> dict:
        res = self.get_scope_history(world_id=world_id,
                                     table="resource_nodes",
                                     scope_field="region_ref",
                                     scope_value=region_id,
                                     max_items=max_items)
        return {"region_id": region_id, **res}

    def get_settlement_history(self, *, world_id: str, settlement_id: str,
                               max_items: int = 300) -> dict:
        out = {"settlement_id": settlement_id, "domains": {}}
        for table, field in (("population_groups", "settlement_ref"),
                             ("resource_stocks", "settlement_ref"),
                             ("households", "settlement_ref"),
                             ("settlement_social_state", "settlement_ref"),
                             ("institutions", "settlement_ref")):
            out["domains"][table] = self.get_scope_history(
                world_id=world_id, table=table, scope_field=field,
                scope_value=settlement_id, max_items=max_items)
        return out

    def get_resource_history(self, *, world_id: str, resource_node_id: str,
                             max_items: int = 200) -> dict:
        return self.get_entity_history(
            world_id=world_id, entity_type="resource_nodes",
            entity_id=str(resource_node_id), max_items=max_items)

    def get_lineage_history(self, *, world_id: str, lineage_id: str,
                            max_items: int = 200) -> dict:
        with self._factory() as s:
            from ...database.models_world import Lineage
            row = s.execute(select(Lineage).where(
                Lineage.world_id == world_id,
                Lineage.lineage_id == lineage_id)).scalar_one_or_none()
            if row is None:
                return {"lineage_id": lineage_id, "entities": [], "events": []}
            return self.get_entity_history(
                world_id=world_id, entity_type="lineages",
                entity_id=str(row.id), max_items=max_items)

    def get_institution_history(self, *, world_id: str, institution_id: str,
                                max_items: int = 200) -> dict:
        with self._factory() as s:
            from ...database.models_world import Institution
            row = s.execute(select(Institution).where(
                Institution.world_id == world_id,
                Institution.institution_id == institution_id)
            ).scalar_one_or_none()
            if row is None:
                return {"institution_id": institution_id, "entities": [],
                        "events": []}
            return self.get_entity_history(
                world_id=world_id, entity_type="institutions",
                entity_id=str(row.id), max_items=max_items)

    # ------------------------------------------------------------ Episode
    def get_tribulation_history(self, *, world_id: str,
                                episode_id: str) -> dict:
        """完整 Episode 历史（schedule/profile/targets/阶段/决策/影响/恢复…）。

        状态派生：COMPLETED / ACTIVE（stage）/ IN_RECOVERY（stage=RECOVERY）
        / INCOMPLETE（未完成；绝不伪装 COMPLETED）。
        """
        with self._factory() as s:
            ep = s.execute(select(TribulationEpisode).where(
                TribulationEpisode.world_id == world_id,
                TribulationEpisode.episode_id == episode_id)
            ).scalar_one_or_none()
            if ep is None:
                return {"episode_id": episode_id, "found": False}
            idx = s.execute(select(HistoryEpisodeIndex).where(
                HistoryEpisodeIndex.world_id == world_id,
                HistoryEpisodeIndex.episode_id == episode_id)
            ).scalar_one_or_none()
            schedule = s.execute(select(TribulationSchedule).where(
                TribulationSchedule.world_id == world_id,
                TribulationSchedule.schedule_id == ep.schedule_ref,
                TribulationSchedule.tier == ep.window_tier)
            ).scalar_one_or_none()
            profile = s.execute(select(TribulationProfile).where(
                TribulationProfile.world_id == world_id,
                TribulationProfile.profile_id == ep.profile_ref)
            ).scalar_one_or_none()
            decisions = [{"decision_id": d.decision_id, "action": d.action,
                          "status": d.status,
                          "submitted_tick": d.submitted_tick,
                          "effective_before_tick": d.effective_before_tick,
                          "source": d.source}
                         for d in s.execute(select(TribulationDecision)
                                            .where(
                TribulationDecision.world_id == world_id,
                TribulationDecision.episode_id == episode_id).order_by(
                    TribulationDecision.submitted_tick,
                    TribulationDecision.decision_id)).scalars()]
            plans = [{"plan_id": p.plan_id, "intensity": p.intensity,
                      "tier": p.tier,
                      "population_risk_num": p.population_risk_num,
                      "population_risk_den": p.population_risk_den,
                      "resource_damage_num": p.resource_damage_num,
                      "resource_damage_den": p.resource_damage_den,
                      "ecology_pressure": p.ecology_pressure,
                      "affected_settlements": p.affected_settlements}
                     for p in s.execute(select(TribulationImpactPlan)
                                        .where(
                TribulationImpactPlan.world_id == world_id,
                TribulationImpactPlan.episode_id == episode_id).order_by(
                    TribulationImpactPlan.plan_id)).scalars()]
            domain_effects = []
            for c in s.execute(select(HistoryStateChange).where(
                    HistoryStateChange.world_id == world_id,
                    HistoryStateChange.episode_id == episode_id).order_by(
                        HistoryStateChange.blessed_tick,
                        HistoryStateChange.id)).scalars():
                domain_effects.append({
                    "state_change_id": c.id,
                    "entity_type": c.entity_type,
                    "entity_id": c.entity_id,
                    "field": c.field,
                    "old_value": c.old_value,
                    "new_value": c.new_value,
                    "engine_id": c.engine_id,
                    "tick": c.blessed_tick})
            recovery = s.execute(select(TribulationRecoveryState).where(
                TribulationRecoveryState.world_id == world_id,
                TribulationRecoveryState.episode_id == episode_id)
            ).scalar_one_or_none()
            residuals = [{"id": r.id, "change_kind": r.change_kind,
                          "payload": r.payload, "persistent": r.persistent}
                         for r in s.execute(select(
                             TribulationResidualChange).where(
                TribulationResidualChange.world_id == world_id,
                TribulationResidualChange.episode_id == episode_id).order_by(
                    TribulationResidualChange.id)).scalars()]
            candidates = [{"candidate_id": c.candidate_id,
                           "discovery_status": c.discovery_status,
                           "development_status": c.development_status,
                           "maturation_requirement":
                               c.maturation_requirement}
                          for c in s.execute(select(
                              ResourceSuccessionCandidate).where(
                ResourceSuccessionCandidate.world_id == world_id,
                ResourceSuccessionCandidate.episode_id == episode_id)
                .order_by(ResourceSuccessionCandidate.candidate_id)
            ).scalars()]
            stage_events = []
            for ev in s.execute(select(WorldEvent).join(
                    CausalHistoryLink,
                    (CausalHistoryLink.source_kind == "EVENT")
                    & (CausalHistoryLink.source_id == WorldEvent.event_uid)
                    & (CausalHistoryLink.target_kind == "EPISODE")
                    & (CausalHistoryLink.target_id == episode_id)
                    & (CausalHistoryLink.relation_type == PART_OF_EPISODE)
                    & (CausalHistoryLink.world_id == world_id)).where(
                        WorldEvent.event_type.in_(_STAGE_TYPES)).order_by(
                            WorldEvent.blessed_tick,
                            WorldEvent.id)).scalars():
                stage_events.append({"event_uid": ev.event_uid,
                                     "event_type": ev.event_type,
                                     "blessed_tick": ev.blessed_tick,
                                     "effect": dict(ev.effect)})
            completed = ep.status == "COMPLETED"
            stage = ep.current_stage
            if completed:
                status = "COMPLETED"
            elif stage == "RECOVERY":
                status = "IN_RECOVERY"
            else:
                status = "ACTIVE"
            return {
                "episode_id": episode_id, "found": True,
                "status": status,
                "completion": "COMPLETED" if completed else "INCOMPLETE",
                "stage": stage,
                "tier": ep.window_tier,
                "entered_tick": ep.entered_tick,
                "transition_tick": ep.transition_tick,
                "completed_tick": idx.completed_tick if idx else None,
                "schedule": {"schedule_id": ep.schedule_ref,
                             "period_years": schedule.period_years
                             if schedule else None},
                "profile": {"profile_id": ep.profile_ref,
                            "theme": profile.theme if profile else None,
                            "intensity_range":
                                [profile.intensity_min, profile.intensity_max]
                                if profile else None},
                "targets": ep.target_settlements,
                "decisions": decisions,
                "plans": plans,
                "domain_effects": domain_effects,
                "recovery": {"status": recovery.status,
                             "progress_num": recovery.progress_num,
                             "progress_den": recovery.progress_den,
                             "started_tick": recovery.started_tick}
                            if recovery else None,
                "residual_changes": residuals,
                "succession_candidates": candidates,
                "stage_events": stage_events,
            }

    # ------------------------------------------------------------ Why
    def explain_state(self, *, world_id: str, entity_type: str,
                      entity_id: str, field: str, max_depth: int = 4,
                      max_nodes: int = 40, start_tick: int | None = None,
                      end_tick: int | None = None,
                      relations: tuple[str, ...] | None = None,
                      include_superseded: bool = False) -> dict:
        """CAUSAL_HISTORY_CHAIN：当前值 ← 最近状态变更 ← 因事件 ← 上游。"""
        eid = str(entity_id)
        with self._factory() as s:
            model = ENTITY_MODELS.get(entity_type)
            current, current_tick = None, None
            if model is not None and hasattr(model, field):
                row = s.get(model, int(eid))
                if row is not None:
                    current = getattr(row, field)
                    current_tick = getattr(row, "updated_blessed_tick", None)
            q = select(HistoryStateChange).where(
                HistoryStateChange.world_id == world_id,
                HistoryStateChange.entity_type == entity_type,
                HistoryStateChange.entity_id == eid,
                HistoryStateChange.field == field)
            if start_tick is not None:
                q = q.where(HistoryStateChange.blessed_tick >= start_tick)
            if end_tick is not None:
                q = q.where(HistoryStateChange.blessed_tick <= end_tick)
            last = s.execute(q.order_by(
                HistoryStateChange.blessed_tick.desc(),
                HistoryStateChange.id.desc()).limit(1)).scalars().first()
            if last is None:
                return {"entity_type": entity_type, "entity_id": eid,
                        "field": field, "current_value": current,
                        "current_value_tick": current_tick,
                        "last_state_change": None, "causes": [],
                        "note": "no indexed state change for this field"}
            last_sc = {"state_change_id": last.id,
                       "old_value": last.old_value,
                       "new_value": last.new_value,
                       "blessed_tick": last.blessed_tick,
                       "event_ref": last.event_ref,
                       "engine_id": last.engine_id,
                       "simulation_run_id": last.simulation_run_id,
                       "episode_id": last.episode_id,
                       "owner_decision_id": last.owner_decision_id}
            budget = {"nodes": 0}
            causes = self._walk_up(
                s, world_id, ("STATE_CHANGE", str(last.id)), depth=0,
                max_depth=max_depth, max_nodes=max_nodes, relations=relations,
                include_superseded=include_superseded, budget=budget,
                start_tick=start_tick, end_tick=end_tick)
            return {"entity_type": entity_type, "entity_id": eid,
                    "field": field, "current_value": current,
                    "current_value_tick": current_tick,
                    "last_state_change": last_sc, "causes": causes,
                    "nodes_visited": budget["nodes"],
                    "truncated": budget["nodes"] >= max_nodes}

    def trace_causes(self, *, world_id: str, kind: str, node_id: str,
                     max_depth: int = 6, max_nodes: int = 60,
                     relations: tuple[str, ...] | None = None,
                     include_superseded: bool = False) -> dict:
        """从任意节点向上游追溯因链（入边 → 源节点递归）。"""
        with self._factory() as s:
            budget = {"nodes": 0}
            causes = self._walk_up(
                s, world_id, (kind, node_id), depth=0, max_depth=max_depth,
                max_nodes=max_nodes, relations=relations,
                include_superseded=include_superseded, budget=budget,
                start_tick=None, end_tick=None)
            return {"node": {"kind": kind, "id": node_id},
                    "causes": causes, "nodes_visited": budget["nodes"],
                    "truncated": budget["nodes"] >= max_nodes}

    def _walk_up(self, s: Session, world_id: str, node: tuple[str, str], *,
                 depth: int, max_depth: int, max_nodes: int,
                 relations: tuple[str, ...] | None,
                 include_superseded: bool, budget: dict,
                 start_tick: int | None, end_tick: int | None) -> list[dict]:
        if depth >= max_depth or budget["nodes"] >= max_nodes:
            return []
        budget["nodes"] += 1
        rel_filter = relations if relations is not None \
            else tuple(TRACE_RELATIONS)
        q = select(CausalHistoryLink).where(
            CausalHistoryLink.world_id == world_id,
            CausalHistoryLink.target_kind == node[0],
            CausalHistoryLink.target_id == node[1],
            CausalHistoryLink.relation_type.in_(rel_filter))
        if not include_superseded:
            q = q.where(CausalHistoryLink.status == "ACTIVE")
        if start_tick is not None:
            q = q.where(CausalHistoryLink.committed_tick >= start_tick)
        if end_tick is not None:
            q = q.where(CausalHistoryLink.committed_tick <= end_tick)
        rows = s.execute(q.order_by(
            CausalHistoryLink.committed_tick,
            CausalHistoryLink.source_id, CausalHistoryLink.target_id,
            CausalHistoryLink.link_id).limit(max_nodes)).scalars().all()
        out: list[dict] = []
        for link in rows:
            src_node = (link.source_kind, link.source_id)
            item = {"relation": link.relation_type,
                    "source": {"kind": link.source_kind,
                               "id": link.source_id},
                    "committed_tick": link.committed_tick,
                    "episode_id": link.episode_id,
                    "status": link.status,
                    "detail": self._node_detail(s, world_id, src_node)}
            if budget["nodes"] < max_nodes and depth + 1 < max_depth:
                item["upstream"] = self._walk_up(
                    s, world_id, src_node, depth=depth + 1,
                    max_depth=max_depth, max_nodes=max_nodes,
                    relations=relations,
                    include_superseded=include_superseded, budget=budget,
                    start_tick=start_tick, end_tick=end_tick)
            out.append(item)
        # 确定性排序：tick → relation priority → source id → link id
        out.sort(key=lambda it: (
            it["committed_tick"] or 0,
            RELATION_PRIORITY.get(it["relation"], 99),
            it["source"]["id"], it["source"]["kind"]))
        return out

    @staticmethod
    def _node_detail(s: Session, world_id: str,
                     node: tuple[str, str]) -> dict | None:
        kind, nid = node
        if kind == "EVENT":
            ev = s.execute(select(WorldEvent).where(
                WorldEvent.event_uid == nid)).scalar_one_or_none()
            if ev is None:
                return None
            return {"event_uid": ev.event_uid, "event_type": ev.event_type,
                    "blessed_tick": ev.blessed_tick, "cause": dict(ev.cause),
                    "effect": dict(ev.effect)}
        if kind == "STATE_CHANGE":
            sc = s.get(HistoryStateChange, int(nid))
            if sc is None:
                return None
            return {"state_change_id": sc.id, "entity_type": sc.entity_type,
                    "entity_id": sc.entity_id, "field": sc.field,
                    "old_value": sc.old_value, "new_value": sc.new_value,
                    "blessed_tick": sc.blessed_tick}
        if kind == "EPISODE":
            ep = s.execute(select(TribulationEpisode).where(
                TribulationEpisode.world_id == world_id,
                TribulationEpisode.episode_id == nid)).scalar_one_or_none()
            if ep is None:
                return None
            return {"episode_id": ep.episode_id, "tier": ep.window_tier,
                    "stage": ep.current_stage, "status": ep.status,
                    "entered_tick": ep.entered_tick,
                    "profile_ref": ep.profile_ref}
        if kind == "PLAN":
            p = s.execute(select(TribulationImpactPlan).where(
                TribulationImpactPlan.world_id == world_id,
                TribulationImpactPlan.plan_id == nid)).scalar_one_or_none()
            return None if p is None else {"plan_id": p.plan_id,
                                           "intensity": p.intensity,
                                           "tier": p.tier}
        if kind == "DECISION":
            d = s.execute(select(TribulationDecision).where(
                TribulationDecision.world_id == world_id,
                TribulationDecision.decision_id == nid)).scalar_one_or_none()
            return None if d is None else {"decision_id": d.decision_id,
                                           "action": d.action,
                                           "status": d.status}
        if kind == "RECOVERY_STATE":
            r = s.execute(select(TribulationRecoveryState).where(
                TribulationRecoveryState.world_id == world_id,
                TribulationRecoveryState.episode_id == nid)
            ).scalar_one_or_none()
            return None if r is None else {"episode_id": r.episode_id,
                                           "status": r.status,
                                           "progress_num": r.progress_num,
                                           "progress_den": r.progress_den}
        if kind == "RESIDUAL":
            r = s.get(TribulationResidualChange, int(nid))
            return None if r is None else {"id": r.id,
                                           "change_kind": r.change_kind,
                                           "payload": r.payload}
        if kind == "SUCCESSION":
            c = s.execute(select(ResourceSuccessionCandidate).where(
                ResourceSuccessionCandidate.world_id == world_id,
                ResourceSuccessionCandidate.candidate_id == nid)
            ).scalar_one_or_none()
            return None if c is None else {"candidate_id": c.candidate_id,
                                           "discovery_status":
                                               c.discovery_status,
                                           "development_status":
                                               c.development_status}
        if kind == "ENTITY":
            etype, _, eid = nid.partition(":")
            return {"entity_type": etype, "entity_id": eid}
        return None

    # ------------------------------------------------------------ Audit
    def history_integrity_audit(self, *, world_id: str) -> dict:
        """HISTORY_INTEGRITY_AUDIT：orphan/环/重复/非法 relation/tick
        paradox/supersede 环/未索引 state change/水印。"""
        with self._factory() as s:
            links = s.execute(select(CausalHistoryLink).where(
                CausalHistoryLink.world_id == world_id).order_by(
                    CausalHistoryLink.link_id)).scalars().all()
            exist = self._batch_node_existence(s, world_id, links)
            orphans: list[dict] = []
            dup: list[dict] = []
            invalid_rel: list[str] = []
            tick_paradox: list[dict] = []
            seen: dict[tuple, int] = {}
            for link in links:
                if link.relation_type not in RELATION_TYPES \
                        and link.relation_type not in invalid_rel:
                    invalid_rel.append(link.relation_type)
                if (link.source_kind, link.source_id) not in exist \
                        or (link.target_kind, link.target_id) not in exist:
                    orphans.append({"link_id": link.link_id,
                                    "relation": link.relation_type,
                                    "source": (link.source_kind,
                                               link.source_id),
                                    "target": (link.target_kind,
                                               link.target_id)})
                key = (link.relation_type, link.source_kind, link.source_id,
                       link.target_kind, link.target_id)
                seen[key] = seen.get(key, 0) + 1
                rule = RELATION_TICK_RULES.get(link.relation_type)
                if rule == TICK_FORWARD and link.source_tick is not None \
                        and link.target_tick is not None \
                        and link.source_tick > link.target_tick:
                    tick_paradox.append({"link_id": link.link_id,
                                         "relation": link.relation_type,
                                         "source_tick": link.source_tick,
                                         "target_tick": link.target_tick})
                if rule == TICK_BACKWARD and link.source_tick is not None \
                        and link.target_tick is not None \
                        and link.source_tick < link.target_tick:
                    tick_paradox.append({"link_id": link.link_id,
                                         "relation": link.relation_type,
                                         "source_tick": link.source_tick,
                                         "target_tick": link.target_tick})
            for k, v in seen.items():
                if v > 1:
                    dup.append({"relation": k[0], "source": (k[1], k[2]),
                                "target": (k[3], k[4]), "count": v})
            cycles = self._find_cycles(s, world_id, links)
            sup_loops = self._supersede_loops(s, world_id, links)
            total_sc = s.execute(select(func.count()).select_from(
                HistoryStateChange).where(
                    HistoryStateChange.world_id == world_id)).scalar() or 0
            from ...database.models_core import WorldStateChange
            legacy_sc = s.execute(select(func.count()).select_from(
                WorldStateChange).where(
                    WorldStateChange.world_id == world_id)).scalar() or 0
            watermark = s.execute(select(HistoryIndexState).where(
                HistoryIndexState.world_id == world_id)).scalar_one_or_none()
            return {
                "links_total": len(links),
                "orphan_links": len(orphans),
                "orphan_samples": orphans[:10],
                "duplicate_links": len(dup),
                "duplicate_samples": dup[:10],
                "invalid_relations": invalid_rel,
                "tick_paradox_links": len(tick_paradox),
                "tick_paradox_samples": tick_paradox[:10],
                "cycle_count": len(cycles),
                "cycle_samples": cycles[:5],
                "supersede_loops": sup_loops,
                "state_changes_total": total_sc,
                "state_changes_indexed": total_sc,
                "state_changes_unindexed": max(legacy_sc - total_sc, 0),
                "legacy_world_state_changes": legacy_sc,                "indexed_through_tick":
                    watermark.indexed_through_tick if watermark else None,
                "clean": (not orphans and not dup and not invalid_rel
                          and not tick_paradox and not cycles
                          and not sup_loops),
            }

    def _find_cycles(self, s: Session, world_id: str,
                     links: list[CausalHistoryLink]) -> list[dict]:
        """迭代 3-color DFS（禁环关系子图）。"""
        adj: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for link in links:
            if link.relation_type not in CYCLE_FORBIDDEN_RELATIONS \
                    or link.status != "ACTIVE":
                continue
            adj.setdefault((link.source_kind, link.source_id), []).append(
                (link.target_kind, link.target_id))
        color: dict[tuple[str, str], int] = {}
        cycles: list[dict] = []
        for start in sorted(adj):
            if color.get(start, 0) != 0:
                continue
            color[start] = 1
            stack: list[tuple[tuple[str, str], int]] = [(start, 0)]
            path: list[tuple[str, str]] = [start]
            while stack:
                node, i = stack[-1]
                nbrs = adj.get(node, ())
                if i >= len(nbrs):
                    color[node] = 2
                    stack.pop()
                    path.pop()
                    continue
                nxt = nbrs[i]
                stack[-1] = (node, i + 1)
                c = color.get(nxt, 0)
                if c == 0:
                    color[nxt] = 1
                    stack.append((nxt, 0))
                    path.append(nxt)
                elif c == 1:
                    idx = path.index(nxt) if nxt in path else 0
                    cycles.append({"nodes": [f"{k}:{i_}" for k, i_ in
                                             path[idx:]] + [f"{nxt[0]}:{nxt[1]}"]})
        return cycles

    @staticmethod
    def _supersede_loops(s: Session, world_id: str,
                         links: list[CausalHistoryLink]) -> list[dict]:
        sup: dict[str, list[str]] = {}
        for link in links:
            if link.relation_type == "SUPERSEDES":
                sup.setdefault(link.target_id, []).append(link.source_id)
        loops: list[dict] = []

        def walk(cur: str, path: list[str]):
            for nxt in sup.get(cur, ()):
                if nxt in path:
                    loops.append({"chain": path[path.index(nxt):] + [nxt]})
                else:
                    walk(nxt, path + [nxt])

        for start in sorted(sup):
            walk(start, [start])
        return loops

    def _node_exists(self, s: Session, world_id: str, kind: str,
                     node_id: str) -> bool:
        from .builder import HistoryLinkBuilder
        return HistoryLinkBuilder()._node_exists(s, world_id, kind, node_id)

    @staticmethod
    def _chunks(seq, size: int = 500):
        seq = list(seq)
        for i in range(0, len(seq), size):
            yield seq[i:i + size]

    @staticmethod
    def _batch_node_existence(s: Session, world_id: str,
                              links: list[CausalHistoryLink]
                              ) -> set[tuple[str, str]]:
        """批量解析全部链接引用节点（审计用；避免逐链查询）。
        IN 列表按 500 分块（SQLite 999 变量上限）。"""
        ids_by_kind: dict[str, set[str]] = {}
        for link in links:
            ids_by_kind.setdefault(link.source_kind, set()).add(link.source_id)
            ids_by_kind.setdefault(link.target_kind, set()).add(link.target_id)
        exist: set[tuple[str, str]] = set()
        ch = HistoryService._chunks

        if "EVENT" in ids_by_kind:
            for batch in ch(ids_by_kind["EVENT"]):
                found = {u for (u,) in s.execute(select(WorldEvent.event_uid)
                                                 .where(
                    WorldEvent.event_uid.in_(batch))).all()}
                for u in found:
                    exist.add(("EVENT", u))
        if "STATE_CHANGE" in ids_by_kind:
            ids = {int(i) for i in ids_by_kind["STATE_CHANGE"]
                   if i.isdigit()}
            for batch in ch(ids):
                found = {str(i) for (i,) in s.execute(select(
                    HistoryStateChange.id).where(
                    HistoryStateChange.id.in_(batch))).all()}
                for i in found:
                    exist.add(("STATE_CHANGE", i))
        if "EPISODE" in ids_by_kind:
            for batch in ch(ids_by_kind["EPISODE"]):
                found = {e for (e,) in s.execute(select(
                    TribulationEpisode.episode_id).where(
                    TribulationEpisode.world_id == world_id,
                    TribulationEpisode.episode_id.in_(batch))).all()}
                for e in found:
                    exist.add(("EPISODE", e))
        if "PLAN" in ids_by_kind:
            for batch in ch(ids_by_kind["PLAN"]):
                found = {p for (p,) in s.execute(select(
                    TribulationImpactPlan.plan_id).where(
                    TribulationImpactPlan.world_id == world_id,
                    TribulationImpactPlan.plan_id.in_(batch))).all()}
                for p in found:
                    exist.add(("PLAN", p))
        if "DECISION" in ids_by_kind:
            for batch in ch(ids_by_kind["DECISION"]):
                found = {d for (d,) in s.execute(select(
                    TribulationDecision.decision_id).where(
                    TribulationDecision.world_id == world_id,
                    TribulationDecision.decision_id.in_(batch))).all()}
                for d in found:
                    exist.add(("DECISION", d))
        if "RECOVERY_STATE" in ids_by_kind:
            for batch in ch(ids_by_kind["RECOVERY_STATE"]):
                found = {e for (e,) in s.execute(select(
                    TribulationRecoveryState.episode_id).where(
                    TribulationRecoveryState.world_id == world_id,
                    TribulationRecoveryState.episode_id.in_(batch))).all()}
                for e in found:
                    exist.add(("RECOVERY_STATE", e))
        if "RESIDUAL" in ids_by_kind:
            ids = {int(i) for i in ids_by_kind["RESIDUAL"] if i.isdigit()}
            for batch in ch(ids):
                found = {str(i) for (i,) in s.execute(select(
                    TribulationResidualChange.id).where(
                    TribulationResidualChange.id.in_(batch))).all()}
                for i in found:
                    exist.add(("RESIDUAL", i))
        if "SUCCESSION" in ids_by_kind:
            for batch in ch(ids_by_kind["SUCCESSION"]):
                found = {c for (c,) in s.execute(select(
                    ResourceSuccessionCandidate.candidate_id).where(
                    ResourceSuccessionCandidate.world_id == world_id,
                    ResourceSuccessionCandidate.candidate_id.in_(batch))
                ).all()}
                for c in found:
                    exist.add(("SUCCESSION", c))
        if "CHECKPOINT" in ids_by_kind:
            from ...database.models_core import SimulationCheckpoint
            ids = {int(i) for i in ids_by_kind["CHECKPOINT"] if i.isdigit()}
            for batch in ch(ids):
                found = {str(i) for (i,) in s.execute(select(
                    SimulationCheckpoint.id).where(
                    SimulationCheckpoint.id.in_(batch))).all()}
                for i in found:
                    exist.add(("CHECKPOINT", i))
        if "ENTITY" in ids_by_kind:
            by_type: dict[str, set[int]] = {}
            for nid in ids_by_kind["ENTITY"]:
                etype, _, eid = nid.partition(":")
                if eid.isdigit() and etype in ENTITY_MODELS:
                    by_type.setdefault(etype, set()).add(int(eid))
            for etype, ids in by_type.items():
                model = ENTITY_MODELS[etype]
                for batch in ch(ids):
                    found = {str(i) for (i,) in s.execute(select(
                        model.id).where(model.id.in_(batch))).all()}
                    for i in found:
                        exist.add(("ENTITY", f"{etype}:{i}"))
        return exist

    # ------------------------------------------------------------ Hash
    def causal_history_hash(self, *, world_id: str) -> dict:
        """causal_history_hash v1：versioned / canonical / 行序无关。

        覆盖 link identity + relation + source/target ids + episode +
        status + committed_tick + semantic_version；不重复 hash 事件
        payload（event_stream_hash 已覆盖事实内容）。
        """
        with self._factory() as s:
            rows = s.execute(select(CausalHistoryLink).where(
                CausalHistoryLink.world_id == world_id).order_by(
                    CausalHistoryLink.link_id)).scalars().all()
            parts = [CAUSAL_HISTORY_HASH_SCHEMA_VERSION, world_id,
                     str(len(rows))]
            for link in rows:
                parts.append("|".join((
                    link.relation_type, link.source_kind, link.source_id,
                    link.target_kind, link.target_id,
                    link.episode_id or "", link.status,
                    str(link.committed_tick), link.semantic_version or "")))
            digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
            return {"schema_version": CAUSAL_HISTORY_HASH_SCHEMA_VERSION,
                    "links": len(rows), "hash": digest}

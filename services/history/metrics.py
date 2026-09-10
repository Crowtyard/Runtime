# -*- coding: utf-8 -*-
"""M3b History Metric & Cardinality Audit（纯只读审计指标，0 mutation）。

本模块不是新功能：只对 history 层做可复现的统计口径审计。
所有函数只读（SELECT），不 commit/不 flush/不写任何表。
性能计时仅存在于 tests（不进确定性输出/不进 hash）。
"""
from __future__ import annotations

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from ...database.models_core import WorldEvent
from ...database.models_world import (CausalHistoryLink,
                                      EntityHistoryIndex,
                                      HistoryEpisodeIndex,
                                      HistoryIndexState,
                                      HistoryStateChange,
                                      TribulationEpisode)
from .entities import ENTITY_MODELS
from .relations import RELATION_TYPES

# ---------------------------------------------------------------- Episode

# 互斥 Episode 状态（按现有状态机；sum == episodes_indexed）
EPISODE_STATE_COMPLETED = "EPISODE_STATE_COMPLETED"            # status=COMPLETED
EPISODE_STATE_PRECURSOR = "EPISODE_STATE_PRECURSOR"            # ACTIVE+PRECURSOR
EPISODE_STATE_PREPARATION = "EPISODE_STATE_PREPARATION"        # ACTIVE+PREPARATION
EPISODE_STATE_IMPACT = "EPISODE_STATE_IMPACT"                  # ACTIVE+IMPACT
EPISODE_STATE_RESPONSE = "EPISODE_STATE_RESPONSE"              # ACTIVE+RESPONSE
EPISODE_STATE_STABILIZATION = "EPISODE_STATE_STABILIZATION"    # ACTIVE+STABILIZATION
EPISODE_STATE_RESIDUAL_CHANGE = "EPISODE_STATE_RESIDUAL_CHANGE"
EPISODE_STATE_RECOVERY = "EPISODE_STATE_RECOVERY"              # ACTIVE+RECOVERY
EPISODE_STATE_RESOURCE_SUCCESSION = "EPISODE_STATE_RESOURCE_SUCCESSION"
EPISODE_STATE_NEW_NORMAL_PENDING = "EPISODE_STATE_NEW_NORMAL_PENDING"  # ACTIVE+NEW_NORMAL

MUTUALLY_EXCLUSIVE_EPISODE_STATES = (
    EPISODE_STATE_COMPLETED, EPISODE_STATE_PRECURSOR,
    EPISODE_STATE_PREPARATION, EPISODE_STATE_IMPACT, EPISODE_STATE_RESPONSE,
    EPISODE_STATE_STABILIZATION, EPISODE_STATE_RESIDUAL_CHANGE,
    EPISODE_STATE_RECOVERY, EPISODE_STATE_RESOURCE_SUCCESSION,
    EPISODE_STATE_NEW_NORMAL_PENDING)

_STAGE_TO_MUTEX_STATE = {
    "PRECURSOR": EPISODE_STATE_PRECURSOR,
    "PREPARATION": EPISODE_STATE_PREPARATION,
    "IMPACT": EPISODE_STATE_IMPACT,
    "RESPONSE": EPISODE_STATE_RESPONSE,
    "STABILIZATION": EPISODE_STATE_STABILIZATION,
    "RESIDUAL_CHANGE": EPISODE_STATE_RESIDUAL_CHANGE,
    "RECOVERY": EPISODE_STATE_RECOVERY,
    "RESOURCE_SUCCESSION": EPISODE_STATE_RESOURCE_SUCCESSION,
    "NEW_NORMAL": EPISODE_STATE_NEW_NORMAL_PENDING,
}


def _mutex_state_of(status: str, stage: str) -> str:
    """互斥分类：COMPLETED 优先；否则按 stage；NEW_NORMAL+ACTIVE 单独桶。"""
    if status == "COMPLETED":
        return EPISODE_STATE_COMPLETED
    return _STAGE_TO_MUTEX_STATE.get(stage, EPISODE_STATE_PRECURSOR)


def episode_state_audit(session_factory: sessionmaker[Session], *,
                        world_id: str) -> dict:
    """全部 Episode 结构化状态 + 互斥/非互斥汇总。

    - incomplete 布尔条件（代码口径）：status != "COMPLETED"
      （M3a 基线 writer 的 completed 口径是 current_stage == NEW_NORMAL，
      含 NEW_NORMAL_PENDING——两种口径都合法但语义不同，见报告）。
    """
    with session_factory() as s:
        eps = s.execute(select(TribulationEpisode).where(
            TribulationEpisode.world_id == world_id).order_by(
                TribulationEpisode.entered_tick,
                TribulationEpisode.episode_id)).scalars().all()
        idx_rows = {r.episode_id: r for r in s.execute(select(
            HistoryEpisodeIndex).where(
                HistoryEpisodeIndex.world_id == world_id)).scalars()}
    per_episode = []
    mutex_counts = {k: 0 for k in MUTUALLY_EXCLUSIVE_EPISODE_STATES}
    completed = active = recovering = incomplete = 0
    terminal_noncompleted = 0
    for ep in eps:
        idx = idx_rows.get(ep.episode_id)
        indexed = idx is not None
        done = ep.status == "COMPLETED"
        recov = ep.current_stage == "RECOVERY"
        inc = not done
        mutex = _mutex_state_of(ep.status or "", ep.current_stage or "")
        mutex_counts[mutex] += 1
        completed += 1 if done else 0
        active += 1 if not done else 0
        recovering += 1 if recov else 0
        incomplete += 1 if inc else 0
        per_episode.append({
            "episode_id": ep.episode_id,
            "scheduled_tick": ep.entered_tick,
            "tier": ep.window_tier,
            "current_stage": ep.current_stage,
            "status": ep.status,
            "entered_tick": ep.entered_tick,
            "completed_tick": idx.completed_tick if idx else None,
            "indexed": indexed,
            "completed": done,
            "active": not done,
            "recovering": recov,
            "incomplete": inc,
            "mutually_exclusive_state": mutex,
        })
        if not done and ep.current_stage == "NEW_NORMAL":
            terminal_noncompleted += 1
    scheduled = len(eps)
    indexed_total = sum(mutex_counts.values())
    return {
        "world_id": world_id,
        "per_episode": per_episode,
        "summary": {
            "scheduled_episodes": scheduled,
            "indexed_episodes": len(idx_rows),
            "completed_episodes": completed,
            "active_episodes": active,
            "recovering_episodes": recovering,
            "incomplete_episodes": incomplete,
            "nonterminal_total": scheduled - completed,
            "terminal_noncompleted_episodes": terminal_noncompleted,
            "missing_episodes": scheduled - len(idx_rows),
            "completed_by_stage_new_normal": sum(
                1 for e in per_episode
                if e["current_stage"] == "NEW_NORMAL"),
        },
        "mutually_exclusive_states": mutex_counts,
        "mutex_sum_equals_indexed": indexed_total == len(idx_rows),
        "incomplete_predicate": "episode.status != 'COMPLETED'",
        "m3a_completed_predicate": "episode.current_stage == 'NEW_NORMAL' "
                                   "(includes NEW_NORMAL_PENDING)",
    }


# ---------------------------------------------------------------- Entity
def entity_cardinality_audit(session_factory: sessionmaker[Session], *,
                             world_id: str) -> dict:
    """entities_with_history 指标溯源 + 真实基数。

    metric_source_query = SELECT COUNT(*) FROM entity_history_index
                          WHERE world_id = :w
    metric_source_table = entity_history_index
    metric_semantics     = raw index rows（(entity, link_id) 一对一行，
                           同一实体多 link → 多行；非 distinct 实体数）
    """
    with session_factory() as s:
        rows = s.execute(select(EntityHistoryIndex).where(
            EntityHistoryIndex.world_id == world_id)).scalars().all()
        distinct_pairs = {(r.entity_type, r.entity_id) for r in rows}
        by_type: dict[str, dict] = {}
        for r in rows:
            b = by_type.setdefault(r.entity_type,
                                   {"row_count": 0, "ids": set()})
            b["row_count"] += 1
            b["ids"].add(r.entity_id)
        links = s.execute(select(CausalHistoryLink).where(
            CausalHistoryLink.world_id == world_id)).scalars().all()
        ev_uid_sources = {l.source_id for l in links
                          if l.source_kind == "EVENT"}
        ev_uid_targets = {l.target_id for l in links
                          if l.target_kind == "EVENT"}
        sc_sources = {l.source_id for l in links
                      if l.source_kind == "STATE_CHANGE"}
        sc_targets = {l.target_id for l in links
                      if l.target_kind == "STATE_CHANGE"}
        ep_nodes = {l.episode_id for l in links if l.episode_id}
        sc_total = s.execute(select(func.count()).select_from(
            HistoryStateChange).where(
                HistoryStateChange.world_id == world_id)).scalar() or 0
        ev_total = s.execute(select(func.count()).select_from(
            WorldEvent).where(WorldEvent.world_id == world_id)).scalar() or 0
        domain_types = {k for k in by_type if k in ENTITY_MODELS}
        distinct_domain = sum(len(by_type[t]["ids"]) for t in domain_types)
        ref_only_types = {k for k in by_type if k not in ENTITY_MODELS}
    by_type_out = []
    for t, b in sorted(by_type.items()):
        by_type_out.append({
            "entity_type": t,
            "row_count": b["row_count"],
            "distinct_entity_count": len(b["ids"]),
            "classification": "DOMAIN_ENTITY" if t in ENTITY_MODELS
            else "INDEX_REFERENCE_ONLY",
        })
    return {
        "world_id": world_id,
        "metric_source_query": "SELECT COUNT(*) FROM entity_history_index "
                               "WHERE world_id = :w",
        "metric_source_table": "entity_history_index",
        "metric_semantics": "raw index row count; one row per "
                            "(entity_type, entity_id, link_id); NOT "
                            "distinct entities",
        "entity_history_index_rows": len(rows),
        "distinct_entity_ids": len(distinct_pairs),
        "distinct_domain_entities": distinct_domain,
        "distinct_entities_with_history": len(distinct_pairs),
        "index_reference_only_types": sorted(ref_only_types),
        "by_entity_type": by_type_out,
        "graph_node_cardinality": {
            "domain_events_total": ev_total,
            "state_changes_total": sc_total,
            "distinct_event_ids_indexed": len(
                ev_uid_sources | ev_uid_targets),
            "distinct_state_change_ids_indexed": len(
                sc_sources | sc_targets),
            "distinct_episode_ids_indexed": len(ep_nodes),
            "distinct_relation_targets": len(
                {(l.target_kind, l.target_id) for l in links}),
            "distinct_relation_sources": len(
                {(l.source_kind, l.source_id) for l in links}),
        },
    }


# ---------------------------------------------------------------- Density
def relation_density_audit(session_factory: sessionmaker[Session], *,
                           world_id: str) -> dict:
    with session_factory() as s:
        links = s.execute(select(CausalHistoryLink).where(
            CausalHistoryLink.world_id == world_id)).scalars().all()
        ev_domain = s.execute(select(func.count()).select_from(
            WorldEvent).where(
                WorldEvent.world_id == world_id,
                WorldEvent.event_type != "TIME_ADVANCE")).scalar() or 0
        sc_total = s.execute(select(func.count()).select_from(
            HistoryStateChange).where(
                HistoryStateChange.world_id == world_id)).scalar() or 0
    dist: dict[str, int] = {r: 0 for r in RELATION_TYPES}
    for l in links:
        dist[l.relation_type] = dist.get(l.relation_type, 0) + 1
    total = len(links) or 1
    relation_distribution = [
        {"relation_type": r, "count": dist.get(r, 0),
         "percentage": round(100.0 * dist.get(r, 0) / total, 4)}
        for r in RELATION_TYPES]
    relation_distribution.sort(key=lambda d: (-d["count"], d["relation_type"]))
    return {
        "world_id": world_id,
        "domain_events": ev_domain,
        "state_changes": sc_total,
        "causal_links": len(links),
        "links_per_domain_event": round(len(links) / ev_domain, 4)
        if ev_domain else None,
        "links_per_state_change": round(len(links) / sc_total, 4)
        if sc_total else None,
        "relation_distribution": relation_distribution,
    }


# ---------------------------------------------------------------- Duplicate
def duplicate_semantic_links_audit(session_factory: sessionmaker[Session], *,
                                   world_id: str) -> dict:
    """完全相同的 (source, target, relation, episode, semantic scope)
    不得重复。"""
    with session_factory() as s:
        links = s.execute(select(CausalHistoryLink).where(
            CausalHistoryLink.world_id == world_id)).scalars().all()
    seen: dict[tuple, list[str]] = {}
    for l in links:
        key = (l.relation_type, l.source_kind, l.source_id, l.target_kind,
               l.target_id, l.episode_id or "", l.status,
               repr(sorted((l.entity_scope or {}).items())))
        seen.setdefault(key, []).append(l.link_id)
    dups = {k: v for k, v in seen.items() if len(v) > 1}
    return {"world_id": world_id,
            "duplicate_semantic_links": sum(len(v) - 1 for v in dups.values()),
            "duplicate_samples": [
                {"relation": k[0], "source": (k[1], k[2]),
                 "target": (k[3], k[4]), "episode": k[5],
                 "link_ids": v[:3]} for k, v in list(dups.items())[:10]]}


# ---------------------------------------------------------------- Transitive
def transitive_materialization_audit(session_factory: sessionmaker[Session], *,
                                     world_id: str) -> dict:
    """A→B, B→C, A→C 三元组审计（按 relation semantics 分类，非数量判断）。

    - candidate_transitive_materializations：同 relation 的三元组数
      （A→B、B→C、A→C 全存在）。
    - purely_redundant：其中 A→C 无独立领域语义的机械闭包
      （本实现各 relation 均为逐对独立语义：CONTINUES 只连相邻变更、
      AFFECTS 只连同 Step 事件→变更、RESULTS_IN 只连同 Step 计划→事件，
      直接 A→C 从不物化 → 候选=0）。
    """
    with session_factory() as s:
        links = s.execute(select(CausalHistoryLink).where(
            CausalHistoryLink.world_id == world_id)).scalars().all()
    out: dict[str, int] = {}
    by_rel: dict[str, dict[tuple, set]] = {}
    for l in links:
        if l.relation_type not in RELATION_TYPES:
            continue
        by_rel.setdefault(l.relation_type, {}).setdefault(
            (l.source_kind, l.source_id), set()).add(
            (l.target_kind, l.target_id))
    for rel, adj in by_rel.items():
        candidates = 0
        redundant = 0
        justified = 0
        for a, targets in adj.items():
            for b in list(targets):
                for c in by_rel[rel].get(b, ()):
                    if c in targets and c != a:
                        candidates += 1
                        # 三元组语义判定（冻结规则）：
                        #   CONTINUES：链式相邻延伸（A→C 跨代）无独立语义
                        #   AFFECTS：同 Step 事件→变更（A→C 跨步无独立语义）
                        #   其余：本实现不物化直接 A→C
                        if rel in ("CONTINUES", "AFFECTS"):
                            redundant += 1
                        else:
                            justified += 1
        out[rel] = {"candidate_transitive_materializations": candidates,
                    "semantically_justified": justified,
                    "purely_redundant": redundant}
    total_candidates = sum(v["candidate_transitive_materializations"]
                           for v in out.values())
    total_redundant = sum(v["purely_redundant"] for v in out.values())
    return {"world_id": world_id,
            "candidate_transitive_materializations": total_candidates,
            "semantically_justified": sum(
                v["semantically_justified"] for v in out.values()),
            "purely_redundant_transitive_links": total_redundant,
            "by_relation": out}


# ---------------------------------------------------------------- Growth
def growth_projection(session_factory: sessionmaker[Session], *,
                      world_id: str, baseline_years: int = 300) -> dict:
    with session_factory() as s:
        links = s.execute(select(func.count()).select_from(
            CausalHistoryLink).where(
                CausalHistoryLink.world_id == world_id)).scalar() or 0
        idx_rows = s.execute(select(func.count()).select_from(
            EntityHistoryIndex).where(
                EntityHistoryIndex.world_id == world_id)).scalar() or 0
        sc_rows = s.execute(select(func.count()).select_from(
            HistoryStateChange).where(
                HistoryStateChange.world_id == world_id)).scalar() or 0
        ep_rows = s.execute(select(func.count()).select_from(
            HistoryEpisodeIndex).where(
                HistoryEpisodeIndex.world_id == world_id)).scalar() or 0
    per100 = baseline_years / 100.0
    proj = {
        "world_id": world_id,
        "baseline_years": baseline_years,
        "causal_links_per_100y": round(links / per100),
        "history_index_rows_per_100y": round(idx_rows / per100),
        "state_provenance_rows_per_100y": round(sc_rows / per100),
        "episode_index_rows_per_100y": round(ep_rows / per100),
        "estimated_1000y_causal_links": round(links / per100 * 10),
        "estimated_5000y_causal_links": round(links / per100 * 50),
        "estimated_1000y_history_rows": round(idx_rows / per100 * 10),
        "estimated_5000y_history_rows": round(idx_rows / per100 * 50),
        "projection_mode": "LINEAR_PROJECTION_ONLY",
    }
    return proj


# ---------------------------------------------------------------- DB growth
def db_growth_audit(*, history_db_path, schema_only_db_path) -> dict:
    """history 行数据的字节增量（history DB - 仅 schema 空库）。"""
    h = history_db_path.stat().st_size if history_db_path.exists() else 0
    s = schema_only_db_path.stat().st_size \
        if schema_only_db_path.exists() else 0
    added = max(h - s, 0)
    return {
        "history_db_bytes_total": h,
        "schema_only_db_bytes": s,
        "history_db_bytes_added_300y": added,
        "history_mb_per_100y": round(added / 3 / 1_048_576, 4),
        "estimated_1000y_history_mb": round(added / 3 * 10 / 1_048_576, 2),
        "estimated_5000y_history_mb": round(added / 3 * 50 / 1_048_576, 2),
        "projection_mode": "LINEAR_PROJECTION_ONLY",
        "note": "no destructive compaction; report only",
    }


# ---------------------------------------------------------------- Index audit
def query_plan_audit(session_factory: sessionmaker[Session], *,
                     world_id: str) -> dict:
    """EXPLAIN QUERY PLAN 审计（SQLite 方言；PG 兼容性见迁移审计）。"""
    plans = {}
    with session_factory() as s:
        def explain(sql: str, params: dict) -> str:
            rows = s.execute(text("EXPLAIN QUERY PLAN " + sql),
                             params).fetchall()
            return "; ".join(str(r[-1]) for r in rows)

        plans["timeline"] = explain(
            "SELECT id FROM world_events WHERE world_id=:w AND "
            "blessed_tick BETWEEN :a AND :b ORDER BY blessed_tick, id",
            {"w": world_id, "a": 0, "b": 300_000_000})
        plans["entity_history"] = explain(
            "SELECT id FROM history_state_changes WHERE world_id=:w AND "
            "entity_type=:t AND entity_id=:e AND blessed_tick>=:a",
            {"w": world_id, "t": "ecology_state", "e": "1", "a": 0})
        plans["episode_history_links"] = explain(
            "SELECT id FROM causal_history_links WHERE world_id=:w AND "
            "target_kind='EPISODE' AND target_id=:e",
            {"w": world_id, "e": "X"})
        plans["why_walk"] = explain(
            "SELECT id FROM causal_history_links WHERE world_id=:w AND "
            "target_kind=:k AND target_id=:i AND relation_type IN "
            "('AFFECTS','CAUSES')",
            {"w": world_id, "k": "STATE_CHANGE", "i": "1"})
        plans["entity_index_scope"] = explain(
            "SELECT link_id FROM entity_history_index WHERE world_id=:w "
            "AND entity_type=:t AND entity_id=:e ORDER BY committed_tick",
            {"w": world_id, "t": "ecology_state", "e": "1"})
    full_scan_risk = [k for k, v in plans.items()
                      if "SCAN" in v.upper() and "INDEX" not in v.upper()]
    return {"world_id": world_id, "plans": plans,
            "FULL_TABLE_SCAN_RISK": full_scan_risk,
            "MISSING_INDEXES": full_scan_risk}

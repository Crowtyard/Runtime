# -*- coding: utf-8 -*-
"""M3b 收口审计测试：MA1–MA29（metric semantics / cardinality / density /
performance / freeze gates）。

全部只读审计；300y fixture 模块级共享（构建一次）。
不改变任何模拟结果；正式 DB / World Seed 零接触（MA26/MA27 除外，只读）。
"""
from __future__ import annotations

from tests.formal_db import readonly_connect as formal_readonly_connect  # noqa: E402

import hashlib
import json
import random
import statistics
import time
from pathlib import Path

import pytest
from sqlalchemy import select

from tests.conftest import PROJECT_ROOT
from tests.golden_baseline import (assert_deterministic_equal, dump_artifact,
                                   golden_bytes_guard, load_artifact,
                                   update_mode_enabled)
from tests.test_m3a_tribulation import _fresh_m3a, _coordinator
from tests.test_m3b_history import _hist_coordinator

from XiaoguangBlessedLandRuntime.database.models_world import (
    CausalHistoryLink, EcologyState, EntityHistoryIndex, HistoryStateChange,
    ResourceNode, ResourceSuccessionCandidate, SettlementSocialState,
    TribulationEpisode)
from XiaoguangBlessedLandRuntime.services.db_lifecycle import \
    migrate_database
from XiaoguangBlessedLandRuntime.services.history.metrics import (
    MUTUALLY_EXCLUSIVE_EPISODE_STATES, db_growth_audit,
    duplicate_semantic_links_audit, entity_cardinality_audit,
    episode_state_audit, growth_projection, query_plan_audit,
    relation_density_audit, transitive_materialization_audit)
from XiaoguangBlessedLandRuntime.services.history.relations import \
    RELATION_TYPES
from XiaoguangBlessedLandRuntime.services.history.service import (
    HistoryService, canonical_causal_history_hash)
from XiaoguangBlessedLandRuntime.services.simulation.m3a_runner import \
    run_m3a_world

REPO = PROJECT_ROOT
W = "MINIWORLD-TEST-001"
BASELINE_DIR = REPO / "tests" / "baselines" / "m3b_causal_history_300y_v1"
M3A_BASELINE = REPO / "tests" / "baselines" / \
    "m3a_tribulation_synthetic_300y_v1"
M2_MANIFEST = REPO / "M2_SIMULATION_SEMANTICS_MANIFEST.json"
SEED_DIR = REPO.parent / "XIAOGUANG_CROW_KB" / "world_seed"

# GB2：本模块（ma28）拥有的 golden 文件，测试前后字节必须不变
_golden_bytes_guard = golden_bytes_guard(*[
    BASELINE_DIR / n for n in (
        "metric_audit.json", "episode_state_audit.json",
        "entity_cardinality_audit.json", "relation_density_audit.json",
        "query_performance.json", "growth_projection.json")])


def _expected(name: str) -> dict:
    """M6D.3 OPT-B：EXPECTED 值来自 committed（已 refrozen）golden baseline artifact
    —— `metric_audit.json` 及其同目录 300y 审计产物是 **single source of golden
    truth**；测试体不再维护第二份数字副本。

    严格性说明（owner §2/§3）：
    - ACTUAL 仍由本次 production 计算独立得到（`entity_cardinality_audit(...)` 等），
      本 helper **只读** committed baseline，绝不使用当前 run 的 artifact 当 expected；
    - 普通验证模式不 regenerate baseline；比较仍是**精确相等**，未改成
      range/approximate/≥/nonzero。
    """
    return load_artifact(BASELINE_DIR / name)

# 300y 审计基准（模块级构建一次）
HIST300: dict = {}


@pytest.fixture(scope="module")
def hist300(tmp_path_factory):
    if HIST300:
        return HIST300
    tmp = tmp_path_factory.mktemp("m3b_audit300")
    env = _fresh_m3a(tmp, 3001)
    coord = _hist_coordinator()
    rep = run_m3a_world(env["factory"], coordinator=coord, years=300)
    schema_only = tmp / "schema_only.db"
    migrate_database("sqlite:///" + str(schema_only).replace("\\", "/"),
                     project_root=REPO)
    HIST300.update({"env": env, "rep": rep,
                    "schema_only_path": schema_only})
    return HIST300


def _svc(hist300) -> HistoryService:
    return HistoryService(hist300["env"]["factory"])


# ---------------------------------------------------------------- MA1-MA4
def test_ma1_episode_state_classification_exhaustive(hist300):
    ep = episode_state_audit(hist300["env"]["factory"], world_id=W)
    rows = ep["per_episode"]
    assert len(rows) == 30
    for r in rows:
        for k in ("episode_id", "scheduled_tick", "tier", "current_stage",
                  "status", "entered_tick", "completed_tick", "indexed",
                  "completed", "active", "recovering", "incomplete"):
            assert k in r, (k, r["episode_id"])
    y290 = [r for r in rows if r["entered_tick"] == 290_000_000][0]
    y300 = [r for r in rows if r["entered_tick"] == 300_000_000][0]
    # 关键冲突解释：y290 已到 NEW_NORMAL 阶段但 status 仍 ACTIVE
    assert y290["current_stage"] == "NEW_NORMAL" and y290["status"] == "ACTIVE"
    assert y290["completed"] is False and y290["incomplete"] is True
    assert y300["current_stage"] == "PRECURSOR" and y300["status"] == "ACTIVE"
    assert y300["indexed"] is True


def test_ma2_episode_mutex_totals_sum_to_indexed(hist300):
    ep = episode_state_audit(hist300["env"]["factory"], world_id=W)
    assert ep["mutex_sum_equals_indexed"] is True
    assert sum(ep["mutually_exclusive_states"].values()) == 30
    assert ep["mutually_exclusive_states"]["EPISODE_STATE_COMPLETED"] == 28
    assert ep["mutually_exclusive_states"][
        "EPISODE_STATE_NEW_NORMAL_PENDING"] == 1
    assert ep["mutually_exclusive_states"]["EPISODE_STATE_PRECURSOR"] == 1
    for k in MUTUALLY_EXCLUSIVE_EPISODE_STATES:
        assert k in ep["mutually_exclusive_states"]


def test_ma3_scheduled_completed_consistency(hist300):
    ep = episode_state_audit(hist300["env"]["factory"], world_id=W)
    s = ep["summary"]
    assert s["scheduled_episodes"] == 30
    assert s["indexed_episodes"] == 30
    assert s["completed_episodes"] == 28
    assert s["incomplete_episodes"] == 2
    assert s["nonterminal_total"] == 2
    assert s["nonterminal_total"] == s["scheduled_episodes"] \
        - s["completed_episodes"]
    assert s["missing_episodes"] == 0
    assert s["terminal_noncompleted_episodes"] == 1
    # M3a 口径 completed=29 = stage==NEW_NORMAL（含 pending）
    assert s["completed_by_stage_new_normal"] == 29


def test_ma4_incomplete_metric_semantics_explicit(hist300):
    ep = episode_state_audit(hist300["env"]["factory"], world_id=W)
    assert ep["incomplete_predicate"] == "episode.status != 'COMPLETED'"
    assert ep["m3a_completed_predicate"] \
        == "episode.current_stage == 'NEW_NORMAL' (includes NEW_NORMAL_PENDING)"
    manual = sum(1 for r in ep["per_episode"] if r["status"] != "COMPLETED")
    assert ep["summary"]["incomplete_episodes"] == manual


# ---------------------------------------------------------------- MA5-MA8
def test_ma5_entity_history_index_rows_correct(hist300):
    ec = entity_cardinality_audit(hist300["env"]["factory"], world_id=W)
    exp = _expected("entity_cardinality_audit.json")   # OPT-B：single source
    with hist300["env"]["factory"]() as s:
        raw = len(s.execute(select(EntityHistoryIndex).where(
            EntityHistoryIndex.world_id == W)).scalars().all())
    assert ec["entity_history_index_rows"] == raw \
        == exp["entity_history_index_rows"]
    assert ec["metric_source_table"] == "entity_history_index"


def test_ma6_distinct_entities_with_history_correct(hist300):
    ec = entity_cardinality_audit(hist300["env"]["factory"], world_id=W)
    exp = _expected("entity_cardinality_audit.json")   # OPT-B：single source
    assert ec["distinct_entities_with_history"] \
        == exp["distinct_entities_with_history"]
    assert ec["distinct_domain_entities"] == exp["distinct_domain_entities"]
    assert ec["distinct_entity_ids"] == exp["distinct_entity_ids"]
    # 结构不变量（与 baseline 无关）：行数 ≠ 实体数（原指标口径错误）
    assert ec["distinct_entities_with_history"] < \
        ec["entity_history_index_rows"]


def test_ma7_domain_entities_separated_from_index_references(hist300):
    ec = entity_cardinality_audit(hist300["env"]["factory"], world_id=W)
    exp = _expected("entity_cardinality_audit.json")
    exp_graph = exp["graph_node_cardinality"]          # OPT-B：single source
    for b in ec["by_entity_type"]:
        assert b["classification"] == "DOMAIN_ENTITY", b["entity_type"]
    # EVENT/STATE_CHANGE/EPISODE 等引用型节点不进 entity index
    assert ec["index_reference_only_types"] == []
    g = ec["graph_node_cardinality"]
    assert g["distinct_event_ids_indexed"] == exp_graph["distinct_event_ids_indexed"]
    assert g["distinct_state_change_ids_indexed"] \
        == exp_graph["distinct_state_change_ids_indexed"]
    assert g["distinct_episode_ids_indexed"] \
        == exp_graph["distinct_episode_ids_indexed"]


def test_ma8_entity_type_grouping_correct(hist300):
    ec = entity_cardinality_audit(hist300["env"]["factory"], world_id=W)
    types = {b["entity_type"] for b in ec["by_entity_type"]}
    assert {"ecology_state", "resource_nodes", "population_groups",
            "settlement_social_state", "households", "lineages",
            "resource_stocks", "institutions"} <= types
    assert sum(b["row_count"] for b in ec["by_entity_type"]) \
        == ec["entity_history_index_rows"]
    assert sum(b["distinct_entity_count"] for b in ec["by_entity_type"]) \
        == ec["distinct_entities_with_history"]


# ---------------------------------------------------------------- MA9-MA12
def test_ma9_causal_link_density_metrics_correct(hist300):
    rd = relation_density_audit(hist300["env"]["factory"], world_id=W)
    exp = _expected("relation_density_audit.json")     # OPT-B：single source
    assert rd["domain_events"] == exp["domain_events"]
    assert rd["state_changes"] == exp["state_changes"]
    assert rd["causal_links"] == exp["causal_links"]
    # 精确相等（比原 <0.01 容差更严格），且期望值来自 committed baseline
    assert rd["links_per_domain_event"] == exp["links_per_domain_event"]
    assert rd["links_per_state_change"] == exp["links_per_state_change"]
    # 结构不变量（与 baseline 无关）
    total = sum(d["count"] for d in rd["relation_distribution"])
    assert total == rd["causal_links"]
    # 冻结词表全部 13 类都在分布中（未使用的为 0）
    assert {d["relation_type"] for d in rd["relation_distribution"]} \
        == set(RELATION_TYPES)


def test_ma10_duplicate_semantic_links_zero(hist300):
    dup = duplicate_semantic_links_audit(hist300["env"]["factory"],
                                         world_id=W)
    assert dup["duplicate_semantic_links"] == 0
    assert dup["duplicate_samples"] == []


def test_ma11_transitive_audit_deterministic(hist300):
    a = transitive_materialization_audit(hist300["env"]["factory"],
                                         world_id=W)
    b = transitive_materialization_audit(hist300["env"]["factory"],
                                         world_id=W)
    assert a == b
    assert a["candidate_transitive_materializations"] == 0
    assert a["purely_redundant_transitive_links"] == 0


def test_ma12_growth_projection_reproducible(hist300):
    gp = growth_projection(hist300["env"]["factory"], world_id=W)
    # OPT-B：single source = committed refrozen growth_projection.json
    exp = _expected("growth_projection.json")["growth_projection"]
    assert gp["causal_links_per_100y"] == exp["causal_links_per_100y"]
    assert gp["history_index_rows_per_100y"] == exp["history_index_rows_per_100y"]
    assert gp["state_provenance_rows_per_100y"] \
        == exp["state_provenance_rows_per_100y"]
    assert gp["episode_index_rows_per_100y"] == exp["episode_index_rows_per_100y"]
    assert gp["estimated_1000y_causal_links"] == exp["estimated_1000y_causal_links"]
    assert gp["estimated_5000y_causal_links"] == exp["estimated_5000y_causal_links"]
    # 语义/结构断言保留（不由 baseline 提供）
    assert gp["projection_mode"] == "LINEAR_PROJECTION_ONLY"


# ---------------------------------------------------------------- MA13-MA17
def _bench(fn, n_iter=20):
    fn()  # warm-up（不计入）
    ts = []
    for _ in range(n_iter):
        t = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t) * 1000)
    return {"p50_ms": round(statistics.median(ts), 3),
            "p95_ms": round(sorted(ts)[int(n_iter * 0.95) - 1], 3),
            "max_ms": round(max(ts), 3),
            "warmup_excluded": True, "iterations": n_iter}


@pytest.fixture(scope="module")
def perf300(hist300):
    svc = _svc(hist300)
    with hist300["env"]["factory"]() as s:
        z = s.execute(select(EcologyState)).scalars().first()
        eps = s.execute(select(TribulationEpisode).order_by(
            TribulationEpisode.entered_tick)).scalars().all()
        major = [e for e in eps if e.window_tier == "MAJOR"][0]
    return {"svc": svc, "zid": str(z.id),
            "major_ep": major.episode_id}


def test_ma13_entity_history_performance_measured(hist300, perf300):
    r = _bench(lambda: perf300["svc"].get_entity_history(
        world_id=W, entity_type="ecology_state",
        entity_id=perf300["zid"]))
    assert r["p50_ms"] < 500  # 批量加载后应远低于此（修复前 778ms）
    perf300["entity_history"] = r


def test_ma14_episode_history_performance_measured(hist300, perf300):
    r = _bench(lambda: perf300["svc"].get_tribulation_history(
        world_id=W, episode_id=perf300["major_ep"]))
    assert r["p50_ms"] < 500
    perf300["episode_history"] = r


def test_ma15_explain_state_performance_measured(hist300, perf300):
    r = _bench(lambda: perf300["svc"].explain_state(
        world_id=W, entity_type="ecology_state", entity_id=perf300["zid"],
        field="habitat_quality", max_depth=4, max_nodes=40))
    assert r["p50_ms"] < 500
    perf300["explain_state"] = r


def test_ma16_timeline_performance_measured(hist300, perf300):
    r = _bench(lambda: perf300["svc"].get_timeline(
        world_id=W, start_tick=299_000_000, end_tick=300_000_000))
    assert r["p50_ms"] < 500
    perf300["timeline"] = r


def test_ma17_query_plan_uses_expected_indexes(hist300):
    qp = query_plan_audit(hist300["env"]["factory"], world_id=W)
    assert qp["FULL_TABLE_SCAN_RISK"] == []
    assert "ix_world_events_tick" in qp["plans"]["timeline"]
    assert "ix_hist_sc_entity" in qp["plans"]["entity_history"]
    assert "ix_hist_links_target" in qp["plans"]["episode_history_links"]


# ---------------------------------------------------------------- MA18-MA21
def test_ma18_why_query_six_samples_valid(hist300):
    svc = _svc(hist300)
    with hist300["env"]["factory"]() as s:
        z = s.execute(select(EcologyState)).scalars().first()
        n = s.execute(select(ResourceNode)).scalars().first()
        st = s.execute(select(SettlementSocialState)).scalars().first()
        eps = s.execute(select(TribulationEpisode).order_by(
            TribulationEpisode.entered_tick)).scalars().all()
        major = [e for e in eps if e.window_tier == "MAJOR"][0]
        final_ep = eps[-1]
        cand = s.execute(select(ResourceSuccessionCandidate)).scalars().first()
    impact_tick = 293_000_000  # episode-290 IMPACT
    # A：某场 Major 灾劫造成了什么
    a = svc.get_tribulation_history(world_id=W, episode_id=major.episode_id)
    assert a["status"] == "COMPLETED"
    assert a["plans"] and a["domain_effects"]
    # B：为什么生态区质量下降（灾劫影响步）
    b = svc.explain_state(world_id=W, entity_type="ecology_state",
                          entity_id=str(z.id), field="habitat_quality",
                          max_depth=4, max_nodes=60, end_tick=impact_tick)
    assert any(c.get("detail") and c["detail"].get("event_type")
               == "TRIBULATION_IMPACT_APPLIED" for c in b["causes"])
    # C：为什么资源节点储量下降
    c = svc.explain_state(world_id=W, entity_type="resource_nodes",
                          entity_id=str(n.id), field="remaining_reserve",
                          max_depth=3, end_tick=impact_tick)
    assert c["last_state_change"] is not None
    assert any((c2.get("detail") or {}).get("event_type")
               == "TRIBULATION_IMPACT_APPLIED" for c2 in c["causes"])
    # D：社会压力为什么变化
    d = svc.explain_state(world_id=W, entity_type="settlement_social_state",
                          entity_id=str(st.id), field="social_stress",
                          max_depth=3, max_nodes=60, end_tick=impact_tick)
    assert any((c2.get("detail") or {}).get("event_type")
               == "TRIBULATION_IMPACT_APPLIED" for c2 in d["causes"])
    # E：succession candidate 来自哪场灾劫
    e = svc.trace_causes(world_id=W, kind="SUCCESSION",
                         node_id=cand.candidate_id, max_depth=5)
    assert e["causes"]
    assert any((c2["relation"], c2["source"]["kind"])
               == ("DERIVED_FROM", "RESIDUAL") for c2 in e["causes"])
    # F：末窗 Episode 阶段
    f = svc.get_tribulation_history(world_id=W, episode_id=final_ep.episode_id)
    assert f["status"] == "ACTIVE" and f["completion"] == "INCOMPLETE"
    assert f["stage"] == "PRECURSOR"


def test_ma19_multi_cause_preserved(hist300):
    svc = _svc(hist300)
    with hist300["env"]["factory"]() as s:
        z = s.execute(select(EcologyState)).scalars().first()
    exp = svc.explain_state(world_id=W, entity_type="ecology_state",
                            entity_id=str(z.id), field="habitat_quality",
                            max_depth=4, max_nodes=60,
                            end_tick=293_000_000)

    def collect(items, acc):
        for c in items:
            acc.add(c["relation"])
            collect(c.get("upstream", []), acc)

    rels: set[str] = set()
    collect(exp["causes"], rels)
    # 灾劫影响 + 正常领域压力 + 状态延续，三类原因并存，不压缩单根因
    assert "AFFECTS" in rels and "CAUSES" in rels and "CONTINUES" in rels
    assert len(exp["causes"]) >= 1


def test_ma20_causal_history_hash_stable(hist300):
    svc = _svc(hist300)
    h1 = svc.causal_history_hash(world_id=W)["hash"]
    h2 = svc.causal_history_hash(world_id=W)["hash"]
    # OPT-B：EXPECTED 取自 committed refrozen metric_audit.json（single source）
    exp = _expected("metric_audit.json")["hash"]["causal_history_hash"]
    assert h1 == h2 == exp


def test_ma21_row_order_independent_hash(hist300):
    svc = _svc(hist300)
    with hist300["env"]["factory"]() as s:
        rows = s.execute(select(CausalHistoryLink).where(
            CausalHistoryLink.world_id == W)).scalars().all()
    rnd = random.Random(42)
    shuffled = list(rows)
    rnd.shuffle(shuffled)
    assert canonical_causal_history_hash(W, shuffled) \
        == svc.causal_history_hash(world_id=W)["hash"]


# ---------------------------------------------------------------- MA22-MA27
def test_ma22_world_state_hash_unchanged(hist300):
    summary = json.loads((M3A_BASELINE / "summary.json").read_text(
        encoding="utf-8"))
    assert hist300["rep"].final_state_hash \
        == summary["final_world_state_hash"]


def test_ma23_event_stream_hash_unchanged(hist300):
    summary = json.loads((M3A_BASELINE / "summary.json").read_text(
        encoding="utf-8"))
    assert hist300["rep"].final_event_stream_hash \
        == summary["final_event_stream_hash"]


def test_ma24_m3a_baseline_unchanged():
    assert M3A_BASELINE.exists()
    for name in ("summary.json", "episode_index.json", "schedule.json",
                 "profiles.json", "decisions.json", "final_state.json"):
        assert (M3A_BASELINE / name).exists(), name


def test_ma25_m2_baselines_unchanged():
    for name in ("m2a_population_miniworld_120y_v1.json",
                 "m2b_resource_economy_miniworld_120y_v1.json",
                 "m2c_ecology_miniworld_120y_v1.json",
                 "m2d_social_miniworld_120y_v2.json"):
        assert (REPO / "tests/baselines" / name).exists(), name
    for seed in ("seed_001.json", "seed_005.json", "summary.json"):
        assert (REPO / "tests/baselines/m2_integrated_1000y_v1" / seed) \
            .exists(), seed
    m = json.loads(M2_MANIFEST.read_text(encoding="utf-8"))
    assert m["tribulation_slot"] == "NOT_REGISTERED"
    assert m["world_state_hash_schema_version"] == 5


def test_ma26_formal_db_remains_empty(formal_db_guard):
    import os
    import sqlite3
    path = os.environ.get("BLR_FORMAL_DB_PATH", "")
    if not path or formal_db_guard is None:
        pytest.skip("BLR_FORMAL_DB_PATH 未设置")
    after = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    assert after == formal_db_guard
    conn = formal_readonly_connect(path)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM world_runtime").fetchone()[0] == 0, \
            "canonical NOT_ACTIVATED = world_runtime 0 行"
        
        for t in ("causal_history_links", "entity_history_index",
                  "history_state_changes", "history_episode_index",
                  "history_index_state", "tribulation_episodes",
                  "world_events"):
            assert conn.execute(
                f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] == 0, t
    finally:
        conn.close()


def test_ma27_world_seed_unchanged():
    manifest = SEED_DIR / "MANIFEST.sha256.txt"
    for line in manifest.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        h, name = line.split("  ", 1)
        assert hashlib.sha256((SEED_DIR / name).read_bytes()).hexdigest() == h


# ---------------------------------------------------------------- MA28-MA29
def test_ma28_metric_audit_baseline_artifacts(hist300, perf300):
    svc = _svc(hist300)
    ep = episode_state_audit(hist300["env"]["factory"], world_id=W)
    ec = entity_cardinality_audit(hist300["env"]["factory"], world_id=W)
    rd = relation_density_audit(hist300["env"]["factory"], world_id=W)
    dup = duplicate_semantic_links_audit(hist300["env"]["factory"],
                                         world_id=W)
    tr = transitive_materialization_audit(hist300["env"]["factory"],
                                          world_id=W)
    gp = growth_projection(hist300["env"]["factory"], world_id=W)
    qp = query_plan_audit(hist300["env"]["factory"], world_id=W)
    dg = db_growth_audit(
        history_db_path=Path(hist300["env"]["db_path"]),
        schema_only_db_path=Path(hist300["schema_only_path"]))
    hash_info = svc.causal_history_hash(world_id=W)
    metric_audit = {
        "episode_summary": ep["summary"],
        "mutually_exclusive_states": ep["mutually_exclusive_states"],
        "incomplete_predicate": ep["incomplete_predicate"],
        "m3a_completed_predicate": ep["m3a_completed_predicate"],
        "metric_rename": {
            "OLD_METRIC_NAME": "entities_with_history",
            "NEW_METRIC_NAME": "entity_history_index_rows",
            "NEW_DISTINCT_METRIC": "distinct_entities_with_history",
            "REASON": "old value was raw entity_history_index row count "
                      "(64,858 rows, one per (entity, link) pair), not "
                      "distinct domain entities (134)"},
        "hash": {"causal_history_hash": hash_info["hash"],
                 "world_state_hash": hist300["rep"].final_state_hash,
                 "event_stream_hash":
                     hist300["rep"].final_event_stream_hash},
        "conflict_resolution_30_29_2": {
            "scheduled": 30, "completed_by_stage_new_normal": 29,
            "terminal_completed": 28,
            "incomplete_status_not_completed": 2,
            "explanation": "M3a counted current_stage==NEW_NORMAL (29 = 28 "
                           "COMPLETED + 1 NEW_NORMAL_PENDING@y290); M3b "
                           "counted status!=COMPLETED (2 = NEW_NORMAL_"
                           "PENDING@y290 + PRECURSOR@y300). Both predicates "
                           "valid; mutually exclusive split: 28+1+1=30."},
    }
    query_performance = {
        "entity_history": perf300.get("entity_history"),
        "episode_history": perf300.get("episode_history"),
        "explain_state": perf300.get("explain_state"),
        "timeline": perf300.get("timeline"),
    }
    growth = {
        "growth_projection": gp, "db_growth": dg,
        "duplicate_semantic_links": dup,
        "transitive_materialization": tr,
        "query_plan_audit": qp,
    }
    artifacts = {
        "metric_audit.json": metric_audit,
        "episode_state_audit.json": ep,
        "entity_cardinality_audit.json": ec,
        "relation_density_audit.json": rd,
        "growth_projection.json": growth,
        "query_performance.json": query_performance,
    }
    # candidate 与 committed golden 逐文件比较（telemetry 剥离）；
    # 普通 pytest 只读 golden。
    if update_mode_enabled():
        # M6D.3 OPT-1（TEST_INFRA_UPDATE_MODE_REPAIR）：update mode 写入当前 artifact
        # 即完成，不先要求等于旧 baseline；normal mode 行为逐字不变。
        for name, artifact in artifacts.items():
            dump_artifact(artifact, BASELINE_DIR / name)
        return
    for name in ("metric_audit.json", "episode_state_audit.json",
                 "entity_cardinality_audit.json", "relation_density_audit.json",
                 "growth_projection.json"):
        golden = load_artifact(BASELINE_DIR / name)
        assert_deterministic_equal(
            golden, artifacts[name],
            label=f"m3b_causal_history_300y_v1/{name}",
            golden_path=BASELINE_DIR / name)
    # query_performance.json 是纯机器计时 telemetry：只比较结构（键集合）
    qp_golden = load_artifact(BASELINE_DIR / "query_performance.json")
    assert set(query_performance) == set(qp_golden)
    assert dup["duplicate_semantic_links"] == 0
    assert tr["candidate_transitive_materializations"] == 0
    assert qp["FULL_TABLE_SCAN_RISK"] == []
    assert ep["mutex_sum_equals_indexed"] is True


def test_ma29_db_growth_measured(hist300):
    dg = db_growth_audit(
        history_db_path=Path(hist300["env"]["db_path"]),
        schema_only_db_path=Path(hist300["schema_only_path"]))
    assert dg["history_db_bytes_added_300y"] > 0
    assert dg["history_mb_per_100y"] > 0
    assert dg["projection_mode"] == "LINEAR_PROJECTION_ONLY"

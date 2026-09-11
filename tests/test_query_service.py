# -*- coding: utf-8 -*-
"""M5 Query Service 测试：M5Q01-14 / M5Q25-27 / M5Q31 / M5Q40-42 / M5Q45-47。

synthetic 激活世界 = M3LONG fixture；formal = NOT_ACTIVATED 世界。
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from tests.conftest import PROJECT_ROOT
from tests.test_m3_integrated_long import (_fresh_m3, _m3_run,
                                           M3_LONG_WORLD_IDS)
from tests.test_scheduler_lifecycle import fresh_scheduler_world

from XiaoguangBlessedLandRuntime.services.query import (ReadOnlyGuard,
                                                        WorldQueryService)

REPO = PROJECT_ROOT
WORLD = M3_LONG_WORLD_IDS[0]
QDIR = REPO / "services" / "query"


def _formal_svc(tmp_path) -> WorldQueryService:
    env = fresh_scheduler_world(tmp_path, 1, activated=False)
    return WorldQueryService(session_factory=env["factory"],
                             world_id=env["world_id"]), env


def _active_svc(tmp_path, i: int, years: int = 30):
    env = _fresh_m3(tmp_path, i, WORLD)
    _m3_run(env, years=years)
    return WorldQueryService(session_factory=env["factory"],
                             world_id=WORLD), env


# ---------------------------------------------------------------- M5Q01-05
def test_m5q01_runtime_status_formal_and_active(tmp_path):
    svc, env = _formal_svc(tmp_path)
    r = svc.get_runtime_status()
    assert r["status"] == "NOT_ACTIVATED"
    assert r["reason"] == "WORLD_NOT_ACTIVATED"
    assert r["current_population"] == "UNKNOWN"
    assert r["current_blessed_tick"] is None
    svc2, env2 = _active_svc(tmp_path, 2, years=30)
    r2 = svc2.get_runtime_status()
    assert r2["status"] == "ACTIVATED"
    assert r2["current_population"] > 0


def test_m5q02_not_activated_population_unknown_not_zero(tmp_path):
    svc, _ = _formal_svc(tmp_path)
    r = svc.get_population_summary()
    assert r["status"] == "NOT_ACTIVATED"
    assert r["summary"] == "UNKNOWN"  # 不是 0


def test_m5q03_null_tick_not_year_zero(tmp_path):
    svc, _ = _formal_svc(tmp_path)
    t = svc.get_world_time()
    assert t["current_blessed_tick"] is None
    assert t["display"] == "NOT_STARTED"  # 不是 Year 0


def test_m5q04_settlement_unknown_before_activation(tmp_path):
    svc, _ = _formal_svc(tmp_path)
    assert svc.get_settlement_summary()["summary"] == "UNKNOWN"
    assert svc.get_resource_summary()["summary"] == "UNKNOWN"


def test_m5q05_no_synthetic_history_leak(tmp_path):
    svc, _ = _formal_svc(tmp_path)
    r = svc.get_history_timeline()
    assert r["status"] == "NOT_ACTIVATED"
    assert r["summary"] == "NONE_OFFICIAL"
    assert r["timeline"] == []
    r2 = svc.get_recent_tribulations()
    assert r2["summary"] == "NONE_OFFICIAL"


# ---------------------------------------------------------------- M5Q07-14
def test_m5q07_population_query_activated(tmp_path):
    svc, _ = _active_svc(tmp_path, 7, years=30)
    r = svc.get_population_summary()
    assert r["status"] == "ACTIVATED"
    assert r["summary"]["total_population"] > 0
    assert set(r["summary"]["species"])


def test_m5q08_resource_query_activated(tmp_path):
    svc, _ = _active_svc(tmp_path, 8, years=30)
    r = svc.get_resource_summary()
    assert r["status"] == "ACTIVATED"
    assert r["summary"]["resource_nodes"] >= 1
    assert r["summary"]["total_remaining_reserve"] >= 0


def test_m5q09_ecology_query_activated(tmp_path):
    svc, _ = _active_svc(tmp_path, 9, years=30)
    r = svc.get_ecology_summary()
    assert r["status"] == "ACTIVATED"
    assert r["summary"]["zones"] >= 1
    assert 0 <= r["summary"]["avg_habitat_quality"] <= 1_000_000


def test_m5q10_social_query_activated(tmp_path):
    svc, _ = _active_svc(tmp_path, 10, years=30)
    r = svc.get_social_summary()
    assert r["status"] == "ACTIVATED"
    assert r["summary"]["households"] >= 1


def test_m5q11_tribulation_query_activated(tmp_path):
    svc, _ = _active_svc(tmp_path, 11, years=30)
    recent = svc.get_recent_tribulations()
    assert recent["status"] == "ACTIVATED"
    assert len(recent["recent"]) >= 1
    active = svc.get_active_tribulations()
    assert "active" in active


def test_m5q12_history_timeline_activated(tmp_path):
    svc, _ = _active_svc(tmp_path, 12, years=30)
    r = svc.get_history_timeline()
    assert r["status"] == "ACTIVATED"
    assert len(r["timeline"]) >= 1


def test_m5q13_explain_state_activated(tmp_path):
    svc, env = _active_svc(tmp_path, 13, years=30)
    from sqlalchemy import select
    from XiaoguangBlessedLandRuntime.database.models_world import EcologyState
    with env["factory"]() as s:
        z = s.execute(select(EcologyState)).scalars().first()
    r = svc.explain_state(entity_type="ecology_state", entity_id=str(z.id),
                          field="habitat_quality")
    assert r["status"] == "ACTIVATED"
    assert r["explanation"] is not None


def test_m5q14_changes_between_ticks_activated(tmp_path):
    svc, _ = _active_svc(tmp_path, 14, years=30)
    r = svc.get_changes_between_ticks(start_tick=0, end_tick=30_000_000)
    assert r["status"] == "ACTIVATED"
    assert "meaningful_classes" in r["changes"]
    assert "TRIBULATION_LIFECYCLE" in r["changes"]["meaningful_classes"]


# ---------------------------------------------------------------- M5Q25-27
def test_m5q25_unknown_preserved(tmp_path):
    svc, _ = _formal_svc(tmp_path)
    r = svc.explain_state(entity_type="ecology_state", entity_id="x",
                          field="habitat_quality")
    assert r["status"] == "NOT_ACTIVATED"
    assert r["summary"] == "UNKNOWN"  # 不自动补数字


def test_m5q26_provenance_preserved(tmp_path):
    svc, _ = _active_svc(tmp_path, 26, years=30)
    r = svc.get_population_summary()
    f = r["facts"][0]
    assert f.authority.value == "AUTHORITATIVE"
    assert f.source_table == "population_groups"
    assert f.as_of_tick is None or isinstance(f.as_of_tick, int)


def test_m5q27_query_zero_mutation(tmp_path):
    svc, env = _active_svc(tmp_path, 27, years=30)
    before = svc._fingerprint()
    with ReadOnlyGuard(svc):
        svc.get_world_snapshot()
        svc.get_history_timeline()
        svc.get_recent_tribulations()
        svc.get_changes_between_ticks(start_tick=0, end_tick=30_000_000)
        svc.explain_state(entity_type="resource_nodes", entity_id="1",
                          field="remaining_reserve")
    assert svc._fingerprint() == before


# ---------------------------------------------------------------- M5Q31
def test_m5q31_runtime_unavailable_fail_closed(tmp_path):
    env = fresh_scheduler_world(tmp_path, 31, activated=False)
    svc = WorldQueryService(
        session_factory=env["factory"], world_id=env["world_id"],
        scheduler_status_provider=lambda: {"scheduler_state": "FAILED"})
    r = svc.get_runtime_status()
    assert r["status"] == "RUNTIME_UNAVAILABLE"
    assert r["reason"] == "SCHEDULER_FAILED"


# ---------------------------------------------------------------- M5Q40-44
def test_m5q40_formal_seed_untouched(tmp_path):
    _, env = _formal_svc(tmp_path)
    with env["factory"]() as s:
        assert s.execute(text(
            "SELECT world_seed_version FROM world_runtime")).scalar() is None


def test_m5q41_formal_tick_remains_null_after_queries(tmp_path):
    svc, env = _formal_svc(tmp_path)
    for _ in range(5):
        svc.get_world_snapshot()
        svc.get_history_timeline()
    with env["factory"]() as s:
        assert s.execute(text(
            "SELECT current_blessed_tick FROM world_runtime")).scalar() is None
        assert s.execute(text(
            "SELECT COUNT(*) FROM world_events")).scalar() == 0


def test_m5q42_formal_events_remain_zero(tmp_path):
    svc, env = _formal_svc(tmp_path)
    svc.get_world_snapshot()
    with env["factory"]() as s:
        assert s.execute(text(
            "SELECT COUNT(*) FROM world_events")).scalar() == 0
        assert s.execute(text(
            "SELECT COUNT(*) FROM simulation_run")).scalar() == 0


def test_m5q43_runtime_query_llm_zero():
    for py in QDIR.rglob("*.py"):
        src = py.read_text(encoding="utf-8")
        # 只扫描真实调用面（docstring 中 LLM 边界说明合法，不算调用）
        for token in ("openai", "anthropic", "import requests",
                      "import httpx", "chat.completions",
                      "llm_client"):
            assert token not in src.lower(), (py, token)


def test_m5q44_runtime_query_network_zero():
    for py in QDIR.rglob("*.py"):
        src = py.read_text(encoding="utf-8")
        for token in ("urllib.request", "socket", "aiohttp"):
            assert token not in src, (py, token)


# ---------------------------------------------------------------- M5Q45-47
def test_m5q45_m2_baselines_unchanged():
    # 只读校验：M2 golden 文件存在且字段与冻结一致（回归套件负责逐字节）
    from tests.golden_baseline import load_artifact
    m = load_artifact(REPO / "tests/baselines/"
                      "m2d_social_miniworld_120y_v2.json")
    assert m["world_state_hash_schema_version"] == 5
    assert m["final_world_state_hash"].startswith("7cd769e0")


def test_m5q46_m3_baselines_unchanged():
    from tests.golden_baseline import load_artifact
    m = load_artifact(REPO / "tests/baselines/"
                      "m3a_tribulation_synthetic_300y_v1/summary.json")
    assert m["world_state_hash_schema_version"] == 6
    assert m["final_world_state_hash"].startswith("0fc6ece0")
    m3b = load_artifact(REPO / "tests/baselines/"
                        "m3b_causal_history_300y_v1/summary.json")
    assert m3b["causal_history_hash"].startswith("c1293e59")


def test_m5q47_m4_scheduler_golden_unchanged(tmp_path):
    """M4 契约保持：formal 世界查询后 scheduler 仍 DORMANT、零租约、
    零 mutation（查询绝不启动/续约 scheduler 或抢 writer）。"""
    svc, env = _formal_svc(tmp_path)
    svc.get_world_snapshot()
    svc.get_history_timeline()
    with env["factory"]() as s:
        assert s.execute(text(
            "SELECT COUNT(*) FROM runtime_lock")).scalar() == 0
        assert s.execute(text(
            "SELECT COUNT(*) FROM simulation_run")).scalar() == 0
        assert s.execute(text(
            "SELECT current_blessed_tick FROM world_runtime")).scalar() is None

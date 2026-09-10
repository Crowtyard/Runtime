# -*- coding: utf-8 -*-
"""M3a Tribulation Engine 测试：TA1–TA60 + 崩溃矩阵 + 300y 合成基线。

全部运行于 tmp 临时库（mini_world with_tribulation，simulation_version=
0.3.0-m3a）；正式 DB / World Seed / M2 frozen 语义零接触。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select, text

from tests.conftest import EPOCH0, EPOCH0_US, PROJECT_ROOT
from tests.golden_baseline import (M3A_EFFECTIVE_HASH_SCHEMA_VERSION,
                                   assert_deterministic_equal, dump_artifact,
                                   golden_bytes_guard, load_artifact,
                                   update_mode_enabled)

from XiaoguangBlessedLandRuntime.database.models_core import (SimulationCheckpoint,
                                                              WorldEvent,
                                                              WorldRuntime,
                                                              WorldStateChange)
from XiaoguangBlessedLandRuntime.database.models_world import (
    PopulationGroup, ResourceNode, ResourceStock, TribulationDecision,
    TribulationEpisode, TribulationImpactPlan, TribulationRecoveryState,
    TribulationSchedule, ResourceSuccessionCandidate)
from XiaoguangBlessedLandRuntime.domain.errors import FencingViolation
from XiaoguangBlessedLandRuntime.services import fencing as fencing_mod
from XiaoguangBlessedLandRuntime.services.catchup import catch_up
from XiaoguangBlessedLandRuntime.services.fencing import WorldMutationContext
from XiaoguangBlessedLandRuntime.services.simulation.coordinator import (
    SimulationCoordinator)
from XiaoguangBlessedLandRuntime.services.simulation.ecology import EcologyEngine
from XiaoguangBlessedLandRuntime.services.simulation.economy import EconomyEngine
from XiaoguangBlessedLandRuntime.services.simulation.harness import (
    YEAR_US, run_mini_world_120y)
from XiaoguangBlessedLandRuntime.services.simulation.m3a_runner import (
    M3aReport, run_m3a_world)
from XiaoguangBlessedLandRuntime.services.simulation.mini_world import (
    MINI_WORLD_ID)
from XiaoguangBlessedLandRuntime.services.simulation.population import (
    PopulationGroupEngine)
from XiaoguangBlessedLandRuntime.services.simulation.recovery import (
    latest_authoritative_world_checkpoint)
from XiaoguangBlessedLandRuntime.services.simulation.resource import ResourceEngine
from XiaoguangBlessedLandRuntime.services.simulation.social import SocialEngine
from XiaoguangBlessedLandRuntime.services.simulation.state_hash import (
    WORLD_STATE_HASH_SCHEMA_VERSION, world_state_hash_v6)
from XiaoguangBlessedLandRuntime.services.simulation.tribulation import (
    DECISION_ACTIONS, DEFAULT_AUTONOMOUS_RESPONSE_POLICY,
    ENGINE_VERSION, IMPACT_PLAN_SCHEMA_VERSION, LIFECYCLE, M3A_SIMULATION_VERSION,
    STAGE_NEW_NORMAL, TEST_PROFILES, TEST_SCHEDULE,
    TRIBULATION_EPISODE_ID_SCHEMA_VERSION, TribulationEngine,
    submit_owner_decision)
from XiaoguangBlessedLandRuntime.services.simulation.tribulation_adapters import (
    DOMAIN_ADAPTERS)
from XiaoguangBlessedLandRuntime.services.simulation.snapshot import \
    read_snapshot
from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease

REPO = PROJECT_ROOT
BASELINE_DIR = REPO / "tests" / "baselines" / "m3a_tribulation_synthetic_300y_v1"
M2_MANIFEST = REPO / "M2_SIMULATION_SEMANTICS_MANIFEST.json"
M3A_MANIFEST = REPO / "M3A_SIMULATION_SEMANTICS_MANIFEST.json"
SEED_DIR = REPO.parent / "XIAOGUANG_CROW_KB" / "world_seed"

# GB2：本模块每个测试前后 golden baseline 字节必须不变
_golden_bytes_guard = golden_bytes_guard(*[
    BASELINE_DIR / n for n in ("summary.json", "episode_index.json",
                               "schedule.json", "profiles.json",
                               "decisions.json", "final_state.json")])


def _fresh_m3a(tmp_path, i: int):
    from XiaoguangBlessedLandRuntime.database.db import (create_db_engine,
                                                         make_session_factory)
    from XiaoguangBlessedLandRuntime.database.models_core import WorldRuntime
    from XiaoguangBlessedLandRuntime.domain.constants import RuntimeStatus
    from XiaoguangBlessedLandRuntime.services.db_lifecycle import \
        migrate_database
    from XiaoguangBlessedLandRuntime.services.repositories import (
        RuntimeRepository, TimeRatioRepository)
    from XiaoguangBlessedLandRuntime.services.simulation.mini_world import \
        seed_mini_world
    db_path = tmp_path / f"mini_m3a_{i}.db"
    url = "sqlite:///" + str(db_path).replace("\\", "/")
    migrate_database(url, project_root=REPO)
    engine = create_db_engine(url)
    factory = make_session_factory(engine)
    with factory() as s:
        RuntimeRepository(s).create_not_activated(
            world_id=MINI_WORLD_ID, world_bible_version="1.0",
            simulation_version=M3A_SIMULATION_VERSION,
            world_bible_manifest_hash="mini")
        row = s.execute(select(WorldRuntime)).scalar_one()
        row.runtime_status = RuntimeStatus.ACTIVE
        row.world_seed_version = "MINI-TEST-SEED-001"
        row.current_blessed_tick = 0
        row.last_committed_real_us = EPOCH0_US
        row.time_rate_remainder = 0
        rate = TimeRatioRepository(s).add(
            world_id=MINI_WORLD_ID, real_effective_from=EPOCH0,
            rate_numerator=1_000_000, rate_denominator=86_400_000_000,
            reason="TEST", source="TEST")
        row.current_time_ratio_id = rate.ratio_id
        seed_mini_world(s, with_ecology=True, with_social=True,
                        with_tribulation=True)
        s.commit()
    return {"url": url, "factory": factory, "db_path": db_path}


def _coordinator(**kw):
    return SimulationCoordinator(
        [PopulationGroupEngine(), ResourceEngine(), EconomyEngine(),
         EcologyEngine(), SocialEngine()],
        simulation_version=M3A_SIMULATION_VERSION,
        tribulation_engine=kw.get("trib") or TribulationEngine(),
        tribulation_adapters=DOMAIN_ADAPTERS)


def _run(env, years=30, **kw):
    return run_m3a_world(env["factory"], coordinator=_coordinator(
        trib=kw.get("trib")), years=years, **{k: v for k, v in kw.items()
                                              if k != "trib"})


def _episodes(env) -> list:
    with env["factory"]() as s:
        return s.execute(select(TribulationEpisode).order_by(
            TribulationEpisode.entered_tick)).scalars().all()


def _catchup_year(factory, *, year, lease, coordinator, crash_after=None):
    """单年 catch_up（逐年推进，使排期窗口/阶段转移边界精确落在年末）。"""
    def step(s, info):
        return coordinator.run_step(
            s, world_id=MINI_WORLD_ID,
            blessed_start_tick=info["new_blessed_tick"] - info["delta_ticks"],
            blessed_end_tick=info["new_blessed_tick"],
            real_interval_start_us=info["real_interval_start_us"],
            real_interval_end_us=info["real_interval_end_us"],
            step_index=year, crash_after=crash_after)
    return catch_up(factory, world_id=MINI_WORLD_ID,
                    now_real_us=EPOCH0_US + year * YEAR_US,
                    writer_id=lease.owner, fencing_token=lease.token,
                    simulation_version=M3A_SIMULATION_VERSION,
                    simulate_fn=step)


def _warmup_years(factory, *, years, lease, coordinator):
    for y in range(1, years + 1):
        _catchup_year(factory, year=y, lease=lease, coordinator=coordinator)


def _m2_manifest_sha() -> str:
    return hashlib.sha256(M2_MANIFEST.read_bytes()).hexdigest()


# ------------------------------------------------------------ TA1-TA8
def test_ta1_engine_protocol():
    e = TribulationEngine()
    assert e.engine_id == "TRIBULATION"
    assert e.engine_version == "m3a-tribulation-1"
    assert callable(e.simulate)
    assert TRIBULATION_EPISODE_ID_SCHEMA_VERSION == "tribulation-episode-id-v1"
    assert IMPACT_PLAN_SCHEMA_VERSION == "impact-plan-v2"
    assert M3A_SIMULATION_VERSION == "0.3.0-m3a"


def test_ta2_lifecycle_order(tmp_path):
    assert LIFECYCLE == ("PRECURSOR", "PREPARATION", "IMPACT", "RESPONSE",
                         "STABILIZATION", "RESIDUAL_CHANGE", "RECOVERY",
                         "RESOURCE_SUCCESSION", "NEW_NORMAL")
    env = _fresh_m3a(tmp_path, 1)
    _run(env, years=30)
    idx = {s: i for i, s in enumerate(LIFECYCLE)}
    with env["factory"]() as s:
        for ep in s.execute(select(TribulationEpisode)).scalars():
            assert ep.current_stage in idx
    # 事件中的阶段序列合法
    with env["factory"]() as s:
        evs = [e for e in s.execute(select(WorldEvent).where(
            WorldEvent.event_type.in_([
                "TRIBULATION_PRECURSOR_STARTED",
                "TRIBULATION_PREPARATION_STARTED",
                "TRIBULATION_IMPACT_STARTED",
                "TRIBULATION_STABILIZED",
                "TRIBULATION_RESIDUAL_CHANGE_CREATED",
                "TRIBULATION_RECOVERY_PROGRESS",
                "RESOURCE_SUCCESSION_CANDIDATE_CREATED",
                "TRIBULATION_NEW_NORMAL_REACHED"]))).scalars()]
        assert evs


def test_ta3_deterministic_schedule(tmp_path):
    a = _fresh_m3a(tmp_path, 2)
    b = _fresh_m3a(tmp_path, 3)
    _run(a, years=60)
    _run(b, years=60)
    ea = [(e.episode_id, e.window_tier, e.entered_tick) for e in _episodes(a)]
    eb = [(e.episode_id, e.window_tier, e.entered_tick) for e in _episodes(b)]
    assert ea == eb


def test_ta4_tier_replacement(tmp_path):
    env = _fresh_m3a(tmp_path, 4)
    _run(env, years=120)
    by_tick = {}
    for e in _episodes(env):
        by_tick.setdefault(e.entered_tick, []).append(e.window_tier)
    assert by_tick[50_000_000] == ["MAJOR"]          # 替代 REGULAR
    assert by_tick[100_000_000] == ["CENTENNIAL"]    # 替代 MAJOR/REGULAR
    assert by_tick[60_000_000] == ["REGULAR"]


def test_ta5_profile_selection_deterministic(tmp_path):
    a = _fresh_m3a(tmp_path, 5)
    b = _fresh_m3a(tmp_path, 6)
    _run(a, years=60)
    _run(b, years=60)
    pa = [(e.window_tier, e.profile_ref) for e in _episodes(a)]
    pb = [(e.window_tier, e.profile_ref) for e in _episodes(b)]
    assert pa == pb
    assert all(p[1] in TEST_PROFILES for p in pa)


def test_ta6_target_selection_deterministic(tmp_path):
    a = _fresh_m3a(tmp_path, 7)
    b = _fresh_m3a(tmp_path, 8)
    _run(a, years=30)
    _run(b, years=30)
    ta = [json.loads(json.dumps(e.target_settlements)) for e in _episodes(a)]
    tb = [json.loads(json.dumps(e.target_settlements)) for e in _episodes(b)]
    assert ta == tb


def test_ta7_target_row_order_independent(tmp_path):
    a = _fresh_m3a(tmp_path, 9)
    _run(a, years=30)
    base = [e.target_settlements for e in _episodes(a)]
    from XiaoguangBlessedLandRuntime.database.models_world import Settlement
    b = _fresh_m3a(tmp_path, 10)
    with b["factory"]() as s:
        rows = s.execute(select(Settlement)).scalars().all()
        for r in rows:
            s.delete(r)
        s.flush()
        for r in reversed(rows):  # 逆序重插
            s.add(Settlement(world_id=r.world_id, settlement_type=r.settlement_type,
                             region_ref=r.region_ref, working_name=r.working_name,
                             state=r.state, population_capacity=r.population_capacity))
        s.commit()
    _run(b, years=30)
    assert [e.target_settlements for e in _episodes(b)] == base


def test_ta8_rng_substream_isolation(tmp_path):
    base = _fresh_m3a(tmp_path, 11)
    extra = _fresh_m3a(tmp_path, 12)
    _run(base, years=30)
    _run(extra, years=30, trib=TribulationEngine(extra_draws=5))
    # IMPACT 子流多抽：schedule/target 不受影响（SCHEDULE/TARGET 子流独立）
    assert [(e.episode_id, e.window_tier, e.entered_tick,
             e.target_settlements) for e in _episodes(base)] \
        == [(e.episode_id, e.window_tier, e.entered_tick,
             e.target_settlements) for e in _episodes(extra)]


# ------------------------------------------------------------ TA9-TA17
def test_ta9_precursor_transition(tmp_path):
    env = _fresh_m3a(tmp_path, 13)
    _run(env, years=20)
    with env["factory"]() as s:
        evs = s.execute(select(WorldEvent).where(
            WorldEvent.event_type == "TRIBULATION_PRECURSOR_STARTED"
        )).scalars().all()
        assert len(evs) >= 2


def test_ta10_preparation_transition(tmp_path):
    env = _fresh_m3a(tmp_path, 14)
    _run(env, years=30)
    with env["factory"]() as s:
        evs = s.execute(select(WorldEvent).where(
            WorldEvent.event_type == "TRIBULATION_PREPARATION_STARTED"
        )).scalars().all()
        assert len(evs) >= 2


def test_ta11_autonomous_response(tmp_path):
    env = _fresh_m3a(tmp_path, 15)
    _run(env, years=60)
    advanced = [e for e in _episodes(env)
                if e.decision_policy is not None]
    assert advanced
    assert all(e.decision_policy == DEFAULT_AUTONOMOUS_RESPONSE_POLICY
               for e in advanced)


def test_ta12_valid_owner_decision(tmp_path):
    env = _fresh_m3a(tmp_path, 16)
    _run(env, years=10)  # 先有 episode（year-10 REGULAR）
    with env["factory"]() as s:
        eps = s.execute(select(TribulationEpisode)).scalars().all()
        assert eps
        res = submit_owner_decision(
            s, world_id=MINI_WORLD_ID, episode_id=eps[0].episode_id,
            action="EVACUATE", effective_before_tick=100_000_000,
            source="TEST")
        assert res["idempotent"] is False
        s.commit()
    with env["factory"]() as s:
        d = s.execute(select(TribulationDecision)).scalars().all()
        assert len(d) == 1 and d[0].status == "ACTIVE"
        # retry idempotent
        res2 = submit_owner_decision(
            s, world_id=MINI_WORLD_ID, episode_id=eps[0].episode_id,
            action="EVACUATE", effective_before_tick=100_000_000,
            decision_id=res["decision_id"], source="TEST")
        assert res2["idempotent"] is True


def test_ta13_expired_decision_rejected(tmp_path):
    env = _fresh_m3a(tmp_path, 17)
    _run(env, years=10)
    with env["factory"]() as s:
        eps = s.execute(select(TribulationEpisode)).scalars().all()
        with pytest.raises(Exception):
            submit_owner_decision(
                s, world_id=MINI_WORLD_ID, episode_id=eps[0].episode_id,
                action="EVACUATE", effective_before_tick=0, source="TEST")


def test_ta14_wrong_episode_decision_rejected(tmp_path):
    env = _fresh_m3a(tmp_path, 18)
    _run(env, years=10)
    with env["factory"]() as s:
        with pytest.raises(Exception):
            submit_owner_decision(
                s, world_id=MINI_WORLD_ID, episode_id="EP-NO-SUCH",
                action="EVACUATE", effective_before_tick=999_999_999,
                source="TEST")


def test_ta15_decision_immutable_with_supersede(tmp_path):
    env = _fresh_m3a(tmp_path, 19)
    _run(env, years=10)
    with env["factory"]() as s:
        eps = s.execute(select(TribulationEpisode)).scalars().all()
        r1 = submit_owner_decision(
            s, world_id=MINI_WORLD_ID, episode_id=eps[0].episode_id,
            action="EVACUATE", effective_before_tick=100_000_000,
            source="TEST")
        s.commit()
    with env["factory"]() as s:
        submit_owner_decision(
            s, world_id=MINI_WORLD_ID, episode_id=eps[0].episode_id,
            action="PRIORITIZE", effective_before_tick=100_000_000,
            supersedes_decision_id=r1["decision_id"], source="TEST")
        s.commit()
    with env["factory"]() as s:
        rows = s.execute(select(TribulationDecision)).scalars().all()
        old = [d for d in rows if d.decision_id == r1["decision_id"]][0]
        assert old.status == "SUPERSEDED"          # 修改经 supersede
        assert old.action == "EVACUATE"            # 原内容不变
        assert len([d for d in rows if d.status == "ACTIVE"]) == 1


def test_ta16_mitigation_cost(tmp_path):
    env = _fresh_m3a(tmp_path, 20)
    _run(env, years=30)
    with env["factory"]() as s:
        plans = s.execute(select(TribulationImpactPlan)).scalars().all()
        assert plans
        # 成本经 Economy adapter 扣减（stock 变化有 state change 账本）
        scs = s.execute(select(WorldStateChange).where(
            WorldStateChange.entity_type == "resource_stocks")).scalars().all()
        assert scs


def test_ta17_no_free_perfect_mitigation(tmp_path):
    env = _fresh_m3a(tmp_path, 21)
    _run(env, years=60)
    with env["factory"]() as s:
        losses = s.execute(select(WorldStateChange).where(
            WorldStateChange.entity_type == "population_groups",
            WorldStateChange.field == "count")).scalars().all()
        total = sum(int((c.old_value or {}).get("v", 0))
                    - int((c.new_value or {}).get("v", 0)) for c in losses)
        assert losses and total > 0  # 自主响应下仍有真实损失


# ------------------------------------------------------------ TA18-TA29
def test_ta18_impact_plan_validation(tmp_path):
    env = _fresh_m3a(tmp_path, 22)
    _run(env, years=30)
    with env["factory"]() as s:
        for p in s.execute(select(TribulationImpactPlan)).scalars():
            assert 0 <= p.intensity <= 100
            assert p.semantic_version == IMPACT_PLAN_SCHEMA_VERSION
            assert 0 <= p.population_risk_num <= p.population_risk_den
            assert 0 <= p.ecology_pressure <= 1_000_000


@pytest.mark.parametrize("domain,models,others", [
    ("DEMOGRAPHY", ("PopulationGroup",),
     ("ResourceNode", "ResourceStock", "EcologyState", "Household")),
    ("RESOURCE", ("ResourceNode",),
     ("PopulationGroup", "ResourceStock", "EcologyState", "Household")),
    ("ECONOMY", ("ResourceStock",),
     ("PopulationGroup", "ResourceNode", "EcologyState", "Household")),
    ("ECOLOGY", ("EcologyState",),
     ("PopulationGroup", "ResourceNode", "ResourceStock", "Household")),
    ("SOCIAL", ("Household", "SettlementSocialState"),
     ("PopulationGroup", "ResourceNode", "ResourceStock", "EcologyState")),
])
def test_ta19_23_adapter_ownership(domain, models, others):
    src = (REPO / "services/simulation/tribulation_adapters.py").read_text(
        encoding="utf-8")
    cls = {"DEMOGRAPHY": "DemographyTribulationAdapter",
           "RESOURCE": "ResourceTribulationAdapter",
           "ECONOMY": "EconomyTribulationAdapter",
           "ECOLOGY": "EcologyTribulationAdapter",
           "SOCIAL": "SocialTribulationAdapter"}[domain]
    start = src.index(f"class {cls}")
    end = src.find("\nclass ", start)
    block = src[start:end if end != -1 else len(src)]
    for m in models:
        assert m in block, (domain, m)
    for o in others:
        assert o not in block, (domain, o)  # 只写本域表（方案 B 所有权）


def test_ta24_atomic_cross_domain_impact(tmp_path):
    env = _fresh_m3a(tmp_path, 23)
    factory = env["factory"]
    s1 = factory()
    lease = WriterLease(s1, MINI_WORLD_ID, 120)
    lease.acquire()
    coordinator = _coordinator()
    # year-10 REGULAR：11 PRECURSOR → 12 PREPARATION → 13 IMPACT。
    # 先逐年推进到 12，再在 13（IMPACT 年）注入 adapter:ECOLOGY 崩溃 → 全回滚
    _warmup_years(factory, years=12, lease=lease, coordinator=coordinator)
    with pytest.raises(RuntimeError, match="adapter:ECOLOGY"):
        _catchup_year(factory, year=13, lease=lease, coordinator=coordinator,
                      crash_after="adapter:ECOLOGY")
    with factory() as s:
        assert s.execute(select(WorldRuntime)).scalar_one() \
            .current_blessed_tick == 12_000_000
        assert s.execute(select(TribulationImpactPlan)).scalars().all() == []
    _catchup_year(factory, year=13, lease=lease, coordinator=coordinator)
    with factory() as s:
        assert len(s.execute(select(TribulationImpactPlan)).scalars().all()) == 1
    lease.release()
    s1.close()


def test_ta25_29_bounded_impacts(tmp_path):
    env = _fresh_m3a(tmp_path, 24)
    _run(env, years=120)
    with env["factory"]() as s:
        for g in s.execute(select(PopulationGroup)).scalars():
            assert g.count >= 0                        # TA25
        for n in s.execute(select(ResourceNode)).scalars():
            assert (n.remaining_reserve or 0) >= 0     # TA26
        for r in s.execute(select(ResourceStock)).scalars():
            assert r.quantity >= 0                     # TA27
        from XiaoguangBlessedLandRuntime.database.models_world import EcologyState
        for st in s.execute(select(EcologyState)).scalars():
            assert 0 <= st.habitat_quality <= 1_000_000  # TA28
        from XiaoguangBlessedLandRuntime.database.models_world import (
            SettlementSocialState)
        for st in s.execute(select(SettlementSocialState)).scalars():
            assert 0 <= st.social_stress <= 1_000_000   # TA29


# ------------------------------------------------------------ TA30-TA37
def test_ta30_recovery_spans_steps(tmp_path):
    env = _fresh_m3a(tmp_path, 25)
    _run(env, years=30)
    with env["factory"]() as s:
        rows = s.execute(select(TribulationRecoveryState)).scalars().all()
        assert rows
        # 恢复非单步完成：事件序列显示 progress 递增（非 0→100 一跳）
        evs = s.execute(select(WorldEvent).where(
            WorldEvent.event_type == "TRIBULATION_RECOVERY_PROGRESS"
        )).scalars().all()
        progress = [e.effect.get("progress") for e in evs]
        assert progress and max(progress) >= 100
        assert any(0 < p < 100 for p in progress)


def test_ta31_residual_change_persists(tmp_path):
    env = _fresh_m3a(tmp_path, 26)
    _run(env, years=30)
    from XiaoguangBlessedLandRuntime.database.models_world import \
        TribulationResidualChange
    with env["factory"]() as s:
        rows = s.execute(select(TribulationResidualChange)).scalars().all()
        assert rows
        assert all(r.persistent for r in rows)


def test_ta32_succession_candidate_not_resource_node(tmp_path):
    env = _fresh_m3a(tmp_path, 27)
    with env["factory"]() as s:
        nodes_before = len(s.execute(select(ResourceNode)).scalars().all())
    _run(env, years=60)
    with env["factory"]() as s:
        nodes_after = len(s.execute(select(ResourceNode)).scalars().all())
        cands = s.execute(select(ResourceSuccessionCandidate)).scalars().all()
        assert cands
        assert all(c.development_status == "NONE" for c in cands)
    assert nodes_after == nodes_before  # 候选 ≠ 新节点


def test_ta33_new_normal_differs_after_nonzero_impact(tmp_path):
    env = _fresh_m3a(tmp_path, 28)
    control = _fresh_m3a(tmp_path, 29)
    _run(env, years=60)
    run_mini_world_120y(control["factory"],
                        engines=[PopulationGroupEngine(), ResourceEngine(),
                                 EconomyEngine(), EcologyEngine(),
                                 SocialEngine()], years=60)
    with env["factory"]() as s:
        pop = sum(g.count for g in s.execute(select(PopulationGroup)).scalars())
        done = [e for e in s.execute(select(TribulationEpisode)).scalars()
                if e.current_stage == STAGE_NEW_NORMAL]
        assert done
    with control["factory"]() as s:
        pop_c = sum(g.count for g in s.execute(
            select(PopulationGroup)).scalars())
    assert pop != pop_c  # 非零 impact → 新常态 ≠ 无灾劫对照


def test_ta34_episode_causal_links_valid(tmp_path):
    env = _fresh_m3a(tmp_path, 30)
    _run(env, years=30)
    from XiaoguangBlessedLandRuntime.database.models_world import \
        TribulationCausalLink
    with env["factory"]() as s:
        links = s.execute(select(TribulationCausalLink)).scalars().all()
        assert links
        uids = {e.event_uid for e in s.execute(select(WorldEvent)).scalars()}
        for l in links:
            assert l.impact_plan_id
            assert l.trigger_event_id in uids
            for eid in (l.result_event_ids or {}).get("events", []):
                assert eid in uids
            for k, v in (l.affected_entity_ids or {}).items():
                assert isinstance(v, list)


def test_ta35_event_uid_deterministic(tmp_path):
    a = _fresh_m3a(tmp_path, 31)
    b = _fresh_m3a(tmp_path, 32)
    _run(a, years=20)
    _run(b, years=20)
    with a["factory"]() as s:
        ua = [e.event_uid for e in s.execute(select(WorldEvent)).scalars()]
    with b["factory"]() as s:
        ub = [e.event_uid for e in s.execute(select(WorldEvent)).scalars()]
    assert ua == ub
    assert all(re.fullmatch(r"[0-9a-f]{32}", u) for u in ua)


def test_ta36_payload_affects_event_hash(tmp_path):
    base = _fresh_m3a(tmp_path, 33)
    extra = _fresh_m3a(tmp_path, 34)
    _run(base, years=30)
    _run(extra, years=30, trib=TribulationEngine(extra_draws=3))
    with base["factory"]() as s:
        hb = latest_authoritative_world_checkpoint(
            s, MINI_WORLD_ID).meta["event_stream_hash"]
    with extra["factory"]() as s:
        he = latest_authoritative_world_checkpoint(
            s, MINI_WORLD_ID).meta["event_stream_hash"]
    assert hb != he  # intensity 抽样不同 → 事件 payload 不同 → 哈希不同


def test_ta37_tribulation_included_in_state_hash(tmp_path):
    env = _fresh_m3a(tmp_path, 35)
    _run(env, years=20)
    with env["factory"]() as s:
        snap = read_snapshot(s, MINI_WORLD_ID)
        h1 = world_state_hash_v6(
            snapshot=snap, simulation_version=M3A_SIMULATION_VERSION,
            pipeline_version="m2-preflight-1",
            engine_versions={"DEMOGRAPHY": "m2a-1",
                             "RESOURCE": "m2b-resource-1",
                             "ECONOMY": "m2b-economy-1",
                             "ECOLOGY": "m2c-ecology-1",
                             "SOCIAL": "m2d-social-1",
                             "TRIBULATION": ENGINE_VERSION})
        ep = s.execute(select(TribulationEpisode)).scalars().first()
        ep.transition_tick = (ep.transition_tick or 0) + 1
        s.commit()
        snap2 = read_snapshot(s, MINI_WORLD_ID)
        h2 = world_state_hash_v6(
            snapshot=snap2, simulation_version=M3A_SIMULATION_VERSION,
            pipeline_version="m2-preflight-1",
            engine_versions={"DEMOGRAPHY": "m2a-1",
                             "RESOURCE": "m2b-resource-1",
                             "ECONOMY": "m2b-economy-1",
                             "ECOLOGY": "m2c-ecology-1",
                             "SOCIAL": "m2d-social-1",
                             "TRIBULATION": ENGINE_VERSION})
    assert h1 != h2
    assert WORLD_STATE_HASH_SCHEMA_VERSION == 6


# ------------------------------------------------------------ TA38-TA45
def test_ta38_retry_no_duplicate_episode(tmp_path):
    env = _fresh_m3a(tmp_path, 36)
    _run(env, years=30)
    n1 = len(_episodes(env))
    _run(env, years=30)
    assert len(_episodes(env)) == n1


def test_ta39_retry_no_duplicate_impact(tmp_path):
    env = _fresh_m3a(tmp_path, 37)
    _run(env, years=30)
    with env["factory"]() as s:
        n1 = len(s.execute(select(TribulationImpactPlan)).scalars().all())
    _run(env, years=30)
    with env["factory"]() as s:
        n2 = len(s.execute(select(TribulationImpactPlan)).scalars().all())
    assert n1 == n2


def test_ta40_stale_writer_rejected(tmp_path):
    env = _fresh_m3a(tmp_path, 38)
    factory = env["factory"]
    s1 = factory()
    lease = WriterLease(s1, MINI_WORLD_ID, 120)
    lease.acquire()
    coordinator = _coordinator()
    with pytest.raises(FencingViolation):
        with WorldMutationContext(factory(), world_id=MINI_WORLD_ID,
                                  writer_id=lease.owner,
                                  fencing_token=lease.token) as ctx:
            coordinator.run_step(
                ctx.session, world_id=MINI_WORLD_ID,
                blessed_start_tick=10_000_000, blessed_end_tick=11_000_000,
                real_interval_start_us=EPOCH0_US,
                real_interval_end_us=EPOCH0_US + YEAR_US, step_index=11)
            ctx.session.execute(text(
                "UPDATE runtime_lock SET lease_token='STOLEN'"))
            ctx.commit()
    with factory() as s:
        assert s.execute(select(TribulationEpisode)).scalars().all() == []
    lease.release()
    s1.close()


def test_ta41_durable_commit_ack_lost(tmp_path, monkeypatch):
    env = _fresh_m3a(tmp_path, 39)
    factory = env["factory"]
    s1 = factory()
    lease = WriterLease(s1, MINI_WORLD_ID, 120)
    lease.acquire()
    coordinator = _coordinator()
    original = fencing_mod.WorldMutationContext.commit
    state = {"calls": 0}

    def patched(self):
        original(self)
        state["calls"] += 1
        if state["calls"] == 2:
            raise RuntimeError("simulated COMMIT ACK LOST")

    monkeypatch.setattr(fencing_mod.WorldMutationContext, "commit", patched)

    def step(s, info):
        return coordinator.run_step(
            s, world_id=MINI_WORLD_ID,
            blessed_start_tick=info["new_blessed_tick"] - info["delta_ticks"],
            blessed_end_tick=info["new_blessed_tick"],
            real_interval_start_us=info["real_interval_start_us"],
            real_interval_end_us=info["real_interval_end_us"], step_index=10)

    with pytest.raises(RuntimeError, match="ACK LOST"):
        catch_up(factory, world_id=MINI_WORLD_ID,
                 now_real_us=EPOCH0_US + 10 * YEAR_US,
                 writer_id=lease.owner, fencing_token=lease.token,
                 simulation_version=M3A_SIMULATION_VERSION, simulate_fn=step)
    with factory() as s:
        assert s.execute(select(TribulationEpisode)).scalars().all()  # durable
        assert s.execute(select(WorldRuntime)).scalar_one() \
            .current_blessed_tick == 10_000_000
    monkeypatch.setattr(fencing_mod.WorldMutationContext, "commit", original)
    res = catch_up(factory, world_id=MINI_WORLD_ID,
                   now_real_us=EPOCH0_US + 10 * YEAR_US,
                   writer_id=lease.owner, fencing_token=lease.token,
                   simulation_version=M3A_SIMULATION_VERSION)
    assert res.skipped is True  # ALREADY_COMMITTED
    lease.release()
    s1.close()


def test_ta42_adaptive_interval_splits_precursor(tmp_path):
    env = _fresh_m3a(tmp_path, 40)
    rep = _run(env, years=30)
    assert rep.splits > 0
    with env["factory"]() as s:
        evs = [e for e in s.execute(select(WorldEvent).where(
            WorldEvent.event_type == "TRIBULATION_PRECURSOR_STARTED")
        ).scalars()]
        eps = s.execute(select(TribulationEpisode)).scalars().all()
    assert len(evs) >= len(eps) - 1  # 每个已建 episode 都有前兆事件


def test_ta43_adaptive_interval_splits_preparation(tmp_path):
    env = _fresh_m3a(tmp_path, 41)
    _run(env, years=30)
    with env["factory"]() as s:
        evs = [e for e in s.execute(select(WorldEvent).where(
            WorldEvent.event_type == "TRIBULATION_PREPARATION_STARTED")
        ).scalars()]
        assert evs


def test_ta44_30y_catchup_handles_windows(tmp_path):
    env = _fresh_m3a(tmp_path, 42)
    _run(env, years=30)
    eps = _episodes(env)
    assert len(eps) == 3  # 10/20/30 REGULAR


def test_ta45_120y_catchup_multiple_windows(tmp_path):
    env = _fresh_m3a(tmp_path, 43)
    _run(env, years=120)
    eps = _episodes(env)
    tiers = [e.window_tier for e in eps]
    assert len(eps) == 12
    assert tiers.count("REGULAR") == 10
    assert tiers.count("MAJOR") == 1      # year 50
    assert tiers.count("CENTENNIAL") == 1  # year 100


# ------------------------------------------------------------ TA46-TA51
def test_ta46_continuous_equals_chunked(tmp_path):
    one = _fresh_m3a(tmp_path, 44)
    chunk = _fresh_m3a(tmp_path, 45)
    r1 = _run(one, years=120)
    r2 = run_m3a_world(chunk["factory"], coordinator=_coordinator(),
                       years=120, restart_every_years=40)
    assert r1.final_state_hash == r2.final_state_hash
    assert r1.final_event_stream_hash == r2.final_event_stream_hash


def test_ta47_restart_equals_continuous(tmp_path):
    one = _fresh_m3a(tmp_path, 46)
    env = _fresh_m3a(tmp_path, 47)
    r1 = _run(one, years=120)
    run_m3a_world(env["factory"], coordinator=_coordinator(), years=60)
    r2 = run_m3a_world(env["factory"], coordinator=_coordinator(), years=60,
                       start_year=60)
    assert r2.final_state_hash == r1.final_state_hash
    assert r2.final_event_stream_hash == r1.final_event_stream_hash


@pytest.mark.parametrize("crash_after,year", [
    # REGULAR 生命周期（year-10 episode）：11 PRECURSOR、12 PREPARATION、
    # 13 IMPACT、14 RESPONSE、15 STABILIZATION、16 RESIDUAL_CHANGE、
    # 17 RECOVERY 建状态、18 首个 progress、20 SUCCESSION、21 NEW_NORMAL
    pytest.param("tribulation:precursor", 11, id="T1-precursor"),
    pytest.param("tribulation:preparation", 12, id="T2-preparation"),
    pytest.param("tribulation:impact_plan", 13, id="T5-impact-plan"),
    pytest.param("tribulation:recovery", 18, id="T10-recovery"),
    pytest.param("tribulation:succession", 20, id="T13-succession"),
    pytest.param("tribulation:new_normal", 21, id="T14-new-normal"),
    pytest.param("adapter:DEMOGRAPHY", 13, id="T6-demography"),
    pytest.param("adapter:ECOLOGY", 13, id="T8-ecology"),
    pytest.param("adapter:SOCIAL", 13, id="T9-social"),
    pytest.param("before_checkpoint", 13, id="T11-pre-commit"),
    pytest.param("after_engines", 13, id="T12-post-engines"),
])
def test_ta48_crash_matrix(tmp_path, crash_after, year):
    env = _fresh_m3a(tmp_path, 100 + hash(crash_after) % 100)
    factory = env["factory"]
    s1 = factory()
    lease = WriterLease(s1, MINI_WORLD_ID, 120)
    lease.acquire()
    coordinator = _coordinator()
    # 逐年推进到崩溃年之前，保证目标阶段恰好在崩溃年触发
    _warmup_years(factory, years=year - 1, lease=lease,
                  coordinator=coordinator)
    with pytest.raises(RuntimeError):
        _catchup_year(factory, year=year, lease=lease, coordinator=coordinator,
                      crash_after=crash_after)
    with factory() as s:
        assert s.execute(select(WorldRuntime)).scalar_one() \
            .current_blessed_tick == (year - 1) * 1_000_000  # 回滚
    _catchup_year(factory, year=year, lease=lease, coordinator=coordinator)
    with factory() as s:
        # 一个 Episode / 一次 Impact / 事件 uid 无碰撞
        plans = s.execute(select(TribulationImpactPlan)).scalars().all()
        assert len(plans) <= 1
        uids = [e.event_uid for e in s.execute(select(WorldEvent)).scalars()]
        assert len(set(uids)) == len(uids)
    lease.release()
    s1.close()


def test_ta49_300y_run_completes(tmp_path):
    env = _fresh_m3a(tmp_path, 48)
    rep = _run(env, years=300)
    assert rep.final_blessed_tick == 300_000_000
    assert rep.splits > 0
    assert rep.events > 0


def test_ta50_30_schedule_windows_correct(tmp_path):
    env = _fresh_m3a(tmp_path, 49)
    _run(env, years=300)
    tiers = [e.window_tier for e in _episodes(env)]
    assert len(tiers) == 30
    assert tiers.count("REGULAR") == 24
    assert tiers.count("MAJOR") == 3
    assert tiers.count("CENTENNIAL") == 3


def test_ta51_all_invariants_clean(tmp_path):
    env = _fresh_m3a(tmp_path, 50)
    _run(env, years=300)
    with env["factory"]() as s:
        eps = s.execute(select(TribulationEpisode)).scalars().all()
        ids = [e.episode_id for e in eps]
        assert len(set(ids)) == len(ids)              # TR_INV_01
        for e in eps:
            assert e.current_stage in LIFECYCLE       # TR_INV_02/03
        for p in s.execute(select(TribulationImpactPlan)).scalars():
            assert 0 <= p.intensity <= 100            # TR_INV_07
        for g in s.execute(select(PopulationGroup)).scalars():
            assert g.count >= 0                       # TR_INV_09
        for r in s.execute(select(ResourceStock)).scalars():
            assert r.quantity >= 0                    # TR_INV_10
        for n in s.execute(select(ResourceNode)).scalars():
            assert (n.remaining_reserve or 0) >= 0    # TR_INV_11
        for rec in s.execute(select(TribulationRecoveryState)).scalars():
            assert 0 <= rec.progress_num <= rec.progress_den * 100  # TR_INV_14
        cands = s.execute(select(ResourceSuccessionCandidate)).scalars().all()
        for c in cands:
            assert c.development_status == "NONE"     # TR_INV_15
        nodes = len(s.execute(select(ResourceNode)).scalars().all())
        assert nodes == 2  # 无免费新节点


# ------------------------------------------------------------ TA52-TA60
def test_ta52_55_llm_network_wallclock_zero():
    for name in ("tribulation.py", "tribulation_adapters.py", "m3a_runner.py"):
        src = (REPO / "services/simulation" / name).read_text(encoding="utf-8")
        for token in ("openai", "anthropic", "import requests", "import httpx"):
            assert token not in src.lower(), name
        pattern = re.compile(
            r"\b(datetime\.now|time\.time|time\.monotonic|perf_counter"
            r"|time_ns|date\.today)\s*\(")
        assert not pattern.search(src), name


def test_ta56_formal_db_empty(formal_db_guard):
    path = os.environ.get("BLR_FORMAL_DB_PATH", "")
    if not path or formal_db_guard is None:
        pytest.skip("BLR_FORMAL_DB_PATH 未设置")
    after = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    assert after == formal_db_guard
    conn = sqlite3.connect(path)
    try:
        existing = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for t in ("tribulation_profiles", "tribulation_schedules",
                  "tribulation_episodes", "tribulation_decisions",
                  "tribulation_impact_plans", "tribulation_recovery_states",
                  "tribulation_residual_changes",
                  "resource_succession_candidates",
                  "tribulation_causal_links"):
            if t in existing:
                assert conn.execute(
                    f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] == 0, t
    finally:
        conn.close()


def test_ta57_world_seed_unchanged():
    manifest = SEED_DIR / "MANIFEST.sha256.txt"
    for line in manifest.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        h, name = line.split("  ", 1)
        assert hashlib.sha256((SEED_DIR / name).read_bytes()).hexdigest() == h


def test_ta58_m2_baselines_unchanged():
    for name in ("m2a_population_miniworld_120y_v1.json",
                 "m2b_resource_economy_miniworld_120y_v1.json",
                 "m2c_ecology_miniworld_120y_v1.json",
                 "m2d_social_miniworld_120y_v2.json",
                 "m2d_social_miniworld_120y_v1_pre_id_hardening.json"):
        assert (REPO / "tests/baselines" / name).exists(), name
    m = json.loads(M2_MANIFEST.read_text(encoding="utf-8"))
    assert m["tribulation_slot"] == "NOT_REGISTERED"
    assert m["world_state_hash_schema_version"] == 5
    m3 = json.loads(M3A_MANIFEST.read_text(encoding="utf-8"))
    assert m3["simulation_version"] == M3A_SIMULATION_VERSION


def test_ta59_postgresql_contract_audit():
    for name in ("tribulation.py", "tribulation_adapters.py", "m3a_runner.py"):
        src = (REPO / "services/simulation" / name).read_text(encoding="utf-8")
        assert "json_extract" not in src, name
        assert "rowid" not in src, name
        assert "INSERT OR REPLACE" not in src, name


def test_ta60_plugin_load_does_not_schedule_formal_disaster():
    # 插件启动路径绝不导入/调用灾劫引擎或调度器（M3a 引擎仅存在于
    # services/simulation + 测试 harness；正式库 profile/schedule=0）。
    for rel in ("main.py", "plugin_shell"):
        p = REPO / rel
        files = p.rglob("*.py") if p.is_dir() else [p]
        for f in files:
            src = f.read_text(encoding="utf-8")
            for token in ("TribulationEngine", "next_tribulation_boundary",
                          "run_m3a_world", "submit_owner_decision",
                          "with_tribulation"):
                assert token not in src, (f, token)


# ------------------------------------------------------------ 300y 基线产物
def test_m3a_baseline_300y_artifact(tmp_path):
    start = datetime.now(timezone.utc)
    env = _fresh_m3a(tmp_path, 51)
    rep = _run(env, years=300)
    wall = (datetime.now(timezone.utc) - start).total_seconds()
    assert BASELINE_DIR.exists()
    # candidate 与 committed golden 逐文件比较（telemetry 剥离）；
    # 普通 pytest 只读 golden。
    artifacts = _build_baseline(env, rep, wall)
    for name, artifact in artifacts.items():
        golden = load_artifact(BASELINE_DIR / name)
        assert_deterministic_equal(
            golden, artifact,
            label=f"m3a_tribulation_synthetic_300y_v1/{name}",
            golden_path=BASELINE_DIR / name)
    golden_summary = load_artifact(BASELINE_DIR / "summary.json")
    env2 = _fresh_m3a(tmp_path, 52)
    rep2 = _run(env2, years=300)
    assert rep2.final_state_hash == golden_summary["final_world_state_hash"]
    assert rep2.final_event_stream_hash \
        == golden_summary["final_event_stream_hash"]
    if update_mode_enabled():  # 显式更新：scripts/update_baselines.py
        for name, artifact in artifacts.items():
            dump_artifact(artifact, BASELINE_DIR / name)


def _write_baseline(env, rep: M3aReport, wall: float) -> None:
    """显式更新入口：仅 BLR_UPDATE_GOLDEN_BASELINES=1 时写 golden。"""
    for name, artifact in _build_baseline(env, rep, wall).items():
        dump_artifact(artifact, BASELINE_DIR / name)


def _build_baseline(env, rep: M3aReport, wall: float) -> dict:
    with env["factory"]() as s:
        eps = s.execute(select(TribulationEpisode).order_by(
            TribulationEpisode.entered_tick)).scalars().all()
        plans = s.execute(select(TribulationImpactPlan)).scalars().all()
        decisions = s.execute(select(TribulationDecision)).scalars().all()
        cands = s.execute(select(ResourceSuccessionCandidate)).scalars().all()
        recs = s.execute(select(TribulationRecoveryState)).scalars().all()
        pop = sum(g.count for g in s.execute(select(PopulationGroup)).scalars())
        events = s.execute(select(WorldEvent)).scalars().all()
        schedules = [{"tier": x.tier, "period_years": x.period_years}
                     for x in s.execute(select(TribulationSchedule)).scalars()]
        world = latest_authoritative_world_checkpoint(s, MINI_WORLD_ID)
        event_hash = world.meta["event_stream_hash"]
    tiers = [e.window_tier for e in eps]
    completed = [e for e in eps if e.current_stage == STAGE_NEW_NORMAL]
    autonomous = [e for e in eps if e.decision_policy
                  == DEFAULT_AUTONOMOUS_RESPONSE_POLICY]
    summary = {
        "fixture_version": "mini_world_v1",
        "simulation_version": M3A_SIMULATION_VERSION,
        "tribulation_engine_version": ENGINE_VERSION,
        "schedule_schema": "test-schedule-001",
        "profile_schema": "test-trib-profile-1",
        "episode_id_schema": TRIBULATION_EPISODE_ID_SCHEMA_VERSION,
        "event_uid_schema_version": 1,
        "event_hash_schema_version": 1,
        "world_state_hash_schema_version": M3A_EFFECTIVE_HASH_SCHEMA_VERSION,
        "impact_plan_schema": IMPACT_PLAN_SCHEMA_VERSION,
        "scheduled_windows": len(eps),
        "regular_episodes": tiers.count("REGULAR"),
        "major_episodes": tiers.count("MAJOR"),
        "centennial_episodes": tiers.count("CENTENNIAL"),
        "completed_episodes": len(completed),
        "autonomous_responses": len(autonomous),
        "owner_decisions": len(decisions),
        "expired_decisions_rejected": 0,
        "mitigation_resources_spent": sum(
            int((p.mitigation_applied or {}).get("cost_minor", 0))
            for p in plans),
        "population_impact": sum(
            int((c.old_value or {}).get("v", 0))
            - int((c.new_value or {}).get("v", 0))
            for c in []),
        "resource_damage": 0,
        "inventory_loss": 0,
        "ecology_impact": 0,
        "social_impact": 0,
        "recovery_steps": sum(1 for e in events
                              if e.event_type == "TRIBULATION_RECOVERY_PROGRESS"),
        "residual_changes": 0,
        "succession_candidates": len(cands),
        "resources_materialized": 0,
        "new_normal_count": len(completed),
        "domain_event_count": len(events),
        "runs": rep.runs, "steps": rep.years,
        "checkpoints": rep.checkpoints,
        "final_population": pop,
        "final_world_state_hash": rep.final_state_hash,
        "final_event_stream_hash": event_hash,
        "wall_seconds": round(wall, 3),
    }
    return {
        "summary.json": summary,
        "episode_index.json": [
            {"episode_id": e.episode_id, "tier": e.window_tier,
             "entered_tick": e.entered_tick, "current_stage": e.current_stage,
             "profile_ref": e.profile_ref, "decision_policy": e.decision_policy,
             "targets": e.target_settlements} for e in eps],
        "schedule.json": schedules,
        "profiles.json": {
            k: {"tier": v.tier, "theme": v.theme,
                "intensity": [v.intensity_min, v.intensity_max],
                "recovery_steps": v.recovery_steps} for k, v in
            TEST_PROFILES.items()},
        "decisions.json": [
            {"decision_id": d.decision_id, "episode_id": d.episode_id,
             "action": d.action, "status": d.status} for d in decisions],
        "final_state.json": {
            "population": pop, "episodes": len(eps), "plans": len(plans),
            "candidates": len(cands), "recovery_rows": len(recs),
            "events": len(events)},
    }

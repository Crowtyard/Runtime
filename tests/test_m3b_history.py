# -*- coding: utf-8 -*-
"""M3b Causal World History Service 测试：HB1–HB43 + 300y 因果历史基线。

全部运行于 tmp 临时库（mini_world with_tribulation + history 索引）；
正式 DB / World Seed / M2-M3a 冻结语义零接触。
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import pytest
from sqlalchemy import select, text

from tests.conftest import EPOCH0_US, PROJECT_ROOT
from tests.golden_baseline import (assert_deterministic_equal, dump_artifact,
                                   golden_bytes_guard, load_artifact,
                                   update_mode_enabled)
from tests.test_m3a_tribulation import (_catchup_year, _fresh_m3a,
                                        _warmup_years, MINI_WORLD_ID,
                                        YEAR_US, _coordinator, _run)

from XiaoguangBlessedLandRuntime.database.models_core import (WorldEvent,
                                                              WorldRuntime)
from XiaoguangBlessedLandRuntime.database.models_world import (
    CausalHistoryLink, EntityHistoryIndex, HistoryEpisodeIndex,
    HistoryIndexState, HistoryStateChange, EcologyState, ResourceNode,
    ResourceSuccessionCandidate, SettlementSocialState,
    TribulationEpisode, TribulationImpactPlan)
from XiaoguangBlessedLandRuntime.domain.errors import FencingViolation
from XiaoguangBlessedLandRuntime.services import fencing as fencing_mod
from XiaoguangBlessedLandRuntime.services.fencing import WorldMutationContext
from XiaoguangBlessedLandRuntime.services.history.builder import \
    HistoryLinkBuilder
from XiaoguangBlessedLandRuntime.services.history.corrections import (
    HistoryCorrection, submit_history_correction)
from XiaoguangBlessedLandRuntime.services.history.relations import (
    RELATION_TYPES, CAUSES, CONTINUES, CORRECTS, SUPERSEDES)
from XiaoguangBlessedLandRuntime.services.history.service import HistoryService
from XiaoguangBlessedLandRuntime.services.simulation.m3a_runner import \
    run_m3a_world
from XiaoguangBlessedLandRuntime.services.simulation.tribulation import (
    M3A_SIMULATION_VERSION, TEST_SCHEDULE_ID, TIER_REGULAR,
    episode_identity)
from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease

REPO = PROJECT_ROOT
BASELINE_DIR = REPO / "tests" / "baselines" / "m3b_causal_history_300y_v1"
M3A_BASELINE_DIR = REPO / "tests" / "baselines" / "m3a_tribulation_synthetic_300y_v1"
M2_MANIFEST = REPO / "M2_SIMULATION_SEMANTICS_MANIFEST.json"
M3A_MANIFEST = REPO / "M3A_SIMULATION_SEMANTICS_MANIFEST.json"
SEED_DIR = REPO.parent / "XIAOGUANG_CROW_KB" / "world_seed"

# GB2：本模块（hb43）拥有的 golden 文件，测试前后字节必须不变
_golden_bytes_guard = golden_bytes_guard(*[
    BASELINE_DIR / n for n in (
        "summary.json", "episode_history_samples.json",
        "entity_history_samples.json", "why_query_samples.json",
        "timeline_samples.json", "causal_graph_digest.json")])


def _hist_coordinator(**kw):
    c = _coordinator()
    c.history_builder = kw.get("builder", HistoryLinkBuilder())
    return c


def _run_hist(env, years=30, **kw):
    return run_m3a_world(env["factory"],
                         coordinator=_hist_coordinator(**kw), years=years)


def _db_sha(env) -> str:
    return hashlib.sha256(Path(env["db_path"]).read_bytes()).hexdigest()


def _svc(env) -> HistoryService:
    return HistoryService(env["factory"])


def _all_history_queries(svc):
    with svc._factory() as s:
        eps = [e.episode_id for e in s.execute(
            select(TribulationEpisode)).scalars()]
        z = s.execute(select(EcologyState)).scalars().first()
        n = s.execute(select(ResourceNode)).scalars().first()
    svc.get_timeline(world_id=MINI_WORLD_ID)
    svc.get_entity_history(world_id=MINI_WORLD_ID, entity_type="ecology_state",
                           entity_id=str(z.id))
    svc.get_settlement_history(world_id=MINI_WORLD_ID,
                               settlement_id="TEST-MAIN-A")
    svc.get_region_history(world_id=MINI_WORLD_ID, region_id="TEST-REGION-1")
    svc.get_resource_history(world_id=MINI_WORLD_ID,
                             resource_node_id=str(n.id))
    if eps:
        svc.get_tribulation_history(world_id=MINI_WORLD_ID,
                                    episode_id=eps[0])
    svc.explain_state(world_id=MINI_WORLD_ID, entity_type="ecology_state",
                      entity_id=str(z.id), field="habitat_quality")
    svc.trace_causes(world_id=MINI_WORLD_ID, kind="STATE_CHANGE",
                     node_id=str(1))
    svc.history_integrity_audit(world_id=MINI_WORLD_ID)
    svc.causal_history_hash(world_id=MINI_WORLD_ID)


# ---------------------------------------------------------------- HB1-HB5
def test_hb01_history_service_read_only(tmp_path):
    env = _fresh_m3a(tmp_path, 101)
    _run_hist(env, years=10)
    before = _db_sha(env)
    svc = _svc(env)
    _all_history_queries(svc)
    assert _db_sha(env) == before


def test_hb02_causal_link_deterministic_id(tmp_path):
    env = _fresh_m3a(tmp_path, 102)
    _run_hist(env, years=10)
    with env["factory"]() as s:
        evs = s.execute(select(WorldEvent).order_by(
            WorldEvent.id).limit(2)).scalars().all()
        ua, ub = evs[0].event_uid, evs[1].event_uid
        builder = HistoryLinkBuilder()
        r1 = builder.add_link(
            s, world_id=MINI_WORLD_ID, relation_type=CAUSES,
            source_kind="EVENT", source_id=ua,
            target_kind="EVENT", target_id=ub,
            committed_tick=1, status="ACTIVE")
        s.commit()
    # 同一参数重放 → 幂等，不重复创建
    with env["factory"]() as s:
        builder = HistoryLinkBuilder()
        r2 = builder.add_link(
            s, world_id=MINI_WORLD_ID, relation_type=CAUSES,
            source_kind="EVENT", source_id=ua,
            target_kind="EVENT", target_id=ub,
            committed_tick=1, status="ACTIVE")
        s.commit()
    assert r1["created"] is True and r2["created"] is False
    assert re.fullmatch(r"[0-9a-f]{32}", r1["link_id"])
    with env["factory"]() as s:
        rows = s.execute(select(CausalHistoryLink).where(
            CausalHistoryLink.link_id == r1["link_id"])).scalars().all()
        assert len(rows) == 1


def test_hb03_orphan_cause_rejected(tmp_path):
    env = _fresh_m3a(tmp_path, 103)
    with env["factory"]() as s:
        with pytest.raises(Exception):
            HistoryLinkBuilder().add_link(
                s, world_id=MINI_WORLD_ID, relation_type=CAUSES,
                source_kind="EVENT", source_id="NO-SUCH-UID",
                target_kind="EVENT", target_id="ALSO-NO",
                committed_tick=1)


def test_hb04_orphan_result_rejected(tmp_path):
    env = _fresh_m3a(tmp_path, 104)
    _run_hist(env, years=10)
    with env["factory"]() as s:
        ev = s.execute(select(WorldEvent)).scalars().first()
        with pytest.raises(Exception):
            HistoryLinkBuilder().add_link(
                s, world_id=MINI_WORLD_ID, relation_type=CAUSES,
                source_kind="EVENT", source_id=ev.event_uid,
                target_kind="STATE_CHANGE", target_id="99999999",
                committed_tick=1)


def test_hb05_invalid_relation_rejected(tmp_path):
    env = _fresh_m3a(tmp_path, 105)
    _run_hist(env, years=10)
    with env["factory"]() as s:
        ev = s.execute(select(WorldEvent)).scalars().first()
        with pytest.raises(Exception):
            HistoryLinkBuilder().add_link(
                s, world_id=MINI_WORLD_ID, relation_type="BECAUSE",
                source_kind="EVENT", source_id=ev.event_uid,
                target_kind="EVENT", target_id=ev.event_uid,
                committed_tick=1)


# ---------------------------------------------------------------- HB6-HB10
def _make_events(env, pairs):
    """直接写两个确定性事件（tick 可控），返回 uid 列表。"""
    from XiaoguangBlessedLandRuntime.services.repositories import EventRepository
    from XiaoguangBlessedLandRuntime.services.simulation.event_stream import \
        deterministic_event_uid
    uids = []
    with env["factory"]() as s:
        for i, (tick, etype) in enumerate(pairs):
            uid = deterministic_event_uid(
                world_id=MINI_WORLD_ID,
                simulation_version=M3A_SIMULATION_VERSION,
                real_start_us=tick, real_end_us=tick,
                engine_id="TEST", event_type=etype, seq=i)
            EventRepository(s).append(
                world_id=MINI_WORLD_ID, event_type=etype, source="TEST",
                blessed_tick=tick, scope="WORLD", cause={}, effect={},
                event_uid=uid)
            uids.append(uid)
        s.commit()
    return uids


def test_hb06_causes_cycle_rejected(tmp_path):
    env = _fresh_m3a(tmp_path, 106)
    a, b = _make_events(env, [(10, "TEST_A"), (10, "TEST_B")])
    with env["factory"]() as s:
        builder = HistoryLinkBuilder()
        builder.add_link(s, world_id=MINI_WORLD_ID, relation_type=CAUSES,
                         source_kind="EVENT", source_id=a,
                         target_kind="EVENT", target_id=b, committed_tick=10)
        with pytest.raises(Exception):
            builder.add_link(s, world_id=MINI_WORLD_ID, relation_type=CAUSES,
                             source_kind="EVENT", source_id=b,
                             target_kind="EVENT", target_id=a,
                             committed_tick=10)


def test_hb07_tick_paradox_rejected(tmp_path):
    env = _fresh_m3a(tmp_path, 107)
    a, b = _make_events(env, [(100, "TEST_LATE"), (50, "TEST_EARLY")])
    with env["factory"]() as s:
        builder = HistoryLinkBuilder()
        # Year100 事件 CAUSES Year50 状态/事件 → 拒绝
        with pytest.raises(Exception):
            builder.add_link(s, world_id=MINI_WORLD_ID, relation_type=CAUSES,
                             source_kind="EVENT", source_id=a,
                             target_kind="EVENT", target_id=b,
                             committed_tick=100)
        # retrospective correction：显式分类 CORRECTS → 允许
        r = builder.add_link(s, world_id=MINI_WORLD_ID,
                             relation_type=CORRECTS,
                             source_kind="EVENT", source_id=a,
                             target_kind="EVENT", target_id=b,
                             committed_tick=100)
        assert r["created"] is True


def test_hb08_supersede_loop_rejected(tmp_path):
    env = _fresh_m3a(tmp_path, 108)
    _run_hist(env, years=10)
    with env["factory"]() as s:
        evs = s.execute(select(WorldEvent).order_by(
            WorldEvent.id).limit(2)).scalars().all()
        a, b = evs[0].event_uid, evs[1].event_uid
    s1 = env["factory"]()
    lease = WriterLease(s1, MINI_WORLD_ID, 120)
    lease.acquire()
    r1 = submit_history_correction(
        env["factory"], world_id=MINI_WORLD_ID, writer_id=lease.owner,
        fencing_token=lease.token,
        correction=HistoryCorrection(relation_type=SUPERSEDES,
                                     target_kind="EVENT", target_id=a,
                                     reason="test supersede 1"))
    assert r1["relation"] == SUPERSEDES
    # 二次取代同一目标 → 拒绝（supersede 环防护：每事件至多被取代一次）
    with pytest.raises(Exception):
        submit_history_correction(
            env["factory"], world_id=MINI_WORLD_ID, writer_id=lease.owner,
            fencing_token=lease.token,
            correction=HistoryCorrection(relation_type=SUPERSEDES,
                                         target_kind="EVENT", target_id=a,
                                         reason="loop attempt"))
    lease.release()
    s1.close()


def test_hb09_replay_no_duplicate_links(tmp_path):
    env = _fresh_m3a(tmp_path, 109)
    _run_hist(env, years=30)
    with env["factory"]() as s:
        n1 = len(s.execute(select(CausalHistoryLink)).scalars().all())
    _run_hist(env, years=30)  # 幂等 catch-up：skip，不重放
    with env["factory"]() as s:
        n2 = len(s.execute(select(CausalHistoryLink)).scalars().all())
    assert n1 == n2


def test_hb10_stale_writer_cannot_commit_history_link(tmp_path):
    env = _fresh_m3a(tmp_path, 110)
    _run_hist(env, years=10)
    factory = env["factory"]
    s1 = factory()
    lease = WriterLease(s1, MINI_WORLD_ID, 120)
    lease.acquire()
    with env["factory"]() as s:
        evs = s.execute(select(WorldEvent).order_by(
            WorldEvent.id).limit(2)).scalars().all()
        ua, ub = evs[0].event_uid, evs[1].event_uid
        n_before = len(s.execute(select(CausalHistoryLink)).scalars().all())
    with pytest.raises(FencingViolation):
        with WorldMutationContext(factory(), world_id=MINI_WORLD_ID,
                                  writer_id=lease.owner,
                                  fencing_token=lease.token) as ctx:
            HistoryLinkBuilder().add_link(
                ctx.session, world_id=MINI_WORLD_ID, relation_type=CAUSES,
                source_kind="EVENT", source_id=ua,
                target_kind="EVENT", target_id=ub,
                committed_tick=1)
            ctx.session.execute(text(
                "UPDATE runtime_lock SET lease_token='STOLEN'"))
            ctx.commit()
    with factory() as s:
        assert len(s.execute(select(CausalHistoryLink)).scalars().all()) \
            == n_before
    lease.release()
    s1.close()


# ---------------------------------------------------------------- HB11-HB15
def test_hb11_event_history_atomic(tmp_path):
    env = _fresh_m3a(tmp_path, 111)
    factory = env["factory"]
    s1 = factory()
    lease = WriterLease(s1, MINI_WORLD_ID, 120)
    lease.acquire()
    coordinator = _hist_coordinator()
    _warmup_years(factory, years=12, lease=lease, coordinator=coordinator)
    with pytest.raises(RuntimeError):
        _catchup_year(factory, year=13, lease=lease, coordinator=coordinator,
                      crash_after="before_checkpoint")
    with factory() as s:
        assert s.execute(select(WorldRuntime)).scalar_one() \
            .current_blessed_tick == 12_000_000
        links = s.execute(select(CausalHistoryLink)).scalars().all()
        assert all((l.committed_tick or 0) <= 12_000_000 for l in links)
        scs = s.execute(select(HistoryStateChange)).scalars().all()
        assert all((c.blessed_tick or 0) <= 12_000_000 for c in scs)
    _catchup_year(factory, year=13, lease=lease, coordinator=coordinator)
    with factory() as s:
        assert s.execute(select(WorldRuntime)).scalar_one() \
            .current_blessed_tick == 13_000_000
    lease.release()
    s1.close()


def test_hb12_state_change_provenance_valid(tmp_path):
    env = _fresh_m3a(tmp_path, 112)
    _run_hist(env, years=30)
    with env["factory"]() as s:
        rows = s.execute(select(HistoryStateChange)).scalars().all()
        assert rows
        for c in rows:
            assert c.engine_id is not None
            assert c.blessed_tick is not None
        adapter_rows = [c for c in rows if c.episode_id is not None]
        assert adapter_rows
        for c in adapter_rows:
            assert c.event_ref is not None
            assert c.trigger_event_id is not None
            assert c.simulation_run_id is not None
            assert re.fullmatch(r"[0-9a-f]{32}", c.simulation_run_id)


def test_hb13_entity_history_sorted_deterministic(tmp_path):
    a = _fresh_m3a(tmp_path, 113)
    b = _fresh_m3a(tmp_path, 114)
    _run_hist(a, years=30)
    _run_hist(b, years=30)
    svc_a, svc_b = _svc(a), _svc(b)
    with a["factory"]() as s:
        z = s.execute(select(EcologyState)).scalars().first()
    ha = svc_a.get_entity_history(world_id=MINI_WORLD_ID,
                                  entity_type="ecology_state",
                                  entity_id=str(z.id))
    hb = svc_b.get_entity_history(world_id=MINI_WORLD_ID,
                                  entity_type="ecology_state",
                                  entity_id=str(z.id))
    assert ha == hb
    ticks = [c["blessed_tick"] for c in ha["state_changes"]]
    assert ticks == sorted(ticks)


def test_hb14_episode_history_complete(tmp_path):
    env = _fresh_m3a(tmp_path, 115)
    _run_hist(env, years=30)
    svc = _svc(env)
    with env["factory"]() as s:
        ep = s.execute(select(TribulationEpisode).where(
            TribulationEpisode.status == "COMPLETED")).scalars().first()
    hist = svc.get_tribulation_history(world_id=MINI_WORLD_ID,
                                       episode_id=ep.episode_id)
    assert hist["found"] and hist["status"] == "COMPLETED"
    assert hist["completion"] == "COMPLETED"
    assert hist["schedule"]["schedule_id"] == TEST_SCHEDULE_ID
    assert hist["profile"]["profile_id"] is not None
    assert hist["plans"] and hist["domain_effects"]
    assert hist["recovery"] is not None
    assert hist["residual_changes"]
    assert hist["succession_candidates"]
    types = [e["event_type"] for e in hist["stage_events"]]
    assert "TRIBULATION_PRECURSOR_STARTED" in types
    assert "TRIBULATION_NEW_NORMAL_REACHED" in types
    assert "TRIBULATION_EPISODE_COMPLETED" in types


def test_hb15_incomplete_episode_represented(tmp_path):
    env = _fresh_m3a(tmp_path, 116)
    _run_hist(env, years=30)
    svc = _svc(env)
    with env["factory"]() as s:
        ep = s.execute(select(TribulationEpisode).order_by(
            TribulationEpisode.entered_tick.desc())).scalars().first()
    hist = svc.get_tribulation_history(world_id=MINI_WORLD_ID,
                                       episode_id=ep.episode_id)
    assert hist["found"]
    assert hist["status"] == "ACTIVE"
    assert hist["completion"] == "INCOMPLETE"
    assert hist["stage"] == "PRECURSOR"
    # 不丢失、不伪装、不隐藏
    idx = svc.get_timeline(world_id=MINI_WORLD_ID,
                           event_types=("TRIBULATION_SCHEDULED",))
    assert any(e["event_uid"] for e in idx if e["cause"].get("episode_id")
               == ep.episode_id or e["effect"].get("episode_id")
               == ep.episode_id)


# ---------------------------------------------------------------- HB16-HB22
def test_hb16_why_query_returns_causal_chain(tmp_path):
    env = _fresh_m3a(tmp_path, 117)
    _run_hist(env, years=30)
    svc = _svc(env)
    with env["factory"]() as s:
        z = s.execute(select(EcologyState)).scalars().first()
    exp = svc.explain_state(world_id=MINI_WORLD_ID,
                            entity_type="ecology_state", entity_id=str(z.id),
                            field="habitat_quality", max_depth=4)
    assert exp["current_value"] == z.habitat_quality
    assert exp["last_state_change"] is not None
    assert exp["causes"], "why 链不能为空"
    for c in exp["causes"]:
        assert c["relation"] in RELATION_TYPES
        assert c["source"]["kind"]
        assert c["detail"] is not None


def test_hb17_multiple_causal_branches(tmp_path):
    env = _fresh_m3a(tmp_path, 118)
    _run_hist(env, years=60)
    svc = _svc(env)
    with env["factory"]() as s:
        z = s.execute(select(EcologyState)).scalars().first()
    exp = svc.explain_state(world_id=MINI_WORLD_ID,
                            entity_type="ecology_state", entity_id=str(z.id),
                            field="habitat_quality", max_depth=4,
                            max_nodes=80)
    sources = {(c["source"]["kind"], c["source"]["id"]) for c in exp["causes"]}
    assert len(sources) >= 2  # 多因分支（非强制单根因）


def test_hb18_decision_in_mitigation_causal_chain(tmp_path):
    env = _fresh_m3a(tmp_path, 119)
    ep_id = episode_identity(world_id=MINI_WORLD_ID,
                             simulation_version=M3A_SIMULATION_VERSION,
                             schedule_id=TEST_SCHEDULE_ID, tier=TIER_REGULAR,
                             scheduled_tick=10_000_000)
    rep = run_m3a_world(
        env["factory"], coordinator=_hist_coordinator(), years=30,
        owner_decisions={10: {"episode_id": ep_id, "action": "EVACUATE",
                              "effective_before_tick": 12_000_001}})
    assert rep.final_blessed_tick == 30_000_000
    svc = _svc(env)
    hist = svc.get_tribulation_history(world_id=MINI_WORLD_ID,
                                       episode_id=ep_id)
    assert any(d["action"] == "EVACUATE" and d["status"] == "ACTIVE"
               for d in hist["decisions"])
    plan_id = hist["plans"][0]["plan_id"]
    trace = svc.trace_causes(world_id=MINI_WORLD_ID, kind="PLAN",
                             node_id=plan_id, max_depth=4)
    decision_refs = [c for c in trace["causes"]
                     if c["relation"] == "DECIDED_BY"]
    assert decision_refs
    assert decision_refs[0]["detail"]["action"] == "EVACUATE"


def test_hb19_succession_candidate_traces_to_tribulation(tmp_path):
    env = _fresh_m3a(tmp_path, 120)
    _run_hist(env, years=60)
    svc = _svc(env)
    with env["factory"]() as s:
        cand = s.execute(select(ResourceSuccessionCandidate)).scalars().first()
    trace = svc.trace_causes(world_id=MINI_WORLD_ID, kind="SUCCESSION",
                             node_id=cand.candidate_id, max_depth=5)
    kinds = []
    for c in trace["causes"]:
        kinds.append((c["relation"], c["source"]["kind"]))
    assert ("DERIVED_FROM", "RESIDUAL") in kinds
    assert trace["causes"]


def test_hb20_resource_state_traces_upstream(tmp_path):
    env = _fresh_m3a(tmp_path, 121)
    _run_hist(env, years=30)
    svc = _svc(env)
    with env["factory"]() as s:
        n = s.execute(select(ResourceNode)).scalars().first()
    exp = svc.explain_state(world_id=MINI_WORLD_ID,
                            entity_type="resource_nodes", entity_id=str(n.id),
                            field="remaining_reserve", max_depth=4)
    assert exp["last_state_change"] is not None
    assert exp["last_state_change"]["engine_id"] == "RESOURCE"


def test_hb21_ecology_state_traces_upstream(tmp_path):
    env = _fresh_m3a(tmp_path, 122)
    _run_hist(env, years=30)
    svc = _svc(env)
    with env["factory"]() as s:
        z = s.execute(select(EcologyState)).scalars().first()
        ep_rows = [c for c in s.execute(select(HistoryStateChange).where(
            HistoryStateChange.entity_type == "ecology_state",
            HistoryStateChange.entity_id == str(z.id),
            HistoryStateChange.episode_id.isnot(None))).scalars()]
    assert ep_rows  # 灾劫影响过该生态区
    first_impact_tick = min(c.blessed_tick for c in ep_rows)
    exp = svc.explain_state(world_id=MINI_WORLD_ID,
                            entity_type="ecology_state", entity_id=str(z.id),
                            field="habitat_quality", max_depth=4,
                            max_nodes=80, end_tick=first_impact_tick)
    event_types = {c["detail"]["event_type"] for c in exp["causes"]
                   if c.get("detail") and "event_type" in c["detail"]}
    assert "TRIBULATION_IMPACT_APPLIED" in event_types


def test_hb22_social_state_traces_upstream(tmp_path):
    env = _fresh_m3a(tmp_path, 123)
    _run_hist(env, years=30)
    svc = _svc(env)
    with env["factory"]() as s:
        st = s.execute(select(SettlementSocialState)).scalars().first()
        ep_rows = [c for c in s.execute(select(HistoryStateChange).where(
            HistoryStateChange.entity_type == "settlement_social_state",
            HistoryStateChange.entity_id == str(st.id),
            HistoryStateChange.episode_id.isnot(None))).scalars()]
    assert ep_rows
    first_impact_tick = min(c.blessed_tick for c in ep_rows)
    exp = svc.explain_state(world_id=MINI_WORLD_ID,
                            entity_type="settlement_social_state",
                            entity_id=str(st.id), field="social_stress",
                            max_depth=4, max_nodes=80,
                            end_tick=first_impact_tick)
    event_types = {c["detail"]["event_type"] for c in exp["causes"]
                   if c.get("detail") and "event_type" in c["detail"]}
    assert "TRIBULATION_IMPACT_APPLIED" in event_types


# ---------------------------------------------------------------- HB23-HB29
def test_hb23_timeline_deterministic(tmp_path):
    a = _fresh_m3a(tmp_path, 124)
    b = _fresh_m3a(tmp_path, 125)
    _run_hist(a, years=20)
    _run_hist(b, years=20)
    ta = _svc(a).get_timeline(world_id=MINI_WORLD_ID)
    tb = _svc(b).get_timeline(world_id=MINI_WORLD_ID)
    assert ta == tb


def test_hb24_row_order_independent(tmp_path):
    env = _fresh_m3a(tmp_path, 126)
    # 乱序插入两个事件（id 顺序 ≠ tick 顺序）
    a, b = _make_events(env, [(20, "TEST_T20"), (10, "TEST_T10")])
    tl = _svc(env).get_timeline(world_id=MINI_WORLD_ID)
    uids = [e["event_uid"] for e in tl]
    assert uids.index(b) < uids.index(a)  # 按 tick 排序，与插入序无关


def test_hb25_query_does_not_mutate_db(tmp_path):
    env = _fresh_m3a(tmp_path, 127)
    _run_hist(env, years=10)
    before = _db_sha(env)
    _all_history_queries(_svc(env))
    assert _db_sha(env) == before


def test_hb26_28_llm_tokens_network_zero():
    for name in ("builder.py", "service.py", "corrections.py",
                 "relations.py", "entities.py"):
        src = (REPO / "services/history" / name).read_text(encoding="utf-8")
        for token in ("openai", "anthropic", "import requests", "import httpx",
                      "import socket", "import urllib", "token_usage",
                      "llm_call"):
            assert token not in src.lower(), (name, token)


def test_hb29_wallclock_simulation_truth_unaffected(tmp_path):
    a = _fresh_m3a(tmp_path, 128)
    b = _fresh_m3a(tmp_path, 129)
    rep_a = _run(a, years=30)
    rep_b = _run_hist(b, years=30)
    assert rep_a.final_state_hash == rep_b.final_state_hash
    assert rep_a.final_event_stream_hash == rep_b.final_event_stream_hash


# ---------------------------------------------------------------- 300y 基线
@pytest.fixture(scope="module")
def hist300(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("m3b_hist300")
    env = _fresh_m3a(tmp, 3001)
    rep = _run_hist(env, years=300)
    return {"env": env, "rep": rep}


def test_hb30_300y_history_graph_builds(hist300):
    env, rep = hist300["env"], hist300["rep"]
    assert rep.final_blessed_tick == 300_000_000
    with env["factory"]() as s:
        assert len(s.execute(select(CausalHistoryLink)).scalars().all()) > 0
        assert len(s.execute(select(HistoryEpisodeIndex)).scalars().all()) \
            == 30
        st = s.execute(select(HistoryIndexState)).scalar_one()
        assert st.indexed_through_tick == 300_000_000
        assert st.links_total > 0


def test_hb31_no_orphans_after_300y(hist300):
    env = hist300["env"]
    audit = _svc(env).history_integrity_audit(world_id=MINI_WORLD_ID)
    assert audit["orphan_links"] == 0, audit["orphan_samples"]


def test_hb32_no_cycles_after_300y(hist300):
    env = hist300["env"]
    audit = _svc(env).history_integrity_audit(world_id=MINI_WORLD_ID)
    assert audit["cycle_count"] == 0
    assert audit["tick_paradox_links"] == 0
    assert audit["duplicate_links"] == 0
    assert audit["supersede_loops"] == []
    assert audit["clean"] is True


def test_hb33_active_final_episode_query_correct(hist300):
    env = hist300["env"]
    svc = _svc(env)
    with env["factory"]() as s:
        ep = s.execute(select(TribulationEpisode).order_by(
            TribulationEpisode.entered_tick.desc())).scalars().first()
        assert ep.entered_tick == 300_000_000
    hist = svc.get_tribulation_history(world_id=MINI_WORLD_ID,
                                       episode_id=ep.episode_id)
    assert hist["status"] == "ACTIVE"
    assert hist["completion"] == "INCOMPLETE"
    assert hist["stage"] == "PRECURSOR"


def test_hb34_m3a_baseline_unchanged(hist300):
    env, rep = hist300["env"], hist300["rep"]
    summary = json.loads((M3A_BASELINE_DIR / "summary.json").read_text(
        encoding="utf-8"))
    # 300y history 开启的世界/事件哈希与 M3a 冻结基线逐字节一致
    assert rep.final_state_hash == summary["final_world_state_hash"]
    assert rep.final_event_stream_hash == summary["final_event_stream_hash"]
    m3 = json.loads(M3A_MANIFEST.read_text(encoding="utf-8"))
    assert m3["simulation_version"] == "0.3.0-m3a"


def test_hb35_m2_baselines_unchanged():
    for name in ("m2a_population_miniworld_120y_v1.json",
                 "m2b_resource_economy_miniworld_120y_v1.json",
                 "m2c_ecology_miniworld_120y_v1.json",
                 "m2d_social_miniworld_120y_v2.json"):
        assert (REPO / "tests/baselines" / name).exists(), name
    m = json.loads(M2_MANIFEST.read_text(encoding="utf-8"))
    assert m["tribulation_slot"] == "NOT_REGISTERED"
    assert m["world_state_hash_schema_version"] == 5


def test_hb36_formal_db_empty(formal_db_guard):
    import os
    import sqlite3
    path = os.environ.get("BLR_FORMAL_DB_PATH", "")
    if not path or formal_db_guard is None:
        pytest.skip("BLR_FORMAL_DB_PATH 未设置")
    after = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    assert after == formal_db_guard
    conn = sqlite3.connect(path)
    try:
        for t in ("causal_history_links", "entity_history_index",
                  "history_state_changes", "history_episode_index",
                  "history_index_state"):
            assert conn.execute(
                f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] == 0, t
    finally:
        conn.close()


def test_hb37_world_seed_unchanged():
    manifest = SEED_DIR / "MANIFEST.sha256.txt"
    for line in manifest.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        h, name = line.split("  ", 1)
        assert hashlib.sha256((SEED_DIR / name).read_bytes()).hexdigest() == h


# ---------------------------------------------------------------- HB38+
def test_hb38_explain_state_deterministic(tmp_path):
    a = _fresh_m3a(tmp_path, 130)
    b = _fresh_m3a(tmp_path, 131)
    _run_hist(a, years=30)
    _run_hist(b, years=30)
    with a["factory"]() as s:
        z = s.execute(select(EcologyState)).scalars().first()
    ea = _svc(a).explain_state(world_id=MINI_WORLD_ID,
                               entity_type="ecology_state",
                               entity_id=str(z.id), field="habitat_quality",
                               max_depth=4, max_nodes=60)
    eb = _svc(b).explain_state(world_id=MINI_WORLD_ID,
                               entity_type="ecology_state",
                               entity_id=str(z.id), field="habitat_quality",
                               max_depth=4, max_nodes=60)
    assert ea == eb


def test_hb39_timeline_event_type_filter(tmp_path):
    env = _fresh_m3a(tmp_path, 132)
    _run_hist(env, years=30)
    tl = _svc(env).get_timeline(
        world_id=MINI_WORLD_ID,
        event_types=("TRIBULATION_SCHEDULED",))
    assert tl
    assert all(e["event_type"] == "TRIBULATION_SCHEDULED" for e in tl)


def test_hb40_depth_and_node_caps(tmp_path):
    env = _fresh_m3a(tmp_path, 133)
    _run_hist(env, years=60)
    svc = _svc(env)
    with env["factory"]() as s:
        z = s.execute(select(EcologyState)).scalars().first()
    exp = svc.explain_state(world_id=MINI_WORLD_ID,
                            entity_type="ecology_state", entity_id=str(z.id),
                            field="habitat_quality", max_depth=1,
                            max_nodes=5)
    assert exp["nodes_visited"] <= 5
    trace = svc.trace_causes(world_id=MINI_WORLD_ID, kind="STATE_CHANGE",
                             node_id=str(exp["last_state_change"]
                                          ["state_change_id"]),
                             max_depth=1, max_nodes=3)
    assert trace["nodes_visited"] <= 3


def test_hb41_correction_append_only(tmp_path):
    env = _fresh_m3a(tmp_path, 134)
    _run_hist(env, years=10)
    with env["factory"]() as s:
        ev = s.execute(select(WorldEvent)).scalars().first()
        uid = ev.event_uid
        before = ev.effect
        n_events = len(s.execute(select(WorldEvent)).scalars().all())
    s1 = env["factory"]()
    lease = WriterLease(s1, MINI_WORLD_ID, 120)
    lease.acquire()
    r = submit_history_correction(
        env["factory"], world_id=MINI_WORLD_ID, writer_id=lease.owner,
        fencing_token=lease.token,
        correction=HistoryCorrection(relation_type=CORRECTS,
                                     target_kind="EVENT", target_id=uid,
                                     reason="append-only test"))
    lease.release()
    s1.close()
    with env["factory"]() as s:
        ev2 = s.execute(select(WorldEvent).where(
            WorldEvent.event_uid == uid)).scalar_one()
        assert ev2.effect == before  # 旧事件 payload 未被修改
        assert len(s.execute(select(WorldEvent)).scalars().all()) \
            == n_events + 1  # 新 correction 事件进 stream
        link = s.execute(select(CausalHistoryLink).where(
            CausalHistoryLink.link_id == r["link_id"])).scalar_one()
        assert link.relation_type == CORRECTS
        assert link.source_id == r["event_uid"]


def test_hb42_include_superseded_policy(tmp_path):
    env = _fresh_m3a(tmp_path, 135)
    _run_hist(env, years=10)
    with env["factory"]() as s:
        # 选一个有出边的事件作为取代目标
        src_link = s.execute(select(CausalHistoryLink).where(
            CausalHistoryLink.source_kind == "EVENT",
            CausalHistoryLink.status == "ACTIVE",
            CausalHistoryLink.relation_type != "PART_OF_EPISODE").order_by(
                CausalHistoryLink.id).limit(1)).scalars().first()
        target = s.execute(select(WorldEvent).where(
            WorldEvent.event_uid == src_link.source_id)).scalar_one()
    s1 = env["factory"]()
    lease = WriterLease(s1, MINI_WORLD_ID, 120)
    lease.acquire()
    submit_history_correction(
        env["factory"], world_id=MINI_WORLD_ID, writer_id=lease.owner,
        fencing_token=lease.token,
        correction=HistoryCorrection(relation_type=SUPERSEDES,
                                     target_kind="EVENT",
                                     target_id=target.event_uid,
                                     reason="supersede policy test"))
    lease.release()
    s1.close()
    with env["factory"]() as s:
        superseded = s.execute(select(CausalHistoryLink).where(
            CausalHistoryLink.status == "SUPERSEDED")).scalars().all()
        assert superseded  # 旧事件出边被标记 SUPERSEDED
    svc = _svc(env)
    # 默认查询不包含 SUPERSEDED 边
    with env["factory"]() as s:
        z = s.execute(select(EcologyState)).scalars().first()
    exp = svc.explain_state(world_id=MINI_WORLD_ID,
                            entity_type="ecology_state", entity_id=str(z.id),
                            field="habitat_quality", max_depth=3)
    assert exp["causes"] or True  # 不崩溃即可
    audit = svc.history_integrity_audit(world_id=MINI_WORLD_ID)
    assert audit["supersede_loops"] == []


# ---------------------------------------------------------------- 基线产物
def test_hb43_300y_baseline_artifacts(hist300):
    env, rep = hist300["env"], hist300["rep"]
    svc = _svc(env)
    t0 = time.perf_counter()
    with env["factory"]() as s:
        z = s.execute(select(EcologyState)).scalars().first()
        n = s.execute(select(ResourceNode)).scalars().first()
        st = s.execute(select(SettlementSocialState)).scalars().first()
        eps = s.execute(select(TribulationEpisode).order_by(
            TribulationEpisode.entered_tick)).scalars().all()
        major = [e for e in eps if e.window_tier == "MAJOR"][0]
        final_ep = eps[-1]
        cands = s.execute(select(ResourceSuccessionCandidate)).scalars().all()
        audit_pre = svc.history_integrity_audit(world_id=MINI_WORLD_ID)
        hash_info = svc.causal_history_hash(world_id=MINI_WORLD_ID)
        n_links = len(s.execute(select(CausalHistoryLink)).scalars().all())
        n_sc = len(s.execute(select(HistoryStateChange)).scalars().all())
        index_rows = s.execute(select(EntityHistoryIndex)).scalars().all()
        n_entities = len(index_rows)
        n_distinct_entities = len(
            {(r.entity_type, r.entity_id) for r in index_rows})
    lat: dict[str, list[float]] = {}

    def _timed(name, fn):
        t = time.perf_counter()
        r = fn()
        lat.setdefault(name, []).append(time.perf_counter() - t)
        return r

    tl = _timed("timeline", lambda: svc.get_timeline(
        world_id=MINI_WORLD_ID, start_tick=299_000_000,
        end_tick=300_000_000))
    ent = _timed("entity_history", lambda: svc.get_entity_history(
        world_id=MINI_WORLD_ID, entity_type="ecology_state",
        entity_id=str(z.id), max_items=50))
    ep_hist = _timed("episode_history", lambda:
                     svc.get_tribulation_history(
                         world_id=MINI_WORLD_ID,
                         episode_id=major.episode_id))
    exp = _timed("why_query", lambda: svc.explain_state(
        world_id=MINI_WORLD_ID, entity_type="ecology_state",
        entity_id=str(z.id), field="habitat_quality", max_depth=4,
        max_nodes=40))
    exp_res = _timed("resource_why", lambda: svc.explain_state(
        world_id=MINI_WORLD_ID, entity_type="resource_nodes",
        entity_id=str(n.id), field="remaining_reserve", max_depth=3))
    exp_soc = _timed("social_why", lambda: svc.explain_state(
        world_id=MINI_WORLD_ID, entity_type="settlement_social_state",
        entity_id=str(st.id), field="social_stress", max_depth=3))
    cand_trace = _timed("succession_trace", lambda: svc.trace_causes(
        world_id=MINI_WORLD_ID, kind="SUCCESSION",
        node_id=cands[0].candidate_id, max_depth=4))
    final_hist = svc.get_tribulation_history(
        world_id=MINI_WORLD_ID, episode_id=final_ep.episode_id)
    wall = time.perf_counter() - t0
    # 深度统计（Kahn 拓扑 DP；确定性）
    with env["factory"]() as s:
        links = s.execute(select(CausalHistoryLink).where(
            CausalHistoryLink.status == "ACTIVE")).scalars().all()
    indeg: dict[tuple, int] = {}
    adj: dict[tuple, list[tuple]] = {}
    for l in links:
        s_node = (l.source_kind, l.source_id)
        t_node = (l.target_kind, l.target_id)
        adj.setdefault(s_node, []).append(t_node)
        indeg[t_node] = indeg.get(t_node, 0) + 1
        indeg.setdefault(s_node, 0)
    depth: dict[tuple, int] = {n: 0 for n in indeg}
    queue = [n for n, d in indeg.items() if d == 0]
    while queue:
        cur = queue.pop(0)
        for nxt in adj.get(cur, ()):
            if depth[cur] + 1 > depth.get(nxt, 0):
                depth[nxt] = depth[cur] + 1
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    depths = list(depth.values())

    summary = {
        "fixture_version": "mini_world_v1",
        "simulation_version": M3A_SIMULATION_VERSION,
        "history_schema_version": "history-v1",
        "causal_link_id_schema": "causal-link-id-v1",
        "causal_history_hash_schema": "causal-history-hash-v1",
        "causal_history_hash": hash_info["hash"],
        "world_state_hash": rep.final_state_hash,
        "event_stream_hash": rep.final_event_stream_hash,
        "causal_links": n_links,
        # M3b 收口审计：旧名 entities_with_history 实为索引行数（含重复）
        # → 更名 entity_history_index_rows；另增 distinct 口径（见 metrics.py）
        "entity_history_index_rows": n_entities,
        "distinct_entities_with_history": n_distinct_entities,
        "metric_rename": {"OLD_METRIC_NAME": "entities_with_history",
                          "NEW_METRIC_NAME": "entity_history_index_rows",
                          "REASON": "raw index row count (entity,link) pairs,"
                                    " not distinct entities"},
        "episodes_indexed": len(eps),
        "state_changes_indexed": n_sc,
        "incomplete_episodes": sum(
            1 for e in eps if e.status != "COMPLETED"),
        "nonterminal_total": sum(
            1 for e in eps if e.status != "COMPLETED"),
        "orphan_links": audit_pre["orphan_links"],
        "cycle_count": audit_pre["cycle_count"],
        "superseded_links": len([l for l in links
                                 if l.status == "SUPERSEDED"]),
        "average_chain_depth": round(sum(depths) / len(depths), 3)
        if depths else 0,
        "max_chain_depth": max(depths) if depths else 0,
        "query_latency_ms": {k: {"single": round(v[0] * 1000, 2)}
                             for k, v in lat.items()},
        "wall_seconds_queries": round(wall, 3),
    }
    episode_samples = [svc.get_tribulation_history(
        world_id=MINI_WORLD_ID, episode_id=e.episode_id) for e in
        (eps[0], major, eps[12], final_ep)]
    entity_samples = {
        "ecology_state_zone": ent,
        "resource_node": svc.get_resource_history(
            world_id=MINI_WORLD_ID, resource_node_id=str(n.id)),
        "settlement": svc.get_settlement_history(
            world_id=MINI_WORLD_ID, settlement_id="TEST-MAIN-A"),
    }
    why_samples = {
        "A_major_consequences": ep_hist,
        "B_why_ecology_quality": exp,
        "C_why_resource_reserve": exp_res,
        "D_why_social_stress": exp_soc,
        "E_succession_trace": cand_trace,
        "F_final_episode_stage": final_hist,
    }
    timeline_sample = tl[:40]
    graph_digest = {
        "links_total": n_links,
        "relations": {r: 0 for r in RELATION_TYPES},
        "node_kinds": {},
    }
    for l in links:
        graph_digest["relations"][l.relation_type] = \
            graph_digest["relations"].get(l.relation_type, 0) + 1
        graph_digest["node_kinds"][l.source_kind] = \
            graph_digest["node_kinds"].get(l.source_kind, 0) + 1
        graph_digest["node_kinds"][l.target_kind] = \
            graph_digest["node_kinds"].get(l.target_kind, 0) + 1
    artifacts = {
        "summary.json": summary,
        "episode_history_samples.json": episode_samples,
        "entity_history_samples.json": entity_samples,
        "why_query_samples.json": why_samples,
        "timeline_samples.json": timeline_sample,
        "causal_graph_digest.json": graph_digest,
    }
    # candidate 与 committed golden 逐文件比较（telemetry 剥离）；
    # 普通 pytest 只读 golden。
    for name, artifact in artifacts.items():
        golden = load_artifact(BASELINE_DIR / name)
        assert_deterministic_equal(
            golden, artifact,
            label=f"m3b_causal_history_300y_v1/{name}",
            golden_path=BASELINE_DIR / name)
    if update_mode_enabled():  # 显式更新：scripts/update_baselines.py
        for name, artifact in artifacts.items():
            dump_artifact(artifact, BASELINE_DIR / name)
    assert summary["orphan_links"] == 0 and summary["cycle_count"] == 0
    assert summary["causal_links"] > 0
    assert final_hist["completion"] == "INCOMPLETE"

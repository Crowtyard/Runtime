# -*- coding: utf-8 -*-
"""M2d Social Foundation 测试：SD1–SD55 + S1–S10 崩溃矩阵 + 120y 基线。

全部运行于 tmp 临时库（mini_world with_ecology+with_social）；正式 DB 零接触。
"""
from __future__ import annotations

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
from tests.golden_baseline import (assert_deterministic_equal, dump_artifact,
                                   golden_bytes_guard, load_artifact,
                                   update_mode_enabled)

from XiaoguangBlessedLandRuntime.database.models_core import (SimulationCheckpoint,
                                                              WorldEvent,
                                                              WorldRuntime)
from XiaoguangBlessedLandRuntime.database.models_world import (
    EcologyState, Household, Institution, Lineage, Person, PopulationGroup,
    ResourceNode, ResourceStock, SettlementSocialState, SocialFeedbackState)
from XiaoguangBlessedLandRuntime.domain.errors import FencingViolation
from XiaoguangBlessedLandRuntime.services import fencing as fencing_mod
from XiaoguangBlessedLandRuntime.services.catchup import catch_up
from XiaoguangBlessedLandRuntime.services.fencing import WorldMutationContext
from XiaoguangBlessedLandRuntime.services.simulation.contracts import (
    ENGINE_ORDER)
from XiaoguangBlessedLandRuntime.services.simulation.coordinator import (
    SimulationCoordinator)
from XiaoguangBlessedLandRuntime.services.simulation.ecology import (
    EcologyEngine)
from XiaoguangBlessedLandRuntime.services.simulation.economy import (
    ENGINE_VERSION as ECO_ECON_VERSION)
from XiaoguangBlessedLandRuntime.services.simulation.economy import EconomyEngine
from XiaoguangBlessedLandRuntime.services.simulation.event_stream import (
    step_event_stream_hash)
from XiaoguangBlessedLandRuntime.services.simulation.harness import (
    YEAR_US, run_mini_world_120y)
from XiaoguangBlessedLandRuntime.services.simulation.mini_world import (
    MINI_WORLD_ID)
from XiaoguangBlessedLandRuntime.services.simulation.population import (
    PopulationGroupEngine)
from XiaoguangBlessedLandRuntime.services.simulation.recovery import (
    latest_authoritative_world_checkpoint)
from XiaoguangBlessedLandRuntime.services.simulation.resource import (
    ENGINE_VERSION as ECO_RES_VERSION)
from XiaoguangBlessedLandRuntime.services.simulation.resource import ResourceEngine
from XiaoguangBlessedLandRuntime.services.simulation.snapshot import \
    read_snapshot
from XiaoguangBlessedLandRuntime.services.simulation.social import (
    ENGINE_VERSION as SOC_ENGINE_VERSION)
from XiaoguangBlessedLandRuntime.services.simulation.social import (
    SOCIAL_PROFILES, SOCIAL_STATE_SCALE, SocialEngine, SocialProfileUnconfigured)
from XiaoguangBlessedLandRuntime.services.simulation.state_hash import (
    WORLD_STATE_HASH_SCHEMA_VERSION_V5, world_state_hash_v5)
from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease

REPO = PROJECT_ROOT
# M2 Review（ID 硬化 social-v1→social-v2）后：新基线 v2；
# 旧 v1（64-bit ID）保留为 m2d_social_miniworld_120y_v1_pre_id_hardening.json
# 冻结历史（不复现、不覆盖）。
BASELINE_PATH = REPO / "tests" / "baselines" / \
    "m2d_social_miniworld_120y_v2.json"
SIM_DIR = REPO / "services" / "simulation"
SIM_VERSION = "0.2.0-preflight"

# GB2：本模块每个测试前后 golden baseline 字节必须不变
_golden_bytes_guard = golden_bytes_guard(BASELINE_PATH)


def _fresh_social(tmp_path, i: int):
    """独立 M2d 环境：迁移 + 激活测试世界 +
    seed_mini_world(with_ecology=True, with_social=True)。"""
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
    db_path = tmp_path / f"mini_soc_{i}.db"
    url = "sqlite:///" + str(db_path).replace("\\", "/")
    migrate_database(url, project_root=REPO)
    engine = create_db_engine(url)
    factory = make_session_factory(engine)
    with factory() as s:
        RuntimeRepository(s).create_not_activated(
            world_id=MINI_WORLD_ID, world_bible_version="1.0",
            simulation_version=SIM_VERSION, world_bible_manifest_hash="mini")
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
        seed_mini_world(s, with_ecology=True, with_social=True)
        s.commit()
    return {"url": url, "factory": factory, "db_path": db_path}


def _engines(**kw):
    return [kw.get("pop") or PopulationGroupEngine(),
            kw.get("res") or ResourceEngine(),
            kw.get("eco") or EconomyEngine(),
            kw.get("ecol") or EcologyEngine(),
            kw.get("soc") or SocialEngine()]


def _run(env, years=120, **kw):
    engines = kw.pop("engines", None)
    if engines is None:
        engines = [kw.pop("pop", None) or PopulationGroupEngine(),
                   kw.pop("res", None) or ResourceEngine(),
                   kw.pop("eco", None) or EconomyEngine(),
                   kw.pop("ecol", None) or EcologyEngine(),
                   kw.pop("soc", None) or SocialEngine()]
    return run_mini_world_120y(env["factory"], engines=engines, years=years,
                               **kw)


def _hh_sums(env) -> dict:
    with env["factory"]() as s:
        out: dict = {}
        for h in s.execute(select(Household)).scalars():
            if h.state != "ACTIVE":
                continue
            key = (h.settlement_ref, h.species)
            out[key] = out.get(key, 0) + h.represented_population
        return out


def _pop_sums(env) -> dict:
    with env["factory"]() as s:
        out: dict = {}
        for g in s.execute(select(PopulationGroup)).scalars():
            key = (g.settlement_ref, g.species)
            out[key] = out.get(key, 0) + g.count
        return out


# ------------------------------------------------------------ SD1-SD6
def test_sd1_social_engine_conforms_protocol():
    e = SocialEngine()
    assert e.engine_id == "SOCIAL"
    assert e.engine_version == "m2d-social-1"
    assert all(hasattr(e, a) for a in ("engine_id", "engine_version",
                                       "simulate"))
    assert callable(e.simulate)


def test_sd2_pipeline_order_d_r_e_ecology_social():
    assert ENGINE_ORDER == ("DEMOGRAPHY", "RESOURCE", "ECONOMY",
                            "ECOLOGY", "SOCIAL")
    with pytest.raises(Exception):
        SimulationCoordinator([SocialEngine(), EcologyEngine(),
                               EconomyEngine(), ResourceEngine(),
                               PopulationGroupEngine()])


def test_sd3_no_direct_commit():
    src = (SIM_DIR / "social.py").read_text(encoding="utf-8")
    assert "session.commit" not in src
    assert ".commit()" not in src
    assert "session.begin" not in src


def test_sd4_household_counts_integer(tmp_path):
    env = _fresh_social(tmp_path, 1)
    _run(env, years=5)
    with env["factory"]() as s:
        for h in s.execute(select(Household)).scalars():
            assert isinstance(h.represented_population, int)
            assert not isinstance(h.represented_population, float)


def test_sd5_household_represented_population_conserved(tmp_path):
    env = _fresh_social(tmp_path, 2)
    _run(env, years=60)
    assert _hh_sums(env) == _pop_sums(env)  # full-coverage 契约（==）


def test_sd6_no_duplicate_population_assignment(tmp_path):
    env = _fresh_social(tmp_path, 3)
    _run(env, years=60)
    with env["factory"]() as s:
        for h in s.execute(select(Household)).scalars():
            assert h.represented_population >= 0
            assert h.state in ("ACTIVE", "DISSOLVED")
        # 无重复占用：ACTIVE 归属和 == 总人口（full coverage ⇒ 恰一次分配）
    assert _hh_sums(env) == _pop_sums(env)


# ------------------------------------------------------------ SD7-SD11
def test_sd7_birth_reconciliation(tmp_path):
    env = _fresh_social(tmp_path, 4)
    rep = _run(env, years=1)
    assert rep.engine_metrics["DEMOGRAPHY"]["births"] > 0
    assert _hh_sums(env) == _pop_sums(env)


def test_sd8_death_reconciliation(tmp_path):
    env = _fresh_social(tmp_path, 5)
    rep = _run(env, years=10)
    assert rep.engine_metrics["DEMOGRAPHY"]["deaths"] > 0
    assert _hh_sums(env) == _pop_sums(env)


def test_sd9_migration_reconciliation(tmp_path):
    env = _fresh_social(tmp_path, 6)
    rep = _run(env, years=20)
    assert rep.engine_metrics["DEMOGRAPHY"]["emigration"] > 0
    assert _hh_sums(env) == _pop_sums(env)


def test_sd10_deterministic_household_formation(tmp_path):
    a = _fresh_social(tmp_path, 7)
    b = _fresh_social(tmp_path, 8)
    for env in (a, b):
        with env["factory"]() as s:
            for h in s.execute(select(Household)).scalars():
                s.delete(h)
            s.commit()
    ra = _run(a, years=1)
    rb = _run(b, years=1)
    assert ra.engine_metrics["SOCIAL"]["households_formed"] \
        == rb.engine_metrics["SOCIAL"]["households_formed"] > 0
    assert _hh_sums(a) == _pop_sums(a)
    assert _hh_sums(b) == _pop_sums(b)


def test_sd11_deterministic_household_dissolution(tmp_path):
    a = _fresh_social(tmp_path, 9)
    b = _fresh_social(tmp_path, 10)
    for env in (a, b):
        with env["factory"]() as s:
            for g in s.execute(select(PopulationGroup)).scalars():
                g.count = 0
            s.commit()
    ra = _run(a, years=1)
    rb = _run(b, years=1)
    assert ra.engine_metrics["SOCIAL"]["households_dissolved"] \
        == rb.engine_metrics["SOCIAL"]["households_dissolved"] > 0
    with a["factory"]() as s:
        active = s.execute(select(Household).where(
            Household.state == "ACTIVE")).scalars().all()
        assert len(active) == 0


# ------------------------------------------------------------ SD12-SD19
def test_sd12_lineage_identity_deterministic(tmp_path):
    a = _fresh_social(tmp_path, 11)
    b = _fresh_social(tmp_path, 12)
    _run(a, years=60)
    _run(b, years=60)
    with a["factory"]() as s:
        la = {lg.lineage_id for lg in s.execute(select(Lineage)).scalars()}
    with b["factory"]() as s:
        lb = {lg.lineage_id for lg in s.execute(select(Lineage)).scalars()}
    assert la == lb


def test_sd13_lineage_persists_across_generations(tmp_path):
    env = _fresh_social(tmp_path, 13)
    rep = _run(env, years=120)
    assert rep.engine_metrics["SOCIAL"]["lineages_founded"] > 0
    with env["factory"]() as s:
        active = s.execute(select(Lineage).where(
            Lineage.status == "ACTIVE")).scalars().all()
        assert active
        assert max(lg.generation for lg in active) >= 3


def test_sd14_lineage_extinction_identity_retained(tmp_path):
    # 构造灭绝场景：B 人口归零 → 下一 Step B lineage EXTINCT 且 identity 保留
    env = _fresh_social(tmp_path, 14)
    with env["factory"]() as s:
        for g in s.execute(select(PopulationGroup).where(
                PopulationGroup.settlement_ref == "TEST-SATELLITE-B"
        )).scalars():
            g.count = 0
        s.commit()
    rep = _run(env, years=1)
    assert rep.engine_metrics["SOCIAL"]["lineages_extinct"] == 1
    with env["factory"]() as s:
        b_lineage = s.execute(select(Lineage).where(
            Lineage.lineage_id == "TEST-LINEAGE-B-001")).scalar_one()
        assert b_lineage.status == "EXTINCT"
        assert b_lineage.lineage_id == "TEST-LINEAGE-B-001"  # identity 保留
        assert b_lineage.represented_population == 0


def test_sd15_no_lineage_ancestry_cycle(tmp_path):
    env = _fresh_social(tmp_path, 15)
    _run(env, years=60)
    with env["factory"]() as s:
        rows = s.execute(select(Lineage)).scalars().all()
        by_id = {lg.lineage_id: lg for lg in rows if lg.lineage_id}
        for lg in rows:
            if not lg.parent_lineage_ref:
                continue
            assert lg.parent_lineage_ref != lg.lineage_id  # SOC_INV_11
            seen = {lg.lineage_id}
            cur = by_id.get(lg.parent_lineage_ref)
            while cur is not None:
                assert cur.lineage_id not in seen  # SOC_INV_12 无环
                seen.add(cur.lineage_id)
                cur = by_id.get(cur.parent_lineage_ref) \
                    if cur.parent_lineage_ref else None


def test_sd16_multi_settlement_lineage_structurally_supported(tmp_path):
    env = _fresh_social(tmp_path, 16)
    with env["factory"]() as s:
        hh = s.execute(select(Household).where(
            Household.settlement_ref == "TEST-MAIN-A")).scalars().first()
        hh.lineage_ref = "TEST-LINEAGE-B-001"  # A 户并入 B lineage
        s.commit()
    _run(env, years=1)  # 不报错：跨聚落 lineage 被引擎正常聚合
    with env["factory"]() as s:
        lg = s.execute(select(Lineage).where(
            Lineage.lineage_id == "TEST-LINEAGE-B-001")).scalar_one()
        assert lg.household_count >= 4  # 3（B）+ 1（A）


def test_sd17_institution_identity_deterministic(tmp_path):
    a = _fresh_social(tmp_path, 17)
    b = _fresh_social(tmp_path, 18)
    _run(a, years=20)
    _run(b, years=20)
    with a["factory"]() as s:
        ia = {i.institution_id: i.state for i in s.execute(
            select(Institution)).scalars()}
    with b["factory"]() as s:
        ib = {i.institution_id: i.state for i in s.execute(
            select(Institution)).scalars()}
    assert ia == ib


def test_sd18_institution_lifecycle_deterministic(tmp_path):
    a = _fresh_social(tmp_path, 19)
    b = _fresh_social(tmp_path, 20)
    ra = _run(a, years=30)
    rb = _run(b, years=30)
    assert ra.engine_metrics["SOCIAL"]["institution_state_transitions"] \
        == rb.engine_metrics["SOCIAL"]["institution_state_transitions"]
    assert ra.engine_metrics["SOCIAL"]["institution_state_transitions"] > 0


def test_sd19_dissolved_institution_modifiers_inactive(tmp_path):
    a = _fresh_social(tmp_path, 21)
    b = _fresh_social(tmp_path, 22)
    with b["factory"]() as s:
        for i in s.execute(select(Institution)).scalars():
            i.state = "DISSOLVED"
        s.commit()
    ra = _run(a, years=1)
    rb = _run(b, years=1)
    # 机构不产生 active modifier：反馈只来自 stress 公式 → 两环境一致
    with a["factory"]() as s:
        fa = {r.settlement_ref: (r.migration_modifier_num,
                                 r.migration_modifier_den)
              for r in s.execute(select(SocialFeedbackState)).scalars()}
    with b["factory"]() as s:
        fb = {r.settlement_ref: (r.migration_modifier_num,
                                 r.migration_modifier_den)
              for r in s.execute(select(SocialFeedbackState)).scalars()}
    assert fa == fb


# ------------------------------------------------------------ SD20-SD24
def test_sd20_social_fixed_point_bounded(tmp_path):
    env = _fresh_social(tmp_path, 23)
    _run(env, years=60)
    with env["factory"]() as s:
        for r in s.execute(select(SettlementSocialState)).scalars():
            assert 0 <= r.social_stress <= SOCIAL_STATE_SCALE
            assert 0 <= r.social_cohesion <= SOCIAL_STATE_SCALE
            assert 0 <= r.household_stability <= SOCIAL_STATE_SCALE
            assert 0 <= r.mobility_pressure <= SOCIAL_STATE_SCALE
            assert isinstance(r.social_stress, int)


def test_sd21_economic_pressure_declared_input_only():
    src = (SIM_DIR / "social.py").read_text(encoding="utf-8")
    assert "economic_pressure_state" in src  # 声明输入
    assert "resource_nodes" not in src       # 不读资源私有状态
    assert "resource_stocks" not in src      # 不读库存私有状态
    assert "production_state" not in src


def test_sd22_ecology_pressure_declared_input_only():
    src = (SIM_DIR / "social.py").read_text(encoding="utf-8")
    assert "ecology_feedback_state" in src
    assert "ecology_state" not in src        # 只读反馈信号，不读生态私有状态


def test_sd23_same_step_social_feedback_prohibited(tmp_path):
    # 第 1 步 DEMOGRAPHY 读到的社会反馈必须是 neutral（种子 1/1）——
    # 本步 Social 结果绝不回写本步 DEMOGRAPHY。
    social_env = _fresh_social(tmp_path, 24)
    rep1 = _run(social_env, years=1)
    from tests.test_m2c_ecology import _fresh_eco as _eco
    eco_env = _eco(tmp_path, 25)
    rep2 = run_mini_world_120y(
        eco_env["factory"],
        engines=[PopulationGroupEngine(), ResourceEngine(),
                 EconomyEngine(), EcologyEngine()], years=1)
    assert rep1.engine_metrics["DEMOGRAPHY"] == rep2.engine_metrics["DEMOGRAPHY"]


def test_sd24_next_step_social_feedback_deterministic(tmp_path):
    a = _fresh_social(tmp_path, 26)
    b = _fresh_social(tmp_path, 27)
    with a["factory"]() as s:
        for fb in s.execute(select(SocialFeedbackState)).scalars():
            fb.migration_modifier_num = 3
            fb.migration_modifier_den = 2  # 预置上一 step 的高迁移压力
        s.commit()
    ra = _run(a, years=1)
    rb = _run(b, years=1)
    assert ra.engine_metrics["DEMOGRAPHY"]["emigration"] \
        > rb.engine_metrics["DEMOGRAPHY"]["emigration"]
    # 确定性：同预置环境重跑一致
    a2 = _fresh_social(tmp_path, 28)
    with a2["factory"]() as s:
        for fb in s.execute(select(SocialFeedbackState)).scalars():
            fb.migration_modifier_num = 3
            fb.migration_modifier_den = 2
        s.commit()
    ra2 = _run(a2, years=1)
    assert ra2.engine_metrics["DEMOGRAPHY"] == ra.engine_metrics["DEMOGRAPHY"]


# ------------------------------------------------------------ SD25-SD29
def test_sd25_social_cannot_mutate_population(tmp_path):
    env = _fresh_social(tmp_path, 29)
    before = _pop_sums(env)
    run_mini_world_120y(env["factory"], engines=[SocialEngine()], years=1)
    assert _pop_sums(env) == before
    src = (SIM_DIR / "social.py").read_text(encoding="utf-8")
    assert 'table="population_groups"' not in src


def test_sd26_social_cannot_mutate_economy(tmp_path):
    env = _fresh_social(tmp_path, 30)
    with env["factory"]() as s:
        before = {r.id: r.quantity for r in s.execute(
            select(ResourceStock)).scalars()}
    run_mini_world_120y(env["factory"], engines=[SocialEngine()], years=1)
    with env["factory"]() as s:
        after = {r.id: r.quantity for r in s.execute(
            select(ResourceStock)).scalars()}
    assert before == after
    src = (SIM_DIR / "social.py").read_text(encoding="utf-8")
    assert 'table="resource_stocks"' not in src


def test_sd27_social_cannot_mutate_ecology(tmp_path):
    env = _fresh_social(tmp_path, 31)
    with env["factory"]() as s:
        before = {r.id: r.habitat_quality for r in s.execute(
            select(EcologyState)).scalars()}
    run_mini_world_120y(env["factory"], engines=[SocialEngine()], years=1)
    with env["factory"]() as s:
        after = {r.id: r.habitat_quality for r in s.execute(
            select(EcologyState)).scalars()}
    assert before == after
    src = (SIM_DIR / "social.py").read_text(encoding="utf-8")
    assert 'table="ecology_state"' not in src


def test_sd28_social_event_uid_deterministic(tmp_path):
    a = _fresh_social(tmp_path, 32)
    b = _fresh_social(tmp_path, 33)
    _run(a, years=3)
    _run(b, years=3)
    with a["factory"]() as s:
        ua = [e.event_uid for e in s.execute(select(WorldEvent)).scalars()
              if e.event_type.startswith(("HOUSEHOLD", "LINEAGE",
                                          "INSTITUTION", "SOCIAL_"))]
    with b["factory"]() as s:
        ub = [e.event_uid for e in s.execute(select(WorldEvent)).scalars()
              if e.event_type.startswith(("HOUSEHOLD", "LINEAGE",
                                          "INSTITUTION", "SOCIAL_"))]
    assert ua == ub
    assert all(re.fullmatch(r"[0-9a-f]{32}", u) for u in ua)


def test_sd29_event_payload_affects_event_stream_hash():
    base = [{"event_uid": "c" * 32, "blessed_tick": 1,
             "event_type": "HOUSEHOLD_FORMED", "source": "SIMULATION",
             "cause": {"settlement": "A"},
             "effect": {"household_id": "h1", "size": 5, "generation": 1},
             "severity": 0.0, "scope": "WORLD"}]
    changed = [dict(base[0], effect={**base[0]["effect"], "size": 9})]
    h1 = step_event_stream_hash(None, world_id="W",
                                simulation_version=SIM_VERSION, events=base)
    h2 = step_event_stream_hash(None, world_id="W",
                                simulation_version=SIM_VERSION,
                                events=changed)
    assert h1 != h2


# ------------------------------------------------------------ SD30-SD33
def test_sd30_social_state_included_in_world_hash(tmp_path):
    env = _fresh_social(tmp_path, 34)
    _run(env, years=2)
    h1 = _hash_v5(env)
    with env["factory"]() as s:
        st = s.execute(select(SettlementSocialState)).scalars().first()
        st.social_stress += 1
        s.commit()
    h2 = _hash_v5(env)
    assert h1 != h2


def test_sd31_hash_row_order_independent(tmp_path):
    env1 = _fresh_social(tmp_path, 35)
    h1 = _hash_v5(env1)
    env2 = _fresh_social(tmp_path, 36)
    with env2["factory"]() as s:
        rows = s.execute(select(Household)).scalars().all()
        for r in rows:
            s.delete(r)
        s.flush()
        for r in reversed(rows):
            s.add(Household(
                world_id=r.world_id, household_id=r.household_id,
                settlement_ref=r.settlement_ref, species=r.species,
                represented_population=r.represented_population,
                generation=r.generation, lineage_ref=r.lineage_ref,
                anchor_group_ref=r.anchor_group_ref, state=r.state,
                formation_version=r.formation_version,
                updated_blessed_tick=r.updated_blessed_tick))
        s.commit()
    h2 = _hash_v5(env2)
    assert h1 == h2


def test_sd32_social_rng_isolated(tmp_path):
    base = _run(_fresh_social(tmp_path, 37), years=4)
    extra = _run(_fresh_social(tmp_path, 38), years=4,
                 soc=SocialEngine(extra_draws=11))
    for eid in ("DEMOGRAPHY", "RESOURCE", "ECONOMY", "ECOLOGY", "SOCIAL"):
        assert extra.engine_metrics[eid] == base.engine_metrics[eid]
    assert extra.final_state_hash == base.final_state_hash


def test_sd33_no_mass_persistent_person_creation(tmp_path):
    env = _fresh_social(tmp_path, 39)
    _run(env, years=120)
    with env["factory"]() as s:
        assert s.execute(select(Person)).scalars().all() == []  # 默认 0


# ------------------------------------------------------------ SD34-SD38
def test_sd34_retry_no_duplicate_household(tmp_path):
    env = _fresh_social(tmp_path, 40)
    _run(env, years=1)
    with env["factory"]() as s:
        before = {h.household_id: (h.state, h.represented_population)
                  for h in s.execute(select(Household)).scalars()}
    _run(env, years=1)
    with env["factory"]() as s:
        after = {h.household_id: (h.state, h.represented_population)
                 for h in s.execute(select(Household)).scalars()}
    assert before == after


def test_sd35_retry_no_duplicate_lineage(tmp_path):
    env = _fresh_social(tmp_path, 41)
    _run(env, years=1)
    with env["factory"]() as s:
        before = {lg.lineage_id: lg.status for lg in s.execute(
            select(Lineage)).scalars()}
    _run(env, years=1)
    with env["factory"]() as s:
        after = {lg.lineage_id: lg.status for lg in s.execute(
            select(Lineage)).scalars()}
    assert before == after


def test_sd36_retry_no_duplicate_institution(tmp_path):
    env = _fresh_social(tmp_path, 42)
    _run(env, years=1)
    with env["factory"]() as s:
        before = {i.institution_id: i.state for i in s.execute(
            select(Institution)).scalars()}
    _run(env, years=1)
    with env["factory"]() as s:
        after = {i.institution_id: i.state for i in s.execute(
            select(Institution)).scalars()}
    assert before == after


def test_sd37_retry_no_duplicate_social_events(tmp_path):
    env = _fresh_social(tmp_path, 43)
    _run(env, years=1)
    with env["factory"]() as s:
        uids = {e.event_uid for e in s.execute(select(WorldEvent)).scalars()}
    _run(env, years=1)
    with env["factory"]() as s:
        assert {e.event_uid for e in s.execute(
            select(WorldEvent)).scalars()} == uids


def test_sd38_stale_writer_cannot_commit_social(tmp_path):
    env = _fresh_social(tmp_path, 44)
    factory = env["factory"]
    s1 = factory()
    lease = WriterLease(s1, MINI_WORLD_ID, 120)
    lease.acquire()
    coordinator = SimulationCoordinator(_engines())
    with pytest.raises(FencingViolation):
        with WorldMutationContext(factory(), world_id=MINI_WORLD_ID,
                                  writer_id=lease.owner,
                                  fencing_token=lease.token) as ctx:
            coordinator.run_step(
                ctx.session, world_id=MINI_WORLD_ID,
                blessed_start_tick=0, blessed_end_tick=1_000_000,
                real_interval_start_us=EPOCH0_US,
                real_interval_end_us=EPOCH0_US + YEAR_US)
            ctx.session.execute(text(
                "UPDATE runtime_lock SET lease_token='STOLEN'"))
            ctx.commit()
    with factory() as s:
        assert len(s.execute(select(Household)).scalars().all()) == 80
        assert s.execute(text(
            "SELECT COUNT(*) FROM world_events")).scalar() == 0
    lease.release()
    s1.close()


# ------------------------------------------------------------ SD39-SD44
def _crash_and_recover_soc(tmp_path, i, crash_after):
    env = _fresh_social(tmp_path, i)
    factory = env["factory"]
    s1 = factory()
    lease = WriterLease(s1, MINI_WORLD_ID, 120)
    lease.acquire()
    coordinator = SimulationCoordinator(_engines())

    def step(s, info, _ca=None):
        return coordinator.run_step(
            s, world_id=MINI_WORLD_ID,
            blessed_start_tick=info["new_blessed_tick"] - info["delta_ticks"],
            blessed_end_tick=info["new_blessed_tick"],
            real_interval_start_us=info["real_interval_start_us"],
            real_interval_end_us=info["real_interval_end_us"],
            step_index=1, crash_after=_ca)

    with pytest.raises(RuntimeError):
        catch_up(factory, world_id=MINI_WORLD_ID,
                 now_real_us=EPOCH0_US + YEAR_US,
                 writer_id=lease.owner, fencing_token=lease.token,
                 simulation_version=SIM_VERSION,
                 simulate_fn=lambda s, info: step(s, info, crash_after))
    with factory() as s:
        assert s.execute(select(WorldRuntime)).scalar_one() \
            .current_blessed_tick == 0
        assert len(s.execute(select(Household)).scalars().all()) == 80
        assert latest_authoritative_world_checkpoint(s, MINI_WORLD_ID) is None
    catch_up(factory, world_id=MINI_WORLD_ID,
             now_real_us=EPOCH0_US + YEAR_US,
             writer_id=lease.owner, fencing_token=lease.token,
             simulation_version=SIM_VERSION, simulate_fn=step)
    ref = _run(_fresh_social(tmp_path, i + 1000), years=1)
    with factory() as s:
        h = latest_authoritative_world_checkpoint(s, MINI_WORLD_ID) \
            .world_state_hash
    assert h == ref.final_state_hash
    lease.release()
    s1.close()


def test_sd39_crash_mid_household_reconciliation(tmp_path):
    _crash_and_recover_soc(tmp_path, 45, "mid:SOCIAL_HOUSEHOLD")


def test_sd40_crash_mid_lineage(tmp_path):
    _crash_and_recover_soc(tmp_path, 46, "mid:SOCIAL_LINEAGE")


def test_sd41_crash_mid_institution(tmp_path):
    _crash_and_recover_soc(tmp_path, 47, "mid:SOCIAL_INSTITUTION")


def test_sd42_crash_after_social_staged(tmp_path):
    _crash_and_recover_soc(tmp_path, 48, "after_engines")


def test_sd43_commit_ack_lost_already_committed(tmp_path, monkeypatch):
    env = _fresh_social(tmp_path, 49)
    factory = env["factory"]
    s1 = factory()
    lease = WriterLease(s1, MINI_WORLD_ID, 120)
    lease.acquire()
    original = fencing_mod.WorldMutationContext.commit
    state = {"calls": 0}

    def patched(self):
        original(self)
        state["calls"] += 1
        if state["calls"] == 2:
            raise RuntimeError("simulated COMMIT ACK LOST")

    monkeypatch.setattr(fencing_mod.WorldMutationContext, "commit", patched)
    coordinator = SimulationCoordinator(_engines())
    with pytest.raises(RuntimeError, match="ACK LOST"):
        catch_up(factory, world_id=MINI_WORLD_ID,
                 now_real_us=EPOCH0_US + YEAR_US,
                 writer_id=lease.owner, fencing_token=lease.token,
                 simulation_version=SIM_VERSION,
                 simulate_fn=lambda s, info: coordinator.run_step(
                     s, world_id=MINI_WORLD_ID,
                     blessed_start_tick=info["new_blessed_tick"]
                     - info["delta_ticks"],
                     blessed_end_tick=info["new_blessed_tick"],
                     real_interval_start_us=info["real_interval_start_us"],
                     real_interval_end_us=info["real_interval_end_us"],
                     step_index=1))
    with factory() as s:
        assert s.execute(select(WorldRuntime)).scalar_one() \
            .current_blessed_tick == 1_000_000
        hh_before = {h.household_id: (h.state, h.represented_population)
                     for h in s.execute(select(Household)).scalars()}
        lg_before = {lg.lineage_id: lg.status for lg in s.execute(
            select(Lineage)).scalars()}
        inst_before = {i.institution_id: i.state for i in s.execute(
            select(Institution)).scalars()}
    monkeypatch.setattr(fencing_mod.WorldMutationContext, "commit", original)
    res = catch_up(factory, world_id=MINI_WORLD_ID,
                   now_real_us=EPOCH0_US + YEAR_US,
                   writer_id=lease.owner, fencing_token=lease.token,
                   simulation_version=SIM_VERSION)
    assert res.skipped is True
    with factory() as s:
        assert {h.household_id: (h.state, h.represented_population)
                for h in s.execute(select(Household)).scalars()} == hh_before
        assert {lg.lineage_id: lg.status for lg in s.execute(
            select(Lineage)).scalars()} == lg_before
        assert {i.institution_id: i.state for i in s.execute(
            select(Institution)).scalars()} == inst_before
    lease.release()
    s1.close()


def test_sd44_world_checkpoint_includes_social_state(tmp_path):
    env = _fresh_social(tmp_path, 50)
    rep = _run(env, years=3)
    with env["factory"]() as s:
        world = latest_authoritative_world_checkpoint(s, MINI_WORLD_ID)
        assert world.meta["engine_versions"]["SOCIAL"] == SOC_ENGINE_VERSION
    assert rep.final_state_hash == _hash_v5(env)


# ------------------------------------------------------------ S1-S8 崩溃矩阵
@pytest.mark.parametrize("crash_after", [
    pytest.param("engine:SOCIAL", id="S1-before-social"),
    pytest.param("mid:SOCIAL_HOUSEHOLD", id="S2-mid-household"),
    pytest.param("after:SOCIAL_HOUSEHOLD", id="S3-after-household-staged"),
    pytest.param("mid:SOCIAL_LINEAGE", id="S4-mid-lineage"),
    pytest.param("after:SOCIAL_LINEAGE", id="S5-after-lineage-staged"),
    pytest.param("mid:SOCIAL_INSTITUTION", id="S6-mid-institution"),
    pytest.param("after_engines", id="S7-after-social-staged"),
    pytest.param("during_apply", id="S8-during-social-db-write"),
])
def test_sd_crash_matrix_s1_s8(tmp_path, crash_after):
    _crash_and_recover_soc(tmp_path, 100 + hash(crash_after) % 300, crash_after)


def test_sd_s9_fencing_recheck_blocks_social(tmp_path):
    """S9：commit 前 fencing 重检（token 被窃）→ 零 Social authoritative write。"""
    env = _fresh_social(tmp_path, 51)
    factory = env["factory"]
    s1 = factory()
    lease = WriterLease(s1, MINI_WORLD_ID, 120)
    lease.acquire()
    coordinator = SimulationCoordinator(_engines())
    with pytest.raises(FencingViolation):
        with WorldMutationContext(factory(), world_id=MINI_WORLD_ID,
                                  writer_id=lease.owner,
                                  fencing_token=lease.token) as ctx:
            coordinator.run_step(
                ctx.session, world_id=MINI_WORLD_ID,
                blessed_start_tick=0, blessed_end_tick=1_000_000,
                real_interval_start_us=EPOCH0_US,
                real_interval_end_us=EPOCH0_US + YEAR_US)
            ctx.session.execute(text(
                "UPDATE runtime_lock SET lease_token='STOLEN'"))
            ctx.commit()
    with factory() as s:
        assert len(s.execute(select(Household)).scalars().all()) == 80
        assert s.execute(text(
            "SELECT COUNT(*) FROM simulation_checkpoints")).scalar() == 0
    lease.release()
    s1.close()


# ------------------------------------------------------------ SD45-SD48
def test_sd45_120y_run_completes(tmp_path):
    env = _fresh_social(tmp_path, 52)
    rep = _run(env, years=120)
    assert rep.steps == 120 and rep.runs == 120 and rep.checkpoints == 240
    assert rep.final_blessed_tick == 120_000_000
    soc = rep.engine_metrics["SOCIAL"]
    assert soc["households_split"] > 0
    assert soc["lineages_founded"] > 0       # lineage 涌现
    assert soc["institution_state_transitions"] > 0
    assert soc["feedback_applications"] == 240
    with env["factory"]() as s:
        lgs = s.execute(select(Lineage)).scalars().all()
        # 分化：至少 1 条子 lineage（parent_lineage_ref 非空）——
        # 灭绝路径由 SD14 构造场景覆盖（B 家系在 120y 内扩张并分化）
        assert sum(1 for lg in lgs if lg.parent_lineage_ref) >= 1
        assert max(lg.generation for lg in lgs) >= 5  # 跨代延续


def test_sd46_120y_social_invariants_pass(tmp_path):
    env = _fresh_social(tmp_path, 53)
    _run(env, years=120)
    assert _hh_sums(env) == _pop_sums(env)         # SOC_INV_02/03
    with env["factory"]() as s:
        for h in s.execute(select(Household)).scalars():
            assert h.represented_population >= 0     # SOC_INV_01
            assert isinstance(h.represented_population, int)  # SOC_INV_08
            assert h.state in ("ACTIVE", "DISSOLVED")
            if h.state == "DISSOLVED":
                assert h.represented_population == 0  # SOC_INV_07
            if h.anchor_group_ref:
                assert s.execute(select(PopulationGroup).where(
                    PopulationGroup.age_cohort == h.anchor_group_ref
                )).scalars().first() is not None     # SOC_INV_05
        settlements = set(s.execute(select(
            PopulationGroup.settlement_ref)).scalars())
        for h in s.execute(select(Household)).scalars():
            assert h.settlement_ref in settlements  # SOC_INV_04
        for lg in s.execute(select(Lineage)).scalars():
            if lg.lineage_id:
                assert lg.represented_population >= 0    # SOC_INV_09
                assert lg.household_count >= 0           # SOC_INV_10
        for i in s.execute(select(Institution)).scalars():
            assert i.state in ("ACTIVE", "DECLINING",
                               "DORMANT", "DISSOLVED")  # SOC_INV_16
        for r in s.execute(select(SettlementSocialState)).scalars():
            assert 0 <= r.social_stress <= SOCIAL_STATE_SCALE  # SOC_INV_20
            assert r.unallocated_population == 0


def test_sd47_continuous_equals_chunked(tmp_path):
    one = _run(_fresh_social(tmp_path, 54), years=120)
    chunk = _run(_fresh_social(tmp_path, 55), years=120,
                 restart_every_years=30)
    assert one.final_state_hash == chunk.final_state_hash
    assert one.population == chunk.population
    assert one.resource == chunk.resource
    assert one.economy == chunk.economy
    assert one.ecology == chunk.ecology
    assert one.social == chunk.social
    assert one.engine_metrics == chunk.engine_metrics


def test_sd48_restart_equals_continuous(tmp_path):
    one = _run(_fresh_social(tmp_path, 56), years=120)
    env = _fresh_social(tmp_path, 57)
    part1 = _run(env, years=60)
    part2 = _run(env, years=60, start_year=60)
    assert part2.final_state_hash == one.final_state_hash
    assert part2.population["end"] == one.population["end"]
    assert part2.social["final_stress"] == one.social["final_stress"]
    for k in ("households_formed", "households_split", "households_dissolved",
              "lineages_founded", "lineages_extinct"):
        assert part1.engine_metrics["SOCIAL"][k] \
            + part2.engine_metrics["SOCIAL"][k] \
            == one.engine_metrics["SOCIAL"][k]


# ------------------------------------------------------------ SD49-SD55
def test_sd49_llm_zero():
    src = (SIM_DIR / "social.py").read_text(encoding="utf-8")
    for token in ("openai", "anthropic", "llm"):
        assert token not in src, token


def test_sd50_network_zero(tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("simulation core 触碰网络")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr("urllib.request.urlopen", _boom, raising=False)
    monkeypatch.setattr("http.client.HTTPConnection", _boom, raising=False)
    rep = _run(_fresh_social(tmp_path, 58), years=5)
    assert rep.final_blessed_tick == 5_000_000


def test_sd51_wall_clock_truth_zero():
    pattern = re.compile(
        r"\b(datetime\.now|time\.time|time\.monotonic|perf_counter"
        r"|time_ns|date\.today)\s*\(")
    src = (SIM_DIR / "social.py").read_text(encoding="utf-8")
    assert not pattern.search(src)


def test_sd52_formal_social_profiles_unconfigured():
    # 注册表只含 synthetic TEST profile；正式种族不绑定任何社会参数
    assert set(SOCIAL_PROFILES) == {"TEST-SOCIAL-PROFILE-001"}
    src = (SIM_DIR / "social.py").read_text(encoding="utf-8")
    for formal in ("Human", "Hairy Men", "Rockmen", "Mermen", "Mushroommen"):
        assert formal not in src


def test_sd53_world_seed_not_consumed():
    for py in SIM_DIR.rglob("*.py"):
        src = py.read_text(encoding="utf-8")
        assert "world_seed" not in src, py
        assert "04_population_baseline" not in src, py


def test_sd54_formal_db_empty_after_suite(formal_db_guard):
    path = os.environ.get("BLR_FORMAL_DB_PATH", "")
    if not path or formal_db_guard is None:
        pytest.skip("BLR_FORMAL_DB_PATH 未设置")
    import hashlib
    after = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    assert after == formal_db_guard
    conn = sqlite3.connect(path)
    try:
        assert conn.execute(
            "SELECT runtime_status FROM world_runtime").fetchone()[0] \
            == "NOT_ACTIVATED"
        existing = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for t in ("households", "settlement_social_state",
                  "social_feedback_state"):
            if t in existing:
                assert conn.execute(
                    f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] == 0, t
        assert conn.execute(
            "SELECT COUNT(*) FROM lineages").fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM institutions").fetchone()[0] == 0
    finally:
        conn.close()


def test_sd55_formal_db_integrity_ok(formal_db_guard):
    path = os.environ.get("BLR_FORMAL_DB_PATH", "")
    if not path or formal_db_guard is None:
        pytest.skip("BLR_FORMAL_DB_PATH 未设置")
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


# ------------------------------------------------------------ 120y 基线产物
def test_m2d_baseline_120y_artifact(tmp_path):
    start = datetime.now(timezone.utc)
    env = _fresh_social(tmp_path, 59)
    rep = _run(env, years=120)
    wall = (datetime.now(timezone.utc) - start).total_seconds()
    assert BASELINE_PATH.exists()
    # candidate 与 committed golden 比较（telemetry 剥离）；普通 pytest 只读
    artifact = _build_m2d_artifact(env, rep, wall)
    golden = load_artifact(BASELINE_PATH)
    assert_deterministic_equal(
        golden, artifact, label="m2d_social_miniworld_120y_v2",
        golden_path=BASELINE_PATH)
    env2 = _fresh_social(tmp_path, 60)
    rep2 = _run(env2, years=120)
    assert rep2.final_state_hash == golden["final_world_state_hash"]
    with env2["factory"]() as s:
        h2 = latest_authoritative_world_checkpoint(
            s, MINI_WORLD_ID).meta["event_stream_hash"]
    assert h2 == golden["final_event_stream_hash"]
    sm = golden["social_metrics"]
    assert rep2.social["final_stress"] == sm["final_stress"]
    for k in ("households_formed", "households_split", "households_dissolved",
              "lineages_founded", "lineages_extinct", "institutions_founded",
              "institutions_dissolved", "feedback_applications"):
        assert rep2.social[k] == sm[k], k
    if update_mode_enabled():  # 显式更新：scripts/update_baselines.py
        dump_artifact(artifact, BASELINE_PATH)


def _hash_v5(env) -> str:
    with env["factory"]() as s:
        snap = read_snapshot(s, MINI_WORLD_ID)
        return world_state_hash_v5(
            snapshot=snap, simulation_version=SIM_VERSION,
            pipeline_version="m2-preflight-1",
            engine_versions={"DEMOGRAPHY": "m2a-1",
                             "RESOURCE": ECO_RES_VERSION,
                             "ECONOMY": ECO_ECON_VERSION,
                             "ECOLOGY": "m2c-ecology-1",
                             "SOCIAL": SOC_ENGINE_VERSION})


def _write_m2d_baseline(env, rep, wall_seconds: float) -> None:
    """显式更新入口：仅 BLR_UPDATE_GOLDEN_BASELINES=1 时写 golden。"""
    dump_artifact(_build_m2d_artifact(env, rep, wall_seconds), BASELINE_PATH)


def _build_m2d_artifact(env, rep, wall_seconds: float) -> dict:
    with env["factory"]() as s:
        latest = latest_authoritative_world_checkpoint(s, MINI_WORLD_ID)
        event_hash = latest.meta["event_stream_hash"]
        hhs = [h for h in s.execute(select(Household)).scalars()]
        lgs = [lg for lg in s.execute(select(Lineage)).scalars()]
        insts = [i for i in s.execute(select(Institution)).scalars()]
        states = {r.settlement_ref: r for r in s.execute(
            select(SettlementSocialState)).scalars()}
    active_hh = [h for h in hhs if h.state == "ACTIVE"]
    artifact = {
        "fixture_version": "mini_world_v1",
        "simulation_version": SIM_VERSION,
        "population_engine_version": "m2a-1",
        "resource_engine_version": ECO_RES_VERSION,
        "economy_engine_version": ECO_ECON_VERSION,
        "ecology_engine_version": "m2c-ecology-1",
        "social_engine_version": SOC_ENGINE_VERSION,
        "rng_schema_version": "m1-derive-seed-v1",
        "event_uid_schema_version": 1,
        "event_hash_schema_version": 1,
        "world_state_hash_schema_version": WORLD_STATE_HASH_SCHEMA_VERSION_V5,
        "social_state_scale_version": "m2d-scale-1",
        "initial_state": {
            "population": 400, "settlements": 2,
            "households": 80, "lineages": 1, "institutions": 2,
            "household_size": 5,
        },
        "final_state": {
            "population": rep.population["end"],
            "active_households": len(active_hh),
            "households_total": len(hhs),
            "mean_household_size": round(
                sum(h.represented_population for h in active_hh)
                / max(len(active_hh), 1), 3),
            "lineages_total": len(lgs),
            "lineages_active": len([lg for lg in lgs
                                    if lg.status == "ACTIVE"]),
            "lineages_extinct": len([lg for lg in lgs
                                     if lg.status == "EXTINCT"]),
            "max_lineage_generation": max((lg.generation for lg in lgs),
                                          default=0),
            "multi_settlement_lineages": len({
                lg.lineage_id for lg in lgs if lg.lineage_id and len({
                    h.settlement_ref for h in hhs
                    if h.lineage_ref == lg.lineage_id and h.state == "ACTIVE"
                }) > 1}),
            "institutions_total": len(insts),
            "institution_states": {i.institution_id: i.state for i in insts},
        },
        "population_metrics": {
            "start": rep.population["start"], "end": rep.population["end"],
            "births": rep.population["births"],
            "deaths": rep.population["deaths"],
            "immigration": rep.engine_metrics["DEMOGRAPHY"]["immigration"],
            "emigration": rep.engine_metrics["DEMOGRAPHY"]["emigration"],
        },
        "resource_metrics": {
            "initial_reserve": rep.resource["initial_reserve"],
            "final_reserve": rep.resource["final_reserve"],
            "total_extracted": rep.resource["total_extracted"],
            "regeneration_applied": rep.resource["regeneration_applied"],
        },
        "economy_metrics": {
            "initial_stock": rep.economy["initial_stock"],
            "final_stock": rep.economy["final_stock"],
            "production_input": rep.economy["production_input"],
            "production_output": rep.economy["production_output"],
            "demand": rep.economy["demand"],
            "fulfilled": rep.economy["fulfilled"],
            "unmet": rep.economy["unmet"],
            "imports": rep.economy["imports"],
            "exports": rep.economy["exports"],
            "transfers": rep.economy["transfers"],
            "shortage_steps": rep.economy["shortage_steps"],
        },
        "ecology_metrics": {
            "initial_quality": rep.ecology["initial_quality"],
            "final_quality": rep.ecology["final_quality"],
            "degradation": rep.ecology["degradation"],
            "recovery": rep.ecology["recovery"],
            "threshold_crossings": rep.ecology["threshold_crossings"],
        },
        "social_metrics": {
            "initial_stress": rep.social["initial_stress"],
            "final_stress": rep.social["final_stress"],
            "min_stress": {k: states[k].stress_min_seen for k in states},
            "max_stress": {k: states[k].stress_max_seen for k in states},
            "households_formed": rep.social["households_formed"],
            "households_split": rep.social["households_split"],
            "households_dissolved": rep.social["households_dissolved"],
            "lineages_founded": rep.social["lineages_founded"],
            "lineages_extinct": rep.social["lineages_extinct"],
            "institutions_founded": rep.social["institutions_founded"],
            "institutions_dissolved": rep.social["institutions_dissolved"],
            "institution_state_transitions": rep.engine_metrics["SOCIAL"][
                "institution_state_transitions"],
            "stress_threshold_crossings": rep.social[
                "stress_threshold_crossings"],
            "feedback_applications": rep.social["feedback_applications"],
        },
        "final_world_state_hash": rep.final_state_hash,
        "final_event_stream_hash": event_hash,
        "runs": rep.runs, "steps": rep.steps,
        "checkpoints": rep.checkpoints,
        "event_counts": {
            "total": rep.events,
            "household_formed": _count_events(env, "HOUSEHOLD_FORMED"),
            "household_split": _count_events(env, "HOUSEHOLD_SPLIT"),
            "household_dissolved": _count_events(env, "HOUSEHOLD_DISSOLVED"),
            "lineage_founded": _count_events(env, "LINEAGE_FOUNDED"),
            "lineage_extinct": _count_events(env, "LINEAGE_EXTINCT"),
            "institution_state_changed": _count_events(
                env, "INSTITUTION_STATE_CHANGED"),
            "stress_threshold_crossed": _count_events(
                env, "SOCIAL_STRESS_THRESHOLD_CROSSED"),
        },
        "performance": {"wall_seconds": round(wall_seconds, 3)},
    }
    return artifact


def _count_events(env, event_type: str) -> int:
    with env["factory"]() as s:
        return len(s.execute(select(WorldEvent).where(
            WorldEvent.event_type == event_type)).scalars().all())

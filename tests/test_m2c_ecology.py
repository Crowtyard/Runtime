# -*- coding: utf-8 -*-
"""M2c Ecology Engine 测试：EC1–EC45 + E1–E7 崩溃矩阵 + 120y 基线。

全部运行于 tmp 临时库（mini_world with_ecology=True）；正式 DB 零接触。
"""
from __future__ import annotations

from tests.formal_db import readonly_connect as formal_readonly_connect  # noqa: E402

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
    EcologyFeedbackState, EcologyState, EcologyZone, PopulationGroup,
    ResourceNode, ResourceStock)
from XiaoguangBlessedLandRuntime.domain.errors import FencingViolation
from XiaoguangBlessedLandRuntime.services import fencing as fencing_mod
from XiaoguangBlessedLandRuntime.services.catchup import catch_up
from XiaoguangBlessedLandRuntime.services.fencing import WorldMutationContext
from XiaoguangBlessedLandRuntime.services.simulation.contracts import (
    ENGINE_ORDER)
from XiaoguangBlessedLandRuntime.services.simulation.coordinator import (
    SimulationCoordinator)
from XiaoguangBlessedLandRuntime.services.simulation.ecology import (
    ECOLOGY_STATE_SCALE, ECOLOGY_STATE_SCALE_VERSION,
    ENGINE_VERSION as ECO_ENGINE_VERSION)
from XiaoguangBlessedLandRuntime.services.simulation.ecology import (
    EcologyEngine, EcologyProfileUnconfigured)
from XiaoguangBlessedLandRuntime.services.simulation.economy import (
    ENGINE_VERSION as ECO_ECON_VERSION)
from XiaoguangBlessedLandRuntime.services.simulation.economy import EconomyEngine
from XiaoguangBlessedLandRuntime.services.simulation.event_stream import (
    step_event_stream_hash)
from XiaoguangBlessedLandRuntime.services.simulation.feedback import (
    demography_ecology_pressure_modifier)
from XiaoguangBlessedLandRuntime.services.simulation.harness import (
    YEAR_US, run_mini_world_120y)
from XiaoguangBlessedLandRuntime.services.simulation.mini_world import (
    MINI_WORLD_ID, MINI_ORE_RESERVE_UNITS, MINI_SCALE)
from XiaoguangBlessedLandRuntime.services.simulation.population import (
    PopulationGroupEngine)
from XiaoguangBlessedLandRuntime.services.simulation.recovery import (
    latest_authoritative_world_checkpoint)
from XiaoguangBlessedLandRuntime.services.simulation.resource import (
    ENGINE_VERSION as ECO_RES_VERSION)
from XiaoguangBlessedLandRuntime.services.simulation.resource import ResourceEngine
from XiaoguangBlessedLandRuntime.services.simulation.snapshot import \
    read_snapshot
from XiaoguangBlessedLandRuntime.services.simulation.state_hash import (
    WORLD_STATE_HASH_SCHEMA_VERSION_V4, world_state_hash_v4)
from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease

REPO = PROJECT_ROOT
BASELINE_PATH = REPO / "tests" / "baselines" / \
    "m2c_ecology_miniworld_120y_v1.json"
SIM_DIR = REPO / "services" / "simulation"
SIM_VERSION = "0.2.0-preflight"

# GB2：本模块每个测试前后 golden baseline 字节必须不变
_golden_bytes_guard = golden_bytes_guard(BASELINE_PATH)


def _fresh_eco(tmp_path, i: int):
    """独立 M2c 环境：迁移 + 激活测试世界 + seed_mini_world(with_ecology=True)。"""
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
    db_path = tmp_path / f"mini_eco_{i}.db"
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
        seed_mini_world(s, with_ecology=True)
        s.commit()
    return {"url": url, "factory": factory, "db_path": db_path}


def _engines(**kw):
    return [kw.get("pop") or PopulationGroupEngine(),
            kw.get("res") or ResourceEngine(),
            kw.get("eco") or EconomyEngine(),
            kw.get("ecol") or EcologyEngine()]


def _run(env, years=120, **kw):
    engines = kw.pop("engines", None)
    if engines is None:
        engines = [kw.pop("pop", None) or PopulationGroupEngine(),
                   kw.pop("res", None) or ResourceEngine(),
                   kw.pop("eco", None) or EconomyEngine(),
                   kw.pop("ecol", None) or EcologyEngine()]
    return run_mini_world_120y(env["factory"], engines=engines, years=years,
                               **kw)


def _fresh_env(tmp_path, i: int):
    from tests.test_preflight_pf import _fresh_env as _fe
    return _fe(tmp_path, i)


# ------------------------------------------------------------ EC1-EC5
def test_ec1_ecology_engine_conforms_protocol():
    e = EcologyEngine()
    assert e.engine_id == "ECOLOGY"
    assert e.engine_version == "m2c-ecology-1"
    assert all(hasattr(e, a) for a in ("engine_id", "engine_version",
                                       "simulate"))
    assert callable(e.simulate)


def test_ec2_pipeline_order_d_r_e_ecology():
    assert ENGINE_ORDER[:4] == ("DEMOGRAPHY", "RESOURCE", "ECONOMY",
                                "ECOLOGY")
    assert ENGINE_ORDER[4:] == ("SOCIAL",)
    with pytest.raises(Exception):
        SimulationCoordinator([EcologyEngine(), EconomyEngine(),
                               ResourceEngine(), PopulationGroupEngine()])


def test_ec3_no_direct_db_commit():
    src = (SIM_DIR / "ecology.py").read_text(encoding="utf-8")
    assert "session.commit" not in src
    assert ".commit()" not in src
    assert "session.begin" not in src


def test_ec4_fixed_point_ecology_state(tmp_path):
    env = _fresh_eco(tmp_path, 1)
    _run(env, years=2)
    with env["factory"]() as s:
        for st in s.execute(select(EcologyState)).scalars():
            assert isinstance(st.habitat_quality, int)
            assert isinstance(st.ecological_stress, int)
            assert isinstance(st.degradation_carry, int)
            assert not isinstance(st.habitat_quality, float)
        for fb in s.execute(select(EcologyFeedbackState)).scalars():
            assert isinstance(fb.yield_modifier_num, int)
            assert isinstance(fb.environmental_stress_num, int)
    assert ECOLOGY_STATE_SCALE == 1_000_000
    assert ECOLOGY_STATE_SCALE_VERSION == "m2c-scale-1"


def test_ec5_bounded_ecological_state(tmp_path):
    env = _fresh_eco(tmp_path, 2)
    _run(env, years=120)
    with env["factory"]() as s:
        for st in s.execute(select(EcologyState)).scalars():
            assert 0 <= st.habitat_quality <= ECOLOGY_STATE_SCALE
            assert 0 <= st.ecological_stress <= ECOLOGY_STATE_SCALE
            assert 0 <= st.regeneration_capacity <= ECOLOGY_STATE_SCALE
            for p in (st.population_pressure, st.extraction_pressure,
                      st.production_pressure, st.depletion_pressure):
                assert 0 <= p <= ECOLOGY_STATE_SCALE
            assert st.quality_min_seen <= st.quality_max_seen \
                <= ECOLOGY_STATE_SCALE


# ------------------------------------------------------------ EC6-EC11
def test_ec6_pressure_deterministic(tmp_path):
    a = _run(_fresh_eco(tmp_path, 3), years=5)
    b = _run(_fresh_eco(tmp_path, 4), years=5)
    assert a.engine_metrics["ECOLOGY"] == b.engine_metrics["ECOLOGY"]
    assert a.final_state_hash == b.final_state_hash


def test_ec7_degradation_deterministic(tmp_path):
    a = _run(_fresh_eco(tmp_path, 5), years=60)
    b = _run(_fresh_eco(tmp_path, 6), years=60)
    assert a.engine_metrics["ECOLOGY"]["degradation_minor"] > 0
    assert a.engine_metrics["ECOLOGY"]["degradation_minor"] \
        == b.engine_metrics["ECOLOGY"]["degradation_minor"]


def test_ec8_recovery_deterministic(tmp_path):
    a = _run(_fresh_eco(tmp_path, 7), years=60)
    b = _run(_fresh_eco(tmp_path, 8), years=60)
    assert a.engine_metrics["ECOLOGY"]["recovery_minor"] > 0
    assert a.engine_metrics["ECOLOGY"]["recovery_minor"] \
        == b.engine_metrics["ECOLOGY"]["recovery_minor"]


def test_ec9_carry_restart_stable(tmp_path):
    env1 = _fresh_eco(tmp_path, 9)
    one = _run(env1, years=2)
    env2 = _fresh_eco(tmp_path, 10)
    _run(env2, years=1)
    part2 = _run(env2, years=1, start_year=1)
    assert part2.final_state_hash == one.final_state_hash
    a = _ecology_rows(env1)
    b = _ecology_rows(env2)
    assert a == b


def _ecology_rows(env) -> dict:
    with env["factory"]() as s:
        return {f"{r.zone_ref}": {
            "quality": r.habitat_quality, "stress": r.ecological_stress,
            "deg_carry": r.degradation_carry, "rec_carry": r.recovery_carry,
            "min": r.quality_min_seen, "max": r.quality_max_seen}
            for r in s.execute(select(EcologyState)).scalars()}


def test_ec10_nonrenewable_regeneration_zero(tmp_path):
    env = _fresh_eco(tmp_path, 11)
    rep = _run(env, years=60)
    with env["factory"]() as s:
        ore = s.execute(select(ResourceNode).where(
            ResourceNode.kind == "TEST-ORE-001")).scalar_one()
        assert ore.regeneration_carry == 0  # 非可再生：再生=0（EC_INV_08）
        assert ore.reserve_ceiling_minor is None
        assert ore.remaining_reserve < MINI_ORE_RESERVE_UNITS * MINI_SCALE
        timber = s.execute(select(ResourceNode).where(
            ResourceNode.kind == "TEST-TIMBER-001")).scalar_one()
        assert timber.reserve_ceiling_minor is not None
    assert rep.resource["regeneration_applied"] > 0  # 可再生：实际再生


def test_ec11_renewable_feedback_deterministic(tmp_path):
    a = _run(_fresh_eco(tmp_path, 12), years=30)
    b = _run(_fresh_eco(tmp_path, 13), years=30)
    assert a.resource["regeneration_applied"] > 0
    assert a.resource["regeneration_applied"] \
        == b.resource["regeneration_applied"]


# ------------------------------------------------------------ EC12-EC20
def test_ec12_ecology_cannot_modify_resource_reserve(tmp_path):
    env = _fresh_eco(tmp_path, 14)
    with env["factory"]() as s:
        before = {n.kind: n.remaining_reserve for n in s.execute(
            select(ResourceNode)).scalars()}
    run_mini_world_120y(env["factory"], engines=[EcologyEngine()], years=1)
    with env["factory"]() as s:
        after = {n.kind: n.remaining_reserve for n in s.execute(
            select(ResourceNode)).scalars()}
    assert before == after
    src = (SIM_DIR / "ecology.py").read_text(encoding="utf-8")
    assert 'table="resource_nodes"' not in src  # 禁止 propose 资源表
    assert "reserve_ceiling_minor" not in src    # 禁止写资源节点状态


def test_ec13_ecology_cannot_modify_population(tmp_path):
    env = _fresh_eco(tmp_path, 15)
    before = _pop_total(env)
    run_mini_world_120y(env["factory"], engines=[EcologyEngine()], years=1)
    assert _pop_total(env) == before


def _pop_total(env) -> int:
    with env["factory"]() as s:
        return sum(g.count for g in s.execute(
            select(PopulationGroup)).scalars())


def test_ec14_ecology_cannot_modify_economy_inventory(tmp_path):
    env = _fresh_eco(tmp_path, 16)
    with env["factory"]() as s:
        before = {r.id: r.quantity for r in s.execute(
            select(ResourceStock)).scalars()}
    run_mini_world_120y(env["factory"], engines=[EcologyEngine()], years=1)
    with env["factory"]() as s:
        after = {r.id: r.quantity for r in s.execute(
            select(ResourceStock)).scalars()}
    assert before == after


def test_ec15_feedback_persisted_reconstructable(tmp_path):
    env1 = _fresh_eco(tmp_path, 17)
    one = _run(env1, years=30)
    env2 = _fresh_eco(tmp_path, 18)
    _run(env2, years=15)
    part2 = _run(env2, years=15, start_year=15)
    assert part2.final_state_hash == one.final_state_hash
    a = _feedback_rows(env1)
    b = _feedback_rows(env2)
    assert a == b


def _feedback_rows(env) -> dict:
    with env["factory"]() as s:
        return {f"{r.zone_ref}": {
            "regen": r.regeneration_capacity_minor_per_year,
            "yn": r.yield_modifier_num, "yd": r.yield_modifier_den,
            "level": r.habitat_stress_level,
            "sn": r.environmental_stress_num,
            "sd": r.environmental_stress_den}
            for r in s.execute(select(EcologyFeedbackState)).scalars()}


def test_ec16_same_step_feedback_prohibited(tmp_path):
    # Step 1：ECO 夹具反馈行是 neutral 种子（regen=0/yield=1）——
    # RESOURCE 第 1 步再生必须为 0（生态本步结果绝不回写本步 RESOURCE）
    eco_env = _fresh_eco(tmp_path, 19)
    rep1 = _run(eco_env, years=1)
    assert rep1.resource["regeneration_applied"] == 0
    # 且第 1 步 DEMOGRAPHY/ECONOMY 与无生态夹具完全一致
    plain = _fresh_env(tmp_path, 20)
    plain_rep = run_mini_world_120y(
        plain["factory"],
        engines=[PopulationGroupEngine(), ResourceEngine(),
                 EconomyEngine()], years=1)
    assert rep1.engine_metrics["DEMOGRAPHY"] \
        == plain_rep.engine_metrics["DEMOGRAPHY"]
    assert rep1.engine_metrics["ECONOMY"] == plain_rep.engine_metrics["ECONOMY"]


def test_ec17_next_step_resource_receives_ecology_feedback(tmp_path):
    env = _fresh_eco(tmp_path, 21)
    rep2 = _run(env, years=2)
    # 第 2 步：RESOURCE 读取第 1 步 committed 生态反馈 → 再生实际发生
    assert rep2.resource["regeneration_applied"] > 0
    with env["factory"]() as s:
        fb = s.execute(select(EcologyFeedbackState)).scalars().all()
        assert all(f.yield_modifier_num <= f.yield_modifier_den for f in fb)
        assert any(f.regeneration_capacity_minor_per_year > 0 for f in fb)


def test_ec18_next_step_demography_receives_ecology_channel(tmp_path):
    env = _fresh_eco(tmp_path, 22)
    with env["factory"]() as s:
        for fb in s.execute(select(EcologyFeedbackState)).scalars():
            fb.habitat_stress_level = "CRITICAL"
            fb.environmental_stress_num = 1_000_000
            fb.environmental_stress_den = 1_000_000
        s.commit()
    rep = _run(env, years=1)
    assert rep.engine_metrics["DEMOGRAPHY"]["max_ecology_stress_level"] == 3
    # 生态压力经 synthetic 映射提高死亡率（与无生态基线对照）
    base = _run(_fresh_eco(tmp_path, 23), years=1)
    assert rep.engine_metrics["DEMOGRAPHY"]["deaths"] \
        >= base.engine_metrics["DEMOGRAPHY"]["deaths"]


def test_ec19_shortage_does_not_degrade_ecology(tmp_path):
    # 经济压力只经声明输入（生产活动）进入生态；短缺≠生态退化。
    # 生产受产能/矿石约束而非需求 → 改 B 食物库存（缺不缺粮）不改生态结果。
    a = _fresh_eco(tmp_path, 24)
    b = _fresh_eco(tmp_path, 25)
    with b["factory"]() as s:
        row = s.execute(select(ResourceStock).where(
            ResourceStock.settlement_ref == "TEST-SATELLITE-B",
            ResourceStock.resource_profile_ref == "TEST-RESOURCE-002"
        )).scalar_one()
        row.quantity = 0  # B 立刻短缺
        s.commit()
    ra = _run(a, years=3)
    rb = _run(b, years=3)
    assert ra.engine_metrics["ECOLOGY"] == rb.engine_metrics["ECOLOGY"]
    # 源级因果边界：ecology.py 不读经济压力表（不把短缺当生态输入）
    src = (SIM_DIR / "ecology.py").read_text(encoding="utf-8")
    assert "economic_pressure_state" not in src


def test_ec20_resource_depletion_not_automatic_degradation(tmp_path):
    # 资源耗尽只经声明的 depletion 压力（1/8 权重）进入生态；无直接映射。
    src = (SIM_DIR / "ecology.py").read_text(encoding="utf-8")
    assert "EXHAUSTED" not in src
    env = _fresh_eco(tmp_path, 26)
    with env["factory"]() as s:
        ore = s.execute(select(ResourceNode).where(
            ResourceNode.kind == "TEST-ORE-001")).scalar_one()
        ore.remaining_reserve = 5
        s.commit()
    rep = _run(env, years=1)
    with env["factory"]() as s:
        st = s.execute(select(EcologyState).where(
            EcologyState.zone_ref == "TEST-ZONE-A")).scalar_one()
        # 耗尽贡献 SCALE 级 depletion 压力，但总压力受权重约束（非瞬时崩溃）
        assert st.depletion_pressure == ECOLOGY_STATE_SCALE
        assert 0 < st.ecological_stress <= ECOLOGY_STATE_SCALE
    assert rep.engine_metrics["RESOURCE"]["depleted"] == 1


# ------------------------------------------------------------ EC21-EC27
def test_ec21_threshold_transition_deterministic(tmp_path):
    a = _fresh_eco(tmp_path, 27)
    b = _fresh_eco(tmp_path, 28)
    for env in (a, b):
        with env["factory"]() as s:
            st = s.execute(select(EcologyState).where(
                EcologyState.zone_ref == "TEST-ZONE-A")).scalar_one()
            st.habitat_quality = 800_500  # 临界：一步退化即越 800,000
            st.quality_min_seen = min(st.quality_min_seen, 800_500)
            s.commit()
    ra = _run(a, years=1)
    rb = _run(b, years=1)
    assert ra.engine_metrics["ECOLOGY"]["threshold_crossings"] \
        == rb.engine_metrics["ECOLOGY"]["threshold_crossings"] == 1
    with a["factory"]() as s:
        ev = s.execute(select(WorldEvent).where(
            WorldEvent.event_type == "ECOLOGY_THRESHOLD_CROSSED"
        )).scalars().all()
        assert len(ev) == 1
        assert ev[0].effect["from_level"] == "HEALTHY"
        assert ev[0].effect["to_level"] == "STRESSED"
        assert ev[0].effect["quality_before_minor"] == 800_500
        assert ev[0].effect["quality_after_minor"] < 800_000


def test_ec22_event_uid_deterministic(tmp_path):
    a = _fresh_eco(tmp_path, 29)
    b = _fresh_eco(tmp_path, 30)
    _run(a, years=3)
    _run(b, years=3)
    with a["factory"]() as s:
        ua = [e.event_uid for e in s.execute(select(WorldEvent)).scalars()]
    with b["factory"]() as s:
        ub = [e.event_uid for e in s.execute(select(WorldEvent)).scalars()]
    assert ua == ub
    assert all(re.fullmatch(r"[0-9a-f]{32}", u) for u in ua)


def test_ec23_event_payload_affects_event_stream_hash():
    base = [{"event_uid": "b" * 32, "blessed_tick": 1,
             "event_type": "ECOLOGY_THRESHOLD_CROSSED",
             "source": "SIMULATION",
             "cause": {"zone_id": "Z"},
             "effect": {"from_level": "HEALTHY", "to_level": "STRESSED",
                        "quality_before_minor": 800_000,
                        "quality_after_minor": 700_000,
                        "pressure_minor": 500_000},
             "severity": 0.0, "scope": "WORLD"}]
    changed = [dict(base[0], effect={**base[0]["effect"],
                                     "quality_after_minor": 500_000})]
    h1 = step_event_stream_hash(None, world_id="W",
                                simulation_version=SIM_VERSION, events=base)
    h2 = step_event_stream_hash(None, world_id="W",
                                simulation_version=SIM_VERSION,
                                events=changed)
    assert h1 != h2


def test_ec24_ecology_included_in_world_state_hash(tmp_path):
    env = _fresh_eco(tmp_path, 31)
    _run(env, years=2)
    h1 = _hash_v4(env)
    with env["factory"]() as s:
        st = s.execute(select(EcologyState)).scalars().first()
        st.habitat_quality += 1
        s.commit()
    h2 = _hash_v4(env)
    assert h1 != h2


def test_ec25_hash_row_order_independent(tmp_path):
    env1 = _fresh_eco(tmp_path, 32)
    h1 = _hash_v4(env1)
    env2 = _fresh_eco(tmp_path, 33)
    with env2["factory"]() as s:
        rows = s.execute(select(EcologyState)).scalars().all()
        for r in rows:
            s.delete(r)
        s.flush()
        for r in reversed(rows):
            s.add(EcologyState(
                world_id=r.world_id, zone_ref=r.zone_ref,
                habitat_quality=r.habitat_quality,
                regeneration_capacity=r.regeneration_capacity,
                ecological_stress=r.ecological_stress,
                quality_min_seen=r.quality_min_seen,
                quality_max_seen=r.quality_max_seen,
                engine_version=r.engine_version))
        s.commit()
    h2 = _hash_v4(env2)
    assert h1 == h2


def test_ec26_ecology_rng_isolated(tmp_path):
    base = _run(_fresh_eco(tmp_path, 34), years=4)
    extra = _run(_fresh_eco(tmp_path, 35), years=4,
                 ecol=EcologyEngine(extra_draws=9))
    assert extra.engine_metrics["DEMOGRAPHY"] == base.engine_metrics[
        "DEMOGRAPHY"]
    assert extra.engine_metrics["RESOURCE"] == base.engine_metrics["RESOURCE"]
    assert extra.engine_metrics["ECONOMY"] == base.engine_metrics["ECONOMY"]
    assert extra.engine_metrics["ECOLOGY"] == base.engine_metrics["ECOLOGY"]
    assert extra.final_state_hash == base.final_state_hash


def test_ec27_no_stochastic_disaster_injected():
    src = (SIM_DIR / "ecology.py").read_text(encoding="utf-8")
    # 引擎算法零 RNG：唯一 ctx.rng 引用是 extra_draws 测试旋钮
    assert src.count("ctx.rng") == 1
    assert "EFFICIENCY_TABLE" not in src
    assert "disaster" not in src.lower()
    assert "tribulation" not in src.lower()


# ------------------------------------------------------------ EC28-EC34
def test_ec28_retry_zero_duplicate_ecology_mutation(tmp_path):
    env = _fresh_eco(tmp_path, 36)
    _run(env, years=1)
    rows_before = _ecology_rows(env)
    _run(env, years=1)
    assert _ecology_rows(env) == rows_before


def test_ec29_retry_zero_duplicate_ecology_events(tmp_path):
    env = _fresh_eco(tmp_path, 37)
    _run(env, years=1)
    with env["factory"]() as s:
        uids = {e.event_uid for e in s.execute(select(WorldEvent)).scalars()}
    _run(env, years=1)
    with env["factory"]() as s:
        assert {e.event_uid for e in s.execute(
            select(WorldEvent)).scalars()} == uids


def test_ec30_stale_writer_cannot_commit_ecology(tmp_path):
    env = _fresh_eco(tmp_path, 38)
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
        st = s.execute(select(EcologyState)).scalars().first()
        assert st.habitat_quality == 900_000  # 生态 0 authoritative write
        assert s.execute(text(
            "SELECT COUNT(*) FROM simulation_checkpoints")).scalar() == 0
    lease.release()
    s1.close()


def _crash_and_recover_eco(tmp_path, i, crash_after):
    env = _fresh_eco(tmp_path, i)
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
        st = s.execute(select(EcologyState)).scalars().first()
        assert st.habitat_quality == 900_000
        assert latest_authoritative_world_checkpoint(s, MINI_WORLD_ID) is None
    catch_up(factory, world_id=MINI_WORLD_ID,
             now_real_us=EPOCH0_US + YEAR_US,
             writer_id=lease.owner, fencing_token=lease.token,
             simulation_version=SIM_VERSION, simulate_fn=step)
    ref = _run(_fresh_eco(tmp_path, i + 1000), years=1)
    with factory() as s:
        h = latest_authoritative_world_checkpoint(s, MINI_WORLD_ID) \
            .world_state_hash
    assert h == ref.final_state_hash
    lease.release()
    s1.close()


def test_ec31_crash_mid_ecology_recovers(tmp_path):
    _crash_and_recover_eco(tmp_path, 39, "mid:ECOLOGY")


def test_ec32_crash_after_ecology_staged_recovers(tmp_path):
    _crash_and_recover_eco(tmp_path, 40, "after_engines")


def test_ec33_commit_ack_lost_does_not_duplicate_ecology(tmp_path,
                                                         monkeypatch):
    env = _fresh_eco(tmp_path, 41)
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
    rows_before = _ecology_rows(env)
    with factory() as s:
        assert s.execute(select(WorldRuntime)).scalar_one() \
            .current_blessed_tick == 1_000_000  # durable 已提交
    monkeypatch.setattr(fencing_mod.WorldMutationContext, "commit", original)
    res = catch_up(factory, world_id=MINI_WORLD_ID,
                   now_real_us=EPOCH0_US + YEAR_US,
                   writer_id=lease.owner, fencing_token=lease.token,
                   simulation_version=SIM_VERSION)
    assert res.skipped is True
    assert _ecology_rows(env) == rows_before  # 生态不重复退化/恢复
    lease.release()
    s1.close()


def test_ec34_world_checkpoint_contains_ecology_state(tmp_path):
    env = _fresh_eco(tmp_path, 42)
    rep = _run(env, years=3)
    with env["factory"]() as s:
        world = latest_authoritative_world_checkpoint(s, MINI_WORLD_ID)
        assert world.meta["engine_versions"]["ECOLOGY"] == ECO_ENGINE_VERSION
    assert rep.final_state_hash == _hash_v4(env)


# ------------------------------------------------------------ E1-E5 崩溃矩阵
@pytest.mark.parametrize("crash_after", [
    pytest.param("engine:ECOLOGY", id="E1-after-economy-staged"),
    pytest.param("mid:ECOLOGY", id="E2-mid-ecology-calculation"),
    pytest.param("after_engines", id="E3-after-ecology-staged"),
    pytest.param("during_apply", id="E4-during-ecology-db-write"),
    pytest.param("before_checkpoint",
                 id="E5-during-ecology-feedback-persistence"),
])
def test_ec_crash_matrix_e1_e5(tmp_path, crash_after):
    _crash_and_recover_eco(tmp_path, 100 + hash(crash_after) % 300, crash_after)


def test_ec_e6_fencing_recheck_blocks_ecology(tmp_path):
    """E6：commit 前 fencing 重检 —— token 被窃 → FENCING_VIOLATION，
    生态/人口/资源/经济/事件/checkpoint 全部 0 authoritative write。"""
    env = _fresh_eco(tmp_path, 43)
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
        st = s.execute(select(EcologyState)).scalars().first()
        assert st.habitat_quality == 900_000
        assert s.execute(text(
            "SELECT COUNT(*) FROM world_events")).scalar() == 0
        assert s.execute(text(
            "SELECT COUNT(*) FROM simulation_checkpoints")).scalar() == 0
    lease.release()
    s1.close()


# ------------------------------------------------------------ EC35-EC38
def test_ec35_120y_integrated_run_completes(tmp_path):
    env = _fresh_eco(tmp_path, 44)
    rep = _run(env, years=120)
    assert rep.steps == 120 and rep.runs == 120 and rep.checkpoints == 240
    assert rep.final_blessed_tick == 120_000_000
    eco = rep.engine_metrics["ECOLOGY"]
    assert eco["degradation_minor"] > 0
    assert eco["recovery_minor"] > 0
    assert eco["threshold_crossings"] > 0
    assert eco["feedback_applications"] == 240
    assert rep.resource["regeneration_applied"] > 0


def test_ec36_120y_all_ecology_invariants_pass(tmp_path):
    env = _fresh_eco(tmp_path, 45)
    _run(env, years=120)
    with env["factory"]() as s:
        for st in s.execute(select(EcologyState)).scalars():
            assert 0 <= st.habitat_quality <= ECOLOGY_STATE_SCALE   # EC_INV_01
            assert st.regeneration_capacity >= 0                    # EC_INV_02
            assert isinstance(st.habitat_quality, int)              # EC_INV_05
            assert st.ecological_stress >= 0                        # EC_INV_06
            assert st.degradation_carry >= 0                        # EC_INV_15
            assert st.recovery_carry >= 0
            assert st.degradation_carry < 10**15
        for fb in s.execute(select(EcologyFeedbackState)).scalars():
            assert fb.regeneration_capacity_minor_per_year >= 0
            assert fb.yield_modifier_den >= 1
        for z in s.execute(select(EcologyZone)).scalars():
            assert z.profile_ref == "TEST-ECOLOGY-PROFILE-001"      # EC_INV_13
    # EC_INV_08：非可再生节点再生=0
    with env["factory"]() as s:
        ore = s.execute(select(ResourceNode).where(
            ResourceNode.kind == "TEST-ORE-001")).scalar_one()
        assert ore.regeneration_carry == 0
        assert ore.remaining_reserve <= MINI_ORE_RESERVE_UNITS * MINI_SCALE


def test_ec37_continuous_equals_chunked(tmp_path):
    one = _run(_fresh_eco(tmp_path, 46), years=120)
    chunk = _run(_fresh_eco(tmp_path, 47), years=120,
                 restart_every_years=30)
    assert one.final_state_hash == chunk.final_state_hash
    assert one.population == chunk.population
    assert one.resource == chunk.resource
    assert one.economy == chunk.economy
    assert one.ecology == chunk.ecology
    assert one.engine_metrics == chunk.engine_metrics


def test_ec38_restart_equals_continuous(tmp_path):
    one = _run(_fresh_eco(tmp_path, 48), years=120)
    env = _fresh_eco(tmp_path, 49)
    part1 = _run(env, years=60)
    part2 = _run(env, years=60, start_year=60)
    assert part2.final_state_hash == one.final_state_hash
    assert part2.population["end"] == one.population["end"]
    assert part2.resource["final_reserve"] == one.resource["final_reserve"]
    assert part2.ecology["final_quality"] == one.ecology["final_quality"]
    for k in ("degradation_minor", "recovery_minor", "threshold_crossings"):
        assert part1.engine_metrics["ECOLOGY"][k] \
            + part2.engine_metrics["ECOLOGY"][k] \
            == one.engine_metrics["ECOLOGY"][k]


# ------------------------------------------------------------ EC39-EC45
def test_ec39_llm_calls_zero():
    for name in ("ecology.py", "feedback.py"):
        src = (SIM_DIR / name).read_text(encoding="utf-8")
        for token in ("openai", "anthropic", "llm"):
            assert token not in src, (name, token)


def test_ec40_network_calls_zero(tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("simulation core 触碰网络")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr("urllib.request.urlopen", _boom, raising=False)
    monkeypatch.setattr("http.client.HTTPConnection", _boom, raising=False)
    rep = _run(_fresh_eco(tmp_path, 50), years=5)
    assert rep.final_blessed_tick == 5_000_000


def test_ec41_wall_clock_simulation_truth_zero():
    pattern = re.compile(
        r"\b(datetime\.now|time\.time|time\.monotonic|perf_counter"
        r"|time_ns|date\.today)\s*\(")
    for name in ("ecology.py",):
        src = (SIM_DIR / name).read_text(encoding="utf-8")
        assert not pattern.search(src), name


def test_ec42_formal_ecology_profiles_remain_unconfigured(tmp_path):
    for ref in ("FORMAL-ZONE-PROFILE-001", "FORMAL-FOREST-PROFILE"):
        with pytest.raises(EcologyProfileUnconfigured) as ei:
            EcologyEngine()._profile_of(ref)
        assert ei.value.code == "ECOLOGY_UNCONFIGURED"
    env = _fresh_eco(tmp_path, 51)
    with env["factory"]() as s:
        z = s.execute(select(EcologyZone)).scalars().first()
        z.profile_ref = "FORMAL-ZONE-PROFILE-001"
        s.commit()
    with pytest.raises(EcologyProfileUnconfigured):
        _run(env, years=1)


def test_ec43_world_seed_not_consumed():
    for py in SIM_DIR.rglob("*.py"):
        src = py.read_text(encoding="utf-8")
        assert "world_seed" not in src, py
        assert "04_population_baseline" not in src, py


def test_ec44_formal_db_empty_after_suite(formal_db_guard):
    path = os.environ.get("BLR_FORMAL_DB_PATH", "")
    if not path or formal_db_guard is None:
        pytest.skip("BLR_FORMAL_DB_PATH 未设置")
    import hashlib
    after = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    assert after == formal_db_guard
    conn = formal_readonly_connect(path)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM world_runtime").fetchone()[0] == 0, \
            "canonical NOT_ACTIVATED = world_runtime 0 行"
        
        existing = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for t in ("ecology_zones", "ecology_state", "ecology_feedback_state"):
            if t in existing:
                assert conn.execute(
                    f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] == 0, t
    finally:
        conn.close()


def test_ec45_formal_db_integrity_ok(formal_db_guard):
    path = os.environ.get("BLR_FORMAL_DB_PATH", "")
    if not path or formal_db_guard is None:
        pytest.skip("BLR_FORMAL_DB_PATH 未设置")
    conn = formal_readonly_connect(path)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


# ------------------------------------------------------------ 120y 基线产物
def test_m2c_baseline_120y_artifact(tmp_path):
    start = datetime.now(timezone.utc)
    env = _fresh_eco(tmp_path, 52)
    rep = _run(env, years=120)
    wall = (datetime.now(timezone.utc) - start).total_seconds()
    assert BASELINE_PATH.exists()
    # candidate 与 committed golden 比较（telemetry 剥离）；普通 pytest 只读
    artifact = _build_m2c_artifact(env, rep, wall)
    golden = load_artifact(BASELINE_PATH)
    assert_deterministic_equal(
        golden, artifact, label="m2c_ecology_miniworld_120y_v1",
        golden_path=BASELINE_PATH)
    env2 = _fresh_eco(tmp_path, 53)
    rep2 = _run(env2, years=120)
    assert rep2.final_state_hash == golden["final_world_state_hash"]
    with env2["factory"]() as s:
        h2 = latest_authoritative_world_checkpoint(
            s, MINI_WORLD_ID).meta["event_stream_hash"]
    assert h2 == golden["final_event_stream_hash"]
    em = golden["ecology_metrics"]
    assert rep2.ecology == {k: em[k] for k in (
        "initial_quality", "final_quality", "degradation", "recovery",
        "threshold_crossings", "feedback_applications")}
    if update_mode_enabled():  # 显式更新：scripts/update_baselines.py
        dump_artifact(artifact, BASELINE_PATH)


def _hash_v4(env) -> str:
    with env["factory"]() as s:
        snap = read_snapshot(s, MINI_WORLD_ID)
        return world_state_hash_v4(
            snapshot=snap, simulation_version=SIM_VERSION,
            pipeline_version="m2-preflight-1",
            engine_versions={"DEMOGRAPHY": "m2a-1",
                             "RESOURCE": ECO_RES_VERSION,
                             "ECONOMY": ECO_ECON_VERSION,
                             "ECOLOGY": ECO_ENGINE_VERSION})


def _write_m2c_baseline(env, rep, wall_seconds: float) -> None:
    """显式更新入口：仅 BLR_UPDATE_GOLDEN_BASELINES=1 时写 golden。"""
    dump_artifact(_build_m2c_artifact(env, rep, wall_seconds), BASELINE_PATH)


def _build_m2c_artifact(env, rep, wall_seconds: float) -> dict:
    with env["factory"]() as s:
        latest = latest_authoritative_world_checkpoint(s, MINI_WORLD_ID)
        event_hash = latest.meta["event_stream_hash"]
        nodes = {n.kind: n.remaining_reserve for n in s.execute(
            select(ResourceNode)).scalars()}
        states = {r.zone_ref: r for r in s.execute(
            select(EcologyState)).scalars()}
        feedbacks = {r.zone_ref: r for r in s.execute(
            select(EcologyFeedbackState)).scalars()}
    eco = rep.engine_metrics["ECOLOGY"]
    artifact = {
        "fixture_version": "mini_world_v1",
        "simulation_version": SIM_VERSION,
        "population_engine_version": "m2a-1",
        "resource_engine_version": ECO_RES_VERSION,
        "economy_engine_version": ECO_ECON_VERSION,
        "ecology_engine_version": ECO_ENGINE_VERSION,
        "rng_schema_version": "m1-derive-seed-v1",
        "event_uid_schema_version": 1,
        "event_hash_schema_version": 1,
        "world_state_hash_schema_version": WORLD_STATE_HASH_SCHEMA_VERSION_V4,
        "ecology_state_scale_version": ECOLOGY_STATE_SCALE_VERSION,
        "initial_state": {
            "population": 400, "settlements": 2,
            "species": "TEST-SPECIES-001",
            "ecology_quality": 900_000,
            "timber_reserve_units": 5_000,
        },
        "final_state": {
            "population": rep.population["end"],
            "reserve_minor_by_node": nodes,
            "ecology_state_by_zone": {
                z: {"quality": states[z].habitat_quality,
                    "min": states[z].quality_min_seen,
                    "max": states[z].quality_max_seen,
                    "stress": states[z].ecological_stress}
                for z in sorted(states)},
            "feedback_by_zone": {
                z: {"regen_per_year": feedbacks[z].
                    regeneration_capacity_minor_per_year,
                    "yield": [feedbacks[z].yield_modifier_num,
                              feedbacks[z].yield_modifier_den],
                    "level": feedbacks[z].habitat_stress_level}
                for z in sorted(feedbacks)},
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
            "feedback_applications": rep.ecology["feedback_applications"],
            "min_quality": {z: states[z].quality_min_seen
                            for z in sorted(states)},
            "max_quality": {z: states[z].quality_max_seen
                            for z in sorted(states)},
        },
        "final_world_state_hash": rep.final_state_hash,
        "final_event_stream_hash": event_hash,
        "runs": rep.runs, "steps": rep.steps,
        "checkpoints": rep.checkpoints,
        "event_counts": {
            "total": rep.events,
            "ecology_threshold_crossed": _count_events(
                env, "ECOLOGY_THRESHOLD_CROSSED"),
        },
        "performance": {"wall_seconds": round(wall_seconds, 3)},
    }
    return artifact


def _count_events(env, event_type: str) -> int:
    with env["factory"]() as s:
        return len(s.execute(select(WorldEvent).where(
            WorldEvent.event_type == event_type)).scalars().all())

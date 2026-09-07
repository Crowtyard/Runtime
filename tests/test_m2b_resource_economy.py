# -*- coding: utf-8 -*-
"""M2b Resource-Economy Engine 测试：RB1–RB53 + 120 年 integrated 基线。

全部运行于 tmp 临时库（mini_world）；正式 DB 零接触（RB52/RB53 + zz 守护）。
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

from tests.conftest import EPOCH0_US, PROJECT_ROOT

from XiaoguangBlessedLandRuntime.database.models_core import (SimulationCheckpoint,
                                                              WorldEvent,
                                                              WorldRuntime)
from XiaoguangBlessedLandRuntime.database.models_world import (
    EconomicPressureState, ProductionRecipe, ProductionState, ResourceNode,
    ResourceProfile, ResourceStock)
from XiaoguangBlessedLandRuntime.domain.errors import FencingViolation
from XiaoguangBlessedLandRuntime.services.catchup import catch_up
from XiaoguangBlessedLandRuntime.services.fencing import WorldMutationContext
from XiaoguangBlessedLandRuntime.services.simulation.contracts import (
    ENGINE_ORDER)
from XiaoguangBlessedLandRuntime.services.simulation.coordinator import (
    SimulationCoordinator)
from XiaoguangBlessedLandRuntime.services.simulation.economy import (
    ENGINE_VERSION as ECO_ENGINE_VERSION)
from XiaoguangBlessedLandRuntime.services.simulation.economy import (
    EconomyEngine, EconomyProfileUnconfigured)
from XiaoguangBlessedLandRuntime.services.simulation.event_stream import (
    step_event_stream_hash)
from XiaoguangBlessedLandRuntime.services.simulation.harness import (
    YEAR_US, run_mini_world_120y)
from XiaoguangBlessedLandRuntime.services.simulation.mini_world import (
    MINI_WORLD_ID, MINI_ORE_CAPACITY_UNITS, MINI_ORE_RESERVE_UNITS,
    MINI_RECIPE, MINI_SCALE)
from XiaoguangBlessedLandRuntime.services.simulation.population import (
    PopulationGroupEngine)
from XiaoguangBlessedLandRuntime.services.simulation.recovery import (
    latest_authoritative_world_checkpoint)
from XiaoguangBlessedLandRuntime.services.simulation.resource import (
    ENGINE_VERSION as RES_ENGINE_VERSION)
from XiaoguangBlessedLandRuntime.services.simulation.resource import (
    ResourceEngine, ResourceProfileUnconfigured)
from XiaoguangBlessedLandRuntime.services.simulation.snapshot import \
    read_snapshot
from XiaoguangBlessedLandRuntime.services.simulation.state_hash import (
    WORLD_STATE_HASH_SCHEMA_VERSION, world_state_hash_v3)
from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease

REPO = PROJECT_ROOT
BASELINE_PATH = REPO / "tests" / "baselines" / \
    "m2b_resource_economy_miniworld_120y_v1.json"
SIM_DIR = REPO / "services" / "simulation"
SIM_VERSION = "0.2.0-preflight"


def _fresh_env(tmp_path, i: int):
    from tests.test_preflight_pf import _fresh_env as _fe
    return _fe(tmp_path, i)


def _engines(**kw):
    return [kw.get("pop") or PopulationGroupEngine(),
            kw.get("res") or ResourceEngine(),
            kw.get("eco") or EconomyEngine()]


def _run(env, years=120, **kw):
    engines = kw.pop("engines", None)
    if engines is None:
        engines = [kw.pop("pop", None) or PopulationGroupEngine(),
                   kw.pop("res", None) or ResourceEngine(),
                   kw.pop("eco", None) or EconomyEngine()]
    return run_mini_world_120y(env["factory"], engines=engines, years=years,
                               **kw)


def _initial_stock(sref: str, ref: str) -> int:
    units = {("TEST-MAIN-A", "TEST-RESOURCE-001"): 1_000,
             ("TEST-MAIN-A", "TEST-RESOURCE-002"): 100,
             ("TEST-SATELLITE-B", "TEST-RESOURCE-001"): 0,
             ("TEST-SATELLITE-B", "TEST-RESOURCE-002"): 0}
    return units[(sref, ref)] * MINI_SCALE


# ------------------------------------------------------------ RB1-RB6
def test_rb1_resource_engine_conforms_frozen_protocol():
    e = ResourceEngine()
    assert e.engine_id == "RESOURCE"
    assert e.engine_version == "m2b-resource-1"
    assert all(hasattr(e, a) for a in ("engine_id", "engine_version",
                                       "simulate"))
    assert callable(e.simulate)


def test_rb2_economy_engine_conforms_frozen_protocol():
    e = EconomyEngine()
    assert e.engine_id == "ECONOMY"
    assert e.engine_version == "m2b-economy-1"
    assert all(hasattr(e, a) for a in ("engine_id", "engine_version",
                                       "simulate"))
    assert callable(e.simulate)


def test_rb3_pipeline_order_demography_resource_economy():
    assert ENGINE_ORDER[:3] == ("DEMOGRAPHY", "RESOURCE", "ECONOMY")
    assert ENGINE_ORDER[3:] == ("ECOLOGY", "SOCIAL")
    with pytest.raises(Exception):
        SimulationCoordinator([EconomyEngine(), ResourceEngine(),
                               PopulationGroupEngine()])


def test_rb4_resource_cannot_direct_commit():
    src = (SIM_DIR / "resource.py").read_text(encoding="utf-8")
    assert "session.commit" not in src
    assert ".commit()" not in src
    assert "session.begin" not in src


def test_rb5_economy_cannot_direct_commit():
    src = (SIM_DIR / "economy.py").read_text(encoding="utf-8")
    assert "session.commit" not in src
    assert ".commit()" not in src
    assert "session.begin" not in src


def test_rb6_resource_quantity_integer_fixed_point(tmp_path):
    env = _fresh_env(tmp_path, 1)
    rep = _run(env, years=2)
    with env["factory"]() as s:
        node = s.execute(select(ResourceNode)).scalar_one()
        assert isinstance(node.remaining_reserve, int)
        assert isinstance(node.extraction_capacity, int)
        assert isinstance(node.extraction_carry, int)
        for stock in s.execute(select(ResourceStock)).scalars():
            assert isinstance(stock.quantity, int)
            assert not isinstance(stock.quantity, float)
            assert isinstance(stock.consumption_carry, int)
        for p in s.execute(select(EconomicPressureState)).scalars():
            assert isinstance(p.demand_minor, int)
            assert isinstance(p.unmet_minor, int)
    assert rep.resource["initial_reserve"] > 0


# ------------------------------------------------------------ RB7-RB11
def test_rb7_fraction_carry_restart_stable(tmp_path):
    one = _run(_fresh_env(tmp_path, 2), years=2)
    env2 = _fresh_env(tmp_path, 3)
    part1 = _run(env2, years=1)
    part2 = _run(env2, years=1, start_year=1)
    assert part2.final_state_hash == one.final_state_hash
    assert part2.resource["final_reserve"] == one.resource["final_reserve"]
    assert part2.economy["final_stock"] == one.economy["final_stock"]
    combined = {k: part1.engine_metrics["ECONOMY"][k]
                + part2.engine_metrics["ECONOMY"][k]
                for k in ("production_input_minor", "production_output_minor",
                          "demand_minor", "fulfilled_minor", "unmet_minor")}
    assert combined == {k: one.engine_metrics["ECONOMY"][k]
                        for k in ("production_input_minor",
                                  "production_output_minor", "demand_minor",
                                  "fulfilled_minor", "unmet_minor")}


def test_rb8_resource_extraction_deterministic(tmp_path):
    a = _run(_fresh_env(tmp_path, 4), years=5)
    b = _run(_fresh_env(tmp_path, 5), years=5)
    assert a.engine_metrics["RESOURCE"] == b.engine_metrics["RESOURCE"]
    assert a.final_state_hash == b.final_state_hash


def test_rb9_extraction_le_capacity(tmp_path):
    rep = _run(_fresh_env(tmp_path, 6), years=120)
    extracted = rep.engine_metrics["RESOURCE"]["extracted_minor"]
    cap = MINI_ORE_CAPACITY_UNITS * MINI_SCALE * 120
    assert 0 < extracted <= cap


def test_rb10_extraction_le_finite_reserve(tmp_path):
    env = _fresh_env(tmp_path, 7)
    rep = _run(env, years=120)
    extracted = rep.engine_metrics["RESOURCE"]["extracted_minor"]
    assert extracted <= MINI_ORE_RESERVE_UNITS * MINI_SCALE
    assert rep.resource["final_reserve"] >= 0


def test_rb11_reserve_never_negative_and_depletes_exactly(tmp_path):
    env = _fresh_env(tmp_path, 8)
    with env["factory"]() as s:
        node = s.execute(select(ResourceNode)).scalar_one()
        node.remaining_reserve = 5
        s.commit()
    rep = _run(env, years=1)
    with env["factory"]() as s:
        node = s.execute(select(ResourceNode)).scalar_one()
        assert node.remaining_reserve == 0
        assert node.state == "EXHAUSTED"
        assert node.state_version >= 1
    assert rep.engine_metrics["RESOURCE"]["depleted"] == 1
    with env["factory"]() as s:
        types = {e.event_type for e in s.execute(select(WorldEvent)).scalars()}
    assert "RESOURCE_DEPLETED" in types


# ------------------------------------------------------------ RB12-RB19
def test_rb12_production_deterministic(tmp_path):
    a = _run(_fresh_env(tmp_path, 9), years=5)
    b = _run(_fresh_env(tmp_path, 10), years=5)
    assert a.engine_metrics["ECONOMY"] == b.engine_metrics["ECONOMY"]
    assert a.final_state_hash == b.final_state_hash


def test_rb13_production_input_cannot_overspend(tmp_path):
    env = _fresh_env(tmp_path, 11)
    _run(env, years=120)
    with env["factory"]() as s:
        for stock in s.execute(select(ResourceStock)).scalars():
            assert stock.quantity >= 0
            # 输入总量 ≤ 期初库存 + 开采 + 迁入（RE_INV_12）
            assert stock.cum_input_minor <= (
                _initial_stock(stock.settlement_ref,
                               stock.resource_profile_ref)
                + stock.cum_extracted_minor + stock.cum_imported_minor)


def test_rb14_production_conversion_obeys_recipe(tmp_path):
    env = _fresh_env(tmp_path, 12)
    _run(env, years=30)
    in_qty = MINI_RECIPE["input_qty_minor"]
    out_qty = MINI_RECIPE["output_qty_minor"]
    with env["factory"]() as s:
        events = s.execute(select(WorldEvent).where(
            WorldEvent.event_type == "PRODUCTION_COMPLETED")).scalars().all()
        assert events
        for e in events:
            eff = e.effect
            assert eff["input_minor"] == eff["batches"] * in_qty
            assert eff["output_minor"] + eff["loss_minor"] \
                == eff["batches"] * out_qty


def test_rb15_consumption_deterministic(tmp_path):
    a = _run(_fresh_env(tmp_path, 13), years=5)
    b = _run(_fresh_env(tmp_path, 14), years=5)
    assert a.engine_metrics["ECONOMY"]["demand_minor"] \
        == b.engine_metrics["ECONOMY"]["demand_minor"]
    assert a.engine_metrics["ECONOMY"]["fulfilled_minor"] \
        == b.engine_metrics["ECONOMY"]["fulfilled_minor"]


def test_rb16_fulfilled_le_demand(tmp_path):
    env = _fresh_env(tmp_path, 15)
    rep = _run(env, years=120)
    eco = rep.engine_metrics["ECONOMY"]
    assert eco["fulfilled_minor"] <= eco["demand_minor"]
    with env["factory"]() as s:
        for e in s.execute(select(WorldEvent).where(
                WorldEvent.event_type == "CONSUMPTION_FULFILLED")).scalars():
            assert e.effect["fulfilled_minor"] <= e.effect["demand_minor"]


def test_rb17_fulfilled_le_stock(tmp_path):
    env = _fresh_env(tmp_path, 16)
    rep = _run(env, years=120)
    with env["factory"]() as s:
        for stock in s.execute(select(ResourceStock).where(
                ResourceStock.resource_profile_ref
                == "TEST-RESOURCE-002")).scalars():
            assert stock.cum_consumed_minor <= (
                _initial_stock(stock.settlement_ref,
                               stock.resource_profile_ref)
                + stock.cum_produced_minor + stock.cum_imported_minor
                + stock.cum_extracted_minor)
    assert rep.economy["fulfilled"] <= rep.economy["demand"]


def test_rb18_unmet_demand_correct(tmp_path):
    env = _fresh_env(tmp_path, 17)
    rep = _run(env, years=120)
    eco = rep.engine_metrics["ECONOMY"]
    assert eco["unmet_minor"] == eco["demand_minor"] - eco["fulfilled_minor"]
    with env["factory"]() as s:
        for e in s.execute(select(WorldEvent).where(
                WorldEvent.event_type == "CONSUMPTION_FULFILLED")).scalars():
            assert e.effect["unmet_minor"] == \
                e.effect["demand_minor"] - e.effect["fulfilled_minor"]


def test_rb19_inventory_never_negative(tmp_path):
    env = _fresh_env(tmp_path, 18)
    _run(env, years=120)
    with env["factory"]() as s:
        for stock in s.execute(select(ResourceStock)).scalars():
            assert stock.quantity >= 0


# ------------------------------------------------------------ RB20-RB24
def test_rb20_transfer_conserves_quantity(tmp_path):
    env = _fresh_env(tmp_path, 19)
    rep = _run(env, years=120)
    eco = rep.engine_metrics["ECONOMY"]
    assert eco["imported_minor"] == eco["exported_minor"]
    assert eco["transfer_quantity_minor"] > 0  # 基线必须实际发生转移
    with env["factory"]() as s:
        for ref in ("TEST-RESOURCE-001", "TEST-RESOURCE-002"):
            rows = s.execute(select(ResourceStock).where(
                ResourceStock.resource_profile_ref == ref)).scalars().all()
            total = sum(r.quantity for r in rows)
            init = sum(_initial_stock(r.settlement_ref, ref) for r in rows)
            flows = sum(r.cum_extracted_minor + r.cum_produced_minor
                        - r.cum_input_minor - r.cum_consumed_minor
                        - r.cum_lost_minor for r in rows)
            assert total == init + flows, ref


def test_rb21_transfer_cannot_double_spend(tmp_path):
    env = _fresh_env(tmp_path, 20)
    rep = _run(env, years=120)
    with env["factory"]() as s:
        for stock in s.execute(select(ResourceStock)).scalars():
            assert stock.quantity >= 0
    eco = rep.engine_metrics["ECONOMY"]
    assert eco["exported_minor"] <= eco["production_output_minor"] \
        + rep.economy["initial_stock"]["TEST-RESOURCE-002"]


def test_rb22_retry_transfer_idempotent(tmp_path):
    env = _fresh_env(tmp_path, 21)
    _run(env, years=1)
    with env["factory"]() as s:
        before = {e.event_uid for e in s.execute(select(WorldEvent)).scalars()}
        stocks = {r.id: r.quantity for r in s.execute(
            select(ResourceStock)).scalars()}
    _run(env, years=1)  # 同区间重试
    with env["factory"]() as s:
        assert {e.event_uid for e in s.execute(
            select(WorldEvent)).scalars()} == before
        assert {r.id: r.quantity for r in s.execute(
            select(ResourceStock)).scalars()} == stocks


def test_rb23_stock_flow_ledger_reconciles(tmp_path):
    env = _fresh_env(tmp_path, 22)
    _run(env, years=60)
    with env["factory"]() as s:
        for r in s.execute(select(ResourceStock)).scalars():
            init = _initial_stock(r.settlement_ref, r.resource_profile_ref)
            flows = (r.cum_extracted_minor + r.cum_produced_minor
                     + r.cum_imported_minor - r.cum_input_minor
                     - r.cum_consumed_minor - r.cum_exported_minor
                     - r.cum_lost_minor)
            assert r.quantity == init + flows, (r.settlement_ref,
                                                r.resource_profile_ref)


def test_rb24_shortage_state_deterministic(tmp_path):
    a = _run(_fresh_env(tmp_path, 23), years=60)
    b = _run(_fresh_env(tmp_path, 24), years=60)
    assert a.engine_metrics["ECONOMY"]["shortage_pairs"] \
        == b.engine_metrics["ECONOMY"]["shortage_pairs"]
    assert a.engine_metrics["ECONOMY"]["unmet_minor"] \
        == b.engine_metrics["ECONOMY"]["unmet_minor"]


# ------------------------------------------------------------ RB25-RB29
def test_rb25_economic_pressure_persists_across_restart(tmp_path):
    env1 = _fresh_env(tmp_path, 25)
    one = _run(env1, years=30)
    env2 = _fresh_env(tmp_path, 26)
    _run(env2, years=15)
    part2 = _run(env2, years=15, start_year=15)
    assert part2.final_state_hash == one.final_state_hash
    a = _pressure_map(env1)
    b = _pressure_map(env2)
    assert set(a) == set(b)
    for k in a:
        for f in ("demand_minor", "fulfilled_minor", "unmet_minor",
                  "shortage_ratio_num", "shortage_ratio_den",
                  "sustained_shortage_steps", "stress_level"):
            assert a[k][f] == b[k][f], (k, f)


def _pressure_map(env) -> dict:
    with env["factory"]() as s:
        return {f"{p.settlement_ref}|{p.resource_profile_ref}": {
            "demand_minor": p.demand_minor,
            "fulfilled_minor": p.fulfilled_minor,
            "unmet_minor": p.unmet_minor,
            "shortage_ratio_num": p.shortage_ratio_num,
            "shortage_ratio_den": p.shortage_ratio_den,
            "sustained_shortage_steps": p.sustained_shortage_steps,
            "stress_level": p.stress_level,
        } for p in s.execute(select(EconomicPressureState)).scalars()}


def test_rb26_economy_feedback_cannot_alter_same_step_demography(tmp_path):
    integrated = _run(_fresh_env(tmp_path, 27), years=1)
    pop_only = run_mini_world_120y(_fresh_env(tmp_path, 28)["factory"],
                                   engines=[PopulationGroupEngine()],
                                   years=1)
    assert integrated.engine_metrics["DEMOGRAPHY"] \
        == pop_only.engine_metrics["DEMOGRAPHY"]
    assert integrated.population == pop_only.population


def test_rb27_next_step_feedback_channel_deterministic(tmp_path):
    env = _fresh_env(tmp_path, 29)
    factory = env["factory"]
    s1 = factory()
    lease = WriterLease(s1, MINI_WORLD_ID, 120)
    lease.acquire()
    coordinator = SimulationCoordinator(_engines())
    levels = []

    def step(s, info, _y):
        return coordinator.run_step(
            s, world_id=MINI_WORLD_ID,
            blessed_start_tick=info["new_blessed_tick"] - info["delta_ticks"],
            blessed_end_tick=info["new_blessed_tick"],
            real_interval_start_us=info["real_interval_start_us"],
            real_interval_end_us=info["real_interval_end_us"],
            step_index=_y)

    for year in range(1, 7):
        res = catch_up(factory, world_id=MINI_WORLD_ID,
                       now_real_us=EPOCH0_US + year * YEAR_US,
                       writer_id=lease.owner, fencing_token=lease.token,
                       simulation_version=SIM_VERSION,
                       simulate_fn=lambda s, info, _y=year: step(s, info, _y))
        levels.append(res.simulate_result.metrics["DEMOGRAPHY"][
            "max_pressure_level"])
    lease.release()
    s1.close()
    # step1：无前置压力（NEXT_COMMITTED_STEP 延迟 → 本步 ECONOMY 不影响）
    assert levels[0] == 0
    # 后续 step：上一 committed step 的 B 聚落短缺 → 压力非 0
    assert any(l > 0 for l in levels[1:])
    # 确定性：另一环境完全复现
    env2 = _fresh_env(tmp_path, 30)
    s2 = env2["factory"]()
    lease2 = WriterLease(s2, MINI_WORLD_ID, 120)
    lease2.acquire()
    coordinator2 = SimulationCoordinator(_engines())
    levels2 = []
    for year in range(1, 7):
        res = catch_up(env2["factory"], world_id=MINI_WORLD_ID,
                       now_real_us=EPOCH0_US + year * YEAR_US,
                       writer_id=lease2.owner, fencing_token=lease2.token,
                       simulation_version=SIM_VERSION,
                       simulate_fn=lambda s, info, _y=year:
                       coordinator2.run_step(
                           s, world_id=MINI_WORLD_ID,
                           blessed_start_tick=info["new_blessed_tick"]
                           - info["delta_ticks"],
                           blessed_end_tick=info["new_blessed_tick"],
                           real_interval_start_us=info[
                               "real_interval_start_us"],
                           real_interval_end_us=info["real_interval_end_us"],
                           step_index=_y))
        levels2.append(res.simulate_result.metrics["DEMOGRAPHY"][
            "max_pressure_level"])
    lease2.release()
    s2.close()
    assert levels == levels2


def test_rb28_formal_species_economy_profiles_remain_unconfigured():
    for species in ("Human", "Hairy Men", "Rockmen", "Mermen", "Mushroommen"):
        with pytest.raises(EconomyProfileUnconfigured) as ei:
            EconomyEngine()._profile_of(species)
        assert ei.value.code == "ECONOMY_UNCONFIGURED"


def test_rb29_formal_resource_profiles_remain_unconfigured(tmp_path):
    for rid in ("FORMAL-ORE-001", "FORMAL-FARM-001"):
        with pytest.raises(ResourceProfileUnconfigured) as ei:
            ResourceEngine()._profile_of(rid)
        assert ei.value.code == "RESOURCE_UNCONFIGURED"
    env = _fresh_env(tmp_path, 31)
    with env["factory"]() as s:
        node = s.execute(select(ResourceNode)).scalar_one()
        node.resource_profile_ref = "FORMAL-ORE-001"
        s.commit()
    with pytest.raises(ResourceProfileUnconfigured):
        _run(env, years=1)


# ------------------------------------------------------------ RB30-RB35
def test_rb30_event_uid_deterministic(tmp_path):
    a = _fresh_env(tmp_path, 32)
    b = _fresh_env(tmp_path, 33)
    _run(a, years=3)
    _run(b, years=3)
    with a["factory"]() as s:
        ua = [e.event_uid for e in s.execute(select(WorldEvent)).scalars()]
    with b["factory"]() as s:
        ub = [e.event_uid for e in s.execute(select(WorldEvent)).scalars()]
    assert ua == ub
    assert all(re.fullmatch(r"[0-9a-f]{32}", u) for u in ua)
    assert len(set(ua)) == len(ua)


def test_rb31_event_payload_included_in_event_stream_hash():
    base = [{"event_uid": "a" * 32, "blessed_tick": 1,
             "event_type": "RESOURCE_TRANSFERRED", "source": "SIMULATION",
             "cause": {"from_settlement": "A"},
             "effect": {"to_settlement": "B", "quantity_minor": 100},
             "severity": 0.0, "scope": "WORLD"}]
    changed = [dict(base[0], effect={"to_settlement": "B",
                                     "quantity_minor": 70})]
    h1 = step_event_stream_hash(None, world_id="W",
                                simulation_version=SIM_VERSION, events=base)
    h2 = step_event_stream_hash(None, world_id="W",
                                simulation_version=SIM_VERSION, events=changed)
    assert h1 != h2


def test_rb32_resource_economy_state_included_in_world_state_hash(tmp_path):
    env = _fresh_env(tmp_path, 34)
    _run(env, years=2)
    h1 = _hash_v3(env)
    with env["factory"]() as s:
        stock = s.execute(select(ResourceStock)).scalars().first()
        stock.quantity += 1
        s.commit()
    h2 = _hash_v3(env)
    assert h1 != h2


def test_rb33_hash_row_order_independent(tmp_path):
    env = _fresh_env(tmp_path, 35)
    h1 = _hash_v3(env)
    env2 = _fresh_env(tmp_path, 36)
    with env2["factory"]() as s:
        rows = s.execute(select(ResourceStock)).scalars().all()
        for r in rows:
            s.delete(r)
        s.flush()
        for r in reversed(rows):
            s.add(ResourceStock(
                world_id=r.world_id, settlement_ref=r.settlement_ref,
                resource_profile_ref=r.resource_profile_ref,
                quantity=r.quantity, consumption_carry=r.consumption_carry,
                engine_version=r.engine_version))
        s.commit()
    h2 = _hash_v3(env2)
    assert h1 == h2


def test_rb34_resource_rng_independent_from_demography(tmp_path):
    base = _run(_fresh_env(tmp_path, 37), years=4)
    extra = _run(_fresh_env(tmp_path, 38), years=4,
                 res=ResourceEngine(extra_draws=7))
    # RESOURCE 多抽 RNG：DEMOGRAPHY 必须完全不变（独立 substream）
    assert extra.engine_metrics["DEMOGRAPHY"] \
        == base.engine_metrics["DEMOGRAPHY"]
    assert extra.population == base.population
    # 且额外抽取确实发生（draw_count 可见）
    assert extra.engine_metrics["RESOURCE"]["nodes"] \
        == base.engine_metrics["RESOURCE"]["nodes"]


def test_rb35_economy_rng_independent_from_resource_demography(tmp_path):
    base = _run(_fresh_env(tmp_path, 39), years=4)
    extra = _run(_fresh_env(tmp_path, 40), years=4,
                 eco=EconomyEngine(extra_draws=5))
    assert extra.engine_metrics["ECONOMY"] == base.engine_metrics["ECONOMY"]
    assert extra.engine_metrics["RESOURCE"] == base.engine_metrics["RESOURCE"]
    assert extra.engine_metrics["DEMOGRAPHY"] == base.engine_metrics["DEMOGRAPHY"]
    assert extra.final_state_hash == base.final_state_hash


# ------------------------------------------------------------ RB36-RB42
def test_rb36_stale_writer_cannot_commit(tmp_path):
    env = _fresh_env(tmp_path, 41)
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
        node = s.execute(select(ResourceNode)).scalar_one()
        assert node.remaining_reserve == MINI_ORE_RESERVE_UNITS * MINI_SCALE
        assert s.execute(text(
            "SELECT COUNT(*) FROM world_events")).scalar() == 0
        assert s.execute(text(
            "SELECT COUNT(*) FROM simulation_checkpoints")).scalar() == 0
        assert s.execute(select(WorldRuntime)).scalar_one() \
            .current_blessed_tick == 0
    lease.release()
    s1.close()


def test_rb37_retry_zero_duplicate_extraction(tmp_path):
    env = _fresh_env(tmp_path, 42)
    a = _run(env, years=1)
    ext = a.engine_metrics["RESOURCE"]["extracted_minor"]
    b = _run(env, years=1)
    assert b.final_blessed_tick == a.final_blessed_tick
    with env["factory"]() as s:
        node = s.execute(select(ResourceNode)).scalar_one()
        assert node.remaining_reserve == \
            MINI_ORE_RESERVE_UNITS * MINI_SCALE - ext


def test_rb38_retry_zero_duplicate_production_consumption(tmp_path):
    env = _fresh_env(tmp_path, 43)
    a = _run(env, years=1)
    _run(env, years=1)
    max_gross = (a.engine_metrics["ECONOMY"]["production_output_minor"]
                 + a.engine_metrics["ECONOMY"]["loss_minor"])
    max_demand = a.engine_metrics["ECONOMY"]["demand_minor"]
    with env["factory"]() as s:
        for stock in s.execute(select(ResourceStock)).scalars():
            assert stock.cum_produced_minor <= max_gross
        for p in s.execute(select(EconomicPressureState)).scalars():
            assert p.demand_minor <= max_demand


def test_rb39_retry_zero_duplicate_events(tmp_path):
    env = _fresh_env(tmp_path, 44)
    _run(env, years=1)
    with env["factory"]() as s:
        uids = {e.event_uid for e in s.execute(select(WorldEvent)).scalars()}
    _run(env, years=1)
    with env["factory"]() as s:
        assert {e.event_uid for e in s.execute(
            select(WorldEvent)).scalars()} == uids


def _crash_and_recover(tmp_path, i, crash_after):
    env = _fresh_env(tmp_path, i)
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
        node = s.execute(select(ResourceNode)).scalar_one()
        assert node.remaining_reserve == MINI_ORE_RESERVE_UNITS * MINI_SCALE
        assert latest_authoritative_world_checkpoint(s, MINI_WORLD_ID) is None
    catch_up(factory, world_id=MINI_WORLD_ID,
             now_real_us=EPOCH0_US + YEAR_US,
             writer_id=lease.owner, fencing_token=lease.token,
             simulation_version=SIM_VERSION, simulate_fn=step)
    ref = _run(_fresh_env(tmp_path, i + 1000), years=1)
    with factory() as s:
        h = latest_authoritative_world_checkpoint(s, MINI_WORLD_ID) \
            .world_state_hash
    assert h == ref.final_state_hash
    lease.release()
    s1.close()


def test_rb40_crash_after_resource_staged_recovers(tmp_path):
    _crash_and_recover(tmp_path, 45, "engine:ECONOMY")


def test_rb41_crash_after_economy_staged_recovers(tmp_path):
    _crash_and_recover(tmp_path, 46, "after_engines")


def test_rb42_time_world_checkpoint_split_consistency(tmp_path):
    env = _fresh_env(tmp_path, 47)
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

    # R8：M2 checkpoint 已建、commit ack 丢失 → 回滚后两层都不存在
    with pytest.raises(RuntimeError):
        catch_up(factory, world_id=MINI_WORLD_ID,
                 now_real_us=EPOCH0_US + YEAR_US,
                 writer_id=lease.owner, fencing_token=lease.token,
                 simulation_version=SIM_VERSION,
                 simulate_fn=lambda s, info: step(s, info, "after_checkpoint"))
    with factory() as s:
        assert s.execute(text(
            "SELECT COUNT(*) FROM simulation_checkpoints")).scalar() == 0
        assert s.execute(select(WorldRuntime)).scalar_one() \
            .current_blessed_tick == 0
    catch_up(factory, world_id=MINI_WORLD_ID,
             now_real_us=EPOCH0_US + YEAR_US,
             writer_id=lease.owner, fencing_token=lease.token,
             simulation_version=SIM_VERSION, simulate_fn=step)
    with factory() as s:
        rows = s.execute(select(SimulationCheckpoint)).scalars().all()
        ticks = {c.checkpoint_blessed_tick for c in rows}
        assert ticks == {1_000_000}  # TIME 与 WORLD 同 tick、同事务
        world = latest_authoritative_world_checkpoint(s, MINI_WORLD_ID)
        assert world is not None
        assert world.meta["checkpoint_kind"] == "WORLD_COMMITTED"
        time_rows = [c for c in rows
                     if c.meta.get("checkpoint_kind") == "TIME_COMMITTED"]
        assert time_rows and time_rows[0].checkpoint_blessed_tick \
            <= world.checkpoint_blessed_tick
    lease.release()
    s1.close()


# ------------------------------------------------------------ R1-R8 崩溃矩阵
@pytest.mark.parametrize("crash_after", [
    "engine:RESOURCE",    # R1：after DEMOGRAPHY staged
    "mid:RESOURCE",       # R2：mid RESOURCE
    "engine:ECONOMY",     # R3：after RESOURCE staged
    "mid:ECONOMY",        # R4：mid ECONOMY
    "after_engines",      # R5：after ECONOMY staged
    "during_apply",       # R6：during authoritative write
    "before_checkpoint",  # R7：事件已写、世界 checkpoint 未建（原子对）
    "after_checkpoint",   # R8：commit ack lost
])
def test_rb_crash_matrix_r1_r8(tmp_path, crash_after):
    _crash_and_recover(tmp_path, 100 + hash(crash_after) % 200, crash_after)


# ------------------------------------------------------------ RB43-RB47
def test_rb43_120y_integrated_run_completes(tmp_path):
    env = _fresh_env(tmp_path, 48)
    rep = _run(env, years=120)
    assert rep.steps == 120
    assert rep.runs == 120
    assert rep.checkpoints == 240
    assert rep.final_blessed_tick == 120_000_000
    assert rep.engine_metrics["RESOURCE"]["extracted_minor"] > 0
    assert rep.engine_metrics["ECONOMY"]["production_output_minor"] > 0


def test_rb44_120y_all_resource_invariants_pass(tmp_path):
    env = _fresh_env(tmp_path, 49)
    rep = _run(env, years=120)
    extracted = MINI_ORE_RESERVE_UNITS * MINI_SCALE - rep.resource[
        "final_reserve"]
    assert 0 <= extracted <= MINI_ORE_RESERVE_UNITS * MINI_SCALE   # RE_INV_03
    assert extracted <= MINI_ORE_CAPACITY_UNITS * MINI_SCALE * 120  # RE_INV_04
    with env["factory"]() as s:
        node = s.execute(select(ResourceNode)).scalar_one()
        assert node.remaining_reserve >= 0                         # RE_INV_02
        assert isinstance(node.remaining_reserve, int)             # RE_INV_08
        assert 0 <= node.extraction_carry < 1_000_000              # RE_INV_18


def test_rb45_120y_all_economy_invariants_pass(tmp_path):
    env = _fresh_env(tmp_path, 50)
    rep = _run(env, years=120)
    eco = rep.engine_metrics["ECONOMY"]
    assert eco["fulfilled_minor"] <= eco["demand_minor"]           # RE_INV_05
    assert eco["unmet_minor"] >= 0                                 # RE_INV_07
    assert eco["imported_minor"] == eco["exported_minor"]          # RE_INV_11
    with env["factory"]() as s:
        for stock in s.execute(select(ResourceStock)).scalars():
            assert stock.quantity >= 0                             # RE_INV_01
            assert isinstance(stock.quantity, int)                 # RE_INV_08
            assert 0 <= stock.consumption_carry < 6_000_000        # RE_INV_18
        for ps in s.execute(select(ProductionState)).scalars():
            assert 0 <= ps.production_carry < 1_000_000            # RE_INV_18
        for p in s.execute(select(EconomicPressureState)).scalars():
            assert p.unmet_minor >= 0
            assert p.fulfilled_minor <= p.demand_minor
            assert p.shortage_ratio_den >= 1
            assert 0 <= p.shortage_ratio_num <= p.shortage_ratio_den


def test_rb46_continuous_equals_chunked_replay(tmp_path):
    one = _run(_fresh_env(tmp_path, 51), years=120)
    chunk = _run(_fresh_env(tmp_path, 52), years=120,
                 restart_every_years=30)
    assert one.final_state_hash == chunk.final_state_hash
    assert one.population == chunk.population
    assert one.resource == chunk.resource
    assert one.economy == chunk.economy
    assert one.engine_metrics == chunk.engine_metrics


def test_rb47_restart_equals_continuous(tmp_path):
    one = _run(_fresh_env(tmp_path, 53), years=120)
    env = _fresh_env(tmp_path, 54)
    part1 = _run(env, years=60)
    part2 = _run(env, years=60, start_year=60)
    assert part2.final_state_hash == one.final_state_hash
    assert part2.population["end"] == one.population["end"]
    assert part2.resource["final_reserve"] == one.resource["final_reserve"]
    assert part2.economy["final_stock"] == one.economy["final_stock"]
    combined = {k: part1.engine_metrics["ECONOMY"][k]
                + part2.engine_metrics["ECONOMY"][k]
                for k in ("production_input_minor", "production_output_minor",
                          "demand_minor", "fulfilled_minor", "unmet_minor",
                          "imported_minor", "exported_minor")}
    assert combined == {k: one.engine_metrics["ECONOMY"][k]
                        for k in ("production_input_minor",
                                  "production_output_minor", "demand_minor",
                                  "fulfilled_minor", "unmet_minor",
                                  "imported_minor", "exported_minor")}
    combined_res = (part1.engine_metrics["RESOURCE"]["extracted_minor"]
                    + part2.engine_metrics["RESOURCE"]["extracted_minor"])
    assert combined_res == one.engine_metrics["RESOURCE"]["extracted_minor"]
    for k in ("births", "deaths", "immigration", "emigration"):
        assert part1.engine_metrics["DEMOGRAPHY"][k] \
            + part2.engine_metrics["DEMOGRAPHY"][k] \
            == one.engine_metrics["DEMOGRAPHY"][k]


# ------------------------------------------------------------ RB48-RB53
def test_rb48_llm_calls_zero():
    for name in ("resource.py", "economy.py", "feedback.py"):
        src = (SIM_DIR / name).read_text(encoding="utf-8")
        for token in ("openai", "anthropic", "llm"):
            assert token not in src, (name, token)


def test_rb49_network_calls_zero(tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("simulation core 触碰网络")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr("urllib.request.urlopen", _boom, raising=False)
    monkeypatch.setattr("http.client.HTTPConnection", _boom, raising=False)
    rep = _run(_fresh_env(tmp_path, 55), years=5)
    assert rep.final_blessed_tick == 5_000_000


def test_rb50_wall_clock_simulation_dependency_zero():
    pattern = re.compile(
        r"\b(datetime\.now|time\.time|time\.monotonic|perf_counter"
        r"|time_ns|date\.today)\s*\(")
    for name in ("resource.py", "economy.py"):
        src = (SIM_DIR / name).read_text(encoding="utf-8")
        assert not pattern.search(src), name


def test_rb51_world_seed_not_consumed():
    for py in SIM_DIR.rglob("*.py"):
        src = py.read_text(encoding="utf-8")
        assert "world_seed" not in src, py
        assert "04_population_baseline" not in src, py


def test_rb52_formal_db_content_remains_empty(formal_db_guard):
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
        assert conn.execute(
            "SELECT COUNT(*) FROM population_groups").fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM resource_nodes").fetchone()[0] == 0
        existing = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for t in ("resource_profiles", "resource_stocks", "production_recipes",
                  "production_state", "economic_pressure_state"):
            if t in existing:
                assert conn.execute(
                    f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] == 0, t
    finally:
        conn.close()


def test_rb53_formal_db_integrity_ok(formal_db_guard):
    path = os.environ.get("BLR_FORMAL_DB_PATH", "")
    if not path or formal_db_guard is None:
        pytest.skip("BLR_FORMAL_DB_PATH 未设置")
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


# ------------------------------------------------------------ 120y 基线产物
def test_m2b_baseline_120y_artifact(tmp_path):
    start = datetime.now(timezone.utc)
    env = _fresh_env(tmp_path, 56)
    rep = _run(env, years=120)
    wall = (datetime.now(timezone.utc) - start).total_seconds()
    _write_m2b_baseline(env, rep, wall)
    assert BASELINE_PATH.exists()
    artifact = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    env2 = _fresh_env(tmp_path, 57)
    rep2 = _run(env2, years=120)
    assert rep2.final_state_hash == artifact["final_world_state_hash"]
    with env2["factory"]() as s:
        h2 = latest_authoritative_world_checkpoint(
            s, MINI_WORLD_ID).meta["event_stream_hash"]
    assert h2 == artifact["final_event_stream_hash"]
    pm = artifact["population_metrics"]
    assert rep2.population == {"start": pm["start"], "end": pm["end"],
                               "births": pm["births"], "deaths": pm["deaths"],
                               "migrations": pm["emigration"]}
    assert rep2.resource["initial_reserve"] == artifact["resource_metrics"][
        "initial_reserve"]
    assert rep2.resource["final_reserve"] == artifact["resource_metrics"][
        "final_reserve"]
    assert rep2.resource["total_extracted"] == artifact["resource_metrics"][
        "total_extracted"]
    em = artifact["economy_metrics"]
    for k in ("initial_stock", "final_stock", "production_input",
              "production_output", "demand", "fulfilled", "unmet", "imports",
              "exports", "transfers", "shortage_steps"):
        assert rep2.economy[k] == em[k], k


def _hash_v3(env) -> str:
    with env["factory"]() as s:
        snap = read_snapshot(s, MINI_WORLD_ID)
        return world_state_hash_v3(
            snapshot=snap, simulation_version=SIM_VERSION,
            pipeline_version="m2-preflight-1",
            engine_versions={"DEMOGRAPHY": "m2a-1",
                             "RESOURCE": RES_ENGINE_VERSION,
                             "ECONOMY": ECO_ENGINE_VERSION})


def _write_m2b_baseline(env, rep, wall_seconds: float) -> None:
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with env["factory"]() as s:
        latest = latest_authoritative_world_checkpoint(s, MINI_WORLD_ID)
        event_hash = latest.meta["event_stream_hash"]
        node = s.execute(select(ResourceNode)).scalar_one()
        stocks = {r.resource_profile_ref: r.quantity for r in s.execute(
            select(ResourceStock)).scalars()}
    artifact = {
        "fixture_version": "mini_world_v1",
        "simulation_version": SIM_VERSION,
        "population_engine_version": "m2a-1",
        "resource_engine_version": RES_ENGINE_VERSION,
        "economy_engine_version": ECO_ENGINE_VERSION,
        "rng_schema_version": "m1-derive-seed-v1",
        "event_uid_schema_version": 1,
        "event_stream_hash_schema_version": 1,
        "world_state_hash_schema_version": WORLD_STATE_HASH_SCHEMA_VERSION,
        "initial_state": {
            "population": 400, "settlements": 2,
            "species": "TEST-SPECIES-001",
            "resource_reserve_units": MINI_ORE_RESERVE_UNITS,
            "ore_capacity_units": MINI_ORE_CAPACITY_UNITS,
            "recipe": MINI_RECIPE["recipe_id"],
        },
        "final_state": {
            "population": rep.population["end"],
            "resource_reserve_units": node.remaining_reserve // MINI_SCALE,
            "stock_minor_by_resource": stocks,
        },
        "population_metrics": {
            "start": rep.population["start"],
            "end": rep.population["end"],
            "births": rep.population["births"],
            "deaths": rep.population["deaths"],
            "immigration": rep.engine_metrics["DEMOGRAPHY"]["immigration"],
            "emigration": rep.engine_metrics["DEMOGRAPHY"]["emigration"],
        },
        "resource_metrics": {
            "initial_reserve": rep.resource["initial_reserve"],
            "final_reserve": rep.resource["final_reserve"],
            "total_extracted": rep.resource["total_extracted"],
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
        "final_world_state_hash": rep.final_state_hash,
        "final_event_stream_hash": event_hash,
        "runs": rep.runs,
        "steps": rep.steps,
        "checkpoints": rep.checkpoints,
        "event_counts": {"total": rep.events,
                         "resource_extracted": _count_events(
                             env, "RESOURCE_EXTRACTED"),
                         "production_completed": _count_events(
                             env, "PRODUCTION_COMPLETED"),
                         "consumption_fulfilled": _count_events(
                             env, "CONSUMPTION_FULFILLED"),
                         "resource_transferred": _count_events(
                             env, "RESOURCE_TRANSFERRED"),
                         "resource_shortage": _count_events(
                             env, "RESOURCE_SHORTAGE")},
        "performance": {"wall_seconds": round(wall_seconds, 3)},
    }
    BASELINE_PATH.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=1), encoding="utf-8")


def _count_events(env, event_type: str) -> int:
    with env["factory"]() as s:
        return len(s.execute(select(WorldEvent).where(
            WorldEvent.event_type == event_type)).scalars().all())

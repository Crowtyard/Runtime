"""M6C.1D — test-only synthetic bootstrap writer + REAL engine runner.

THIS_IS_TEST_ONLY_SYNTHETIC_BOOTSTRAP (never imported by production code).

Flow (owner §3):
    temp SQLite -> migrations -> real activation service (synthetic seed)
    -> confirm ACTIVE -> test-only bootstrap transaction -> commit -> real engine run

TEST_BOOTSTRAP_ATOMICITY_WITH_ACTIVATION = NOT_TESTED_IN_M6C1D
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
from fractions import Fraction

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from sqlalchemy import func, select, text  # noqa: E402

from tests import m6c1d_support as S  # noqa: E402
from XiaoguangBlessedLandRuntime.database.db import (  # noqa: E402
    create_db_engine, make_session_factory)
from XiaoguangBlessedLandRuntime.database.models_core import WorldEvent  # noqa: E402
from XiaoguangBlessedLandRuntime.database.models_world import (  # noqa: E402
    EcologyFeedbackState, EcologyState, EcologyZone, EconomicPressureState,
    Institution, Lineage, Household, PopulationGroup, ProductionRecipe,
    ProductionState, ResourceNode, ResourceProfile, ResourceStock, Settlement,
    SettlementSocialState, SocialFeedbackState, Tribulation, TribulationEpisode,
    TribulationProfile, TribulationSchedule)
from XiaoguangBlessedLandRuntime.services.db_lifecycle import migrate_database  # noqa: E402
from XiaoguangBlessedLandRuntime.services.simulation.ecology import (  # noqa: E402
    ECOLOGY_STATE_SCALE)
from XiaoguangBlessedLandRuntime.services.simulation.m3a_runner import (  # noqa: E402
    run_m3a_world)

WORLD_ID = S.WORLD_ID
EPOCH0_US = 1_767_225_600_000_000
SIMULATION_VERSION = S.SIMULATION_VERSION
CHECKPOINTS = (0, 4, 10, 50, 100, 300)


# ------------------------------------------------------------------ bootstrap rows
def write_bootstrap_rows(session) -> dict:
    """Write the owner-selected bootstrap payload (P-A/RE-A/E-B/S-B/T-B)."""
    p1 = S.candidate("P1", "P-A")
    re_a = S.candidate("RE1", "RE-A")
    e_b = S.candidate("E1", "E-B")
    s_b = S.candidate("S1", "S-B")
    t_b = S.candidate("T1", "T-B")

    matrix = S.allocation()
    buckets = int(p1["PROFILE"]["cohort_buckets"])
    zone_id = "ZONE-01"

    # settlements (population_capacity = NULL per owner P-A)
    for slot, kind, _cap in S.SETTLEMENT_SLOTS:
        session.add(Settlement(world_id=WORLD_ID, settlement_type=kind,
                               region_ref=None, working_name=slot,
                               state="ACTIVE", population_capacity=None))

    # population_groups: 12 settlements x 4 species x 61 buckets = 2928
    for j, (slot, _k, _c) in enumerate(S.SETTLEMENT_SLOTS):
        for i, (species, _total) in enumerate(S.SPECIES):
            counts = S.cohort_counts(matrix[i][j])
            assert sum(counts) == matrix[i][j]
            for b, n in enumerate(counts):
                session.add(PopulationGroup(
                    world_id=WORLD_ID, species=species, settlement_ref=slot,
                    age_cohort=str(b), occupation_group=None, household_stats=None,
                    count=n, updated_blessed_tick=0, age_advance_carry_ticks=0,
                    species_profile_ref="FORMAL-SPECIES-001",
                    demography_version="formal-1.0"))

    # resources: 7 formal profiles + 7 nodes (minimal topology) + 12x7 stocks
    per_capita = Fraction(re_a["VALUES"]["per_capita_demand"])
    loss = Fraction(re_a["VALUES"]["loss"])
    recipe_input = 100
    recipe_output = int(Fraction(recipe_input) * (Fraction(1) - loss))
    capacity_multiple = Fraction(re_a["VALUES"]["capacity_multiple"])
    node_extraction_total = 0
    main_annual = int(Fraction(S.SETTLEMENT_SLOTS[0][2]) * per_capita)
    for kind in S.CONSUMPTION_KINDS:
        session.add(ProductionRecipe(
            world_id=WORLD_ID, recipe_id=f"RECIPE-{kind}",
            input_resource_ref=kind, input_qty_minor=recipe_input,
            output_resource_ref=kind, output_qty_minor=recipe_output,
            capacity_batches_per_year=max(1, int(
                Fraction(main_annual) * capacity_multiple / recipe_output)),
            labor_per_batch=10, loss_num=loss.numerator,
            loss_den=loss.denominator, semantic_version="formal-1.0"))
        session.add(ResourceProfile(
            world_id=WORLD_ID, resource_id=kind, unit="unit",
            quantity_scale=1_000_000, renewability="RENEWABLE",
            extractability="EXTRACTABLE", consumption_category="CONSUMPTION",
            production_usability="INPUT", semantic_version="formal-1.0"))
    stocks_rows = 0
    for j, (slot, _k, _c) in enumerate(S.SETTLEMENT_SLOTS):
        settlement_pop = sum(matrix[i][j] for i in range(len(S.SPECIES)))
        annual = int(Fraction(settlement_pop) * per_capita)
        for kind in S.CONSUMPTION_KINDS:
            session.add(ResourceStock(
                world_id=WORLD_ID, settlement_ref=slot, resource_profile_ref=kind,
                quantity=annual, consumption_carry=0, updated_blessed_tick=0))
            stocks_rows += 1
            session.add(EconomicPressureState(
                world_id=WORLD_ID, settlement_ref=slot, resource_profile_ref=kind))
            session.add(ProductionState(
                world_id=WORLD_ID, settlement_ref=slot,
                recipe_ref=f"RECIPE-{kind}", production_carry=0,
                updated_blessed_tick=0))
    node_reserve = 10_000_000_000
    for kind in S.CONSUMPTION_KINDS:
        annual_total = int(Fraction(
            sum(sum(matrix[i][j] for i in range(len(S.SPECIES)))
                for j in range(len(S.SETTLEMENT_SLOTS)))) * per_capita)
        extraction = int(Fraction(annual_total) * capacity_multiple
                         / len(S.CONSUMPTION_KINDS))
        node_extraction_total += extraction
        session.add(ResourceNode(
            world_id=WORLD_ID, kind=kind, region_ref=None, state="STABLE",
            yield_model=None, history_ref=None, resource_profile_ref=kind,
            settlement_relation=S.SETTLEMENT_SLOTS[0][0],
            remaining_reserve=node_reserve, extraction_capacity=extraction,
            extraction_carry=0, last_extracted_minor=0, engine_version=None,
            state_version=0, updated_blessed_tick=0, reserve_ceiling_minor=None,
            regeneration_carry=0))

    # ecology: 1 minimal root zone (E-B) + state + feedback, FULL_QUALITY
    session.add(EcologyZone(world_id=WORLD_ID, zone_id=zone_id, region_ref=None,
                            settlement_relation=S.SETTLEMENT_SLOTS[0][0],
                            profile_ref="FORMAL-ECOLOGY-001",
                            semantic_version="formal-1.0"))
    session.add(EcologyState(
        world_id=WORLD_ID, zone_ref=zone_id, habitat_quality=ECOLOGY_STATE_SCALE,
        regeneration_capacity=ECOLOGY_STATE_SCALE, ecological_stress=0,
        population_pressure=0, extraction_pressure=0, production_pressure=0,
        depletion_pressure=0, external_pressure=0, degradation_carry=0,
        recovery_carry=0, quality_min_seen=ECOLOGY_STATE_SCALE,
        quality_max_seen=ECOLOGY_STATE_SCALE, updated_blessed_tick=0))
    session.add(EcologyFeedbackState(
        world_id=WORLD_ID, zone_ref=zone_id,
        regeneration_capacity_minor_per_year=0, habitat_stress_level="NONE",
        updated_blessed_tick=0))

    # social: 12 settlements x (state + feedback)
    for slot, _k, _c in S.SETTLEMENT_SLOTS:
        session.add(SettlementSocialState(world_id=WORLD_ID, settlement_ref=slot))
        session.add(SocialFeedbackState(world_id=WORLD_ID, settlement_ref=slot))

    # tribulation: 3 formal profiles (DB rows) + 3 schedules 10/50/100
    specs = S.tribulation_registry()
    for profile_id, spec in specs.items():
        session.add(TribulationProfile(
            world_id=WORLD_ID, profile_id=profile_id, tier=spec.tier,
            theme=spec.theme, intensity_min=spec.intensity_min,
            intensity_max=spec.intensity_max, precursor_steps=spec.precursor_steps,
            preparation_steps=spec.preparation_steps, impact_steps=spec.impact_steps,
            population_risk_num=spec.population_risk.numerator,
            population_risk_den=spec.population_risk.denominator,
            resource_damage_num=spec.resource_damage.numerator,
            resource_damage_den=spec.resource_damage.denominator,
            inventory_damage_num=spec.inventory_damage.numerator,
            inventory_damage_den=spec.inventory_damage.denominator,
            production_disruption_num=spec.production_disruption.numerator,
            production_disruption_den=spec.production_disruption.denominator,
            social_displacement_num=spec.social_displacement.numerator,
            social_displacement_den=spec.social_displacement.denominator,
            institution_disruption_num=spec.institution_disruption.numerator,
            institution_disruption_den=spec.institution_disruption.denominator,
            ecology_pressure=spec.ecology_pressure,
            recovery_steps=spec.recovery_steps, status="FORMAL",
            targeting_rules={}, succession_rules=spec.succession_rules,
            source_refs={"owner_selection": "M6C1C/T-B"},
            semantic_version="formal-1.0"))
    for tier, period in S.packet()["NUMERIC_OD_T1"]["periods"].items():
        session.add(TribulationSchedule(
            world_id=WORLD_ID, schedule_id=f"SCHEDULE-{tier}", tier=tier,
            period_years=int(period), enabled=True, semantic_version="formal-1.0"))

    session.flush()
    return {"buckets": buckets, "stocks_rows": stocks_rows,
            "node_extraction_total": node_extraction_total,
            "recipe_output": recipe_output,
            "per_capita": str(per_capita), "s_b": s_b, "e_b": e_b, "t_b": t_b}


# ------------------------------------------------------------------ world build
def build_world(work: pathlib.Path, *, tag: str = "world",
                via: str = "activation") -> dict:
    """migrated temp DB -> ACTIVE synthetic world -> test-only bootstrap rows.

    via="activation"：走真实 activation service（owner §3 首选流程）。
    via="direct"    ：M3a 风格直接构造 ACTIVE runtime 行（activation service 的
                      writer-lease 在 SQLite 独立进程下会竞争失败；direct 模式只跳过
                      激活路径本身，**不改任何 production semantics**）。
    """
    work.mkdir(parents=True, exist_ok=True)
    db_path = work / f"m6c1d_{tag}.db"
    url = "sqlite:///" + str(db_path).replace("\\", "/")
    migrate_database(url, project_root=ROOT)
    engine = create_db_engine(url)
    factory = make_session_factory(engine)
    outcome = None
    seed_dir = None
    if via == "activation":
        from tests.m6_activation_support import (build_synthetic_seed,
                                                 synthetic_request)
        from XiaoguangBlessedLandRuntime.services.activation import (
            activate_formal_world)
        seed_dir = build_synthetic_seed(work, name=f"seed_{tag}")
        request = synthetic_request(seed_dir, world_id=WORLD_ID,
                                    activation_anchor_us=EPOCH0_US)
        outcome = activate_formal_world(factory, request=request)
    else:
        from XiaoguangBlessedLandRuntime.database.models_core import WorldRuntime
        from XiaoguangBlessedLandRuntime.domain.constants import RuntimeStatus
        from XiaoguangBlessedLandRuntime.services.repositories import (
            RuntimeRepository, TimeRatioRepository)
        from datetime import datetime, timezone
        with factory() as session:
            RuntimeRepository(session).create_not_activated(
                world_id=WORLD_ID, world_bible_version="1.0",
                simulation_version=SIMULATION_VERSION,
                world_bible_manifest_hash="synthetic-m6c1d")
            row = session.execute(select(WorldRuntime)).scalar_one()
            row.runtime_status = RuntimeStatus.ACTIVE
            row.world_seed_version = "SYNTHETIC-M6C1D-SEED"
            row.current_blessed_tick = 0
            row.last_committed_real_us = EPOCH0_US
            row.time_rate_remainder = 0
            rate = TimeRatioRepository(session).add(
                world_id=WORLD_ID,
                real_effective_from=datetime.fromtimestamp(
                    EPOCH0_US / 1_000_000, tz=timezone.utc),
                rate_numerator=1_000_000, rate_denominator=86_400_000_000,
                reason="TEST", source="TEST")
            row.current_time_ratio_id = rate.ratio_id
            session.commit()
    with factory() as session:
        info = write_bootstrap_rows(session)
        session.commit()
    return {"url": url, "factory": factory, "engine": engine, "db_path": db_path,
            "seed_dir": seed_dir, "outcome": outcome, "info": info, "via": via}


def self_check(env: dict) -> dict:
    """owner §5 — 任何不一致即 STOP（不启动长跑）。"""
    factory = env["factory"]
    out: dict = {}
    with factory() as s:
        out["SETTLEMENT_ROWS"] = s.scalar(select(func.count()).select_from(Settlement))
        out["POPULATION_GROUP_ROWS"] = s.scalar(
            select(func.count()).select_from(PopulationGroup))
        out["POPULATION_SUM"] = int(s.scalar(
            select(func.coalesce(func.sum(PopulationGroup.count), 0))) or 0)
        out["GROUP_TOTALS"] = [
            int(s.scalar(select(func.coalesce(func.sum(PopulationGroup.count), 0))
                         .where(PopulationGroup.species == sp)) or 0)
            for sp, _ in S.SPECIES]
        out["SETTLEMENT_TOTALS"] = [
            int(s.scalar(select(func.coalesce(func.sum(PopulationGroup.count), 0))
                         .where(PopulationGroup.settlement_ref == slot)) or 0)
            for slot, _k, _c in S.SETTLEMENT_SLOTS]
        out["RESOURCE_PROFILE_ROWS"] = s.scalar(
            select(func.count()).select_from(ResourceProfile))
        out["RESOURCE_NODE_ROWS"] = s.scalar(
            select(func.count()).select_from(ResourceNode))
        out["RESOURCE_STOCK_ROWS"] = s.scalar(
            select(func.count()).select_from(ResourceStock))
        out["ECOLOGY_ROOT_ROWS"] = s.scalar(
            select(func.count()).select_from(EcologyZone))
        out["ECOLOGY_STATE_ROWS"] = s.scalar(
            select(func.count()).select_from(EcologyState))
        out["ECOLOGY_FEEDBACK_ROWS"] = s.scalar(
            select(func.count()).select_from(EcologyFeedbackState))
        out["SOCIAL_ROWS"] = (s.scalar(select(func.count())
                                       .select_from(SettlementSocialState))
                              + s.scalar(select(func.count())
                                         .select_from(SocialFeedbackState)))
        out["TRIBULATION_SCHEDULE_ROWS"] = s.scalar(
            select(func.count()).select_from(TribulationSchedule))
        out["TWIN_GENESIS"] = s.scalar(
            select(func.count()).select_from(WorldEvent)
            .where(WorldEvent.event_type == "WORLD_SEED_ACTIVATED"))
    # TEST profile references must be zero anywhere in the world data
    with factory() as s:
        out["TEST_PROFILE_REFERENCES"] = int(s.scalar(text(
            "SELECT (SELECT COUNT(*) FROM population_groups "
            " WHERE species LIKE 'TEST%' OR species_profile_ref LIKE 'TEST%')"
            " + (SELECT COUNT(*) FROM resource_profiles WHERE resource_id LIKE 'TEST%')"
            " + (SELECT COUNT(*) FROM tribulation_profiles "
            "    WHERE profile_id LIKE 'TEST%' OR status LIKE 'TEST%')")) or 0)
    out["POPULATION_TOTAL_OK"] = out["POPULATION_SUM"] == 12_000
    out["GROUP_TOTALS_OK"] = out["GROUP_TOTALS"] == [4000, 3000, 2500, 2500]
    out["SETTLEMENT_TOTALS_OK"] = out["SETTLEMENT_TOTALS"] == [2000] * 4 + [500] * 8
    out["ROWS_OK"] = (out["POPULATION_GROUP_ROWS"] == 12 * 4 * 61
                      and out["RESOURCE_NODE_ROWS"] == 7
                      and out["TRIBULATION_SCHEDULE_ROWS"] == 3
                      and out["TEST_PROFILE_REFERENCES"] == 0)
    out["SELF_CHECK"] = all(out[k] for k in (
        "POPULATION_TOTAL_OK", "GROUP_TOTALS_OK", "SETTLEMENT_TOTALS_OK", "ROWS_OK"))
    return out

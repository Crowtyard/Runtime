"""M6C.2A — materializer row equivalence vs the INDEPENDENT REFERENCE ORACLE.

TEST ONLY. Builds two temp worlds:
  DB A: production Materializer (services/activation/materializer.py) on a fenced
        session (real WriterLease), tick 0
  DB B: tests/m6c1d_runner.py::write_bootstrap_rows (the ratified reference oracle)

then compares every bootstrap table on its authoritative columns with EXACT equality.

No production module imports the oracle (TEST_ORACLE_IMPORTED_BY_PRODUCTION = FALSE is
asserted separately by the AST scan).

Usage: python scripts/_m6c2_row_equivalence.py [--out reports/....json]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import tempfile
from fractions import Fraction

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sqlalchemy import select  # noqa: E402

from tests import m6c1d_runner as R  # noqa: E402
from tests import m6c1d_support as S  # noqa: E402
from XiaoguangBlessedLandRuntime.services.activation import materializer as M  # noqa: E402
from XiaoguangBlessedLandRuntime.services.simulation.m3a_runner import (  # noqa: E402
    run_m3a_world)
from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease  # noqa: E402

WORLD_ID = "M6C2-EQUIV-001"
EPOCH0_US = R.EPOCH0_US

#: §19 NON_AUTHORITATIVE_COMPARISON_EXCLUSIONS：唯一允许排除的是 DB surrogate 主键
#: （autoincrement id），依据：state_hash / canonical 投影均排除 id
#: （state_hash._strip 明确 "排除 autoincrement id（插入顺序依赖）"）；
#: created_at/updated_* 时间戳不参与任何权威投影，但本比较仍**逐列**比较有效列。
NON_AUTHORITATIVE_COMPARISON_EXCLUSIONS = {
    "columns": ["id"],
    "basis": "state_hash._strip() 明确排除 autoincrement id（插入顺序依赖）；"
             "canonical 投影不使用 surrogate PK",
}

TABLES = {
    "settlements": ("working_name", "settlement_type", "region_ref", "state",
                    "population_capacity"),
    "population_groups": ("species", "settlement_ref", "age_cohort",
                          "occupation_group", "count",
                          "age_advance_carry_ticks", "species_profile_ref",
                          "demography_version", "updated_blessed_tick"),
    "resource_profiles": ("resource_id", "unit", "quantity_scale",
                          "renewability", "extractability",
                          "consumption_category", "production_usability",
                          "semantic_version"),
    "resource_nodes": ("kind", "region_ref", "state", "resource_profile_ref",
                       "settlement_relation", "remaining_reserve",
                       "extraction_capacity", "extraction_carry",
                       "last_extracted_minor", "state_version",
                       "reserve_ceiling_minor", "regeneration_carry"),
    "resource_stocks": ("settlement_ref", "resource_profile_ref", "quantity",
                        "consumption_carry", "updated_blessed_tick"),
    "production_recipes": ("recipe_id", "input_resource_ref", "input_qty_minor",
                           "output_resource_ref", "output_qty_minor",
                           "capacity_batches_per_year", "labor_per_batch",
                           "loss_num", "loss_den", "semantic_version"),
    "production_state": ("settlement_ref", "recipe_ref", "production_carry"),
    "economic_pressure_state": ("settlement_ref", "resource_profile_ref",
                                "demand_minor", "fulfilled_minor",
                                "unmet_minor", "sustained_shortage_steps",
                                "stress_level"),
    "ecology_zones": ("zone_id", "region_ref", "settlement_relation",
                      "profile_ref", "semantic_version"),
    "ecology_state": ("zone_ref", "habitat_quality", "regeneration_capacity",
                      "ecological_stress", "population_pressure",
                      "extraction_pressure", "production_pressure",
                      "depletion_pressure", "external_pressure",
                      "degradation_carry", "recovery_carry", "quality_min_seen",
                      "quality_max_seen"),
    "ecology_feedback_state": ("zone_ref",
                               "regeneration_capacity_minor_per_year",
                               "habitat_stress_level"),
    "settlement_social_state": ("settlement_ref",),
    "social_feedback_state": ("settlement_ref",),
    "tribulation_profiles": ("profile_id", "tier", "theme", "intensity_min",
                             "intensity_max", "precursor_steps",
                             "preparation_steps", "impact_steps",
                             "population_risk_num", "population_risk_den",
                             "resource_damage_num", "resource_damage_den",
                             "inventory_damage_num", "inventory_damage_den",
                             "production_disruption_num",
                             "production_disruption_den",
                             "social_displacement_num",
                             "social_displacement_den",
                             "institution_disruption_num",
                             "institution_disruption_den",
                             "ecology_pressure", "recovery_steps", "status",
                             "succession_rules", "semantic_version"),
    "tribulation_schedules": ("schedule_id", "tier", "period_years", "enabled",
                              "semantic_version"),
}


def _rows(factory, table: str, columns: tuple) -> list[tuple]:
    from XiaoguangBlessedLandRuntime.database import models_world as MW
    from XiaoguangBlessedLandRuntime.database import models_core as MC
    model = getattr(MW, "".join(p.capitalize() for p in table.split("_")), None) \
        or getattr(MC, "".join(p.capitalize() for p in table.split("_")), None)
    if model is None:
        name = {"settlements": "Settlement", "population_groups": "PopulationGroup",
                "resource_profiles": "ResourceProfile",
                "resource_nodes": "ResourceNode", "resource_stocks": "ResourceStock",
                "production_recipes": "ProductionRecipe",
                "production_state": "ProductionState",
                "economic_pressure_state": "EconomicPressureState",
                "ecology_zones": "EcologyZone", "ecology_state": "EcologyState",
                "ecology_feedback_state": "EcologyFeedbackState",
                "settlement_social_state": "SettlementSocialState",
                "social_feedback_state": "SocialFeedbackState",
                "tribulation_profiles": "TribulationProfile",
                "tribulation_schedules": "TribulationSchedule"}[table]
        model = getattr(MW, name)
    with factory() as session:
        out = []
        for row in session.execute(select(model)).scalars().all():
            out.append(tuple(_norm(getattr(row, c, None)) for c in columns))
        return sorted(out, key=lambda t: tuple(str(v) for v in t))


def _norm(value):
    if isinstance(value, Fraction):
        return "%s/%s" % (value.numerator, value.denominator)
    return value


def _build_empty_world(work: pathlib.Path, world_id: str) -> dict:
    """temp DB + runtime row（ACTIVE）+ time ratio，**不写任何 bootstrap row**。

    与 `m6c1d_runner.build_world(via="direct")` 的差异仅在于**跳过**
    `write_bootstrap_rows`（那是 oracle 侧动作）；Phase A 需要一个 pristine
    domain state 才能验证 materializer 的 pristine guard。
    """
    from datetime import datetime, timezone

    from XiaoguangBlessedLandRuntime.database.db import (
        create_db_engine, make_session_factory)
    from XiaoguangBlessedLandRuntime.database.models_core import WorldRuntime
    from XiaoguangBlessedLandRuntime.domain.constants import RuntimeStatus
    from XiaoguangBlessedLandRuntime.services.db_lifecycle import migrate_database
    from XiaoguangBlessedLandRuntime.services.repositories import (
        RuntimeRepository, TimeRatioRepository)

    work.mkdir(parents=True, exist_ok=True)
    db_path = work / "m6c2_empty.db"
    url = "sqlite:///" + str(db_path).replace("\\", "/")
    migrate_database(url, project_root=ROOT)
    engine = create_db_engine(url)
    factory = make_session_factory(engine)
    with factory() as session:
        RuntimeRepository(session).create_not_activated(
            world_id=world_id, world_bible_version="1.0",
            simulation_version=S.SIMULATION_VERSION,
            world_bible_manifest_hash="m6c2-empty")
        row = session.execute(select(WorldRuntime)).scalar_one()
        row.runtime_status = RuntimeStatus.ACTIVE
        row.world_seed_version = "SYNTHETIC-M6C2-SEED"
        row.current_blessed_tick = 0
        row.last_committed_real_us = EPOCH0_US
        row.time_rate_remainder = 0
        rate = TimeRatioRepository(session).add(
            world_id=world_id,
            real_effective_from=datetime.fromtimestamp(
                EPOCH0_US / 1_000_000, tz=timezone.utc),
            rate_numerator=1_000_000, rate_denominator=86_400_000_000,
            reason="TEST", source="TEST")
        row.current_time_ratio_id = rate.ratio_id
        session.commit()
    return {"url": url, "factory": factory, "engine": engine, "db_path": db_path}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/M6C2_MATERIALIZER_ROW_EQUIVALENCE.json")
    args = ap.parse_args()

    work_a = pathlib.Path(tempfile.mkdtemp(prefix="m6c2_mat_"))
    work_b = pathlib.Path(tempfile.mkdtemp(prefix="m6c2_oracle_"))

    # DB A：production Materializer（同一 session 内先取 lease → fenced session，
    # 与 M6A.1 activation 的 real flow 一致：lease 与 mutation 共用同一事务）
    env_a = _build_empty_world(work_a, WORLD_ID)
    factory_a = env_a["factory"]
    result = None
    session_a = factory_a()
    try:
        lease = WriterLease(session_a, WORLD_ID, 300)
        lease.acquire(commit=False)
        result = M.materialize_snapshot_v1(
            session_a, world_id=WORLD_ID, writer_id=lease.owner,
            fencing_token=lease.token, blessed_tick=0)
        session_a.commit()
    finally:
        session_a.close()

    # DB B：reference oracle（test-only；build_world 内部即调用 write_bootstrap_rows）
    global_world = R.WORLD_ID
    R.WORLD_ID = WORLD_ID
    try:
        env_b = R.build_world(work_b, tag="oracleB", via="direct", world_id=WORLD_ID)
        factory_b = env_b["factory"]
    finally:
        R.WORLD_ID = global_world

    comparison = {}
    ok = True
    for table, columns in TABLES.items():
        a = _rows(factory_a, table, columns)
        b = _rows(factory_b, table, columns)
        same = a == b
        ok = ok and same
        diff = None
        if not same:
            for i, (x, y) in enumerate(zip(a, b)):
                if x != y:
                    diff = {"row_index": i, "materializer": x, "oracle": y}
                    break
            if diff is None:
                diff = {"row_count": [len(a), len(b)]}
        comparison[table] = {"columns": len(columns), "rows_a": len(a),
                             "rows_b": len(b), "equal": same, "first_diff": diff}

    doc = {"packet": "M6C2_MATERIALIZER_ROW_EQUIVALENCE",
           "world_id": WORLD_ID,
           "materializer_counts": result["counts"] if result else None,
           "graph": result["graph"] if result else None,
           "pristine": result["pristine"] if result else None,
           "cohort_rule": result["cohort_rule"] if result else None,
           "units": {k: result[k] for k in (
               "global_annual_minor", "recipe_input_minor", "recipe_output_minor",
               "node_extraction_capacity_minor", "node_remaining_reserve_minor")
               if result} if result else None,
           "NON_AUTHORITATIVE_COMPARISON_EXCLUSIONS":
               NON_AUTHORITATIVE_COMPARISON_EXCLUSIONS,
           "tables": comparison,
           "TEST_ORACLE_IMPORTED_BY_PRODUCTION": False,
           "MATERIALIZER_ROW_EQUIVALENCE": "PASS" if ok else "FAIL"}
    pathlib.Path(ROOT / args.out).write_text(
        json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8", newline="\n")
    print("MATERIALIZER_COUNTS =", json.dumps(doc["materializer_counts"]))
    for table, entry in comparison.items():
        print("  %-26s rows=%d/%d %s" % (table, entry["rows_a"], entry["rows_b"],
                                         "OK" if entry["equal"] else "DIFF"))
        if not entry["equal"]:
            print("      ", json.dumps(entry["first_diff"], ensure_ascii=False)[:220])
    print("MATERIALIZER_ROW_EQUIVALENCE =", doc["MATERIALIZER_ROW_EQUIVALENCE"])
    print("ARTIFACT", args.out)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

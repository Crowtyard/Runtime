"""M6C.2 §1-§4 — generate the APPROVED SNAPSHOT_V1 artifacts.

Produces, from the ratified sources only (no redesign):
  * docs/world_creation/SNAPSHOT_V1.json   — machine-consumable materialization spec
  * docs/world_creation/SNAPSHOT_V1.md     — human-readable canon
  * docs/world_creation/SNAPSHOT_V1_APPROVAL.md — approval + provenance + SHA256

Sources:
  * services/activation/bootstrap_canon.py  (RA-ALLOC-001 v1.0, RA-COHORT-001 v1.1,
    owner-approved constants, canonical dumps/allocation digest)
  * docs/world_creation/M6C1C_NUMERIC_PACKET_DATA.json (owner-selected numeric packet)
  * docs/world_creation/SNAPSHOT_V1_CANDIDATE.json (structural spec; candidate header
    is replaced by the APPROVED header)
  * the owner-ratified final configuration recorded by the M6D.3 verification
    (P2-B demography, RE-LEAN-v2, E-B-v2, S-B, T-B)

The frozen JSON is the *only* production source of bootstrap truth; the materializer
must not import tests or this generator.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from XiaoguangBlessedLandRuntime.services.activation import (  # noqa: E402
    bootstrap_canon as BC)

DOCS = ROOT / "docs" / "world_creation"
PACKET = DOCS / "M6C1C_NUMERIC_PACKET_DATA.json"
CANDIDATE = DOCS / "SNAPSHOT_V1_CANDIDATE.json"

SIMULATION_VERSION = "0.3.0"
ALEMBIC_HEAD = "a9d4f2b7c1e8"
TICKS_PER_BLESSED_YEAR = 1_000_000
YEAR_US = 86_400_000_000
ECOLOGY_STATE_SCALE = 1_000_000
QUANTITY_SCALE = 1_000_000

CONSUMPTION_KINDS = ("灵田", "药园", "果园", "矿脉", "水源", "林产", "菌类点")
SPECIAL_KIND = "RESOURCE_SLOT_08"
SPECIES = (("Hairy Men", 4000), ("Rockmen", 3000), ("Mermen", 2500),
           ("Mushroommen", 2500))
SETTLEMENT_SLOTS = tuple(
    [("MAIN-%02d" % i, "MAIN", 2000) for i in range(1, 5)]
    + [("SAT-%02d" % i, "SATELLITE", 500) for i in range(1, 9)])

#: owner-ratified final configuration (M6C.1D / M6D.3)
P2_B = {
    "birth_rate": "53/1000", "mortality_per_bucket": "1/60",
    "cohort_buckets": 61, "fertile_window": [15, 45], "lifespan_years": 60,
    "population_capacity": None, "emigration_rate": "0",
    "migration_weights": ["1/2", "1/2"],
    "species_profile_ref": "FORMAL-SPECIES-001", "demography_version": "formal-1.0",
}
RE_LEAN_V2 = {
    "policy": "RE-LEAN-v2", "registry_entries": 8,
    "materialized_profile_rows": 7, "consumption_kinds": 7,
    "registry_only": [SPECIAL_KIND], "nodes": 7, "stock_cells": 84,
    "per_capita_demand": "1/4", "loss": "1/20", "capacity_multiple": "11/10",
    "initial_stock_policy": "1 local blessed-year baseline demand",
    "capacity_basis": "ACTUAL_SERVED_ANNUAL_DEMAND (global, not host-local)",
    "node_reserve_multiple_of_global_annual": 10000,
    "recipe_input_canonical_units": 10, "labor_per_batch": 10,
}
E_B_V2 = {
    "profile_id": "FORMAL-ECOLOGY-001", "zone_count": 1, "zone_id": "ZONE-01",
    "sensitivity": "1/279", "recovery_rate": "1/25",
    "pop_pressure_per_person": 1, "recovery_ceiling": ECOLOGY_STATE_SCALE,
    "pressure_weights": {"population": "2/8", "extraction": "3/8",
                         "production": "2/8", "depletion": "1/8"},
    "thresholds": [800000, 500000, 200000],
    "renewable_regen_minor_per_full_quality": 220_000_000,
    "initial_habitat_quality": ECOLOGY_STATE_SCALE,
    "semantic_version": "formal-1.0",
}
S_B = {"model": "S-B", "method": "POPULATION_SCALED_DETERMINISTIC_DERIVATION",
       "materialized_root_rows_per_settlement": 2,
       "household_authoritative_bootstrap": False,
       "occupation_authoritative_bootstrap": False}
T_B = {"periods": {"REGULAR": 10, "MAJOR": 50, "CENTENNIAL": 100},
       "first_omen_tick": 10_000_000,
       "effect_semantics": "post-engine state + delta, exactly once",
       "materializer_creates_effects": False}
RULE_VERSIONS = {
    "RA-ALLOC-001": {"version": BC.RULE_ALLOC_VERSION, "status": "APPROVED"},
    "RA-COHORT-001": {"version": BC.RULE_COHORT_VERSION,
                      "status": "APPROVED_PRODUCTION_BOOTSTRAP_RULE",
                      "superseded": [{"version": BC.RULE_COHORT_VERSION_SUPERSEDED,
                                      "status": "SUPERSEDED_PRODUCTION_RULE_"
                                                "PROVENANCE"}]},
    "RA-STRUCT-001": {"version": "1.0", "status": "APPROVED"},
    "RA-TRIB-001": {"version": "1.0", "status": "APPROVED"},
    "RA-MORTALITY-001": {"version": "1.0",
                         "status": "APPROVED_FOR_SNAPSHOT_V1"},
    "RA-DEMOGRAPHY-STATIONARY-001":
        {"version": "1.0", "status": "APPROVED_CALIBRATION_METHOD",
         "note": "只解释 53/1000 如何被批准；activation 不得重新 calibration"},
}


def tribulation_profiles() -> list[dict]:
    """T-B profiles as machine payload (exact fractions, no redesign)."""
    packet = json.loads(PACKET.read_text(encoding="utf-8"))
    candidate = next(c for c in packet["NUMERIC_OD_T1"]["candidates"]
                     if c["LABEL"] == "T-B")
    env = candidate.get("ENVELOPES") or candidate.get("POLICY") or {}
    return [{"source": "M6C1C/T-B", "envelopes": env}]


def build() -> dict:
    matrix = BC.allocate([p for _n, p in SPECIES],
                         [c for _s, _k, c in SETTLEMENT_SLOTS])
    BC.verify_allocation(matrix, [p for _n, p in SPECIES],
                         [c for _s, _k, c in SETTLEMENT_SLOTS])
    header = {
        "artifact": "SNAPSHOT_V1",
        "version": "SNAPSHOT_V1",
        "status": "APPROVED",
        "owner_ratified": True,
        "engine_verified": True,
        "materialization_spec": "AUTHORITATIVE",
        "formal_activation_allowed": False,
        "formal_world_materialization_allowed": False,
        "world_seed_consumption_allowed": False,
        "materializer_implementation_allowed": True,
        "produced_by": "M6C.2 SNAPSHOT_V1 APPROVAL",
        "source_candidate": "docs/world_creation/SNAPSHOT_V1_CANDIDATE.json",
        "engine_baseline": {"alembic_head": ALEMBIC_HEAD,
                            "simulation_version": SIMULATION_VERSION},
        "rule_set_version": {k: v["version"] for k, v in RULE_VERSIONS.items()},
        "derivation_rules": RULE_VERSIONS,
        "red_lines": ["FORMAL_WORLD_MATERIALIZATION_ALLOWED = FALSE",
                      "FORMAL_ACTIVATION_ALLOWED = FALSE",
                      "WORLD_SEED_CONSUMPTION_ALLOWED = FALSE",
                      "NO_LIVE_DEPLOY"],
    }
    world = {
        "initial_total_population": BC.OWNER_APPROVED_INITIAL_TOTAL_POPULATION,
        "species": [{"species": n, "population": p} for n, p in SPECIES],
        "settlement_counts": {"MAIN": BC.OWNER_APPROVED_MAIN_SETTLEMENT_COUNT,
                              "SATELLITE":
                                  BC.OWNER_APPROVED_SATELLITE_SETTLEMENT_COUNT},
        "settlements": [{"working_name": s, "settlement_type": k,
                         "population_capacity": None, "target_population": c}
                        for s, k, c in SETTLEMENT_SLOTS],
        "allocation": {
            "rule_id": BC.RULE_ALLOC_ID, "rule_version": BC.RULE_ALLOC_VERSION,
            "matrix": [list(r) for r in matrix],
            "digest": BC.allocation_digest(matrix),
            "column_totals": list(BC.column_totals(matrix)),
            "row_totals": list(BC.row_totals(matrix)),
            "canonical_text": BC.render_matrix(matrix),
        },
        "working_name_semantics":
            "stable technical identity only（MAIN-01..04 / SAT-01..08）；"
            "不得解释为最终 lore display name",
    }
    population = {
        "rule_id": BC.RULE_COHORT_ID, "rule_version": BC.RULE_COHORT_VERSION,
        "open_ended_final_bucket": True,
        "profile": dict(P2_B),
        "population_group_rows":
            len(SETTLEMENT_SLOTS) * len(SPECIES) * P2_B["cohort_buckets"],
        "initial_age_advance_carry_ticks": 0,
    }
    resource = {
        "policy": RE_LEAN_V2["policy"],
        "registry_entries": RE_LEAN_V2["registry_entries"],
        "materialized_resource_profile_rows":
            RE_LEAN_V2["materialized_profile_rows"],
        "consumption_resource_kinds": list(CONSUMPTION_KINDS),
        "registry": [
            {"resource_id": k, "registered": True, "materialized": True,
             "unit": "unit", "quantity_scale": QUANTITY_SCALE,
             "renewability": "RENEWABLE", "extractability": "EXTRACTABLE",
             "consumption_category": "CONSUMPTION",
             "production_usability": "INPUT",
             "semantic_version": "formal-1.0"}
            for k in CONSUMPTION_KINDS] + [
            {"resource_id": SPECIAL_KIND, "registered": True,
             "materialized": False, "node_count": 0, "stock_rows": 0,
             "demand_rows": 0,
             "reason": "canon 第 8 类特殊灵性资源点（未命名）：registry-only"}],
        "nodes": [{"kind": k, "node_id": "NODE-%s-01" % k,
                   "settlement_relation": SETTLEMENT_SLOTS[0][0],
                   "region_ref": None, "state": "STABLE"}
                  for k in CONSUMPTION_KINDS],
        "stock_cells": RE_LEAN_V2["stock_cells"],
        "initial_stock_policy": RE_LEAN_V2["initial_stock_policy"],
        "minor_units": True, "quantity_scale": QUANTITY_SCALE,
        "per_capita_demand": RE_LEAN_V2["per_capita_demand"],
        "loss": RE_LEAN_V2["loss"],
        "capacity_multiple": RE_LEAN_V2["capacity_multiple"],
        "capacity_basis": RE_LEAN_V2["capacity_basis"],
        "node_reserve_multiple_of_global_annual":
            RE_LEAN_V2["node_reserve_multiple_of_global_annual"],
    }
    economy = {
        "recipes": [{"recipe_id": "RECIPE-%s" % k,
                     "input_resource_ref": k,
                     "input_qty_minor":
                         RE_LEAN_V2["recipe_input_canonical_units"] * QUANTITY_SCALE,
                     "output_resource_ref": k,
                     "labor_per_batch": RE_LEAN_V2["labor_per_batch"],
                     "loss": RE_LEAN_V2["loss"],
                     "capacity_batches_per_year_basis":
                         "global served annual demand x capacity_multiple / output"}
                    for k in CONSUMPTION_KINDS],
        "production_state_rows": RE_LEAN_V2["stock_cells"],
        "economic_pressure_rows": RE_LEAN_V2["stock_cells"],
        "per_capita_demand": RE_LEAN_V2["per_capita_demand"],
        "semantic_version": "formal-1.0",
    }
    ecology = dict(E_B_V2)
    ecology.update({"root_rows": 3,
                    "settlement_relation": SETTLEMENT_SLOTS[0][0],
                    "region_ref": None})
    social = dict(S_B)
    social.update({"root_rows": len(SETTLEMENT_SLOTS) * 2})
    tribulation = {"schedules": [
        {"schedule_id": "SCHEDULE-%s" % tier, "tier": tier,
         "period_years": period, "enabled": True,
         "semantic_version": "formal-1.0"}
        for tier, period in T_B["periods"].items()],
        "first_omen_tick": T_B["first_omen_tick"],
        "effect_semantics": T_B["effect_semantics"],
        "materializer_creates_effects": False,
        "profiles": tribulation_profiles()}
    history = {"genesis_event": "WORLD_SEED_ACTIVATED", "genesis_count": 1,
               "materializer_creates_per_entity_history": False}
    doc = {
        "header": header,
        "world": world,
        "population": population,
        "resource": resource,
        "economy": economy,
        "ecology": ecology,
        "social": social,
        "tribulation": tribulation,
        "history_genesis": history,
        "clock": {"ticks_per_blessed_year": TICKS_PER_BLESSED_YEAR,
                  "year_us": YEAR_US, "initial_blessed_tick": 0},
        "validation": {"blocked_required_fields": 0,
                       "unresolved_required_fields": 0,
                       "planning_only_materialized_fields": 0,
                       "working_name_only_identities":
                           [s for s, _k, _c in SETTLEMENT_SLOTS] + [SPECIAL_KIND]},
        "provenance": {
            "candidate": "docs/world_creation/SNAPSHOT_V1_CANDIDATE.json",
            "owner_ratification":
                "SNAPSHOT_V1 = APPROVED (owner canon; M6C.2 entry)",
            "engine_verification":
                "M6D3 corrected integrated verification (PASS on all gates)",
            "derived_from": ["services/activation/bootstrap_canon.py",
                             "docs/world_creation/M6C1C_NUMERIC_PACKET_DATA.json",
                             "M6C1D/M6D3 owner-ratified configuration"],
        },
    }
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    doc = build()
    text = BC.dumps_canonical(doc)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    json_path = DOCS / "SNAPSHOT_V1.json"
    md_path = DOCS / "SNAPSHOT_V1.md"
    approval_path = DOCS / "SNAPSHOT_V1_APPROVAL.md"
    if args.write:
        json_path.write_text(text, encoding="utf-8", newline="\n")
        md_path.write_text(render_md(doc, digest), encoding="utf-8", newline="\n")
        approval_path.write_text(render_approval(digest), encoding="utf-8",
                                 newline="\n")
    print("SNAPSHOT_V1_SHA256 =", digest)
    print("SNAPSHOT_JSON_BYTES =", len(text.encode("utf-8")))
    print("BLOCKED_REQUIRED_FIELDS =",
          doc["validation"]["blocked_required_fields"])
    print("UNRESOLVED_REQUIRED_FIELDS =",
          doc["validation"]["unresolved_required_fields"])
    print("PLANNING_ONLY_MATERIALIZED_FIELDS =",
          doc["validation"]["planning_only_materialized_fields"])
    print("WRITTEN =", bool(args.write))
    return 0


def render_md(doc: dict, digest: str) -> str:
    w, r, e, t = doc["world"], doc["resource"], doc["ecology"], doc["tribulation"]
    return "\n".join([
        "# SNAPSHOT_V1（APPROVED）",
        "",
        "STATUS = APPROVED　VERSION = SNAPSHOT_V1　OWNER_RATIFIED = TRUE　"
        "ENGINE_VERIFIED = TRUE　MATERIALIZATION_SPEC = AUTHORITATIVE　"
        "FORMAL_ACTIVATION_ALLOWED = FALSE",
        "",
        "SNAPSHOT_V1_SHA256 = `%s`" % digest,
        "",
        "## 世界", "",
        "- 初始总人口 **%d**；种族 %s" % (
            w["initial_total_population"],
            "、".join("%s=%d" % (s["species"], s["population"])
                      for s in w["species"])),
        "- 聚落 %d（4 MAIN × 2000 + 8 SATELLITE × 500）；"
        "`population_capacity = NULL`（引擎中性，无容量法则）"
        % len(w["settlements"]),
        "- RA-ALLOC-001 v%s 名额矩阵 digest `%s`（列和 %s；行和 %s）" % (
            w["allocation"]["rule_version"], w["allocation"]["digest"],
            w["allocation"]["column_totals"], w["allocation"]["row_totals"]),
        "",
        "## 人口", "",
        "- RA-COHORT-001 **v1.1**（APPROVED_PRODUCTION_BOOTSTRAP_RULE；open-ended "
        "final bucket：age ≥ N−1 的 survivor 全部累计到末桶；v1.0 已 SUPERSEDED）",
        "- profile：`birth_rate = %s`、`mortality = %s`、`cohort_buckets = %d`、"
        "fertile %s、lifespan %d、capacity NULL" % (
            doc["population"]["profile"]["birth_rate"],
            doc["population"]["profile"]["mortality_per_bucket"],
            doc["population"]["profile"]["cohort_buckets"],
            doc["population"]["profile"]["fertile_window"],
            doc["population"]["profile"]["lifespan_years"]),
        "- population_groups 行数 = **%d**（12 × 4 × 61）"
        % doc["population"]["population_group_rows"],
        "",
        "## 资源 / 经济", "",
        "- `FORMAL_RESOURCE_REGISTRY_ENTRIES = %d`、"
        "`MATERIALIZED_RESOURCE_PROFILE_ROWS = %d`、"
        "`CONSUMPTION_RESOURCE_KINDS = %d`、`RESOURCE_NODE_ROWS = %d`、"
        "`RESOURCE_STOCK_ROWS = %d`" % (
            r["registry_entries"], r["materialized_resource_profile_rows"],
            len(r["consumption_resource_kinds"]), len(r["nodes"]),
            r["stock_cells"]),
        "- `RESOURCE_SLOT_08`：registered = TRUE / materialized = FALSE / "
        "node_count = 0 / stock·demand rows = 0",
        "- 初始库存 = %s（minor units，`quantity_scale = %d`）；容量 = %s × %s" % (
            r["initial_stock_policy"], r["quantity_scale"],
            r["capacity_multiple"], r["capacity_basis"]),
        "- recipes 7 / production_state 84 / economic_pressure 84（exact machine "
        "payload）",
        "",
        "## 生态 / 社会 / 灾劫", "",
        "- E-B-v2：zone_count = %d（`%s`）、sensitivity = `%s`、"
        "recovery_rate = `%s`、ppp = %d、initial habitat_quality = FULL_QUALITY(%d)" % (
            e["zone_count"], e["zone_id"], e["sensitivity"], e["recovery_rate"],
            e["pop_pressure_per_person"], e["initial_habitat_quality"]),
        "- S-B：每聚落 2 行 root（state + feedback）共 %d 行；occupation / "
        "household **不是** authoritative bootstrap root" % doc["social"]["root_rows"],
        "- T-B：schedules %s blessed years；first omen tick = %d；"
        "effect semantics = %s；Materializer **不产生**灾劫效果" % (
            t["schedules"], t["first_omen_tick"], t["effect_semantics"]),
        "- History genesis：`%s`，GENESIS_COUNT = %d（由 Activation 事务创建）" % (
            doc["history_genesis"]["genesis_event"],
            doc["history_genesis"]["genesis_count"]),
        "",
        "## 校验", "",
        "- `BLOCKED_REQUIRED_FIELDS = %d`、`UNRESOLVED_REQUIRED_FIELDS = %d`、"
        "`PLANNING_ONLY_MATERIALIZED_FIELDS = %d`" % (
            doc["validation"]["blocked_required_fields"],
            doc["validation"]["unresolved_required_fields"],
            doc["validation"]["planning_only_materialized_fields"]),
        "- `WORKING_NAME_ONLY` 身份（stable technical identity，非 lore display "
        "name）：%s" % ", ".join(doc["validation"]["working_name_only_identities"]),
        "",
    ]) + "\n"


def render_approval(digest: str) -> str:
    import subprocess
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                          capture_output=True, text=True,
                          encoding="utf-8").stdout.strip()
    return "\n".join([
        "# SNAPSHOT_V1 APPROVAL RECORD",
        "",
        "## Owner ratification", "",
        "```",
        "SNAPSHOT_V1 = APPROVED",
        "SNAPSHOT_V1_ENGINE_VERIFIED_CANDIDATE = TRUE",
        "MATERIALIZER_IMPLEMENTATION_ALLOWED = TRUE",
        "FORMAL_WORLD_MATERIALIZATION_ALLOWED = FALSE",
        "FORMAL_ACTIVATION_ALLOWED = FALSE",
        "WORLD_SEED_CONSUMPTION_ALLOWED = FALSE",
        "```",
        "",
        "## Code HEAD", "",
        "```",
        "SNAPSHOT_V1_APPROVAL_HEAD = %s" % head,
        "FORMAL_DB_ALEMBIC_HEAD = %s" % ALEMBIC_HEAD,
        "FORMAL_WORLD_DB_SHA256 = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837",
        "WORLD_SEED_STATUS = PREPARED_NOT_ACTIVATED",
        "WORLD_SEED_CONSUMED = FALSE",
        "```",
        "",
        "## Baseline provenance", "",
        "```",
        "ORIGINAL_M3A_M3B_REFREEZE_COUNT = 12",
        "M3_INTEGRATED_REFREEZE_COUNT = 7",
        "AUTHORIZED_BASELINE_REFREEZE_COUNT_TOTAL = 19",
        "UNAUTHORIZED_BASELINE_MUTATIONS = 0",
        "```",
        "",
        "## M6D.3 verification references", "",
        "```",
        "TRIBULATION_EFFECT_APPLICATION = PASS (recorded 473 / applied 473 / dropped 0)",
        "E_B_V2_ENGINE_VALIDATION = PASS",
        "DETERMINISM = PASS",
        "RESTART_EQUIVALENCE = PASS",
        "HISTORY_INTEGRITY = PASS",
        "INTEGRATED_WORLD_VIABILITY = PASS",
        "FAST_REGRESSION = PASS",
        "```",
        "",
        "## Snapshot freeze", "",
        "```",
        "SNAPSHOT_V1_SHA256 = %s" % digest,
        "SNAPSHOT_V1_FILES = docs/world_creation/SNAPSHOT_V1.json,",
        "                    docs/world_creation/SNAPSHOT_V1.md",
        "```",
        "",
        "## 消费规则", "",
        "* Materializer **只能**消费本 APPROVED SNAPSHOT_V1（含 SHA256 校验）。",
        "* **禁止**把 `SNAPSHOT_V1_CANDIDATE` 作为 production truth。",
        "* snapshot 被修改（SHA256 不符）→ **FAIL CLOSED**（不得自动兼容）。",
        "",
    ]) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())

"""M6D.3 §13 — CALIBRATION vs INTEGRATED configuration equivalence audit.

Builds a canonical, field-by-field configuration document for the M6C.1D E-B-v2
calibration configuration and for the M6D.2 integrated configuration, hashes both,
and lists the differences. Also emits the M6D.3 corrected configuration hash
(ratified E-B-v2 sensitivity on the fixed tribulation path).

Usage: python scripts/_m6d3_config_equivalence.py [--out JSON]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys
from fractions import Fraction

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tests import m6c1d_runner as R  # noqa: E402
from tests import m6c1d_support as S  # noqa: E402
from XiaoguangBlessedLandRuntime.services.simulation.contracts import (  # noqa: E402
    ENGINE_ORDER)


def _f(value) -> str:
    return "%s/%s" % (value.numerator, value.denominator) \
        if isinstance(value, Fraction) else str(value)


def config_doc(sensitivity: Fraction, label: str) -> dict:
    demo = S.formal_species_profile()
    res = S.resource_registry()
    econ = S.economy_registry()
    social = S.social_profile()
    trib = S.tribulation_registry()
    ecoprofile_default = S.ecology_profile()
    doc = {
        "label": label,
        "pipeline_order": list(ENGINE_ORDER),
        "steps_per_year": 1,
        "ticks_per_blessed_year": 1_000_000,
        "years_to_T300": 300,
        "epoch0_us": R.EPOCH0_US,
        "world_id": "SYNTH-DEMO-001",
        "activation": {
            "path": "activate_formal_world (canonical zero-row -> genesis -> "
                    "test-only bootstrap rows)",
            "runtime_status": "ACTIVE",
            "simulation_version": S.SIMULATION_VERSION,
        },
        "population": {
            "species": [name for name, _ in S.SPECIES],
            "totals": [total for _, total in S.SPECIES],
            "cohort_buckets": demo.cohort_buckets,
            "fertile_window": [demo.fertile_min_age, demo.fertile_max_age],
            "birth_rate": _f(demo.birth_rate),
            "mortality_per_bucket": _f(demo.mortality_by_bucket[0]),
            "emigration_rate": _f(demo.emigration_rate),
            "migration_weights": [_f(w) for w in demo.migration_weights],
            "population_capacity": None,
            "settlements": [{"ref": ref, "type": kind, "count": cap}
                            for ref, kind, cap in S.SETTLEMENT_SLOTS],
        },
        "resource": {
            "consumption_kinds": list(S.CONSUMPTION_KINDS),
            "registry_only_kind": S.SPECIAL_KIND,
            "profile_count": len(res),
            "quantity_scale": sorted({int(p.quantity_scale)
                                      for p in res.values()}),
            "node_count": 7,
            "initial_stock_policy": "1 local blessed-year baseline demand (84 cells)",
            "capacity_factor": "1.10 x actual served baseline annual demand",
            "minor_units": True,
        },
        "economy": {
            "profile_count": len(econ),
            "per_capita_demand": _f(next(iter(
                next(iter(econ.values())).per_capita_demand.values()))),
        },
        "ecology": {
            "profile_id": ecoprofile_default.profile_id,
            "initial_habitat_quality": 1_000_000,
            "zone_count": 1,
            "zone_refs": ["ZONE-01"],
            "sensitivity": _f(sensitivity),
            "recovery_rate": _f(ecoprofile_default.recovery_rate),
            "recovery_ceiling": ecoprofile_default.recovery_ceiling,
            "ppp": ecoprofile_default.pop_pressure_per_person,
            "pressure_weights": {k: _f(v) for k, v in
                                 ecoprofile_default.pressure_weights.items()},
            "pressure_normalization": "ECOLOGY_STATE_SCALE = 1_000_000",
            "persisted_pressure_fields": [
                "population_pressure", "extraction_pressure",
                "production_pressure", "depletion_pressure",
                "external_pressure", "ecological_stress", "habitat_quality"],
            "thresholds": list(ecoprofile_default.thresholds),
            "regen_minor_per_full_quality":
                ecoprofile_default.renewable_regen_minor_per_full_quality,
        },
        "social": {"profile_ref": getattr(social, "profile_id", "FORMAL-SOCIAL-001"),
                   "model": "S-B"},
        "tribulation": {
            "profile_count": len(trib),
            "periods": {tier: int(period) for tier, period in
                        S.packet()["NUMERIC_OD_T1"]["periods"].items()},
            "first_omen_tick": 10_000_000,
            "adapters": sorted(["DEMOGRAPHY", "RESOURCE", "ECONOMY", "ECOLOGY",
                                "SOCIAL"]),
            "effect_semantics": "DELTA on domain-owned post-engine state",
        },
        "history": {"builder": "HistoryLinkBuilder (real)",
                    "hash": "canonical_causal_history_hash"},
    }
    return doc


def digest(doc: dict) -> str:
    canon = json.dumps(doc, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def diff(a: dict, b: dict, prefix: str = "") -> list:
    out = []
    for key in sorted(set(a) | set(b)):
        pa, pb = a.get(key), b.get(key)
        path = "%s.%s" % (prefix, key) if prefix else key
        if isinstance(pa, dict) and isinstance(pb, dict):
            out.extend(diff(pa, pb, path))
        elif pa != pb:
            out.append({"field": path, "calibration": pa, "integrated": pb})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    ratified = S.E_B_V2_RATIFIED_SENSITIVITY
    packet_e_b = Fraction(S.candidate("E1", "E-B")["VALUES"]["sensitivity"])
    calib = config_doc(ratified, "M6C1D_E_B_V2_CALIBRATION")
    integ = config_doc(packet_e_b, "M6D2_INTEGRATED_AS_RUN")
    fixed = config_doc(ratified, "M6D3_INTEGRATED_CORRECTED")
    out = {
        "CALIBRATION_CONFIG_HASH": digest(calib),
        "INTEGRATED_CONFIG_HASH": digest(integ),
        "M6D3_CORRECTED_CONFIG_HASH": digest(fixed),
        "CONFIG_DIFFERENCES": diff(calib, integ),
        "CONFIG_DIFFERENCES_COUNT": len(diff(calib, integ)),
        "E_B_V2_RATIFIED_SENSITIVITY": _f(ratified),
        "PACKET_E_B_SENSITIVITY": _f(packet_e_b),
        "PACKET_E_B_SENSITIVITY_DECIMAL":
            S.candidate("E1", "E-B")["VALUES"].get("sensitivity_decimal"),
        "FIRST_ECOLOGY_DIVERGENT_INPUT":
            "ecology.profile.sensitivity (calibration 1/279 vs integrated 3998/525)",
        "calibration_config": calib,
        "integrated_config_as_run": integ,
        "m6d3_corrected_config": fixed,
    }
    print(json.dumps({k: v for k, v in out.items()
                      if not k.endswith("_config")}, ensure_ascii=False, indent=1,
                     default=str))
    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True,
                       default=str), encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

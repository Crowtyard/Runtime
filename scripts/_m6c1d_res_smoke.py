"""M6C.1D-R1C — TIER-1 (7 served-demand producers) real-engine resource smoke.

Test-only: temp file-backed SQLite, synthetic activation world, P-A/RE-LEAN-v2/E-B/S-B/T-B.
Runs the REAL pipeline (TIME→DEMOGRAPHY→RESOURCE→ECONOMY→ECOLOGY→SOCIAL→TRIBULATION→HISTORY)
for T0/T1/T4/T10 and reports per-(settlement × resource) stock flow, shortages, the four
ecology pressures (read from ecology_state — the engine's own persisted inputs) and quality.

Usage: python scripts/_m6c1d_res_smoke.py [--years 10] [--out <json>] [--drop-kind <kind>]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sqlalchemy import select, text  # noqa: E402

from tests import m6c1d_runner as R  # noqa: E402
from tests import m6c1d_support as S  # noqa: E402
from XiaoguangBlessedLandRuntime.services.simulation.m3a_runner import (  # noqa: E402
    run_m3a_world)


def cell_metrics(factory) -> dict:
    """Per (settlement × resource) stock-flow ledger + shortage pressure rows."""
    from XiaoguangBlessedLandRuntime.database.models_world import (
        EconomicPressureState, ResourceStock)
    out = {}
    with factory() as s:
        rows = s.execute(select(
            ResourceStock.settlement_ref, ResourceStock.resource_profile_ref,
            ResourceStock.quantity, ResourceStock.cum_extracted_minor,
            ResourceStock.cum_produced_minor, ResourceStock.cum_imported_minor,
            ResourceStock.cum_exported_minor, ResourceStock.cum_consumed_minor,
            ResourceStock.cum_lost_minor)).all()
        for (sref, ref, qty, extr, prod, imp, exp, cons, lost) in rows:
            out[f"{sref}|{ref}"] = {
                "ending_stock": int(qty), "extraction": int(extr),
                "production": int(prod), "transfer_in": int(imp),
                "transfer_out": int(exp), "consumption": int(cons), "lost": int(lost)}
        pressure = {}
        for row in s.execute(select(EconomicPressureState)).scalars().all():
            pressure[f"{row.settlement_ref}|{row.resource_profile_ref}"] = {
                "demand_minor": int(row.demand_minor),
                "fulfilled_minor": int(row.fulfilled_minor),
                "unmet_minor": int(row.unmet_minor),
                "sustained_shortage_steps": int(row.sustained_shortage_steps),
                "stress_level": row.stress_level}
    return {"cells": out, "pressure": pressure}


def ecology_metrics(factory) -> dict:
    from XiaoguangBlessedLandRuntime.database.models_world import EcologyState
    with factory() as s:
        row = s.execute(select(EcologyState)).scalars().first()
        if row is None:
            return {}
        return {"habitat_quality": int(row.habitat_quality),
                "population_pressure": int(row.population_pressure),
                "extraction_pressure": int(row.extraction_pressure),
                "production_pressure": int(row.production_pressure),
                "depletion_pressure": int(row.depletion_pressure),
                "ecological_stress": int(row.ecological_stress),
                "regeneration_capacity": int(row.regeneration_capacity)}


def counts(factory) -> dict:
    from XiaoguangBlessedLandRuntime.database.models_world import (
        ResourceNode, ResourceProfile)
    with factory() as s:
        return {"resource_profiles": int(s.scalar(
            select(text("COUNT(*)")).select_from(ResourceProfile)) or 0),
            "resource_nodes": int(s.scalar(
                select(text("COUNT(*)")).select_from(ResourceNode)) or 0)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "reports" / "M6C1D_RESOURCE_SMOKE.json"))
    ap.add_argument("--until", type=int, default=10)
    ap.add_argument("--drop-kind", default=None,
                    help="reduction proof: omit the producer node for this kind")
    args = ap.parse_args()

    work = pathlib.Path(tempfile.mkdtemp(prefix="m6c1d_r1c_"))
    env = R.build_world(work, tag="res", via="direct")
    if args.drop_kind:
        from XiaoguangBlessedLandRuntime.database.models_world import ResourceNode
        with env["factory"]() as s:
            s.query(ResourceNode).filter(
                ResourceNode.kind == args.drop_kind).delete()
            s.commit()
    result: dict = {"work_dir": str(work), "via": "direct",
                    "drop_kind": args.drop_kind, "checkpoints": {}}
    result["bootstrap"] = counts(env["factory"])
    result["self_check"] = R.self_check(env)

    coordinator = S.build_coordinator()
    tick = 0
    targets = [x for x in (1, 4, 10, 50, 100, 300) if x <= args.until]
    for target in targets:
        years = target - tick
        if years <= 0:
            continue
        report = run_m3a_world(env["factory"], coordinator=coordinator,
                               world_id=R.WORLD_ID, epoch0_us=R.EPOCH0_US,
                               years=years, start_year=tick)
        tick = target
        metrics = cell_metrics(env["factory"])
        result["checkpoints"][f"T{target}"] = {
            "final_blessed_tick": getattr(report, "final_blessed_tick", None),
            "state_hash": getattr(report, "final_state_hash", None),
            "engine": metrics,
            "ecology": ecology_metrics(env["factory"])}
    out = pathlib.Path(args.out)
    out.write_text(json.dumps(result, ensure_ascii=False, default=str, indent=1,
                              sort_keys=True), encoding="utf-8", newline="\n")

    # ---- evaluation -------------------------------------------------------
    last = f"T{max(targets)}"
    t10 = result["checkpoints"][last]
    cells = t10["engine"]["cells"]
    pressure = t10["engine"]["pressure"]
    kinds = sorted({k.split("|")[1] for k in cells})
    never_supplied, zero_end, shortage_cells = [], [], []
    for key, cell in cells.items():
        supplied = (cell["extraction"] + cell["production"] + cell["transfer_in"])
        if supplied == 0:
            never_supplied.append(key)
        if cell["ending_stock"] == 0:
            zero_end.append(key)
        p = pressure.get(key, {})
        if p.get("unmet_minor", 0) > 0 or p.get("sustained_shortage_steps", 0) > 0:
            shortage_cells.append((key, p.get("unmet_minor"),
                                   p.get("sustained_shortage_steps"),
                                   p.get("stress_level")))
    print("BOOTSTRAP", json.dumps(result["bootstrap"]))
    print("SELF_CHECK", result["self_check"]["SELF_CHECK"],
          "TEST_PROFILE_REFERENCES", result["self_check"]["TEST_PROFILE_REFERENCES"])
    print("RESOURCE_PROFILE_ROWS", result["self_check"]["RESOURCE_PROFILE_ROWS"],
          "RESOURCE_NODE_ROWS", result["self_check"]["RESOURCE_NODE_ROWS"])
    for cp in [f"T{x}" for x in targets]:
        eco = result["checkpoints"][cp]["ecology"]
        print(cp, "quality", eco.get("habitat_quality"),
              "pressures(pop/ext/prod/dep)", eco.get("population_pressure"),
              eco.get("extraction_pressure"), eco.get("production_pressure"),
              eco.get("depletion_pressure"), "stress", eco.get("ecological_stress"))
    print("LAST", last)
    print("T10_KINDS", kinds)
    print("T10_NEVER_SUPPLIED_CELLS", len(never_supplied), never_supplied[:7])
    print("T10_ZERO_ENDING_CELLS", len(zero_end), zero_end[:7])
    print("T10_SHORTAGE_CELLS", len(shortage_cells), shortage_cells[:5])
    print("ARTIFACT", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""M6C.1D LANE A driver — REAL engine long-run truth (test-only).

via=direct synthetic world (LANE_A_ACTIVATION_EQUIVALENCE = NOT_CLAIMED).
Writes incremental JSON so a partial run still yields evidence.

Usage: python scripts/_m6c1d_laneA.py --out <json> [--phases 4,10,50,100,300]
                                      [--determinism] [--restart]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import tempfile
import time
import traceback

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sqlalchemy import func, select  # noqa: E402

from tests import m6c1d_runner as R  # noqa: E402
from tests import m6c1d_support as S  # noqa: E402
from XiaoguangBlessedLandRuntime.services.simulation.m3a_runner import (  # noqa: E402
    run_m3a_world)

TEST_PROFILE_USAGE = {"count": 0}


class _CountingRegistry(dict):
    """Runtime observation: any read of a TEST_* registry is a fallback event."""

    def __getitem__(self, key):  # noqa: D105
        TEST_PROFILE_USAGE["count"] += 1
        return super().__getitem__(key)

    def get(self, key, default=None):  # noqa: D105
        TEST_PROFILE_USAGE["count"] += 1
        return super().get(key, default)


def install_test_profile_watch() -> list[str]:
    """Replace every module-level TEST registry with a counting proxy."""
    from XiaoguangBlessedLandRuntime.services.simulation import (
        ecology as eco_mod, economy as econ_mod, population as pop_mod,
        resource as res_mod, social as soc_mod, tribulation as trib_mod)
    patched = []
    for module, attr in ((pop_mod, "SPECIES_PROFILES"), (res_mod, "RESOURCE_PROFILES"),
                         (econ_mod, "SPECIES_ECONOMY_PROFILES"),
                         (eco_mod, "ECOLOGY_PROFILES"), (soc_mod, "SOCIAL_PROFILES"),
                         (trib_mod, "TEST_PROFILES")):
        current = getattr(module, attr, None)
        if isinstance(current, dict) and not isinstance(current, _CountingRegistry):
            setattr(module, attr, _CountingRegistry(current))
            patched.append(f"{module.__name__}.{attr}")
    return patched


def db_metrics(factory) -> dict:
    from XiaoguangBlessedLandRuntime.database.models_world import (
        EcologyState, EconomicPressureState, Household, Institution, Lineage,
        PopulationGroup, ResourceStock, SettlementSocialState, TribulationEpisode)
    with factory() as s:
        total = int(s.scalar(select(func.coalesce(
            func.sum(PopulationGroup.count), 0))) or 0)
        rows = int(s.scalar(select(func.count()).select_from(PopulationGroup)) or 0)
        by_species = {sp: int(s.scalar(select(func.coalesce(
            func.sum(PopulationGroup.count), 0)).where(
                PopulationGroup.species == sp)) or 0) for sp, _ in S.SPECIES}
        stocks = {r: int(q) for r, q in s.execute(
            select(ResourceStock.resource_profile_ref,
                   func.sum(ResourceStock.quantity)).group_by(
                ResourceStock.resource_profile_ref)).all()}
        min_stock = int(s.scalar(select(func.coalesce(
            func.min(ResourceStock.quantity), 0))) or 0)
        quality = [int(q) for q in s.scalars(
            select(EcologyState.habitat_quality)).all()]
        stress = [int(q) for q in s.scalars(
            select(EcologyState.ecological_stress)).all()]
        return {
            "population_total": total,
            "population_rows": rows,
            "population_by_species": by_species,
            "cohort_sum_equals_total": rows == 2928 and
            total == sum(by_species.values()),
            "stock_by_resource": stocks,
            "stock_total": sum(stocks.values()),
            "stock_min_cell": min_stock,
            "habitat_quality": quality,
            "ecology_stress": stress,
            "households": int(s.scalar(select(func.count())
                                       .select_from(Household)) or 0),
            "lineages": int(s.scalar(select(func.count())
                                     .select_from(Lineage)) or 0),
            "institutions": int(s.scalar(select(func.count())
                                         .select_from(Institution)) or 0),
            "social_state_rows": int(s.scalar(select(func.count())
                                              .select_from(SettlementSocialState)) or 0),
            "pressure_rows": int(s.scalar(select(func.count())
                                          .select_from(EconomicPressureState)) or 0),
            "tribulation_episodes": int(s.scalar(select(func.count())
                                                 .select_from(TribulationEpisode)) or 0),
        }


def run_phase(work: pathlib.Path, years: int, *, tag: str,
              start_year: int = 0, env: dict | None = None) -> dict:
    """One real pipeline run; returns report + DB metrics."""
    env = env or R.build_world(work, tag=tag, via="direct")
    coordinator = S.build_coordinator()
    t0 = time.time()
    report = run_m3a_world(env["factory"], coordinator=coordinator,
                           world_id=R.WORLD_ID, epoch0_us=R.EPOCH0_US,
                           years=years, start_year=start_year)
    metrics = db_metrics(env["factory"])
    return {
        "tag": tag, "years": years, "start_year": start_year,
        "wall_seconds": round(time.time() - t0, 1),
        "final_blessed_tick": getattr(report, "final_blessed_tick", None),
        "final_state_hash": getattr(report, "final_state_hash", None),
        "final_event_stream_hash": getattr(report, "final_event_stream_hash", None),
        "engine_metrics": getattr(report, "metrics", None),
        "db": metrics,
        "env": env,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--phases", default="4,10,50,100,300")
    ap.add_argument("--determinism", action="store_true")
    ap.add_argument("--restart", action="store_true")
    args = ap.parse_args()
    out_path = pathlib.Path(args.out)
    patched = install_test_profile_watch()
    result: dict = {"patched_registries": patched, "phases": {}, "errors": []}
    work = pathlib.Path(tempfile.mkdtemp(prefix="m6c1d_laneA_"))
    result["work_dir"] = str(work)

    def flush():
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result["test_profile_usage_count"] = TEST_PROFILE_USAGE["count"]
        out_path.write_text(json.dumps(result, ensure_ascii=False, default=str,
                                       indent=1, sort_keys=True),
                            encoding="utf-8", newline="\n")

    try:
        for phase in [p for p in args.phases.split(",") if p]:
            years = int(phase)
            try:
                run = run_phase(work, years, tag=f"p{years}")
                env = run.pop("env")
                result["phases"][f"T{years}"] = run
                flush()
                if years == 100:
                    result["env100"] = {"db_path": str(env["db_path"]),
                                        "url": env["url"]}
                    flush()
            except Exception as exc:  # noqa: BLE001
                result["errors"].append({"phase": years, "error": repr(exc),
                                         "trace": traceback.format_exc()[-1500:]})
                flush()
                break

        if args.determinism:
            try:
                a = run_phase(work, 300, tag="det_a")
                b = run_phase(work, 300, tag="det_b")
                result["determinism"] = {
                    "run1_state": a["final_state_hash"],
                    "run2_state": b["final_state_hash"],
                    "run1_events": a["final_event_stream_hash"],
                    "run2_events": b["final_event_stream_hash"],
                    "state_equal": a["final_state_hash"] == b["final_state_hash"],
                    "events_equal": a["final_event_stream_hash"]
                    == b["final_event_stream_hash"],
                    "run1_wall_seconds": a["wall_seconds"],
                    "run2_wall_seconds": b["wall_seconds"],
                }
            except Exception as exc:  # noqa: BLE001
                result["errors"].append({"phase": "determinism", "error": repr(exc)})
            flush()

        if args.restart:
            try:
                env = R.build_world(work, tag="restart", via="direct")
                first = run_phase(work, 100, tag="restart_a", env=env)
                db_path, url = str(env["db_path"]), env["url"]
                del env, first
                # process-equivalent rebuild: new engine/factory/coordinator
                from XiaoguangBlessedLandRuntime.database.db import (
                    create_db_engine, make_session_factory)
                engine = create_db_engine(url)
                factory = make_session_factory(engine)
                env2 = {"url": url, "factory": factory, "engine": engine,
                        "db_path": pathlib.Path(db_path), "via": "direct"}
                second = run_phase(work, 200, tag="restart_b", start_year=100,
                                   env=env2)
                result["restart"] = {
                    "final_state_hash": second["final_state_hash"],
                    "final_event_stream_hash": second["final_event_stream_hash"],
                    "wall_seconds": second["wall_seconds"],
                    "db": second["db"],
                }
            except Exception as exc:  # noqa: BLE001
                result["errors"].append({"phase": "restart", "error": repr(exc),
                                         "trace": traceback.format_exc()[-1500:]})
            flush()
    finally:
        flush()
    print("LANE_A_DONE", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

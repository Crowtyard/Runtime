"""M6D.2 — FINAL POST-DETERMINISM INTEGRATED WORLD VERIFICATION (test-only runner).

THIS_IS_TEST_ONLY. Runs the FULL frozen pipeline
TIME → DEMOGRAPHY → RESOURCE → ECONOMY → ECOLOGY → SOCIAL → TRIBULATION → HISTORY
on a temp SQLite synthetic world with the OWNER-FINAL candidate profiles, wires the
REAL history builder, and collects the owner-§12 checkpoints (T0/T10/T50/T100/T300).

Modes
  continuous : build world (production synthetic activation path) → run 0..until
  part1      : build world → run 0..split, leave the DB in --workdir for restart
  part2      : reopen the DB in --workdir (NEW PROCESS) → run split..until

Owner-final candidate (M6D.2 §9):
  DEMOGRAPHY birth_rate 53/1000, lifespan 60, mortality 1/60, fertility 15–45,
             capacity NULL, four species share one profile
  RESOURCE   RE-LEAN-v2, 8 profiles (7 consumption kinds + registry-only slot 08),
             7 production nodes, 1 local blessed-year initial stock,
             capacity = 1.10 × actual served annual demand
  ECOLOGY    E-B-v2 sensitivity 1/279, recovery 1/25, ppp 1, initial HQ full
  SOCIAL     S-B
  TRIBULATION T-B periods 10/50/100, first omen tick 10_000_000

Usage:
  python scripts/_m6d2_integrated.py --mode continuous --until 300 --workdir DIR --out J
  python scripts/_m6d2_integrated.py --mode part1 --split 100 --workdir DIR --out J
  python scripts/_m6d2_integrated.py --mode part2 --split 100 --until 300 --workdir DIR --out J
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sqlalchemy import func, select  # noqa: E402

from tests import m6c1d_runner as R  # noqa: E402
from tests import m6c1d_support as S  # noqa: E402
from XiaoguangBlessedLandRuntime.database.db import (  # noqa: E402
    create_db_engine, make_session_factory)
from XiaoguangBlessedLandRuntime.database.models_core import WorldEvent  # noqa: E402
from XiaoguangBlessedLandRuntime.database.models_world import (  # noqa: E402
    CausalHistoryLink, EcologyState, EconomicPressureState, EntityHistoryIndex,
    HistoryIndexState, Household, Institution, Lineage, PopulationGroup,
    ProductionRecipe, ProductionState, ResourceStock, TribulationEpisode,
    TribulationSchedule)
from XiaoguangBlessedLandRuntime.services.history.builder import (  # noqa: E402
    HistoryLinkBuilder)
from XiaoguangBlessedLandRuntime.services.history.service import HistoryService  # noqa: E402
from XiaoguangBlessedLandRuntime.services.simulation.m3a_runner import (  # noqa: E402
    run_m3a_world)

DEFAULT_WORLD_ID = "SYNTH-DEMO-001"
CHECKPOINTS = (0, 10, 50, 100, 300)
DEMO_METRIC_KEYS = ("births", "deaths", "immigration", "emigration")
IMPACT_TYPES = ("DEMOGRAPHY_IMPACT_APPLIED", "RESOURCE_IMPACT_APPLIED",
                "ECONOMY_IMPACT_APPLIED", "ECOLOGY_IMPACT_APPLIED",
                "SOCIAL_IMPACT_APPLIED")
SOCIAL_KEYWORDS = ("HOUSEHOLD", "LINEAGE", "INSTITUTION", "SOCIAL", "SPLIT",
                   "FORM")
TRIBULATION_FIRST_OMEN_TICK = 10_000_000
metrics_union: dict = {}


def db_path_of(workdir: pathlib.Path) -> pathlib.Path:
    return workdir / "m6c1d_world.db"


def open_world(workdir: pathlib.Path, world_id: str) -> dict:
    path = db_path_of(workdir)
    if not path.exists():
        raise SystemExit(f"reopen failed: {path} does not exist")
    url = "sqlite:///" + str(path).replace("\\", "/")
    engine = create_db_engine(url)
    factory = make_session_factory(engine)
    R.WORLD_ID = world_id
    return {"url": url, "factory": factory, "engine": engine, "db_path": path,
            "seed_dir": None, "outcome": None, "info": None, "via": "reopen"}


def build(workdir: pathlib.Path, world_id: str, via: str) -> dict:
    env = R.build_world(workdir, tag="world", via=via, world_id=world_id)
    if env["db_path"] != db_path_of(workdir):
        raise SystemExit(f"unexpected db path {env['db_path']}")
    return env


def _sum(session, column) -> int:
    return int(session.scalar(select(func.coalesce(func.sum(column), 0))) or 0)


def event_type_census(session) -> dict[str, int]:
    rows = session.execute(select(WorldEvent.event_type,
                                  func.count()).group_by(WorldEvent.event_type)).all()
    return {str(t): int(n) for t, n in rows}


def collect(env: dict, world_id: str, *, cum: dict, start_pop: int,
            with_integrity: bool) -> dict:
    factory = env["factory"]
    out: dict = {}
    with factory() as s:
        out["population_total"] = _sum(s, PopulationGroup.count)
        out["population_by_species"] = {
            sp: int(s.scalar(select(func.coalesce(
                func.sum(PopulationGroup.count), 0))
                .where(PopulationGroup.species == sp)) or 0)
            for sp, _ in S.SPECIES}
        always_zero = s.execute(select(func.count()).select_from(ResourceStock)
                                .where((ResourceStock.cum_extracted_minor == 0)
                                       & (ResourceStock.cum_produced_minor == 0)
                                       & (ResourceStock.cum_imported_minor == 0))
                                ).scalar()
        out["resource"] = {
            "ending_stock_minor": _sum(s, ResourceStock.quantity),
            "cum_extracted_minor": _sum(s, ResourceStock.cum_extracted_minor),
            "cum_produced_minor": _sum(s, ResourceStock.cum_produced_minor),
            "cum_transfer_in_minor": _sum(s, ResourceStock.cum_imported_minor),
            "cum_transfer_out_minor": _sum(s, ResourceStock.cum_exported_minor),
            "cum_consumed_minor": _sum(s, ResourceStock.cum_consumed_minor),
            "cum_lost_minor": _sum(s, ResourceStock.cum_lost_minor),
            "stock_cells": int(s.scalar(select(func.count())
                                        .select_from(ResourceStock)) or 0),
            "permanent_zero_supply_cells": int(always_zero or 0),
        }
        pressure = s.execute(select(
            EconomicPressureState.unmet_minor,
            EconomicPressureState.demand_minor,
            EconomicPressureState.fulfilled_minor,
            EconomicPressureState.sustained_shortage_steps,
            EconomicPressureState.stress_level)).all()
        out["economy"] = {
            "demand_minor": sum(int(r[1] or 0) for r in pressure),
            "fulfilled_minor": sum(int(r[2] or 0) for r in pressure),
            "unmet_minor": sum(int(r[0] or 0) for r in pressure),
            "unmet_cells": sum(1 for r in pressure if int(r[0] or 0) > 0),
            "pressure_rows": len(pressure),
            "max_sustained_shortage_steps": max(
                [int(r[3] or 0) for r in pressure] or [0]),
            "stress_levels": sorted({str(r[4]) for r in pressure}),
            "production_state_rows": int(s.scalar(select(func.count())
                                                  .select_from(ProductionState)) or 0),
            "production_recipe_rows": int(s.scalar(select(func.count())
                                                   .select_from(ProductionRecipe)) or 0),
        }
        eco = s.execute(select(EcologyState)).scalars().first()
        out["ecology"] = {} if eco is None else {
            "habitat_quality": int(eco.habitat_quality),
            "ecological_stress": int(eco.ecological_stress),
            "population_pressure": int(eco.population_pressure),
            "extraction_pressure": int(eco.extraction_pressure),
            "production_pressure": int(eco.production_pressure),
            "depletion_pressure": int(eco.depletion_pressure),
            "external_pressure": int(eco.external_pressure),
            "quality_min_seen": int(eco.quality_min_seen),
            "quality_max_seen": int(eco.quality_max_seen),
        }
        out["social"] = {
            "households": int(s.scalar(select(func.count()).select_from(Household)) or 0),
            "lineages": int(s.scalar(select(func.count()).select_from(Lineage)) or 0),
            "institutions": int(s.scalar(select(func.count())
                                         .select_from(Institution)) or 0),
        }
        episodes = s.execute(select(TribulationEpisode.entered_tick)
                             .order_by(TribulationEpisode.entered_tick)).scalars().all()
        schedules = s.execute(select(TribulationSchedule.tier,
                                     TribulationSchedule.period_years)
                              .order_by(TribulationSchedule.tier)).all()
        out["tribulation"] = {
            "episodes_total": len(episodes),
            "episode_ticks": [int(t) for t in episodes][:40],
            "first_episode_tick": int(episodes[0]) if episodes else None,
            "schedules": {str(t): int(p) for t, p in schedules},
        }
        impact = s.execute(select(WorldEvent.event_type, WorldEvent.effect)
                           .where(WorldEvent.event_type.in_(IMPACT_TYPES))).all()
        losses = 0
        counts = {t: 0 for t in IMPACT_TYPES}
        for etype, effect in impact:
            counts[str(etype)] = counts.get(str(etype), 0) + 1
            if isinstance(effect, dict):
                losses += int(effect.get("population_loss", 0) or 0)
        out["tribulation"]["impact_event_counts"] = counts
        out["tribulation"]["casualties_total"] = losses
        out["tribulation"]["casualties_cum_delta"] = \
            losses - cum.get("casualties", 0)
        cum["casualties"] = losses
        out["history"] = {
            "world_events": int(s.scalar(select(func.count())
                                         .select_from(WorldEvent)) or 0),
            "causal_history_links": int(s.scalar(select(func.count())
                                                 .select_from(CausalHistoryLink)) or 0),
            "entity_history_index_rows": int(s.scalar(select(func.count())
                                                      .select_from(EntityHistoryIndex)) or 0),
            "history_index_state_rows": int(s.scalar(select(func.count())
                                                     .select_from(HistoryIndexState)) or 0),
        }
        idx = s.execute(select(HistoryIndexState)).scalars().first()
        out["history"]["indexed_through_tick"] = \
            int(idx.indexed_through_tick) if idx is not None else None
        out["history"]["links_total"] = int(idx.links_total) if idx is not None else None

    # ---- population accounting identity (owner §13) --------------------
    cum.setdefault("demo", {k: 0 for k in DEMO_METRIC_KEYS})
    demo = cum["demo"]
    rhs = (start_pop + demo["births"] + demo["immigration"]
           - demo["deaths"] - demo["emigration"] - cum["casualties"])
    other = out["population_total"] - rhs
    out["accounting"] = {
        "start_population": start_pop,
        "natural_births": demo["births"],
        "immigration": demo["immigration"],
        "natural_deaths": demo["deaths"],
        "emigration": demo["emigration"],
        "tribulation_casualties": cum["casualties"],
        "other_authoritative_losses": other,
        "identity_rhs": rhs,
        "actual_population": out["population_total"],
        "identity_ok": other == 0,
    }
    if with_integrity:
        svc = HistoryService(factory)
        audit = svc.history_integrity_audit(world_id=world_id)
        out["history_integrity"] = {
            "orphan_links": int(audit.get("orphan_links", -1)),
            "cycle_count": int(audit.get("cycle_count", -1)),
            "tick_paradox_links": int(audit.get("tick_paradox_links", -1)),
            "duplicate_links": int(audit.get("duplicate_links", -1)),
            "invalid_relations": len(audit.get("invalid_relations", []) or []),
            "clean": bool(audit.get("clean", False)),
        }
        out["causal_history_hash"] = svc.causal_history_hash(world_id=world_id)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("continuous", "part1", "part2"),
                    default="continuous")
    ap.add_argument("--until", type=int, default=300)
    ap.add_argument("--split", type=int, default=100)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--world-id", default=DEFAULT_WORLD_ID)
    ap.add_argument("--via", default="activation", choices=("activation", "direct"))
    args = ap.parse_args()

    workdir = pathlib.Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    result: dict = {
        "mode": args.mode, "world_id": args.world_id,
        "python_hashseed": os.environ.get("PYTHONHASHSEED", "<unset>"),
        "pid": os.getpid(), "until": args.until, "split": args.split,
        "birth_rate": "53/1000",
        "history_builder": "HistoryLinkBuilder(real)",
        "checkpoints": {}, "per_year": [],
    }

    if args.mode == "part2":
        env = open_world(workdir, args.world_id)
        result["via"] = "reopen"
        start_year = args.split
        result["reopen"] = True
    else:
        env = build(workdir, args.world_id, args.via)
        result["via"] = env["via"]
        result["self_check"] = R.self_check(env)
        result["activation"] = None if env["outcome"] is None else {
            "status": getattr(env["outcome"], "status", None)
            if not isinstance(env["outcome"], dict) else env["outcome"].get("status"),
            "anchor_us": getattr(env["outcome"], "activation_anchor_us", None)
            if not isinstance(env["outcome"], dict)
            else env["outcome"].get("activation_anchor_us"),
        }
        start_year = 0
        if not result["self_check"]["SELF_CHECK"]:
            result["ABORT"] = "SELF_CHECK_FAILED"
            pathlib.Path(args.out).write_text(
                json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True,
                           default=str), encoding="utf-8", newline="\n")
            print("ABORT SELF_CHECK_FAILED", json.dumps(result["self_check"]),
                  flush=True)
            return 3

    coordinator = S.build_coordinator()
    coordinator.history_builder = HistoryLinkBuilder()

    end_year = args.split if args.mode == "part1" else args.until
    result["end_year"] = end_year

    cum: dict = {"demo": {k: 0 for k in DEMO_METRIC_KEYS}, "casualties": 0}
    with env["factory"]() as s:
        start_pop = int(s.scalar(select(func.coalesce(
            func.sum(PopulationGroup.count), 0))) or 0)
    result["start_population"] = start_pop

    if 0 in CHECKPOINTS and start_year == 0:
        result["checkpoints"]["T0"] = collect(env, args.world_id, cum=cum,
                                              start_pop=start_pop,
                                              with_integrity=False)

    last_report = None
    for year in range(start_year + 1, end_year + 1):
        report = run_m3a_world(env["factory"], coordinator=coordinator,
                               world_id=args.world_id, epoch0_us=R.EPOCH0_US,
                               years=1, start_year=year - 1)
        last_report = report
        metrics = getattr(report, "metrics", {}) or {}
        demog = metrics.get("DEMOGRAPHY", {}) or {}
        for key in DEMO_METRIC_KEYS:
            cum["demo"][key] += int(demog.get(key, 0) or 0)
        metrics_union.setdefault("DEMOGRAPHY", {})
        for engine_id, payload in metrics.items():
            if isinstance(payload, dict):
                bucket = metrics_union.setdefault(engine_id, {})
                for k, v in payload.items():
                    if isinstance(v, (int, bool)):
                        bucket[k] = bucket.get(k, 0) + int(v)
                    else:
                        bucket[k] = v
        with env["factory"]() as s:
            unmet = int(s.scalar(select(func.count()).select_from(
                EconomicPressureState).where(
                EconomicPressureState.unmet_minor > 0)) or 0)
            habitat = int(s.scalar(select(func.coalesce(
                func.max(EcologyState.habitat_quality), 0))) or 0)
        result["per_year"].append({"year": year, "unmet_cells": unmet,
                                   "habitat_quality": habitat})
        if year in CHECKPOINTS:
            result["checkpoints"][f"T{year}"] = collect(
                env, args.world_id, cum=cum, start_pop=start_pop,
                with_integrity=(year == end_year and args.mode != "part1"))
        if year % 25 == 0 or year == end_year:
            entry = result["checkpoints"].get(
                f"T{year}", {}).get("population_total", "")
            print("YEAR %d pop=%s unmet=%d habitat=%d elapsed=%.0fs"
                  % (year, entry, unmet, habitat, time.time() - started),
                  flush=True)

    if last_report is None:
        with env["factory"]() as s:
            last_state = last_event = None
    else:
        last_state = getattr(last_report, "final_state_hash", None)
        last_event = getattr(last_report, "final_event_stream_hash", None)
    result["final_state_hash"] = last_state
    result["final_event_stream_hash"] = last_event
    result["final_blessed_tick"] = (getattr(last_report, "final_blessed_tick", None)
                                    if last_report is not None else None)
    result["cumulative_metrics"] = metrics_union
    result["cumulative_demography"] = cum["demo"]
    result["shortage_years"] = [row["year"] for row in result["per_year"]
                                if row["unmet_cells"] > 0]
    result["SHORTAGE_YEARS_TOTAL"] = len(result["shortage_years"])
    with env["factory"]() as s:
        result["event_type_census"] = event_type_census(s)
    result["event_type_census"] = dict(sorted(
        result["event_type_census"].items()))
    census = result["event_type_census"]
    result["social_event_total"] = sum(
        n for t, n in census.items()
        if any(k in t.upper() for k in SOCIAL_KEYWORDS))
    result["TEST_PROFILE_USAGE_COUNT"] = (
        result.get("self_check", {}).get("TEST_PROFILE_REFERENCES"))
    result["WORLD_SEED_ACTIVATED_GENESIS_COUNT"] = (
        result.get("self_check", {}).get("TWIN_GENESIS"))
    result["elapsed_s"] = round(time.time() - started, 1)
    if env["db_path"].exists() and args.mode == "part1":
        result["db_sha256"] = hashlib.sha256(
            pathlib.Path(env["db_path"]).read_bytes()).hexdigest()

    pathlib.Path(args.out).write_text(
        json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True,
                   default=str), encoding="utf-8", newline="\n")
    print("ARTIFACT", args.out, flush=True)
    print("M6D2_MODE", args.mode, "state", last_state, "events", last_event,
          "elapsed", result["elapsed_s"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

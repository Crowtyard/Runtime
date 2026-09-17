"""M6D — single-process demography baseline probe used for the hash-seed matrix.

Each invocation is a FRESH Python process (PYTHONHASHSEED must be set before the
interpreter starts; this script never sets it itself — the caller does).

Prints one JSON blob: per-checkpoint populations + final state/event hashes, and
optionally per-year state hashes (for FIRST_DIVERGENT_YEAR pinpointing).

Usage: python scripts/_m6d_hashseed_probe.py --seed SYNTH-DEMO-001 --until 300 \
           --out <json> [--per-year 30]
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import tempfile
from fractions import Fraction

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sqlalchemy import func, select  # noqa: E402

from tests import m6c1d_runner as R  # noqa: E402
from tests import m6c1d_support as S  # noqa: E402
from XiaoguangBlessedLandRuntime.services.simulation.coordinator import (  # noqa: E402
    SimulationCoordinator)
from XiaoguangBlessedLandRuntime.services.simulation.m3a_runner import (  # noqa: E402
    run_m3a_world)
from XiaoguangBlessedLandRuntime.services.simulation.population import (  # noqa: E402
    PopulationGroupEngine)

BIRTH_RATE = Fraction(53, 1000)
CHECKPOINTS = (10, 50, 100, 300)


def coordinator() -> SimulationCoordinator:
    profile = S.formal_species_profile()
    object.__setattr__(profile, "birth_rate", BIRTH_RATE)
    return SimulationCoordinator(
        [PopulationGroupEngine(profiles={name: profile for name, _ in S.SPECIES})],
        simulation_version="0.3.0")


def population(factory) -> int:
    from XiaoguangBlessedLandRuntime.database.models_world import PopulationGroup
    with factory() as s:
        return int(s.scalar(select(func.coalesce(func.sum(PopulationGroup.count), 0))) or 0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", default="SYNTH-DEMO-001")
    ap.add_argument("--until", type=int, default=300)
    ap.add_argument("--per-year", type=int, default=0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    work = pathlib.Path(tempfile.mkdtemp(prefix="m6d_probe_"))
    env = R.build_world(work, tag="probe", via="direct", world_id=args.seed)
    coord = coordinator()
    tots = {"births": 0, "deaths": 0, "immigration": 0, "emigration": 0}
    p0 = population(env["factory"])
    series = {"T0": {"population": p0}}
    per_year = {}
    tick = 0
    last_state = last_event = None

    if args.per_year:
        for year in range(1, args.per_year + 1):
            rep = run_m3a_world(env["factory"], coordinator=coord, world_id=args.seed,
                                epoch0_us=R.EPOCH0_US, years=1, start_year=year - 1)
            m = (getattr(rep, "metrics", {}) or {}).get("DEMOGRAPHY", {})
            for key in tots:
                tots[key] += int(m.get(key, 0) or 0)
            per_year[f"Y{year}"] = {"population": population(env["factory"]),
                                    "state_hash": getattr(rep, "final_state_hash", None),
                                    "event_hash": getattr(rep, "final_event_stream_hash", None)}
        tick = args.per_year

    for target in [c for c in CHECKPOINTS if c <= args.until and c > tick]:
        rep = run_m3a_world(env["factory"], coordinator=coord, world_id=args.seed,
                            epoch0_us=R.EPOCH0_US, years=target - tick, start_year=tick)
        tick = target
        m = (getattr(rep, "metrics", {}) or {}).get("DEMOGRAPHY", {})
        for key in tots:
            tots[key] += int(m.get(key, 0) or 0)
        pop = population(env["factory"])
        rhs = p0 + tots["births"] + tots["immigration"] - tots["deaths"] - tots["emigration"]
        series[f"T{target}"] = {"population": pop, "cum": dict(tots),
                                "identity_ok": rhs == pop}
        last_state = getattr(rep, "final_state_hash", None)
        last_event = getattr(rep, "final_event_stream_hash", None)

    out = {
        "label": args.label,
        "python_hashseed": os.environ.get("PYTHONHASHSEED", "<unset>"),
        "pid": os.getpid(),
        "seed": args.seed,
        "birth_rate": f"{BIRTH_RATE.numerator}/{BIRTH_RATE.denominator}",
        "until": args.until,
        "population_by_checkpoint": {k: v["population"] for k, v in series.items()},
        "identity_ok": all(v.get("identity_ok", True) for v in series.values()),
        "final_state_hash": last_state,
        "final_event_stream_hash": last_event,
        "per_year": per_year,
    }
    pathlib.Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1,
                                                 sort_keys=True), encoding="utf-8",
                                      newline="\n")
    print("PROBE " + json.dumps({k: out[k] for k in (
        "label", "python_hashseed", "pid", "population_by_checkpoint",
        "final_state_hash", "final_event_stream_hash", "identity_ok")},
        ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

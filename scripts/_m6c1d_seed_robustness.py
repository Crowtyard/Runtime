"""M6C.1D — P2-B multi-seed robustness (RA-DEMOGRAPHY-STATIONARY-001 verification).

Five fixed, versioned synthetic test identities SYNTH-DEMO-001..005.  The deterministic
RNG identity derives from ``world_id`` (services/rng_service.RngService(world_id=...)),
so distinct world identities give distinct deterministic streams while **every other**
variable stays identical (12000 people, 4 groups, 12 settlements, 61 cohorts,
RA-COHORT-001 v1.1, lifespan 60, mortality 1/60, fertility 15-45, birth_rate 53/1000,
capacity NULL).  Only the demography baseline pipeline runs (PopulationGroupEngine alone),
so no tribulation/resource/ecology/social shock pollutes intrinsic demography.

Per seed: T10/T50/T100/T300 population + births/deaths/immigration/emigration and the
population accounting identity.  Each seed additionally repeats its 300y run to prove
byte-identical determinism, and reports births/deaths (natural change), tribulation
casualties (0 by construction here) and other losses (identity closes -> 0).

Usage: python scripts/_m6c1d_seed_robustness.py [--until 300] [--out x.json] [--repeat]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import statistics
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

SEEDS = ("SYNTH-DEMO-001", "SYNTH-DEMO-002", "SYNTH-DEMO-003", "SYNTH-DEMO-004",
         "SYNTH-DEMO-005")
BIRTH_RATE = Fraction(53, 1000)
CHECKPOINTS = (10, 50, 100, 300)
BAND = (11_400, 12_600)


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


def run_seed(world_id: str, until: int, *, tag: str) -> dict:
    work = pathlib.Path(tempfile.mkdtemp(prefix=f"m6c1d_seed_{tag}_"))
    env = R.build_world(work, tag=tag, via="direct", world_id=world_id)
    coord = coordinator()
    tots = {"births": 0, "deaths": 0, "immigration": 0, "emigration": 0}
    p0 = population(env["factory"])
    series = {"T0": {"population": p0, "cum": dict(tots), "identity_ok": True}}
    tick = 0
    last_hash = last_event_hash = None
    for target in [c for c in CHECKPOINTS if c <= until]:
        report = run_m3a_world(env["factory"], coordinator=coord, world_id=world_id,
                               epoch0_us=R.EPOCH0_US, years=target - tick,
                               start_year=tick)
        tick = target
        m = (getattr(report, "metrics", {}) or {}).get("DEMOGRAPHY", {})
        for key in tots:
            tots[key] += int(m.get(key, 0) or 0)
        pop = population(env["factory"])
        rhs = p0 + tots["births"] + tots["immigration"] - tots["deaths"] - tots["emigration"]
        series[f"T{target}"] = {"population": pop, "cum": dict(tots),
                                "identity_rhs": rhs, "identity_ok": rhs == pop}
        last_hash = getattr(report, "final_state_hash", None)
        last_event_hash = getattr(report, "final_event_stream_hash", None)
    return {"world_id": world_id, "birth_rate": f"{BIRTH_RATE.numerator}/{BIRTH_RATE.denominator}",
            "until": until, "series": series,
            "final_population": series[f"T{max(c for c in CHECKPOINTS if c <= until)}"]["population"],
            "identity_all_ok": all(v.get("identity_ok", True) for v in series.values()),
            "final_state_hash": last_hash, "final_event_stream_hash": last_event_hash}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--until", type=int, default=300)
    ap.add_argument("--out", default=str(ROOT / "reports" / "M6C1D_SEED_ROBUSTNESS.json"))
    ap.add_argument("--repeat", action="store_true",
                    help="repeat each seed's run to prove exact determinism")
    args = ap.parse_args()

    results = []
    for index, seed in enumerate(SEEDS, 1):
        res = run_seed(seed, args.until, tag=f"s{index}")
        line = ("SEED%d %s T10=%s T50=%s T100=%s T300=%s identity=%s"
                % (index, seed, res["series"].get("T10", {}).get("population"),
                   res["series"].get("T50", {}).get("population"),
                   res["series"].get("T100", {}).get("population"),
                   res["series"].get("T300", {}).get("population"),
                   res["identity_all_ok"]))
        if args.repeat:
            again = run_seed(seed, args.until, tag=f"s{index}r")
            same = (again["final_state_hash"] == res["final_state_hash"]
                    and again["final_event_stream_hash"] == res["final_event_stream_hash"])
            res["repeat_state_hash"] = again["final_state_hash"]
            res["repeat_event_hash"] = again["final_event_stream_hash"]
            res["repeat_identical"] = same
            line += " repeat_identical=%s" % same
        results.append(res)
        print(line, flush=True)

    t300 = [r["series"].get("T300", {}).get("population") for r in results
            if r["series"].get("T300")]
    t100 = [r["series"].get("T100", {}).get("population") for r in results
            if r["series"].get("T100")]
    in_band = [BAND[0] <= v <= BAND[1] for v in t300]
    summary = {
        "P2_B_BIRTH_RATE": "53/1000",
        "T100_PER_SEED": t100, "T300_PER_SEED": t300,
        "MULTI_SEED_MIN": min(t300) if t300 else None,
        "MULTI_SEED_MAX": max(t300) if t300 else None,
        "MULTI_SEED_MEAN": round(statistics.fmean(t300), 1) if t300 else None,
        "MULTI_SEED_MEDIAN": statistics.median(t300) if t300 else None,
        "BAND": list(BAND),
        "IN_BAND_PER_SEED": in_band,
        "SEEDS_IN_BAND": sum(1 for x in in_band if x),
        "P2_B_MULTI_SEED_ROBUSTNESS": "PASS" if all(in_band) else "FAIL",
        "POPULATION_ACCOUNTING_IDENTITY": "PASS" if all(
            r["identity_all_ok"] for r in results) else "FAIL",
        "DETERMINISTIC_RNG_REPRODUCIBILITY": (
            "PASS" if args.repeat and all(r.get("repeat_identical") for r in results)
            else ("NOT_RUN" if not args.repeat else "FAIL")),
    }
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "runs": results}, ensure_ascii=False,
                              default=str, indent=1, sort_keys=True),
                   encoding="utf-8", newline="\n")
    print("SUMMARY", json.dumps(summary, ensure_ascii=False))
    print("ARTIFACT", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""M6C.1D — RA-DEMOGRAPHY-STATIONARY-001 (test-only birth_rate calibration).

DEMOGRAPHY BASELINE RUN: identical 12 settlements / 12000 people / 61 cohorts / shared
formal profile, but the pipeline contains **only** the frozen PopulationGroupEngine.
Because no other engine runs, the external feedback rows keep their neutral defaults
(no shortage mortality, no ecology mortality, no social modifiers) and there is no
TRIBULATION engine -> intrinsic demographic dynamics only. No frozen engine is modified.

Each run reports the population accounting identity:
    T0 + births + immigration - deaths - emigration == Tn

Usage: python scripts/_m6c1d_demog_calib.py --birth-rate 185/4096 --until 300 [--out x.json]
       python scripts/_m6c1d_demog_calib.py --scan 0.045,0.050,0.055,0.060
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

from sqlalchemy import func, select, text  # noqa: E402

from tests import m6c1d_runner as R  # noqa: E402
from tests import m6c1d_support as S  # noqa: E402
from XiaoguangBlessedLandRuntime.services.simulation.coordinator import (  # noqa: E402
    SimulationCoordinator)
from XiaoguangBlessedLandRuntime.services.simulation.m3a_runner import (  # noqa: E402
    run_m3a_world)
from XiaoguangBlessedLandRuntime.services.simulation.population import (  # noqa: E402
    PopulationGroupEngine)

CHECKPOINTS = (10, 50, 100, 300)


def demography_only_coordinator(birth_rate: Fraction) -> SimulationCoordinator:
    """Real PopulationGroupEngine only (no external engines -> neutral feedback)."""
    profile = S.formal_species_profile()
    object.__setattr__(profile, "birth_rate", birth_rate)
    return SimulationCoordinator(
        [PopulationGroupEngine(profiles={name: profile for name, _ in S.SPECIES})],
        simulation_version="0.3.0")


def population(factory) -> tuple[int, dict, int]:
    from XiaoguangBlessedLandRuntime.database.models_world import PopulationGroup
    with factory() as s:
        total = int(s.scalar(select(func.coalesce(func.sum(PopulationGroup.count), 0))) or 0)
        rows = int(s.scalar(select(func.count()).select_from(PopulationGroup)) or 0)
        by = {sp: int(s.scalar(select(func.coalesce(func.sum(PopulationGroup.count), 0))
                                 .where(PopulationGroup.species == sp)) or 0)
              for sp, _ in S.SPECIES}
    return total, by, rows


def run_candidate(birth_rate: Fraction, until: int, *, tag: str = "cal") -> dict:
    work = pathlib.Path(tempfile.mkdtemp(prefix=f"m6c1d_demog_{tag}_"))
    env = R.build_world(work, tag=tag, via="direct")
    coordinator = demography_only_coordinator(birth_rate)
    tots = {"births": 0, "deaths": 0, "immigration": 0, "emigration": 0}
    series = {}
    tick = 0
    p0 = population(env["factory"])[0]
    series["T0"] = {"population": p0, "cum": dict(tots), "identity_ok": True}
    for target in [c for c in CHECKPOINTS if c <= until]:
        report = run_m3a_world(env["factory"], coordinator=coordinator,
                               world_id=R.WORLD_ID, epoch0_us=R.EPOCH0_US,
                               years=target - tick, start_year=tick)
        tick = target
        m = (getattr(report, "metrics", {}) or {}).get("DEMOGRAPHY", {})
        for key in tots:
            tots[key] += int(m.get(key, 0) or 0)
        pop, by, rows = population(env["factory"])
        identity_rhs = p0 + tots["births"] + tots["immigration"] \
            - tots["deaths"] - tots["emigration"]
        series[f"T{target}"] = {
            "population": pop, "by_species": by, "cohort_rows": rows,
            "cum": dict(tots),
            "identity_rhs": identity_rhs,
            "identity_ok": identity_rhs == pop,
        }
    return {"birth_rate": f"{birth_rate.numerator}/{birth_rate.denominator}",
            "birth_rate_decimal": round(float(birth_rate), 8),
            "until": until, "with_tribulation": False,
            "external_feedback": "NEUTRAL_DEFAULTS_NO_OTHER_ENGINES",
            "work_dir": str(work), "series": series,
            "final_population": series[f"T{max(c for c in CHECKPOINTS if c <= until)}"]["population"],
            "identity_all_ok": all(v.get("identity_ok", True) for v in series.values())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--birth-rate", default="185/4096")
    ap.add_argument("--until", type=int, default=300)
    ap.add_argument("--scan", default=None, help="comma-separated decimals to scan")
    ap.add_argument("--out", default=str(ROOT / "reports" / "M6C1D_DEMOGRAPHY_CALIBRATION.json"))
    args = ap.parse_args()

    results = []
    if args.scan:
        for token in args.scan.split(","):
            token = token.strip()
            if not token:
                continue
            br = Fraction(token).limit_denominator(1_000_000)
            res = run_candidate(br, args.until, tag=f"s{abs(hash(token)) % 997}")
            results.append(res)
            print("SCAN %-14s T100=%s T300=%s identity=%s"
                  % (res["birth_rate"], res["series"].get("T100", {}).get("population"),
                     res["series"].get("T300", {}).get("population"),
                     res["identity_all_ok"]))
    else:
        br = Fraction(args.birth_rate)
        res = run_candidate(br, args.until, tag="main")
        results.append(res)
        for cp, vals in res["series"].items():
            print(cp, "population", vals["population"], "cum", vals["cum"],
                  "identity_ok", vals.get("identity_ok"))
        print("FINAL", res["final_population"], "IDENTITY_ALL_OK", res["identity_all_ok"])

    out = pathlib.Path(args.out)
    existing = []
    if out.exists():
        try:
            existing = json.loads(out.read_text(encoding="utf-8")).get("runs", [])
        except Exception:  # noqa: BLE001
            existing = []
    out.write_text(json.dumps({"runs": existing + results}, ensure_ascii=False,
                              default=str, indent=1, sort_keys=True),
                   encoding="utf-8", newline="\n")
    print("ARTIFACT", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

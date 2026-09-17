"""M6D.1 — test-only RNG + entity-order trace probe (NO production change).

Records, for each demography step:
  * GROUP  : the order in which PopulationGroupEngine processes (settlement, species)
  * RNG    : every RngStream.chance() draw — stream tag, per-stream call index,
             probability, result

Comparing two fresh processes with different PYTHONHASHSEED yields
FIRST_DIVERGENT_RNG_CALL_INDEX and the first differing entity position, which
classifies the divergence as
  case A = same entity, different RNG result        (RngService / derivation problem)
  case B = same RNG sequence, different entity      (processing-order problem)

`--normalize-order` applies a TEST-ONLY canonical settlement rank so the causal
experiment can be run without touching production code.

Usage: python scripts/_m6d_trace_probe.py --years 1 --out <json> [--normalize-order]
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

import XiaoguangBlessedLandRuntime.services.rng_service as RNG  # noqa: E402
from XiaoguangBlessedLandRuntime.database.models_world import (  # noqa: E402
    PopulationGroup)
from XiaoguangBlessedLandRuntime.services.simulation import population as POP  # noqa: E402
from XiaoguangBlessedLandRuntime.services.simulation.coordinator import (  # noqa: E402
    SimulationCoordinator)
from XiaoguangBlessedLandRuntime.services.simulation.m3a_runner import (  # noqa: E402
    run_m3a_world)
from XiaoguangBlessedLandRuntime.services.simulation.population import (  # noqa: E402
    PopulationGroupEngine)

BIRTH_RATE = Fraction(53, 1000)

TRACE: list[dict] = []
STREAMS: dict[int, int] = {}


def install_trace() -> None:
    orig_stream = RNG.RngService.stream
    orig_chance = RNG.RngStream.chance

    def stream(self, *, subsystem, blessed_period_tick, entity_scope="WORLD"):
        s = orig_stream(self, subsystem=subsystem,
                        blessed_period_tick=blessed_period_tick,
                        entity_scope=entity_scope)
        s._m6d_tag = "%s@%d" % (subsystem, blessed_period_tick)
        return s

    def chance(self, p):
        tag = getattr(self, "_m6d_tag", "<untagged>")
        idx = STREAMS.get(id(self), 0)
        STREAMS[id(self)] = idx + 1
        result = orig_chance(self, p)
        TRACE.append({"kind": "RNG", "stream": tag, "stream_call_index": idx,
                      "seq": len(TRACE), "p": repr(p), "result": bool(result)})
        return result

    RNG.RngService.stream = stream
    RNG.RngStream.chance = chance

    orig_step = POP.PopulationGroupEngine._step_group

    def step_group(self, ctx, rows, settlement_ref, species, capacity,
                   social_fert=Fraction(1)):
        TRACE.append({"kind": "GROUP", "seq": len(TRACE),
                      "settlement": settlement_ref, "species": species,
                      "n_rows": sum(1 for r in rows
                                    if r["settlement_ref"] == settlement_ref
                                    and r["species"] == species)})
        return orig_step(self, ctx, rows, settlement_ref, species, capacity,
                         social_fert)

    POP.PopulationGroupEngine._step_group = step_group


def install_canonical_set_order() -> dict:
    """TEST-ONLY: neutralize ONLY the hash-ordered set literal in
    PopulationGroupEngine.simulate by intercepting module-level `sorted()` when
    called on a set of (settlement_ref, species) tuples.

    `_settlement_order` is deliberately left untouched: it is also used as an
    index into SpeciesDemographyProfile.migration_weights, so replacing it would
    change engine semantics (observed: IndexError). This hook therefore simulates
    exactly the candidate production fix without touching production code.
    """
    import builtins
    orig_sorted = builtins.sorted
    order = POP._settlement_order

    def patched(iterable, key=None, reverse=False):
        if isinstance(iterable, (set, frozenset)) and not reverse:
            items = list(iterable)
            if items and all(isinstance(i, tuple) and len(i) == 2 for i in items):
                def canon(k):
                    ref = k[0]
                    return (order(ref), "" if ref is None else str(ref),
                            "" if k[1] is None else str(k[1]))
                return orig_sorted(items, key=canon)
        return orig_sorted(iterable, key=key, reverse=reverse)

    POP.sorted = patched
    return {"mode": "POP_MODULE_SORTED_INTERCEPT_SET_ONLY",
            "canonical_sort_key": "(_settlement_order(settlement_ref), settlement_ref, species)"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", default="SYNTH-DEMO-001")
    ap.add_argument("--years", type=int, default=1)
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="")
    ap.add_argument("--normalize-order", action="store_true")
    args = ap.parse_args()

    work = pathlib.Path(tempfile.mkdtemp(prefix="m6d_trace_"))
    env = R.build_world(work, tag="trace", via="direct", world_id=args.seed)

    normalization = None
    if args.normalize_order:
        normalization = install_canonical_set_order()

    install_trace()
    profile = S.formal_species_profile()
    object.__setattr__(profile, "birth_rate", BIRTH_RATE)
    coord = SimulationCoordinator(
        [PopulationGroupEngine(profiles={name: profile for name, _ in S.SPECIES})],
        simulation_version="0.3.0")

    per_year = {}
    for year in range(1, args.years + 1):
        rep = run_m3a_world(env["factory"], coordinator=coord, world_id=args.seed,
                            epoch0_us=R.EPOCH0_US, years=1, start_year=year - 1)
        with env["factory"]() as s:
            pop = int(s.scalar(select(func.coalesce(func.sum(PopulationGroup.count), 0)))
                      or 0)
        per_year[f"Y{year}"] = {"population": pop,
                                "state_hash": getattr(rep, "final_state_hash", None),
                                "event_hash": getattr(rep, "final_event_stream_hash", None)}

    out = {
        "label": args.label,
        "python_hashseed": os.environ.get("PYTHONHASHSEED", "<unset>"),
        "pid": os.getpid(),
        "seed": args.seed,
        "birth_rate": f"{BIRTH_RATE.numerator}/{BIRTH_RATE.denominator}",
        "years": args.years,
        "normalization": normalization,
        "per_year": per_year,
        "trace": TRACE,
    }
    pathlib.Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1,
                                                 sort_keys=True), encoding="utf-8",
                                      newline="\n")
    groups = [e for e in TRACE if e["kind"] == "GROUP"]
    draws = [e for e in TRACE if e["kind"] == "RNG"]
    print("TRACE " + json.dumps({
        "label": args.label, "hashseed": out["python_hashseed"], "pid": os.getpid(),
        "per_year": per_year, "group_steps": len(groups), "rng_draws": len(draws),
        "normalize": bool(args.normalize_order),
        "first_group_order": [(g["settlement"], g["species"]) for g in groups[:6]]},
        ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

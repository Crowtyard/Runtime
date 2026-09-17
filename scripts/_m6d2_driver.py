"""M6D.2 — final integrated determinism + restart-equivalence driver.

Runs the integrated verification (scripts/_m6d2_integrated.py) in SEPARATE OS
processes and compares the owner-required hashes:

  RUN1 : continuous 300y, PYTHONHASHSEED not pinned
  RUN2 : continuous 300y, PYTHONHASHSEED not pinned  (independent process)
  RUN3a: 0→split years, PYTHONHASHSEED=0
  RUN3b: split→300 years in a NEW process on RUN3a's DB, PYTHONHASHSEED=42

  DETERMINISM            = RUN1.state == RUN2.state and RUN1.events == RUN2.events
  RESTART_EQUIVALENCE    = RUN3b.state == RUN1.state and RUN3b.history == RUN1.history
  PYTHONHASHSEED_INDEPENDENT_RESTART = RUN3b == RUN1 (different hash seeds across
                                       the restart boundary)

Usage: python scripts/_m6d2_driver.py [--until 300] [--split 100] [--world-id SYNTH-DEMO-001]
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "_m6d2_integrated.py"


def run_stage(label: str, args: list[str], *, hashseed: str | None,
              timeout: int) -> dict:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    if hashseed is None:
        env.pop("PYTHONHASHSEED", None)
    else:
        env["PYTHONHASHSEED"] = hashseed
    started = time.time()
    proc = subprocess.run([sys.executable, str(RUNNER)] + args, cwd=str(ROOT),
                          env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
    print("---- %s (hashseed=%s, %.0fs, rc=%d)"
          % (label, hashseed or "<unset>", time.time() - started,
             proc.returncode), flush=True)
    for line in (proc.stdout or "").strip().splitlines()[-6:]:
        print("   ", line, flush=True)
    if proc.returncode != 0:
        print((proc.stderr or "")[-2500:], flush=True)
        raise SystemExit(f"stage {label} failed rc={proc.returncode}")
    out = pathlib.Path(args[args.index("--out") + 1])
    return json.loads(out.read_text(encoding="utf-8"))


def report_fields(a: dict) -> dict:
    cps = a.get("checkpoints", {})
    t = lambda n: cps.get(f"T{n}", {})  # noqa: E731
    eco = t(a["until"]).get("ecology", {})
    res = t(a["until"]).get("resource", {})
    econ = t(a["until"]).get("economy", {})
    soc = t(a["until"]).get("social", {})
    tri = t(a["until"]).get("tribulation", {})
    hist = t(a["until"]).get("history", {})
    integ = t(a["until"]).get("history_integrity", {})
    pop = t(a["until"]).get("population_by_species", {})
    return {
        "POP_T10": t(10).get("population_total"),
        "POP_T50": t(50).get("population_total"),
        "POP_T100": t(100).get("population_total"),
        "POP_T300": t(300).get("population_total"),
        "POP_BY_SPECIES_T300": pop,
        "POPULATION_ACCOUNTING_IDENTITY":
            "PASS" if t(a["until"]).get("accounting", {}).get("identity_ok")
            else "FAIL",
        "RESOURCE_SHORTAGE_YEARS_300": a.get("SHORTAGE_YEARS_TOTAL"),
        "RESOURCE_UNMET_DEMAND_CELLS": econ.get("unmet_cells"),
        "PERMANENT_ZERO_SUPPLY_CELLS": res.get("permanent_zero_supply_cells"),
        "HABITAT_T10": t(10).get("ecology", {}).get("habitat_quality"),
        "HABITAT_T50": t(50).get("ecology", {}).get("habitat_quality"),
        "HABITAT_T100": t(100).get("ecology", {}).get("habitat_quality"),
        "HABITAT_T300": eco.get("habitat_quality"),
        "ECOLOGY_STRESS_T300": eco.get("ecological_stress"),
        "SOCIAL_EVENTS_T300": a.get("social_event_total"),
        "SOCIAL_ROWS_T300": soc,
        "TRIBULATION_EPISODES_T300": tri.get("episodes_total"),
        "TRIBULATION_FIRST_EPISODE_TICK": tri.get("first_episode_tick"),
        "TRIBULATION_CASUALTIES_T300": tri.get("casualties_total"),
        "TRIBULATION_SCHEDULES": tri.get("schedules"),
        "HISTORY_EVENT_COUNT": hist.get("world_events"),
        "ENTITY_HISTORY_INDEX_ROWS": hist.get("entity_history_index_rows"),
        "HISTORY_CAUSAL_LINKS": hist.get("causal_history_links"),
        "HISTORY_ORPHAN_LINKS": integ.get("orphan_links"),
        "HISTORY_CAUSAL_CYCLES": integ.get("cycle_count"),
        "HISTORY_INVALID_REFS": integ.get("invalid_relations"),
        "HISTORY_CLEAN": integ.get("clean"),
        "WORLD_SEED_ACTIVATED_GENESIS_COUNT":
            a.get("WORLD_SEED_ACTIVATED_GENESIS_COUNT"),
        "TEST_PROFILE_USAGE_COUNT": a.get("TEST_PROFILE_USAGE_COUNT"),
        "FINAL_STATE_HASH": a.get("final_state_hash"),
        "FINAL_EVENT_STREAM_HASH": a.get("final_event_stream_hash"),
        "CAUSAL_HISTORY_HASH": t(a["until"]).get("causal_history_hash"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--until", type=int, default=300)
    ap.add_argument("--split", type=int, default=100)
    ap.add_argument("--world-id", default="SYNTH-DEMO-001")
    ap.add_argument("--timeout", type=int, default=21600)
    ap.add_argument("--out", default=str(
        ROOT / "reports" / "M6D2_FINAL_INTEGRATED_VERIFICATION.json"))
    args = ap.parse_args()

    root = pathlib.Path(tempfile.mkdtemp(prefix="m6d2_"))
    arts: dict[str, dict] = {}

    def stage(label: str, mode: str, workdir: pathlib.Path, hashseed: str | None,
              split: int) -> dict:
        out = root / f"{label}.json"
        return run_stage(label, ["--mode", mode, "--until", str(args.until),
                                 "--split", str(split),
                                 "--workdir", str(workdir),
                                 "--world-id", args.world_id,
                                 "--out", str(out)],
                         hashseed=hashseed, timeout=args.timeout)

    arts["RUN1"] = stage("RUN1_continuous", "continuous", root / "run1", None, 0)
    arts["RUN2"] = stage("RUN2_continuous", "continuous", root / "run2", None, 0)
    arts["RUN3a"] = stage("RUN3a_part1", "part1", root / "run3", "0", args.split)
    arts["RUN3b"] = stage("RUN3b_part2", "part2", root / "run3", "42", args.split)

    r1, r2, r3 = (report_fields(arts["RUN1"]), report_fields(arts["RUN2"]),
                  report_fields(arts["RUN3b"]))
    determinism = (r1["FINAL_STATE_HASH"] == r2["FINAL_STATE_HASH"]
                   and r1["FINAL_EVENT_STREAM_HASH"] == r2["FINAL_EVENT_STREAM_HASH"])
    restart = (r3["FINAL_STATE_HASH"] == r1["FINAL_STATE_HASH"]
               and r3["FINAL_EVENT_STREAM_HASH"] == r1["FINAL_EVENT_STREAM_HASH"]
               and r3["CAUSAL_HISTORY_HASH"] == r1["CAUSAL_HISTORY_HASH"])

    print("\n================ M6D.2 FINAL INTEGRATED VERIFICATION ================")
    for k, v in r1.items():
        print("%-36s %s" % (k, json.dumps(v, ensure_ascii=False)
                            if isinstance(v, (dict, list)) else v))
    print("\nRUN2 FINAL_STATE_HASH            ", r2["FINAL_STATE_HASH"])
    print("RUN2 FINAL_EVENT_STREAM_HASH     ", r2["FINAL_EVENT_STREAM_HASH"])
    print("RUN3 (0→%d hashseed=0, %d→%d hashseed=42)"
          % (args.split, args.split, args.until))
    print("RUN3 FINAL_STATE_HASH            ", r3["FINAL_STATE_HASH"])
    print("RUN3 FINAL_EVENT_STREAM_HASH     ", r3["FINAL_EVENT_STREAM_HASH"])
    print("RUN3 CAUSAL_HISTORY_HASH         ", r3["CAUSAL_HISTORY_HASH"])
    print("\nDETERMINISM                      ", "PASS" if determinism else "FAIL")
    print("RESTART_EQUIVALENCE              ", "PASS" if restart else "FAIL")
    print("PYTHONHASHSEED_INDEPENDENT_RESTART",
          "PASS" if restart and r3["FINAL_STATE_HASH"] == r1["FINAL_STATE_HASH"]
          else "FAIL")
    print("RUN1_HASHSEED", arts["RUN1"]["python_hashseed"],
          "RUN2_HASHSEED", arts["RUN2"]["python_hashseed"])
    print("ARTIFACT_DIR", root)

    payload = {"report": r1, "run2": r2, "run3": r3,
               "DETERMINISM": "PASS" if determinism else "FAIL",
               "RESTART_EQUIVALENCE": "PASS" if restart else "FAIL",
               "PYTHONHASHSEED_INDEPENDENT_RESTART":
                   "PASS" if restart else "FAIL",
               "run1_hashseed": arts["RUN1"]["python_hashseed"],
               "run2_hashseed": arts["RUN2"]["python_hashseed"],
               "run3_hashseeds": [arts["RUN3a"]["python_hashseed"],
                                  arts["RUN3b"]["python_hashseed"]],
               "until": args.until, "split": args.split,
               "world_id": args.world_id,
               "run1_elapsed_s": arts["RUN1"]["elapsed_s"],
               "run2_elapsed_s": arts["RUN2"]["elapsed_s"],
               "run3_elapsed_s": [arts["RUN3a"]["elapsed_s"],
                                  arts["RUN3b"]["elapsed_s"]],
               "event_type_census": arts["RUN1"].get("event_type_census"),
               "per_year_tail": arts["RUN1"].get("per_year", [])[-5:]}
    pathlib.Path(args.out).write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True,
                   default=str), encoding="utf-8", newline="\n")
    print("REPORT", args.out)
    return 0 if (determinism and restart) else 1


if __name__ == "__main__":
    raise SystemExit(main())

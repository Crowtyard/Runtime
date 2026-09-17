"""M6D.1 — post-fix hash-seed gate (PYTHONHASHSEED 0 / 1 / 42 / default + repeat).

Each label runs in a FRESH process. PASS requires every per-year state/event hash
AND every checkpoint population to be byte-identical across all labels.

Usage: python scripts/_m6d_hashseed_gate.py [--years 10] [--until 100] [--seed SYNTH-DEMO-001]
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROBE = ROOT / "scripts" / "_m6d_hashseed_probe.py"


def run_probe(label: str, hashseed: str | None, *, seed: str, until: int,
              years: int, out_dir: pathlib.Path) -> dict:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    if hashseed is None:
        env.pop("PYTHONHASHSEED", None)
    else:
        env["PYTHONHASHSEED"] = hashseed
    out = out_dir / f"{label}.json"
    cmd = [sys.executable, str(PROBE), "--seed", seed, "--until", str(until),
           "--per-year", str(years), "--label", label, "--out", str(out)]
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=3600)
    if proc.returncode != 0:
        print("PROBE_FAILED", label, proc.returncode)
        print((proc.stderr or "")[-3000:])
        raise SystemExit(2)
    data = json.loads(out.read_text(encoding="utf-8"))
    print("PROBE_OK", label, "pid", data["pid"],
          "pop", data["population_by_checkpoint"],
          "state", str(data["final_state_hash"])[:16],
          "events", str(data["final_event_stream_hash"])[:16], flush=True)
    return data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=10)
    ap.add_argument("--until", type=int, default=100)
    ap.add_argument("--seed", default="SYNTH-DEMO-001")
    args = ap.parse_args()
    out_dir = pathlib.Path(tempfile.mkdtemp(prefix="m6d_gate_"))
    labels: list[tuple[str, str | None]] = [
        ("H0", "0"), ("H0R", "0"), ("H1", "1"), ("H42", "42"),
        ("HDEFAULT", None)]
    runs = {label: run_probe(label, hs, seed=args.seed, until=args.until,
                             years=args.years, out_dir=out_dir)
            for label, hs in labels}

    ref_label, ref = "H0", runs["H0"]
    ok = True
    for label, data in runs.items():
        same_state = data["final_state_hash"] == ref["final_state_hash"]
        same_events = data["final_event_stream_hash"] == ref["final_event_stream_hash"]
        same_pop = data["population_by_checkpoint"] == ref["population_by_checkpoint"]
        same_year = all(
            data["per_year"][k]["state_hash"] == ref["per_year"][k]["state_hash"]
            for k in ref["per_year"])
        print("GATE %-9s state=%s events=%s pop=%s per_year=%s"
              % (label, same_state, same_events, same_pop, same_year))
        ok = ok and same_state and same_events and same_pop and same_year

    print("\nHASH_SEED_GATE =", "PASS" if ok else "FAIL")
    print("HASH_SEED_GATE_VALUES = 0/1/42/default (+0-repeat)")
    print("final_state_hash =", ref["final_state_hash"])
    print("final_event_stream_hash =", ref["final_event_stream_hash"])
    print("population_by_checkpoint =", json.dumps(ref["population_by_checkpoint"]))
    print("identity_ok =", ref["identity_ok"])
    print("ARTIFACT_DIR", out_dir)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

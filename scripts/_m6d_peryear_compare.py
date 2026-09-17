"""M6D.1 — per-year divergence localizer.

Spawns the demography probe in two FRESH processes (PYTHONHASHSEED=0 and 1, plus an
optional default-seed run), each recording year-by-year state/event hashes, then reports
the first divergent year and the per-year population deltas.

Usage: python scripts/_m6d_peryear_compare.py [--years 10] [--seed SYNTH-DEMO-001]
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


def run_probe(hashseed: str | None, years: int, seed: str, out_dir: pathlib.Path,
              trace: bool) -> dict:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    if hashseed is None:
        env.pop("PYTHONHASHSEED", None)
        label = "default"
    else:
        env["PYTHONHASHSEED"] = hashseed
        label = f"H{hashseed}"
    out = out_dir / f"{label}.json"
    cmd = [sys.executable, str(PROBE), "--seed", seed, "--until", str(years),
           "--per-year", str(years), "--label", label, "--out", str(out)]
    if trace:
        cmd.append("--trace")
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=1800)
    if proc.returncode != 0:
        print("PROBE_FAILED", label, proc.returncode)
        print((proc.stderr or "")[-2000:])
        raise SystemExit(2)
    data = json.loads(out.read_text(encoding="utf-8"))
    print("PROBE_OK", label, "pid", data["pid"])
    return data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=10)
    ap.add_argument("--seed", default="SYNTH-DEMO-001")
    ap.add_argument("--trace", action="store_true")
    ap.add_argument("--include-default", action="store_true")
    args = ap.parse_args()

    out_dir = pathlib.Path(tempfile.mkdtemp(prefix="m6d_peryear_"))
    runs = {
        "H0": run_probe("0", args.years, args.seed, out_dir, args.trace),
        "H1": run_probe("1", args.years, args.seed, out_dir, args.trace),
    }
    if args.include_default:
        runs["DEFAULT"] = run_probe(None, args.years, args.seed, out_dir, args.trace)
    if args.trace:
        runs["H0B"] = run_probe("0", args.years, args.seed, out_dir, args.trace)

    print("\nYEAR-BY-YEAR (state_hash | population)")
    first_divergent_year = None
    for year in range(1, args.years + 1):
        key = f"Y{year}"
        cells = []
        for label, data in runs.items():
            entry = data["per_year"].get(key, {})
            cells.append("%s=%s|%s" % (label, str(entry.get("state_hash"))[:12],
                                       entry.get("population")))
        h0 = runs["H0"]["per_year"][key]["state_hash"]
        h1 = runs["H1"]["per_year"][key]["state_hash"]
        flag = ""
        if h0 != h1 and first_divergent_year is None:
            first_divergent_year = year
            flag = "  <== FIRST_DIVERGENT_YEAR"
        print("%-5s %s%s" % (key, "  ".join(cells), flag))

    print("\nH0_VS_H1_SAME_YEARS =",
          [y for y in range(1, args.years + 1)
           if runs["H0"]["per_year"][f"Y{y}"]["state_hash"]
           == runs["H1"]["per_year"][f"Y{y}"]["state_hash"]])
    print("FIRST_DIVERGENT_YEAR =", first_divergent_year)
    if "H0B" in runs:
        same = all(runs["H0"]["per_year"][f"Y{y}"]["state_hash"]
                   == runs["H0B"]["per_year"][f"Y{y}"]["state_hash"]
                   for y in range(1, args.years + 1))
        print("H0_REPEAT_WITHIN_SEED_EXACT =", same)
    if "trace" in runs["H0"]:
        print("TRACE_FILES", runs["H0"].get("trace_path"), runs["H1"].get("trace_path"))
    print("ARTIFACT_DIR", out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

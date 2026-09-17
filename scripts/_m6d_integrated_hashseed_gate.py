"""M6D.1 — integrated (full pipeline) hash-seed gate.

Runs the REAL-engine TIER-1 smoke twice in fresh processes with different
PYTHONHASHSEED values and compares every checkpoint state hash plus the complete
per-(settlement × resource) ledger and ecology pressure/quality payload.

Coverage: TIME→DEMOGRAPHY→RESOURCE→ECONOMY→ECOLOGY→SOCIAL→TRIBULATION→HISTORY.

Usage: python scripts/_m6d_integrated_hashseed_gate.py [--until 100] [--seeds 0,1]
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
SMOKE = ROOT / "scripts" / "_m6c1d_res_smoke.py"


def run(label: str, hashseed: str, until: int, out_dir: pathlib.Path) -> dict:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONHASHSEED"] = hashseed
    out = out_dir / f"integrated_{label}.json"
    cmd = [sys.executable, str(SMOKE), "--until", str(until), "--out", str(out)]
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=7200)
    if proc.returncode != 0:
        print("SMOKE_FAILED", label, proc.returncode)
        print((proc.stderr or "")[-3000:])
        raise SystemExit(2)
    print("SMOKE_OK", label, "pid?")
    data = json.loads(out.read_text(encoding="utf-8"))
    for cp, payload in sorted(data["checkpoints"].items()):
        print(" ", label, cp, "state_hash", str(payload.get("state_hash"))[:20],
              "quality", payload["ecology"].get("habitat_quality"))
    return data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--until", type=int, default=100)
    ap.add_argument("--seeds", default="0,1")
    args = ap.parse_args()
    out_dir = pathlib.Path(tempfile.mkdtemp(prefix="m6d_integrated_"))
    seeds = [s.strip() for s in args.seeds.split(",") if s.strip()]
    runs = {s: run(f"H{s}", s, args.until, out_dir) for s in seeds}

    ref_seed = seeds[0]
    ref = runs[ref_seed]
    ok = True
    print("\nCHECKPOINT COMPARISON (ref = H%s)" % ref_seed)
    for cp in sorted(ref["checkpoints"], key=lambda c: int(c[1:])):
        r = ref["checkpoints"][cp]
        for seed in seeds[1:]:
            other = runs[seed]["checkpoints"][cp]
            same_hash = r.get("state_hash") == other.get("state_hash")
            same_engine = r.get("engine") == other.get("engine")
            same_eco = r.get("ecology") == other.get("ecology")
            same_tick = r.get("final_blessed_tick") == other.get("final_blessed_tick")
            print("  %-6s H%s vs H%s  state_hash=%s engine=%s ecology=%s tick=%s"
                  % (cp, ref_seed, seed, same_hash, same_engine, same_eco,
                     same_tick))
            ok = ok and same_hash and same_engine and same_eco and same_tick

    print("\nINTEGRATED_HASH_SEED_GATE =", "PASS" if ok else "FAIL")
    print("INTEGRATED_HASH_SEED_VALUES =", ",".join(seeds))
    print("INTEGRATED_UNTIL =", args.until)
    print("final_state_hash =", ref["checkpoints"][f"T{args.until}"].get("state_hash"))
    print("ARTIFACT_DIR", out_dir)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

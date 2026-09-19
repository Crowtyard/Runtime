"""M6C.2 §6/§7 — cross-process bootstrap determinism (tick-0 materialization only).

Spawns three fresh processes (PYTHONHASHSEED 0 / 42 / default), each materializing into
its own fresh temp SQLite, then compares the canonical bootstrap hash AND the per-table
canonical digests.

Usage: python scripts/_m6c2_bootstrap_determinism.py [--out reports/....json]
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
WORKER = ROOT / "scripts" / "_m6c2_materialize_once.py"
RUNS = [("A", "0"), ("B", "42"), ("C", None)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/M6C2_BOOTSTRAP_DETERMINISM.json")
    args = ap.parse_args()
    out_dir = pathlib.Path(tempfile.mkdtemp(prefix="m6c2_det_runs_"))
    runs = {}
    for label, seed in RUNS:
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        if seed is None:
            env.pop("PYTHONHASHSEED", None)
        else:
            env["PYTHONHASHSEED"] = seed
        out = out_dir / ("run_%s.json" % label)
        proc = subprocess.run(
            [sys.executable, str(WORKER), "--label", label, "--out", str(out)],
            cwd=str(ROOT), env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=1800)
        if proc.returncode != 0:
            print("WORKER_FAILED", label, proc.returncode)
            print((proc.stderr or "")[-1500:])
            raise SystemExit(2)
        print((proc.stdout or "").strip()[-200:])
        runs[label] = json.loads(out.read_text(encoding="utf-8"))

    hashes = {label: runs[label]["BOOTSTRAP_CANONICAL_HASH"] for label in runs}
    same_hash = len(set(hashes.values())) == 1
    tables = sorted(runs["A"]["per_table_digest"])
    row_diff = 0
    table_diff = {}
    for table in tables:
        digests = {label: runs[label]["per_table_digest"].get(table)
                   for label in runs}
        if len(set(digests.values())) != 1:
            row_diff += 1
            table_diff[table] = digests
    doc = {
        "packet": "M6C2_BOOTSTRAP_DETERMINISM",
        "runs": {label: {"python_hashseed": runs[label]["python_hashseed"],
                         "pid": runs[label]["pid"],
                         "BOOTSTRAP_CANONICAL_HASH":
                             runs[label]["BOOTSTRAP_CANONICAL_HASH"],
                         "row_counts": runs[label]["row_counts"],
                         "cohort_rule": runs[label]["cohort_rule"]}
                 for label in runs},
        "BOOTSTRAP_CANONICAL_HASH_PYHASH0": hashes.get("A"),
        "BOOTSTRAP_CANONICAL_HASH_PYHASH42": hashes.get("B"),
        "BOOTSTRAP_CANONICAL_HASH_DEFAULT": hashes.get("C"),
        "BOOTSTRAP_DETERMINISM": "PASS" if same_hash else "FAIL",
        "BOOTSTRAP_ROW_DIFF_COUNT": row_diff,
        "per_table_diff": table_diff,
        "tables_compared": len(tables),
        "projection_version": runs["A"]["projection_version"],
        "simulation_started": False,
    }
    pathlib.Path(ROOT / args.out).write_text(
        json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8", newline="\n")
    for label in runs:
        print("  RUN-%s hashseed=%-8s hash=%s" % (
            label, runs[label]["python_hashseed"],
            runs[label]["BOOTSTRAP_CANONICAL_HASH"][:24]))
    print("BOOTSTRAP_DETERMINISM =", doc["BOOTSTRAP_DETERMINISM"])
    print("BOOTSTRAP_ROW_DIFF_COUNT =", row_diff, "of", len(tables), "tables")
    print("ARTIFACT", args.out)
    return 0 if (same_hash and row_diff == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())

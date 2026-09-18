"""M6D.3 §6 — two independent candidate-capture passes + equality check.

Runs the three affected M3 artifact tests twice with the read-only candidate
observer (diagnostic capture only; nothing is written into tests/baselines), then
compares the captured candidate artifacts byte-for-byte:

    NEW_BASELINE_RUN1 == NEW_BASELINE_RUN2

Usage: python scripts/_m6d3_candidate_determinism.py [--out reports/....json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
NODES = [
    "tests/test_m3a_tribulation.py::test_m3a_baseline_300y_artifact",
    "tests/test_m3b_history.py::test_hb43_300y_baseline_artifacts",
    "tests/test_m3b_metric_audit.py::test_ma28_metric_audit_baseline_artifacts",
]


def capture(label: str) -> dict:
    out_dir = pathlib.Path(tempfile.mkdtemp(prefix="m6d3_cand_%s_" % label))
    env = dict(os.environ)
    env["PYTHONPATH"] = "scripts"
    env["PYTHONIOENCODING"] = "utf-8"
    env["M6D3_CANDIDATE_OUT"] = str(out_dir)
    env["M6D3_CANDIDATE_CONTINUE"] = "1"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "_m6d3_candidate_observer",
         "-q"] + NODES,
        cwd=str(ROOT), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=7200)
    files = {}
    for path in sorted(out_dir.glob("*.dumped.json")):
        files[path.name.replace(".dumped.json", "")] = {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
            "path": str(path),
        }
    print("[%s] rc=%d captured=%d" % (label, proc.returncode, len(files)),
          flush=True)
    tail = (proc.stdout or "").strip().splitlines()[-3:]
    for line in tail:
        print("    ", line[:150], flush=True)
    return {"dir": str(out_dir), "files": files}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out",
                    default="reports/M6D3_BASELINE_REFREEZE_CANDIDATES.json")
    args = ap.parse_args()
    run1 = capture("run1")
    run2 = capture("run2")

    names = sorted(set(run1["files"]) | set(run2["files"]))
    compare = {}
    identical = True
    for name in names:
        a = run1["files"].get(name)
        b = run2["files"].get(name)
        same = bool(a and b and a["sha256"] == b["sha256"])
        identical = identical and same
        compare[name] = {"run1_sha256": a and a["sha256"],
                         "run2_sha256": b and b["sha256"], "equal": same}
    doc = {
        "packet": "M6D3_BASELINE_REFREEZE_CANDIDATES",
        "capture_mode": "READ_ONLY_OBSERVER (nothing written into tests/baselines)",
        "nodes": NODES,
        "run1": run1,
        "run2": run2,
        "comparison": compare,
        "NEW_BASELINE_RUN1_EQ_RUN2": "PASS" if identical else "FAIL",
        "candidate_file_count": len(names),
    }
    pathlib.Path(args.out).write_text(
        json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8", newline="\n")
    print("NEW_BASELINE_RUN1_EQ_RUN2 =", doc["NEW_BASELINE_RUN1_EQ_RUN2"],
          "(%d files)" % len(names))
    for name in names:
        row = compare[name]
        print("  %-46s %s" % (name, "EQUAL" if row["equal"] else "DIFF"))
    print("ARTIFACT", args.out)
    # keep run1 candidates for the provenance manifest
    keep = ROOT / "reports" / "_m6d3_candidates_keep"
    if keep.exists():
        shutil.rmtree(keep)
    shutil.copytree(run1["dir"], keep)
    print("CANDIDATES_KEPT", keep)
    return 0 if identical else 1


if __name__ == "__main__":
    raise SystemExit(main())

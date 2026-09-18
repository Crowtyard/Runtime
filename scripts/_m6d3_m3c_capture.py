"""M6D.3 §1/§2/§6 — M3-integrated candidate inventory capture (repo-external, READ-ONLY
w.r.t. tests/baselines).

Runs the official candidate-generation mechanism of tests/test_m3_integrated_long.py
(M3C_CANDIDATE_DIR, repo-external per that module's design) for the three artifact
nodes, concurrently (lt1 seeds and lt7 endurance in separate processes), for one or
two independent passes:

  pass 1 -> <out>/run1   (RUN1 evidence)
  pass 2 -> <out>/run2   (RUN2 evidence, separate processes)
  then lt13 summary per pass (uses the pass's own candidate dir)

Nothing is written into tests/baselines: capture mode never enables
BLR_UPDATE_GOLDEN_BASELINES.

Usage: python scripts/_m6d3_m3c_capture.py --out DIR [--passes 1|2] [--label run1]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
LT1 = "tests/test_m3_integrated_long.py::test_lt1_1000y_five_seeds"
LT7 = "tests/test_m3_integrated_long.py::test_lt7_5000y_endurance"
LT13 = "tests/test_m3_integrated_long.py::test_lt13_summary_artifact"


def launch(node: str, cand_dir: pathlib.Path, xml: pathlib.Path,
           log: pathlib.Path) -> subprocess.Popen:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["M3C_CANDIDATE_DIR"] = str(cand_dir)
    env.pop("BLR_UPDATE_GOLDEN_BASELINES", None)   # 绝不在 capture 模式写 golden
    fh = log.open("w", encoding="utf-8")
    return subprocess.Popen(
        [sys.executable, "-m", "pytest", "-q", "--junitxml=" + str(xml), node],
        cwd=str(ROOT), env=env, stdout=fh, stderr=subprocess.STDOUT)


def run_one(node: str, cand_dir: pathlib.Path, tag: str) -> int:
    xml = cand_dir.parent / ("%s.xml" % tag)
    log = cand_dir.parent / ("%s.log" % tag)
    proc = launch(node, cand_dir, xml, log)
    return proc.wait()


def capture(out: pathlib.Path, label: str) -> dict:
    cand = out / label
    cand.mkdir(parents=True, exist_ok=True)
    started = time.time()
    # lt1（5 seeds）与 lt7（5000y）并发独立进程
    p1 = launch(LT1, cand, out / ("%s_lt1.xml" % label), out / ("%s_lt1.log" % label))
    p7 = launch(LT7, cand, out / ("%s_lt7.xml" % label), out / ("%s_lt7.log" % label))
    rc1 = p1.wait()
    rc7 = p7.wait()
    rc13 = run_one(LT13, cand, "%s_lt13" % label)
    files = {}
    for path in sorted(cand.rglob("*.json")):
        files[str(path.relative_to(cand)).replace("\\", "/")] = {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size_bytes": path.stat().st_size,
        }
    print("[%s] lt1 rc=%d lt7 rc=%d lt13 rc=%d files=%d (%.0fs)"
          % (label, rc1, rc7, rc13, len(files), time.time() - started), flush=True)
    return {"label": label, "dir": str(cand), "lt1_rc": rc1, "lt7_rc": rc7,
            "lt13_rc": rc13, "files": files,
            "elapsed_s": round(time.time() - started, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--passes", type=int, default=2)
    ap.add_argument("--report", default="")
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    result = {"packet": "M6D3_M3C_CANDIDATE_CAPTURE", "out": str(out),
              "passes": []}
    for index in range(1, args.passes + 1):
        label = "run%d" % index
        result["passes"].append(capture(out, label))
    if args.report:
        pathlib.Path(args.report).write_text(
            json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8", newline="\n")
    print("CAPTURE_DONE", json.dumps(
        [{"label": p["label"], "files": len(p["files"]),
          "elapsed_s": p["elapsed_s"]} for p in result["passes"]]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

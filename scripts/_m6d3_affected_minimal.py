"""M6D.3 §14 — minimal affected regression after the M3-integrated refreeze.

Runs, with JUnit-exact counting:
  G1 scheduler determinism reader  (m3_integrated_1000y_v1/seed_001.json)
  G2 scheduler endurance reader    (m3_integrated_5000y_seed001_v1.json)
  G3 M5Q46 query-service guard
  G4 M3-integrated artifact nodes  (normal-mode comparison against refrozen goldens)

Usage: python scripts/_m6d3_affected_minimal.py [--out reports/....json] [--only G1]
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
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]

GROUPS = {
    "G1": ["tests/test_scheduler_determinism.py::"
           "test_scheduler_1000y_reproduces_frozen_seed001"],
    "G2": ["tests/test_scheduler_endurance.py::"
           "test_scheduler_5000y_endurance_reproduces_frozen"],
    "G3": ["tests/test_query_service.py::test_m5q46_m3_baselines_unchanged"],
    "G4": ["tests/test_m3_integrated_long.py::test_lt1_1000y_five_seeds",
           "tests/test_m3_integrated_long.py::test_lt7_5000y_endurance",
           "tests/test_m3_integrated_long.py::test_lt13_summary_artifact"],
}


def parse_junit(path: pathlib.Path) -> dict:
    if not path.exists():
        return {"collected": 0, "passed": 0, "failed": 0, "errors": 0,
                "skipped": 0, "failure_ids": [], "error_ids": []}
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root)
    out = {"collected": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0,
           "failure_ids": [], "error_ids": []}
    for suite in suites:
        for case in suite.iter("testcase"):
            out["collected"] += 1
            cid = "%s::%s" % (case.get("classname", ""), case.get("name", ""))
            if case.find("failure") is not None:
                out["failed"] += 1
                out["failure_ids"].append(cid)
            elif case.find("error") is not None:
                out["errors"] += 1
                out["error_ids"].append(cid)
            elif case.find("skipped") is not None:
                out["skipped"] += 1
            else:
                out["passed"] += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/M6D3_AFFECTED_MINIMAL_REGRESSION.json")
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    workdir = pathlib.Path(tempfile.mkdtemp(prefix="m6d3_affected_"))
    doc = {"packet": "M6D3_AFFECTED_MINIMAL_REGRESSION", "workdir": str(workdir),
           "groups": {}}
    ok = True
    for label, nodes in GROUPS.items():
        if args.only and label != args.only:
            continue
        xml = workdir / ("%s.xml" % label)
        log = workdir / ("%s.log" % label)
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        env.pop("M3C_CANDIDATE_DIR", None)      # normal mode: compare committed goldens
        env.pop("BLR_UPDATE_GOLDEN_BASELINES", None)
        started = time.time()
        with log.open("w", encoding="utf-8") as fh:
            proc = subprocess.run([sys.executable, "-m", "pytest", "-q",
                                   "--junitxml=" + str(xml)] + nodes,
                                  cwd=str(ROOT), env=env, stdout=fh,
                                  stderr=subprocess.STDOUT, timeout=21600)
        stats = parse_junit(xml)
        stats.update({"label": label, "rc": proc.returncode, "nodes": nodes,
                      "elapsed_s": round(time.time() - started, 1),
                      "log": str(log), "junit": str(xml)})
        doc["groups"][label] = stats
        ok = ok and stats["failed"] == 0 and stats["errors"] == 0
        print("[%s] rc=%d collected=%d passed=%d failed=%d errors=%d skipped=%d "
              "(%.0fs)" % (label, proc.returncode, stats["collected"],
                           stats["passed"], stats["failed"], stats["errors"],
                           stats["skipped"], stats["elapsed_s"]), flush=True)
        for cid in stats["failure_ids"][:10]:
            print("    FAILED", cid, flush=True)
    doc["AFFECTED_TARGETED_REGRESSION"] = "PASS" if ok else "FAIL"
    pathlib.Path(ROOT / args.out).write_text(
        json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8", newline="\n")
    print("AFFECTED_TARGETED_REGRESSION =", doc["AFFECTED_TARGETED_REGRESSION"])
    print("ARTIFACT", args.out)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

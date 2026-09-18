"""M6D.3 §J — final ordered targeted regression (after the query fingerprint fix).

Order (owner ruling J):
  1 query fingerprint regression
  2 B2 query-service tests
  3 scheduler determinism readers
  4 scheduler endurance reader
  5 M3 integrated baseline readers
  6 M3a/M3b
  7 history
  8 M6/M6D3
  9 wider targeted

Also emits the §I protective check result:
  M3_INTEGRATED_BASELINE_ARTIFACT_DIFF_AFTER_QUERY_FIX (must be 0).

Usage: python scripts/_m6d3_final_targeted.py [--out reports/....json] [--only N]
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

STEPS = [
    ("1_query_fingerprint", ["tests/test_query_fingerprint.py"]),
    ("2_b2_query_service", ["tests/test_query_service.py"]),
    ("3_scheduler_determinism", ["tests/test_scheduler_determinism.py"]),
    ("4_scheduler_endurance", ["tests/test_scheduler_endurance.py"]),
    ("5_m3_integrated_readers", ["tests/test_m3_integrated_long.py"]),
    ("6_m3a_m3b", ["tests/test_m3a_tribulation.py", "tests/test_m3b_history.py",
                   "tests/test_m3b_metric_audit.py"]),
    ("7_history_integrity", ["tests/test_m3b_metric_audit.py",
                             "tests/test_m3b_history.py",
                             "tests/test_m3_preflight.py"]),
    ("8_m6_m6d3", ["tests/test_m6d3_tribulation_effect_application.py",
                   "tests/test_golden_update_mode.py"] + [
                       "tests/" + p.name for p in sorted(
                           (ROOT / "tests").glob("test_m6*.py"))]),
    ("9_wider_targeted", []),   # filled by the wider driver below
]

WIDER = [
    "tests/test_m2a_population.py", "tests/test_m2b_resource_economy.py",
    "tests/test_m2c_ecology.py", "tests/test_m2d_social.py",
    "tests/test_m2_review.py", "tests/test_m3_preflight.py",
    "tests/test_scheduler_determinism.py",
    "tests/test_scheduler_crash_recovery.py", "tests/test_writer_recovery.py",
    "tests/test_preflight_pf.py", "tests/test_hardening_hp.py",
]


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


def gather_m6() -> list[str]:
    out = []
    for path in sorted((ROOT / "tests").glob("test_m6*.py")):
        out.append("tests/" + path.name)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/M6D3_FINAL_TARGETED_REGRESSION.json")
    ap.add_argument("--only", default="")
    ap.add_argument("--steps", default="",
                    help="comma-separated step prefixes to run, e.g. 1,2,6,7,8,9 "
                         "(default: all)")
    args = ap.parse_args()
    workdir = pathlib.Path(tempfile.mkdtemp(prefix="m6d3_final_"))
    steps = []
    for label, nodes in STEPS:
        if label == "9_wider_targeted":
            files = [f for f in (WIDER + gather_m6()) if (ROOT / f).exists()]
            nodes = sorted(set(files))
        if label == "8_m6_m6d3":
            nodes = sorted(set(nodes + gather_m6()))
        steps.append((label, nodes))

    doc = {"packet": "M6D3_FINAL_TARGETED_REGRESSION", "workdir": str(workdir),
           "steps": {}}
    wanted = [s.strip() for s in args.steps.split(",") if s.strip()]
    ok = True
    for label, nodes in steps:
        if args.only and not label.startswith(args.only):
            continue
        if wanted and not any(label.startswith(w) for w in wanted):
            print("[%s] SKIPPED_BY_REQUEST" % label, flush=True)
            doc["steps"][label] = {"status": "SKIPPED_BY_REQUEST"}
            continue
        xml = workdir / ("%s.xml" % label)
        log = workdir / ("%s.log" % label)
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        env.pop("M3C_CANDIDATE_DIR", None)
        env.pop("BLR_UPDATE_GOLDEN_BASELINES", None)
        started = time.time()
        with log.open("w", encoding="utf-8") as fh:
            proc = subprocess.run([sys.executable, "-m", "pytest", "-q",
                                   "--junitxml=" + str(xml)] + nodes,
                                  cwd=str(ROOT), env=env, stdout=fh,
                                  stderr=subprocess.STDOUT, timeout=28800)
        stats = parse_junit(xml)
        stats.update({"rc": proc.returncode, "nodes": nodes,
                      "elapsed_s": round(time.time() - started, 1),
                      "log": str(log), "junit": str(xml)})
        doc["steps"][label] = stats
        ok = ok and stats["failed"] == 0 and stats["errors"] == 0
        print("[%s] rc=%d collected=%d passed=%d failed=%d errors=%d skipped=%d "
              "(%.0fs)" % (label, proc.returncode, stats["collected"],
                           stats["passed"], stats["failed"], stats["errors"],
                           stats["skipped"], stats["elapsed_s"]), flush=True)
        for cid in stats["failure_ids"][:10]:
            print("    FAILED", cid, flush=True)

    # §I 保护性检查
    status = subprocess.run(["git", "-C", str(ROOT), "status", "--short", "--",
                             "tests/baselines"], capture_output=True, text=True,
                            encoding="utf-8").stdout.strip()
    diff = subprocess.run(["git", "-C", str(ROOT), "diff", "--name-only", "--",
                           "tests/baselines"], capture_output=True, text=True,
                          encoding="utf-8").stdout.strip()
    doc["M3_INTEGRATED_BASELINE_ARTIFACT_DIFF_AFTER_QUERY_FIX"] = (
        len([l for l in (status + "\n" + diff).splitlines() if l.strip()]))
    doc["TARGETED_REGRESSION"] = "PASS" if ok else "FAIL"
    pathlib.Path(ROOT / args.out).write_text(
        json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8", newline="\n")
    print("M3_INTEGRATED_BASELINE_ARTIFACT_DIFF_AFTER_QUERY_FIX =",
          doc["M3_INTEGRATED_BASELINE_ARTIFACT_DIFF_AFTER_QUERY_FIX"])
    print("TARGETED_REGRESSION =", doc["TARGETED_REGRESSION"])
    print("ARTIFACT", args.out)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

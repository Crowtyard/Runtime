"""M6D.3 §13 — canonical fast regression, chunked + persistent.

Runs the canonical fast suite (`pytest tests -q --ignore=tests/test_m3_integrated_long.py`)
in chunks, writing a JUnit XML + log per chunk so partial progress survives, then
aggregates exact counts from the XML (this host swallows pytest's final summary line,
so the XML is the authoritative source).

Chunks are ordered so the known-heavy files (scheduler 1000y/5000y, m2_review_long,
m3a/m3b 300y) run in their own chunks and can be resumed individually.

Usage:
  python scripts/_m6d3_fast_regression_chunked.py [--out reports/....json]
                                                  [--only-chunk N] [--resume]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
IGNORE = ["tests/test_m3_integrated_long.py"]

HEAVY = [
    ["tests/test_scheduler_budget_equivalence.py",
     "tests/test_scheduler_endurance.py",
     "tests/test_scheduler_determinism.py",
     "tests/test_scheduler_crash_recovery.py",
     "tests/test_scheduler_lifecycle.py",
     "tests/test_scheduler_dormant_gate.py"],
    ["tests/test_m2_review_long.py"],
    ["tests/test_m3a_tribulation.py", "tests/test_m3b_history.py",
     "tests/test_m3b_metric_audit.py"],
]


def discover() -> list[str]:
    files = sorted(
        str(pathlib.Path(p).relative_to(ROOT)).replace("\\", "/")
        for p in glob.glob(str(ROOT / "tests" / "test_*.py"))
        + glob.glob(str(ROOT / "tests" / "zz_*.py")))
    return [f for f in files if f not in IGNORE]


def build_chunks() -> list[list[str]]:
    files = discover()
    heavy_flat = {f for chunk in HEAVY for f in chunk}
    rest = [f for f in files if f not in heavy_flat]
    chunks = [list(c) for c in HEAVY]
    target = max(1, len(rest) // 4)
    for i in range(0, len(rest), target):
        chunks.append(rest[i:i + target])
    return [c for c in chunks if c]


def parse_junit(path: pathlib.Path) -> dict:
    if not path.exists():
        return {"collected": 0, "passed": 0, "failed": 0, "errors": 0,
                "skipped": 0, "failure_ids": [], "error_ids": [],
                "skipped_ids": []}
    tree = ET.parse(path)
    suites = [tree.getroot()] if tree.getroot().tag == "testsuite" \
        else list(tree.getroot())
    out = {"collected": 0, "passed": 0, "failed": 0, "errors": 0,
           "skipped": 0, "failure_ids": [], "error_ids": [], "skipped_ids": []}
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
                out["skipped_ids"].append(cid)
            else:
                out["passed"] += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/M6D3_FAST_REGRESSION.json")
    ap.add_argument("--workdir", default="")
    ap.add_argument("--only-chunk", type=int, default=0)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()
    workdir = pathlib.Path(args.workdir or tempfile.mkdtemp(
        prefix="m6d3_fast_"))
    workdir.mkdir(parents=True, exist_ok=True)
    chunks = build_chunks()
    print("CHUNKS=%d WORKDIR=%s" % (len(chunks), workdir), flush=True)

    totals = {"collected": 0, "passed": 0, "failed": 0, "errors": 0,
              "skipped": 0, "failure_ids": [], "error_ids": [], "skipped_ids": []}
    chunk_records = []
    for index, files in enumerate(chunks, 1):
        if args.only_chunk and index != args.only_chunk:
            continue
        xml = workdir / ("chunk%02d.xml" % index)
        log = workdir / ("chunk%02d.log" % index)
        if args.resume and xml.exists():
            print("chunk %d: reusing existing JUnit" % index, flush=True)
        else:
            started = time.time()
            env = dict(os.environ)
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUNBUFFERED"] = "1"
            with log.open("w", encoding="utf-8") as fh:
                proc = subprocess.run(
                    [sys.executable, "-m", "pytest", "-q",
                     "--junitxml=" + str(xml)] + files,
                    cwd=str(ROOT), env=env, stdout=fh,
                    stderr=subprocess.STDOUT, timeout=21600)
            print("chunk %d: rc=%d %.0fs (%d files)"
                  % (index, proc.returncode, time.time() - started, len(files)),
                  flush=True)
        stats = parse_junit(xml)
        stats["index"] = index
        stats["files"] = files
        stats["log"] = str(log)
        stats["junit"] = str(xml)
        chunk_records.append(stats)
        for key in ("collected", "passed", "failed", "errors", "skipped"):
            totals[key] += stats[key]
        totals["failure_ids"].extend(stats["failure_ids"])
        totals["error_ids"].extend(stats["error_ids"])
        totals["skipped_ids"].extend(stats["skipped_ids"])
        print("   collected=%d passed=%d failed=%d errors=%d skipped=%d"
              % (stats["collected"], stats["passed"], stats["failed"],
                 stats["errors"], stats["skipped"]), flush=True)

    doc = {
        "packet": "M6D3_FAST_REGRESSION",
        "command": "pytest tests -q --ignore=tests/test_m3_integrated_long.py "
                   "(chunked, JUnit-based counting)",
        "workdir": str(workdir),
        "chunks": chunk_records,
        "FAST_COLLECTED": totals["collected"],
        "FAST_PASSED": totals["passed"],
        "FAST_FAILED": totals["failed"],
        "FAST_ERRORS": totals["errors"],
        "FAST_SKIPS": totals["skipped"],
        "FAST_FAILURE_IDS": totals["failure_ids"][:50],
        "FAST_ERROR_IDS": totals["error_ids"][:50],
        "FAST_SKIPPED_SAMPLE": totals["skipped_ids"][:60],
        "FAST_REGRESSION": "PASS" if (totals["failed"] == 0
                                      and totals["errors"] == 0) else "FAIL",
    }
    pathlib.Path(args.out).write_text(
        json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8", newline="\n")
    print("\nFAST_COLLECTED=%d FAST_PASSED=%d FAST_FAILED=%d FAST_ERRORS=%d "
          "FAST_SKIPS=%d" % (totals["collected"], totals["passed"],
                             totals["failed"], totals["errors"],
                             totals["skipped"]))
    print("FAST_REGRESSION =", doc["FAST_REGRESSION"])
    return 0 if doc["FAST_REGRESSION"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

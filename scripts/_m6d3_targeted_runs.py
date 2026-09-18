"""M6D.3 §10/§11 — targeted regression runs (affected set + wider set), JUnit-counted.

Owner §10: the previously-run affected set (TARGETED_COLLECTED = 146).
Owner §11: M2 family + M3 engine set + M3a tribulation + M3b history + metric audit +
history integrity + determinism + restart + M6 targeted + M6D3 effect identity.

Counts come from the JUnit XML (authoritative on this host), never from a pasted
historical number.

Usage: python scripts/_m6d3_targeted_runs.py [--out reports/....json] [--only affected|wider]
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

AFFECTED = [
    "tests/test_m3a_tribulation.py",
    "tests/test_m3b_history.py",
    "tests/test_m3b_metric_audit.py",
    "tests/test_m6d3_tribulation_effect_application.py",
    "tests/test_golden_update_mode.py",
]

WIDER_EXTRA = [
    "tests/test_m2a_population.py",
    "tests/test_m2b_resource_economy.py",
    "tests/test_m2c_ecology.py",
    "tests/test_m2d_social.py",
    "tests/test_m2_review.py",
    "tests/test_m3_preflight.py",
    "tests/test_scheduler_determinism.py",
    "tests/test_scheduler_crash_recovery.py",
    "tests/test_writer_recovery.py",
    "tests/test_preflight_pf.py",
    "tests/test_hardening_hp.py",
]


def gather_m6() -> list[str]:
    out = []
    for pat in ("test_m6*.py",):
        for path in sorted((ROOT / "tests").glob(pat)):
            rel = "tests/" + path.name
            if rel not in AFFECTED:
                out.append(rel)
    return out


def parse_junit(path: pathlib.Path) -> dict:
    if not path.exists():
        return {"collected": 0, "passed": 0, "failed": 0, "errors": 0,
                "skipped": 0, "failure_ids": [], "error_ids": [],
                "skipped_ids": []}
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root)
    out = {"collected": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0,
           "failure_ids": [], "error_ids": [], "skipped_ids": []}
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


def run_set(label: str, files: list[str], workdir: pathlib.Path) -> dict:
    xml = workdir / ("%s.xml" % label)
    log = workdir / ("%s.log" % label)
    started = time.time()
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    with log.open("w", encoding="utf-8") as fh:
        proc = subprocess.run([sys.executable, "-m", "pytest", "-q",
                               "--junitxml=" + str(xml)] + files,
                              cwd=str(ROOT), env=env, stdout=fh,
                              stderr=subprocess.STDOUT, timeout=21600)
    stats = parse_junit(xml)
    stats["label"] = label
    stats["rc"] = proc.returncode
    stats["elapsed_s"] = round(time.time() - started, 1)
    stats["files"] = files
    stats["log"] = str(log)
    stats["junit"] = str(xml)
    print("[%s] rc=%d collected=%d passed=%d failed=%d errors=%d skipped=%d "
          "(%.0fs)" % (label, proc.returncode, stats["collected"],
                       stats["passed"], stats["failed"], stats["errors"],
                       stats["skipped"], stats["elapsed_s"]), flush=True)
    for cid in stats["failure_ids"][:20]:
        print("    FAILED", cid, flush=True)
    for cid in stats["error_ids"][:20]:
        print("    ERROR ", cid, flush=True)
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/M6D3_TARGETED_REGRESSION.json")
    ap.add_argument("--only", choices=("affected", "wider"), default="")
    args = ap.parse_args()
    workdir = pathlib.Path(tempfile.mkdtemp(prefix="m6d3_targeted_"))
    result = {"packet": "M6D3_TARGETED_REGRESSION", "workdir": str(workdir)}
    if args.only in ("", "affected"):
        result["affected"] = run_set("affected", AFFECTED, workdir)
    if args.only in ("", "wider"):
        files = AFFECTED + WIDER_EXTRA + gather_m6()
        seen, ordered = set(), []
        for f in files:
            if f not in seen and (ROOT / f).exists():
                seen.add(f)
                ordered.append(f)
        result["wider"] = run_set("wider", ordered, workdir)
    ok = True
    for key in ("affected", "wider"):
        if key in result:
            ok = ok and result[key]["failed"] == 0 and result[key]["errors"] == 0
    result["TARGETED_REGRESSION"] = "PASS" if ok else "FAIL"
    pathlib.Path(args.out).write_text(
        json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8", newline="\n")
    print("TARGETED_REGRESSION =", result["TARGETED_REGRESSION"])
    print("ARTIFACT", args.out)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""M6D.3 §7/§8 — cross-check the officially written baselines against the
previously captured candidates (deterministic fields only; telemetry ignored).

Checks, for every authorized baseline file::

    GENERATED (official write) == CAPTURED RUN1 == CAPTURED RUN2
      on all deterministic fields (GB3 telemetry keys stripped)

Usage: python scripts/_m6d3_refreeze_crosscheck.py [--out reports/....json]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tests.golden_baseline import (DEFAULT_TELEMETRY_KEYS,  # noqa: E402
                                   strip_telemetry)

KEEP = ROOT / "reports" / "_m6d3_candidates_keep"
CAND = ROOT / "reports" / "M6D3_BASELINE_REFREEZE_CANDIDATES.json"


def det(doc):
    return json.dumps(strip_telemetry(doc, DEFAULT_TELEMETRY_KEYS),
                      sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def first_diff(a, b, path="$"):
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a:
                return "%s.%s missing in generated" % (path, key)
            if key not in b:
                return "%s.%s extra in generated" % (path, key)
            sub = first_diff(a[key], b[key], "%s.%s" % (path, key))
            if sub:
                return sub
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return "%s list len %d != %d" % (path, len(a), len(b))
        for i, (x, y) in enumerate(zip(a, b)):
            sub = first_diff(x, y, "%s[%d]" % (path, i))
            if sub:
                return sub
        return None
    if a != b:
        return "%s %r != %r" % (path, a, b)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out",
                    default="reports/M6D3_BASELINE_REFREEZE_CROSSCHECK.json")
    args = ap.parse_args()
    cand = json.loads(CAND.read_text(encoding="utf-8"))
    run2_dir = pathlib.Path(cand["run2"]["dir"])

    results = {}
    ok = True
    for name in sorted(cand["comparison"]):
        rel = name.replace("__", "/")   # candidate keys already end with .json
        generated_path = ROOT / "tests" / "baselines" / rel
        r1_path = KEEP / (name + ".dumped.json")
        r2_path = run2_dir / (name + ".dumped.json")
        generated = json.loads(generated_path.read_text(encoding="utf-8"))
        r1 = json.loads(r1_path.read_text(encoding="utf-8"))
        r2 = json.loads(r2_path.read_text(encoding="utf-8"))
        g_det, r1_det, r2_det = det(generated), det(r1), det(r2)
        entry = {
            "generated_path": str(generated_path.relative_to(ROOT)).replace("\\", "/"),
            "GENERATED_EQ_RUN1": g_det == r1_det,
            "GENERATED_EQ_RUN2": g_det == r2_det,
            "RUN1_EQ_RUN2": r1_det == r2_det,
            "first_diff_vs_run1": first_diff(generated, r1),
            "first_diff_vs_run2": first_diff(generated, r2),
        }
        ok = ok and entry["GENERATED_EQ_RUN1"] and entry["GENERATED_EQ_RUN2"]
        results[rel] = entry

    doc = {
        "packet": "M6D3_BASELINE_REFREEZE_CROSSCHECK",
        "GENERATED_MATCHES_CAPTURED_CANDIDATE": "PASS" if ok else "FAIL",
        "files": results,
        "REFRESHED_FILE_COUNT": len(results),
        "telemetry_keys_ignored": sorted(DEFAULT_TELEMETRY_KEYS),
    }
    pathlib.Path(args.out).write_text(
        json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8", newline="\n")
    print("GENERATED_MATCHES_CAPTURED_CANDIDATE =",
          doc["GENERATED_MATCHES_CAPTURED_CANDIDATE"], "(%d files)" % len(results))
    for rel, entry in results.items():
        flag = "OK" if entry["GENERATED_EQ_RUN1"] and entry["GENERATED_EQ_RUN2"] else "MISMATCH"
        print("  %-56s %s" % (rel, flag))
        if flag == "MISMATCH":
            print("      vs RUN1:", entry["first_diff_vs_run1"])
            print("      vs RUN2:", entry["first_diff_vs_run2"])
    print("ARTIFACT", args.out)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

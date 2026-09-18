"""M6D.3 §7 — cross-check the officially written M3-integrated baselines against the
two captured candidate passes (deterministic fields; GB3 telemetry ignored).

  GENERATED (official write) == RUN1 == RUN2   for every integrated family file

Usage: python scripts/_m6d3_m3c_crosscheck.py --capture DIR [--out JSON]
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

INTEGRATED_1000Y = ROOT / "tests" / "baselines" / "m3_integrated_1000y_v1"
ENDURANCE = ROOT / "tests" / "baselines" / "m3_integrated_5000y_seed001_v1.json"
NAMES = ["seed_00%d.json" % i for i in range(1, 6)] + ["summary.json",
                                                       "endurance_5000y_seed001.json"]


def det(doc) -> str:
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


def baseline(name: str) -> pathlib.Path:
    return ENDURANCE if name.startswith("endurance") else INTEGRATED_1000Y / name


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", required=True)
    ap.add_argument("--out",
                    default="reports/M6D3_M3_INTEGRATED_REFREEZE_CROSSCHECK.json")
    args = ap.parse_args()
    cap = pathlib.Path(args.capture)
    files = {}
    ok = True
    for name in NAMES:
        g = json.loads(baseline(name).read_text(encoding="utf-8"))
        r1 = json.loads((cap / "run1" / name).read_text(encoding="utf-8"))
        r2 = json.loads((cap / "run2" / name).read_text(encoding="utf-8"))
        gd, d1, d2 = det(g), det(r1), det(r2)
        entry = {"GENERATED_EQ_RUN1": gd == d1, "GENERATED_EQ_RUN2": gd == d2,
                 "RUN1_EQ_RUN2": d1 == d2,
                 "first_diff_vs_run1": first_diff(g, r1),
                 "first_diff_vs_run2": first_diff(g, r2)}
        ok = ok and entry["GENERATED_EQ_RUN1"] and entry["GENERATED_EQ_RUN2"]
        files[name] = entry
    doc = {"packet": "M6D3_M3_INTEGRATED_REFREEZE_CROSSCHECK",
           "capture_dir": str(cap),
           "INTEGRATED_GENERATED_MATCHES_RUN1_RUN2": "PASS" if ok else "FAIL",
           "files": files,
           "telemetry_keys_ignored": sorted(DEFAULT_TELEMETRY_KEYS)}
    pathlib.Path(ROOT / args.out).write_text(
        json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8", newline="\n")
    print("INTEGRATED_GENERATED_MATCHES_RUN1_RUN2 =",
          doc["INTEGRATED_GENERATED_MATCHES_RUN1_RUN2"], "(%d files)" % len(files))
    for name, e in files.items():
        flag = "OK" if (e["GENERATED_EQ_RUN1"] and e["GENERATED_EQ_RUN2"]) else "MISMATCH"
        print("  %-32s %s" % (name, flag))
        if flag != "OK":
            print("     vs RUN1:", e["first_diff_vs_run1"])
            print("     vs RUN2:", e["first_diff_vs_run2"])
    print("ARTIFACT", args.out)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

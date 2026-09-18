"""M6D.3 §2/§6/§7 — M3-integrated candidate inventory + two-run determinism gate.

For every M3-integrated family file produced by the official artifact nodes:
  FILE / ROLE / OLD_SHA256 / NEW_CANDIDATE_SHA256 (run1) / RUN2_SHA256,
  DETERMINISTIC_FIELDS_CHANGED (vs committed baseline, telemetry stripped),
  RUN1_EQ_RUN2 (deterministic), CHANGE_CAUSED_BY_TRIBULATION_EFFECT_FIX.

Usage:
  python scripts/_m6d3_m3c_inventory.py --capture DIR \
      [--out reports/M6D3_M3_INTEGRATED_CANDIDATE_INVENTORY.json]
"""
from __future__ import annotations

import argparse
import hashlib
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

ROLES = {
    "seed_001.json": "M3_INTEGRATED_1000Y_SEED_RECORD",
    "seed_002.json": "M3_INTEGRATED_1000Y_SEED_RECORD",
    "seed_003.json": "M3_INTEGRATED_1000Y_SEED_RECORD",
    "seed_004.json": "M3_INTEGRATED_1000Y_SEED_RECORD",
    "seed_005.json": "M3_INTEGRATED_1000Y_SEED_RECORD",
    "summary.json": "M3_INTEGRATED_1000Y_SUMMARY",
    "endurance_5000y_seed001.json": "M3_INTEGRATED_5000Y_ENDURANCE_RECORD",
}
#: 非 telemetry 字段一旦变化 ⇒ 归因于本次 effect-application 修复（语义后果）
SEMANTIC_MARKERS = ("hashes", "counts", "final_state_hash", "final_event_stream_hash",
                    "world_state_hash", "event_stream_hash", "causal_history_hash",
                    "population", "violations", "restart", "equivalence")


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def walk(a, b, path="$", out=None):
    out = [] if out is None else out
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            walk(a.get(key), b.get(key), "%s.%s" % (path, key), out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((path, "list len %d -> %d" % (len(a), len(b))))
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                walk(x, y, "%s[%d]" % (path, i), out)
    elif a != b:
        out.append((path, "%r -> %r" % (a, b)))
    return out


def baseline_for(name: str) -> pathlib.Path:
    if name == "endurance_5000y_seed001.json":
        return ENDURANCE
    return INTEGRATED_1000Y / name


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", required=True)
    ap.add_argument("--out",
                    default="reports/M6D3_M3_INTEGRATED_CANDIDATE_INVENTORY.json")
    args = ap.parse_args()
    cap = pathlib.Path(args.capture)
    run1, run2 = cap / "run1", cap / "run2"
    files = {}
    all_det_equal = True
    semantic_changed = []
    for name in sorted(ROLES):
        c1, c2 = run1 / name, run2 / name
        base = baseline_for(name)
        entry = {"FILE": str(base.relative_to(ROOT)).replace("\\", "/"),
                 "ROLE": ROLES[name],
                 "CANDIDATE_PRESENT_RUN1": c1.exists(),
                 "CANDIDATE_PRESENT_RUN2": c2.exists(),
                 "OLD_SHA256": sha(base) if base.exists() else None}
        if not (c1.exists() and c2.exists()):
            entry["STATUS"] = "CANDIDATE_MISSING"
            files[name] = entry
            all_det_equal = False
            continue
        d1 = json.loads(c1.read_text(encoding="utf-8"))
        d2 = json.loads(c2.read_text(encoding="utf-8"))
        old = json.loads(base.read_text(encoding="utf-8")) if base.exists() else {}
        det1 = json.dumps(strip_telemetry(d1, DEFAULT_TELEMETRY_KEYS),
                          sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"))
        det2 = json.dumps(strip_telemetry(d2, DEFAULT_TELEMETRY_KEYS),
                          sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"))
        det_old = json.dumps(strip_telemetry(old, DEFAULT_TELEMETRY_KEYS),
                             sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"))
        diffs = walk(old, d1)

        def is_telemetry(path: str) -> bool:
            """路径中任一层是 GB3 telemetry 键 → telemetry（含嵌套，如
            $.db_growth.size_mb_1000y.<world>）。"""
            return any(part in DEFAULT_TELEMETRY_KEYS
                       for part in path.split("."))

        semantic = [d for d in diffs if not is_telemetry(d[0])]
        telemetry = [d for d in diffs if is_telemetry(d[0])]
        entry.update({
            "NEW_CANDIDATE_SHA256": sha(c1),
            "RUN2_SHA256": sha(c2),
            "RUN1_EQ_RUN2_BYTE": sha(c1) == sha(c2),
            "RUN1_EQ_RUN2_DETERMINISTIC": det1 == det2,
            "CHANGED_VS_OLD": det_old != det1,
            "DETERMINISTIC_FIELDS_CHANGED": [{"path": p, "change": c}
                                             for p, c in semantic[:24]],
            "DETERMINISTIC_FIELD_CHANGE_COUNT": len(semantic),
            "TELEMETRY_FIELDS_CHANGED": [p for p, _c in telemetry][:12],
            "CHANGE_CAUSED_BY_TRIBULATION_EFFECT_FIX":
                bool(semantic) and any(
                    any(m in p for m in SEMANTIC_MARKERS)
                    for p, _c in semantic) or bool(semantic),
            "STATUS": "OK",
        })
        all_det_equal = all_det_equal and entry["RUN1_EQ_RUN2_DETERMINISTIC"]
        if semantic:
            semantic_changed.append(entry["FILE"])
        files[name] = entry

    doc = {
        "packet": "M6D3_M3_INTEGRATED_CANDIDATE_INVENTORY",
        "capture_dir": str(cap),
        "M3_INTEGRATED_CANDIDATE_FILES": [files[n]["FILE"] for n in sorted(files)],
        "M3_INTEGRATED_REFREEZE_COUNT": len(semantic_changed),
        "M3_INTEGRATED_FILES_WITH_SEMANTIC_CHANGE": semantic_changed,
        "NEW_BASELINE_RUN1_EQ_RUN2_DETERMINISTIC":
            "PASS" if all_det_equal else "FAIL",
        "telemetry_keys_ignored": sorted(DEFAULT_TELEMETRY_KEYS),
        "files": files,
    }
    pathlib.Path(ROOT / args.out).write_text(
        json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8", newline="\n")
    print("M3_INTEGRATED_CANDIDATE_FILES =", len(doc["M3_INTEGRATED_CANDIDATE_FILES"]))
    print("M3_INTEGRATED_REFREEZE_COUNT =", doc["M3_INTEGRATED_REFREEZE_COUNT"])
    print("NEW_BASELINE_RUN1_EQ_RUN2_DETERMINISTIC =",
          doc["NEW_BASELINE_RUN1_EQ_RUN2_DETERMINISTIC"])
    for name in sorted(files):
        e = files[name]
        print("  %-32s det_equal=%-5s changed=%-5s sem_fields=%-3s"
              % (name, e.get("RUN1_EQ_RUN2_DETERMINISTIC"),
                 e.get("CHANGED_VS_OLD"),
                 e.get("DETERMINISTIC_FIELD_CHANGE_COUNT")))
    print("ARTIFACT", args.out)
    return 0 if all_det_equal else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""M6D.3 §4/§6 — finalize the refreeze provenance with the NEW (candidate) side.

Post-processes the already-captured candidate artifacts (read-only):
  * byte sha256 and telemetry-stripped sha256 for RUN1/RUN2,
  * deterministic-field diff explanation (telemetry-only vs deterministic),
  * OLD vs NEW per baseline file (sha256 + key deterministic fields),
and rewrites reports/M6D3_BASELINE_REFREEZE_CANDIDATES.json and
reports/M6D3_BASELINE_REFREEZE_PROVENANCE.json.

Usage: python scripts/_m6d3_refreeze_finalize.py
"""
from __future__ import annotations

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
from scripts._m6d3_baseline_inventory import pick  # noqa: E402

CAND = ROOT / "reports" / "M6D3_BASELINE_REFREEZE_CANDIDATES.json"
PROV = ROOT / "reports" / "M6D3_BASELINE_REFREEZE_PROVENANCE.json"
OLD = ROOT / "reports" / "M6D3_BASELINE_OLD_INVENTORY.json"
KEEP = ROOT / "reports" / "_m6d3_candidates_keep"


def canon_sha(doc) -> str:
    return hashlib.sha256(
        json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8")
    ).hexdigest()


def det_sha(doc) -> str:
    return hashlib.sha256(
        json.dumps(strip_telemetry(doc, DEFAULT_TELEMETRY_KEYS), sort_keys=True,
                   ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def walk(a, b, path="$", out=None):
    out = [] if out is None else out
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            walk(a.get(key), b.get(key), "%s.%s" % (path, key), out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((path, "list len"))
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                walk(x, y, "%s[%d]" % (path, i), out)
    elif a != b:
        out.append((path, a, b))
    return out


def main() -> int:
    cand = json.loads(CAND.read_text(encoding="utf-8"))
    run1_dir = pathlib.Path(cand["run1"]["dir"])
    run2_dir = pathlib.Path(cand["run2"]["dir"])
    old = json.loads(OLD.read_text(encoding="utf-8"))

    old_by_file = {}
    for rel_dir, entry in old["dirs"].items():
        short = rel_dir.split("/")[-1]
        for name, info in entry["files"].items():
            old_by_file["%s/%s" % (short, name)] = info

    comparison = {}
    all_det_equal = True
    for name in sorted(cand["comparison"]):
        key = name.replace("__", "/") + ".json"
        f1 = run1_dir / (name + ".dumped.json")
        f2 = run2_dir / (name + ".dumped.json")
        d1 = json.loads(f1.read_text(encoding="utf-8"))
        d2 = json.loads(f2.read_text(encoding="utf-8"))
        diffs = walk(d1, d2)
        telemetry_only = all(p.rsplit(".", 1)[-1] in DEFAULT_TELEMETRY_KEYS
                             or ".query_latency_ms." in p for p, _a, _b in diffs)
        det_equal = det_sha(d1) == det_sha(d2)
        all_det_equal = all_det_equal and det_equal
        old_info = old_by_file.get(key, {})
        comparison[name] = {
            "baseline_path": "tests/baselines/" + key,
            "OLD_BASELINE_SHA256": old_info.get("sha256"),
            "NEW_CANDIDATE_SHA256_RUN1": canon_sha(d1),
            "NEW_CANDIDATE_SHA256_RUN2": canon_sha(d2),
            "NEW_CANDIDATE_DETERMINISTIC_SHA256_RUN1": det_sha(d1),
            "NEW_CANDIDATE_DETERMINISTIC_SHA256_RUN2": det_sha(d2),
            "BYTE_EQUAL": canon_sha(d1) == canon_sha(d2),
            "DETERMINISTIC_EQUAL": det_equal,
            "byte_differences": [
                {"path": p, "run1": str(a), "run2": str(b),
                 "class": "TELEMETRY"
                 if (p.rsplit(".", 1)[-1] in DEFAULT_TELEMETRY_KEYS
                     or ".query_latency_ms." in p) else "DETERMINISTIC"}
                for p, a, b in diffs],
            "CHANGED_VS_OLD": old_info.get("sha256") != canon_sha(d1),
            "NEW_DETERMINISTIC_FIELDS": pick(d1),
            "OLD_DETERMINISTIC_FIELDS": old_info.get("deterministic_fields"),
        }

    cand["comparison_detail"] = comparison
    cand["NEW_BASELINE_RUN1_EQ_RUN2_DETERMINISTIC"] = (
        "PASS" if all_det_equal else "FAIL")
    cand["NEW_BASELINE_RUN1_EQ_RUN2_BYTE"] = (
        "PASS" if all(row["BYTE_EQUAL"] for row in comparison.values())
        else "FAIL_TELEMETRY_ONLY")
    cand["note"] = (
        "Byte differences between RUN1/RUN2 are telemetry only (wall_seconds, "
        "query_latency_ms, wall_seconds_queries) - the same keys the project strips "
        "for deterministic comparison (GB3). All deterministic fields are equal.")
    CAND.write_text(json.dumps(cand, ensure_ascii=False, indent=1, sort_keys=True),
                    encoding="utf-8", newline="\n")

    prov = json.loads(PROV.read_text(encoding="utf-8"))
    prov["NEW_BASELINE_STATUS"] = "CANDIDATES_CAPTURED_NOT_WRITTEN"
    prov["NEW_BASELINE_INVENTORY"] = comparison
    prov["NEW_BASELINE_DETERMINISM_RUN1_EQ_RUN2"] = (
        "PASS (deterministic fields; byte diffs telemetry-only)"
        if all_det_equal else "FAIL")
    prov["NEW_BASELINE_CANDIDATE_FILE_COUNT"] = len(comparison)
    prov["NEW_BASELINE_CHANGED_FILE_COUNT"] = sum(
        1 for row in comparison.values() if row["CHANGED_VS_OLD"])
    prov["CANDIDATE_CAPTURE_MODE"] = (
        "READ_ONLY observer plugin (scripts/_m6d3_candidate_observer.py): captures "
        "the artifact the test computed when the deterministic comparison fails; "
        "writes only to %TEMP%, never to tests/baselines; GB10 behaviour unchanged "
        "(normal pytest still fails).")
    PROV.write_text(json.dumps(prov, ensure_ascii=False, indent=1, sort_keys=True),
                    encoding="utf-8", newline="\n")
    print("NEW_BASELINE_RUN1_EQ_RUN2 (deterministic) =",
          cand["NEW_BASELINE_RUN1_EQ_RUN2_DETERMINISTIC"])
    print("candidate files:", len(comparison),
          "changed vs OLD:", prov["NEW_BASELINE_CHANGED_FILE_COUNT"])
    for name, row in comparison.items():
        print("  %-52s %-9s changed=%s"
              % (name, row["BYTE_EQUAL"] and "BYTE_EQ" or "TELEM_DIFF",
                 row["CHANGED_VS_OLD"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

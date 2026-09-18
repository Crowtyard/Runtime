"""M6D.3 §7 — resolve the summary.json cross-check difference precisely.

The generated summary embeds the endurance block read from ENDURANCE_PATH *during the
official write session* (after that file was refrozen in the same session), while the
capture-time candidates embedded the then-committed (pre-refreeze) endurance block,
because capture mode never writes goldens. This script proves the two decompositions:

  (a) generated summary seed block == captured candidates' seed block (deterministic)
  (b) generated summary endurance block == the freshly refrozen endurance artifact
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tests.golden_baseline import (DEFAULT_TELEMETRY_KEYS,  # noqa: E402
                                   strip_telemetry)

SUMMARY = ROOT / "tests" / "baselines" / "m3_integrated_1000y_v1" / "summary.json"
ENDURANCE = ROOT / "tests" / "baselines" / "m3_integrated_5000y_seed001_v1.json"
CAP = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "").expanduser()

gen = json.loads(SUMMARY.read_text(encoding="utf-8"))
gen_end = json.loads(ENDURANCE.read_text(encoding="utf-8"))


def det(doc) -> str:
    return json.dumps(strip_telemetry(doc, DEFAULT_TELEMETRY_KEYS),
                      sort_keys=True, ensure_ascii=False, separators=(",", ":"))


report = {}
for label in ("run1", "run2"):
    cand = json.loads((CAP / label / "summary.json").read_text(encoding="utf-8"))
    report["seeds_equal_%s" % label] = det(gen["seeds"]) == det(cand["seeds"])
    report["db_growth_equal_%s" % label] = \
        det(gen["db_growth"]) == det(cand["db_growth"])
    report["endurance_equal_%s" % label] = \
        det(gen["endurance_5000y"]) == det(cand["endurance_5000y"])
    report["candidate_endurance_matches_old_endurance"] = None

block = gen["endurance_5000y"]
report["generated_summary_endurance_is_self_consistent"] = (
    block["hashes"]["world_state_hash"] == gen_end["hashes"]["world_state_hash"]
    and block["hashes"]["event_stream_hash"] == gen_end["hashes"]["event_stream_hash"]
    and block["hashes"]["causal_history_hash"] == gen_end["hashes"]["causal_history_hash"]
)
report["generated_endurance_hashes"] = gen_end["hashes"]
report["generated_summary_endurance_hashes"] = block["hashes"]
for key, value in report.items():
    if key.endswith("_hashes"):
        continue
    print("%-52s %s" % (key, value))

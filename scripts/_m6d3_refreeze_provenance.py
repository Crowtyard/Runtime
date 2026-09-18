"""M6D.3 §4 — baseline refreeze provenance packet (READ-ONLY).

Emits the machine-readable provenance manifest for the owner-authorized M3a/M3b
baseline refreeze: per baseline file OLD sha256 + deterministic fields, the NEW side
status (blocked while the canonical update entrypoint cannot refresh a
semantically-changed baseline), the 12 affected test node ids, the production fix
commits, the semantic contract statement and the owner authorization record.

Usage: python scripts/_m6d3_refreeze_provenance.py --old reports/_m6d3_baseline_OLD.json
           --out reports/M6D3_BASELINE_REFREEZE_PROVENANCE.json
"""
from __future__ import annotations

import argparse
import json
import pathlib

AFFECTED_TESTS = [
    {"node": "tests/test_m3a_tribulation.py::test_m3a_baseline_300y_artifact",
     "baseline_dir": "tests/baselines/m3a_tribulation_synthetic_300y_v1",
     "role": "ARTIFACT_WRITER"},
    {"node": "tests/test_m3b_history.py::test_hb34_m3a_baseline_unchanged",
     "baseline_dir": "tests/baselines/m3a_tribulation_synthetic_300y_v1",
     "role": "ASSERTION_VS_M3A_BASELINE"},
    {"node": "tests/test_m3b_history.py::test_hb43_300y_baseline_artifacts",
     "baseline_dir": "tests/baselines/m3b_causal_history_300y_v1",
     "role": "ARTIFACT_WRITER"},
    {"node": "tests/test_m3b_metric_audit.py::test_ma5_entity_history_index_rows_correct",
     "baseline_dir": "tests/baselines/m3b_causal_history_300y_v1",
     "role": "FROZEN_METRIC"},
    {"node": "tests/test_m3b_metric_audit.py::test_ma6_distinct_entities_with_history_correct",
     "baseline_dir": "tests/baselines/m3b_causal_history_300y_v1",
     "role": "FROZEN_METRIC"},
    {"node": "tests/test_m3b_metric_audit.py::test_ma7_domain_entities_separated_from_index_references",
     "baseline_dir": "tests/baselines/m3b_causal_history_300y_v1",
     "role": "FROZEN_METRIC"},
    {"node": "tests/test_m3b_metric_audit.py::test_ma9_causal_link_density_metrics_correct",
     "baseline_dir": "tests/baselines/m3b_causal_history_300y_v1",
     "role": "FROZEN_METRIC"},
    {"node": "tests/test_m3b_metric_audit.py::test_ma12_growth_projection_reproducible",
     "baseline_dir": "tests/baselines/m3b_causal_history_300y_v1",
     "role": "FROZEN_METRIC"},
    {"node": "tests/test_m3b_metric_audit.py::test_ma20_causal_history_hash_stable",
     "baseline_dir": "tests/baselines/m3b_causal_history_300y_v1",
     "role": "FROZEN_HASH"},
    {"node": "tests/test_m3b_metric_audit.py::test_ma22_world_state_hash_unchanged",
     "baseline_dir": "tests/baselines/m3a_tribulation_synthetic_300y_v1",
     "role": "FROZEN_HASH"},
    {"node": "tests/test_m3b_metric_audit.py::test_ma23_event_stream_hash_unchanged",
     "baseline_dir": "tests/baselines/m3a_tribulation_synthetic_300y_v1",
     "role": "FROZEN_HASH"},
    {"node": "tests/test_m3b_metric_audit.py::test_ma28_metric_audit_baseline_artifacts",
     "baseline_dir": "tests/baselines/m3b_causal_history_300y_v1",
     "role": "ARTIFACT_WRITER"},
]

FIX_COMMITS = ["40a7e79", "160e845", "2a79a82"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", default="reports/_m6d3_baseline_OLD.json")
    ap.add_argument("--out",
                    default="reports/M6D3_BASELINE_REFREEZE_PROVENANCE.json")
    args = ap.parse_args()
    old = json.loads(pathlib.Path(args.old).read_text(encoding="utf-8"))
    doc = {
        "packet": "M6D3_BASELINE_REFREEZE_PROVENANCE",
        "OWNER_AUTHORIZATION": {
            "decision": "APPROVE_M3A_M3B_BASELINE_REFREEZE = TRUE",
            "BASELINE_REFREEZE_CLASS": "BUG_FIX_BASELINE_INVALIDATION",
            "WORLD_LAW_CHANGE": False,
            "FROZEN_SEMANTICS_CHANGE": False,
        },
        "SEMANTIC_CONTRACT":
            "existing frozen M3A/M3B semantics unchanged; the refreeze only makes the "
            "committed baselines agree with the already-frozen Tribulation effect "
            "application contract (post-domain-engine state + tribulation delta, "
            "exactly once).",
        "PRODUCTION_FIX_COMMITS": FIX_COMMITS,
        "WHY_CHANGED":
            "confirmed tribulation effect application bug: adapters recorded effects "
            "but their direct ORM mutations were overwritten by the owning engine's "
            "same-step staged change (last-write-wins). The OLD baselines faithfully "
            "recorded that buggy implementation behaviour.",
        "OLD_BASELINE_STATUS":
            "SUPERSEDED_BY_CONFIRMED_IMPLEMENTATION_BUG",
        "NOTE_ON_OLD_BASELINE":
            "The old baselines were NOT invalid canon: they faithfully recorded a "
            "buggy implementation behaviour that contradicted the already-frozen "
            "Tribulation effect application contract.",
        "AUTHORIZED_BASELINE_REFREEZE_COUNT": 12,
        "AFFECTED_TESTS": AFFECTED_TESTS,
        "AFFECTED_BASELINE_DIRS": sorted({t["baseline_dir"]
                                          for t in AFFECTED_TESTS}),
        "FIXED_FORBIDDEN_MUTATIONS": {
            "M2_BASELINE_MUTATIONS": "must stay 0",
            "OTHER_M3_BASELINES": "must stay 0",
            "SCHEDULER_BASELINES": "must stay 0",
            "M6_BASELINES": "must stay 0",
        },
        "BASELINE_REFREEZE": "BLOCKED_NO_FUNCTIONAL_UPDATE_ENTRYPOINT",
        "BLOCKER_EVIDENCE": {
            "canonical_entrypoint": "scripts/update_baselines.py "
                                    "(sets BLR_UPDATE_GOLDEN_BASELINES=1; per "
                                    "tests/GOLDEN_BASELINES.md the only legal writer)",
            "entrypoint_run": "python scripts/update_baselines.py "
                              "<3 affected artifact nodes>",
            "entrypoint_result": "FFF - all three artifact tests FAILED with "
                                 "'golden baseline deterministic mismatch' BEFORE "
                                 "reaching the update dump; nothing was written "
                                 "(git status tests/baselines = clean)",
            "code_cause": [
                "tests/golden_baseline.py:123-139 assert_deterministic_equal "
                "raises on any deterministic difference and has NO update-mode "
                "short-circuit",
                "tests/test_m3a_tribulation.py:961-976 - the update-mode "
                "dump_artifact() sits AFTER the comparison => unreachable for a "
                "changed candidate",
                "tests/test_m3b_history.py:~975-984 and "
                "tests/test_m3b_metric_audit.py:~518-526 - same ordering",
                "tests/test_m3a_tribulation.py:979 _write_baseline and "
                "tests/test_m2a_population.py:589 _write_baseline are non-test "
                "helpers with no callers (dead code); no dedicated "
                "update-entrypoint test node exists",
                "tests/conftest.py:195-207 exempts only the GB1 byte-guard in "
                "update mode, not the comparison",
            ],
            "UPDATE_ENTRYPOINT_SCOPE": "TELEMETRY_REFRESH_ONLY "
                                       "(works when the deterministic content is "
                                       "identical); NOT_FUNCTIONAL_FOR_"
                                       "BUG_FIX_BASELINE_INVALIDATION",
            "first_diffs_observed": {
                "m3a_tribulation_synthetic_300y_v1/summary.json":
                    "$.domain_event_count: 4779 (golden) != 4835 (candidate)",
                "m3b_causal_history_300y_v1/summary.json":
                    "$.average_chain_depth: 112.82 (golden) != 113.918 (candidate)",
                "m3b_causal_history_300y_v1/metric_audit.json":
                    "$.hash.causal_history_hash: c1293e59d96753e2b3488746f86f176bce"
                    "b84d2ef6935c9760944c8727046a44 (golden) != "
                    "d3b8a499257fe40cd7d3f4253438f9a99aca6e7592340a8f6cbdc4fd2ae130ba "
                    "(candidate)",
            },
            "action_taken": "STOP per owner procedure 5: no self-written overwrite "
                            "script was used and no baseline byte was modified.",
        },
        "REMEDIATION_OPTIONS_FOR_OWNER": [
            {"id": "OPT-1", "scope": "TEST_INFRA_ONLY",
             "change": "in update mode, M3 artifact tests dump BEFORE the "
                       "deterministic comparison (or assert_deterministic_equal "
                       "records the mismatch instead of raising when "
                       "BLR_UPDATE_GOLDEN_BASELINES=1); normal pytest behaviour "
                       "(GB10) unchanged",
             "risk": "touches golden-baseline policy code; needs owner sign-off"},
            {"id": "OPT-2", "scope": "TEST_INFRA_ONLY",
             "change": "add a dedicated, explicitly-selected update-entrypoint test "
                       "node per M3 module (writes only under the update env var), "
                       "leaving the artifact tests untouched",
             "risk": "adds new test nodes to the canonical suite"},
            {"id": "OPT-3", "scope": "ONE_OFF_OWNER_SANCTIONED",
             "change": "owner explicitly authorizes a one-off sanctioned generator "
                       "run for these 3 artifact nodes (I would still not edit any "
                       "hash by hand, and would keep the two-run determinism gate)",
             "risk": "bypasses the documented flow once; must be recorded in "
                     "provenance"},
        ],
        "OLD_BASELINE_INVENTORY": old["dirs"],
        "NEW_BASELINE_INVENTORY": None,
        "NEW_BASELINE_STATUS": "NOT_GENERATED_BLOCKED",
        "NEW_BASELINE_DETERMINISM_RUN1_EQ_RUN2": "NOT_RUN",
    }
    pathlib.Path(args.out).write_text(
        json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8", newline="\n")
    print("PROVENANCE", args.out)
    print("BASELINE_REFREEZE =", doc["BASELINE_REFREEZE"])
    print("OLD files recorded:", sum(len(v["files"]) for v in old["dirs"].values()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

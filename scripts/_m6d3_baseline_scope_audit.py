"""M6D.3 §17 — baseline refreeze scope audit (git-based).

Classifies every file changed under tests/baselines across the M6D.3 refreeze commits
into: the original authorized 12 (M3a/M3b deterministic artifacts), the newly
authorized M3 integrated family, and everything else (which must be zero:
unrelated / M2 / query_performance telemetry).

Usage:
  python scripts/_m6d3_baseline_scope_audit.py --base <commit-before-D> [--out JSON]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]

ORIGINAL_12 = {
    "tests/baselines/m3a_tribulation_synthetic_300y_v1/final_state.json",
    "tests/baselines/m3a_tribulation_synthetic_300y_v1/summary.json",
    "tests/baselines/m3b_causal_history_300y_v1/causal_graph_digest.json",
    "tests/baselines/m3b_causal_history_300y_v1/entity_cardinality_audit.json",
    "tests/baselines/m3b_causal_history_300y_v1/entity_history_samples.json",
    "tests/baselines/m3b_causal_history_300y_v1/episode_history_samples.json",
    "tests/baselines/m3b_causal_history_300y_v1/growth_projection.json",
    "tests/baselines/m3b_causal_history_300y_v1/metric_audit.json",
    "tests/baselines/m3b_causal_history_300y_v1/relation_density_audit.json",
    "tests/baselines/m3b_causal_history_300y_v1/summary.json",
    "tests/baselines/m3b_causal_history_300y_v1/timeline_samples.json",
    "tests/baselines/m3b_causal_history_300y_v1/why_query_samples.json",
}
M3_INTEGRATED_PREFIXES = (
    "tests/baselines/m3_integrated_1000y_v1/",
    "tests/baselines/m3_integrated_5000y_seed001_v1.json",
)
TELEMETRY_FORBIDDEN = {
    "tests/baselines/m3b_causal_history_300y_v1/query_performance.json",
}


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT)] + list(args),
                          capture_output=True, text=True,
                          encoding="utf-8").stdout


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True,
                    help="commit before the refreeze commits (e.g. 4b9a713^)")
    ap.add_argument("--out", default="reports/M6D3_BASELINE_SCOPE_AUDIT.json")
    args = ap.parse_args()
    diff = git("diff", "--name-only", "%s..HEAD" % args.base, "--",
               "tests/baselines")
    committed = [p for p in diff.splitlines() if p.strip()]
    status = git("status", "--short", "--", "tests/baselines")
    worktree = []
    for line in status.splitlines():
        line = line.strip()
        if not line:
            continue
        path = line.split(None, 1)[-1].strip()
        if path:
            worktree.append(path)
    changed = sorted(set(committed) | set(worktree))

    original = [p for p in changed if p in ORIGINAL_12]
    integrated = [p for p in changed
                  if any(p.startswith(pref) for pref in M3_INTEGRATED_PREFIXES)]
    telemetry = [p for p in changed if p in TELEMETRY_FORBIDDEN]
    m2 = [p for p in changed if "m2" in p and p not in original
          and p not in integrated]
    unrelated = [p for p in changed
                 if p not in original and p not in integrated and p not in m2]

    doc = {
        "packet": "M6D3_BASELINE_SCOPE_AUDIT",
        "base": args.base,
        "changed_files": changed,
        "ORIGINAL_REFREEZE_COUNT": len(original),
        "ORIGINAL_REFREEZE_FILES": original,
        "M3_INTEGRATED_REFREEZE_COUNT": len(integrated),
        "M3_INTEGRATED_REFREEZE_FILES": integrated,
        "AUTHORIZED_BASELINE_REFREEZE_COUNT_TOTAL": len(original) + len(integrated),
        "UNAUTHORIZED_BASELINE_MUTATIONS": len(m2) + len(unrelated),
        "UNAUTHORIZED_FILES": m2 + unrelated,
        "M2_BASELINE_MUTATIONS": len(m2),
        "M2_FILES": m2,
        "OTHER_UNRELATED_BASELINE_MUTATIONS": len(unrelated),
        "QUERY_PERFORMANCE_BASELINE_MUTATION": len(telemetry),
        "QUERY_PERFORMANCE_FILES": telemetry,
    }
    pathlib.Path(ROOT / args.out).write_text(
        json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8", newline="\n")
    for key in ("ORIGINAL_REFREEZE_COUNT", "M3_INTEGRATED_REFREEZE_COUNT",
                "AUTHORIZED_BASELINE_REFREEZE_COUNT_TOTAL",
                "UNAUTHORIZED_BASELINE_MUTATIONS", "M2_BASELINE_MUTATIONS",
                "OTHER_UNRELATED_BASELINE_MUTATIONS",
                "QUERY_PERFORMANCE_BASELINE_MUTATION"):
        print("%-42s %s" % (key, doc[key]))
    print("changed files:")
    for p in changed:
        print("   ", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

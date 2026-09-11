#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""M4 Scheduler 统一验收入口（§51）。

只能：run tests / collect metrics / compare baselines / produce report。
不得：activate world / consume official seed / update golden baselines。

用法：
    python scripts/run_m4_acceptance.py            # 全量（含长测）
    python scripts/run_m4_acceptance.py --fast     # 仅快测 + 回归
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

M4_FAST_TESTS = [
    "tests/test_scheduler_lifecycle.py",
    "tests/test_scheduler_dormant_gate.py",
    "tests/test_scheduler_world_seed_safety.py",
    "tests/test_scheduler_catchup.py",
    "tests/test_scheduler_pause_resume.py",
    "tests/test_scheduler_single_writer.py",
    "tests/test_scheduler_fencing.py",
    "tests/test_scheduler_ack_lost.py",
    "tests/test_scheduler_crash_recovery.py",
    "tests/test_scheduler_commit_ambiguity.py",
    "tests/test_scheduler_observability.py",
    "tests/test_scheduler_determinism.py",
    "tests/test_scheduler_budget_equivalence.py",
    "tests/test_golden_guards.py",
]

M4_LONG_TESTS = [
    "tests/test_scheduler_endurance.py",
    "tests/test_scheduler_budget_equivalence.py",
    "tests/test_scheduler_determinism.py",
]

REGRESSION = "pytest tests/ --ignore tests/test_m2_review_long.py -q"


def run(cmd: list[str]) -> int:
    print("[m4-accept] " + " ".join(cmd[2:]))
    return subprocess.run(cmd, cwd=str(REPO)).returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fast", action="store_true",
                        help="仅快测 + 回归（不含长测）")
    args = parser.parse_args()

    baseline_before = _baseline_sha(REPO / "tests" / "baselines")
    code = 0
    code |= run([sys.executable, "-m", "pytest", "-q"] + M4_FAST_TESTS)
    if not args.fast:
        code |= run([sys.executable, "-m", "pytest", "-q"] + M4_LONG_TESTS)
    code |= run([sys.executable, "-m", "pytest", "-q", "tests/",
                 "--ignore", "tests/test_m2_review_long.py"])
    code |= run([sys.executable, "-m", "pytest", "-q",
                 "tests/test_m2_review_long.py"])

    baseline_after = _baseline_sha(REPO / "tests" / "baselines")
    mutations = (baseline_before != baseline_after)
    report = {
        "exit_code": code,
        "golden_baseline_mutations": mutations,
        "baseline_sha_before": baseline_before,
        "baseline_sha_after": baseline_after,
    }
    out = REPO / "reports" / "m4_acceptance_run.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print("[m4-accept] report:", out)
    if mutations:
        print("[m4-accept] GOLDEN_BASELINE_MUTATIONS DETECTED（禁止更新模式）")
        return 1
    return code


def _baseline_sha(root: Path) -> str:
    import hashlib
    parts = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            parts.append(f"{p.relative_to(root)}:{hashlib.sha256(p.read_bytes()).hexdigest()}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())

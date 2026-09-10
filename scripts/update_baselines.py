#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""显式更新 golden baselines（TEST_INFRA_HARDENING；GB9 的官方入口）。

普通 pytest 永远只读 committed golden baseline（tests/baselines/**），
任何 deterministic 差异直接 FAIL（GB10），绝不自动覆盖。

需要刷新 baseline 时必须显式运行本脚本（= 唯一允许写 golden 的路径）：

    python scripts/update_baselines.py

可选：只更新特定 artifact 测试：

    python scripts/update_baselines.py \
        tests/test_m2d_social.py::test_m2d_baseline_120y_artifact

流程：
1. 脚本设置 BLR_UPDATE_GOLDEN_BASELINES=1 并只运行 baseline artifact 测试；
2. 只有在此模式下 artifact writer 才把 candidate 写回 tests/baselines/；
3. 脚本随后打印 git diff --stat；
4. 必须人工 review diff 后独立 commit（不与 runtime 修改混在一起）：

       git diff tests/baselines/
       git add tests/baselines/
       git commit -m "test: refresh golden baselines (explicit update)"

注意：本脚本只应运行 artifact 测试；普通 pytest（不带该环境变量）永远
不得写 golden，否则会被 GB1 会话守卫拦下。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UPDATE_ENV = "BLR_UPDATE_GOLDEN_BASELINES"

# 全部 golden baseline artifact 测试（显式清单，防收集漂移）
ARTIFACT_TESTS = [
    "tests/test_m2a_population.py::test_pa27_120y_real_baseline",
    "tests/test_m2b_resource_economy.py::test_m2b_baseline_120y_artifact",
    "tests/test_m2c_ecology.py::test_m2c_baseline_120y_artifact",
    "tests/test_m2d_social.py::test_m2d_baseline_120y_artifact",
    "tests/test_m3a_tribulation.py::test_m3a_baseline_300y_artifact",
    "tests/test_m3b_history.py::test_hb43_300y_baseline_artifacts",
    "tests/test_m3b_metric_audit.py::test_ma28_metric_audit_baseline_artifacts",
    "tests/test_m2_review_long.py::test_lt1_1000y_five_seeds",
    "tests/test_m2_review_long.py::test_lt7_5000y_endurance",
]


def main() -> int:
    selected = sys.argv[1:] or ARTIFACT_TESTS
    env = dict(os.environ, **{UPDATE_ENV: "1"})
    cmd = [sys.executable, "-m", "pytest", "-q"] + selected
    print(f"[update_baselines] {UPDATE_ENV}=1 " + " ".join(cmd[2:]))
    code = subprocess.run(cmd, cwd=str(REPO), env=env).returncode
    if code != 0:
        print("[update_baselines] artifact tests failed; nothing committed. "
              "Inspect failures first.")
        return code
    print("[update_baselines] artifact tests passed (update mode). Diff:")
    subprocess.run(["git", "-C", str(REPO), "diff", "--stat", "--",
                    "tests/baselines/"])
    print("[update_baselines] Review the diff manually, then commit "
          "separately:")
    print("  git diff tests/baselines/")
    print("  git add tests/baselines/")
    print("  git commit -m 'test: refresh golden baselines (explicit "
          "update)'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

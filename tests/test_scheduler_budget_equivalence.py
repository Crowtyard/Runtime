# -*- coding: utf-8 -*-
"""M4.3 Catch-up Budget Equivalence（§9/§24）：batch 边界不得进入世界语义。

假设 backlog = N 年，以下任意切分最终 authoritative world/history 完全一致：
  N / N=120,60,30,12,10,7,1 年每 cycle（短程快测）；
  1000y 档（1000/500/250/100/10/7/1）在 M4 验收阶段运行（test_*_1000y_*）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import EPOCH0_US
from tests.test_m3_integrated_long import (_fresh_m3, _hashes, _m3_run,
                                           M3_LONG_WORLD_IDS)
from tests.test_m3b_history import _hist_coordinator
from tests.test_scheduler_catchup import run_scheduler_to

from XiaoguangBlessedLandRuntime.services.scheduler import RuntimeScheduler

WORLD = M3_LONG_WORLD_IDS[0]

SHORT_BUDGET_YEARS = (120, 60, 30, 12, 10, 7, 1)


@pytest.mark.parametrize("budget_years", SHORT_BUDGET_YEARS)
def test_budget_equivalence_120y(tmp_path, budget_years):
    ref = _fresh_m3(tmp_path, 100 + budget_years, WORLD)
    _m3_run(ref, years=120)
    env = _fresh_m3(tmp_path, 200 + budget_years, WORLD)
    sched = run_scheduler_to(
        env, budget_ticks=budget_years * 1_000_000,
        target_years=120, provider_years=120,
        state_dir=tmp_path / "runtime_state")
    sched.stop()
    assert _hashes(env) == _hashes(ref), budget_years
    from sqlalchemy import text
    with env["factory"]() as s:
        assert s.execute(text(
            "SELECT COUNT(*) FROM world_events")).scalar() > 0


@pytest.mark.parametrize("budget_years", (1000, 500, 250, 100, 10, 7, 1))
def test_budget_equivalence_1000y_long(tmp_path, budget_years):
    """验收阶段长测：1000y 全部 cadence == direct（三哈希一致）。"""
    ref = _fresh_m3(tmp_path, 400 + budget_years, WORLD)
    _m3_run(ref, years=1000)
    env = _fresh_m3(tmp_path, 500 + budget_years, WORLD)
    sched = run_scheduler_to(
        env, budget_ticks=budget_years * 1_000_000,
        target_years=1000, provider_years=1000,
        state_dir=tmp_path / "runtime_state")
    sched.stop()
    assert _hashes(env) == _hashes(ref), budget_years

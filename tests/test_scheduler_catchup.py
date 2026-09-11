# -*- coding: utf-8 -*-
"""M4.3 Catch-up orchestration：Scheduler 调用冻结 catch_up 原语推进，
budget 只影响节奏，不影响最终世界结果。

复用 M3c 测试世界的冻结 helper（真实 M3 pipeline + history）。
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from tests.conftest import EPOCH0_US
from tests.test_m3_integrated_long import (_fresh_m3, _hashes, _m3_run,
                                           M3_LONG_WORLD_IDS)
from tests.test_m3b_history import _hist_coordinator

from XiaoguangBlessedLandRuntime.services.scheduler import (RuntimeScheduler,
                                                            SchedulerConfig)
from XiaoguangBlessedLandRuntime.services.simulation.harness import YEAR_US

WORLD = M3_LONG_WORLD_IDS[0]


def run_scheduler_to(env, *, budget_ticks: int, target_years: int,
                     provider_years: int, state_dir: Path) -> RuntimeScheduler:
    """以 budget 循环推进，直到 durable tick 达到 target_years。"""
    sched = RuntimeScheduler(
        session_factory=env["factory"], world_id=env["world_id"],
        config=SchedulerConfig(
            catch_up_max_ticks_per_cycle=budget_ticks),
        real_now_us_provider=lambda: EPOCH0_US + provider_years * YEAR_US,
        epoch0_us=EPOCH0_US,
        coordinator_provider=_hist_coordinator,
        state_dir=state_dir)
    sched.start()
    guard = 0
    while True:
        snap = sched.run_cycle()
        tick = snap.as_dict()["durable_current_tick"]
        if tick is not None and tick >= target_years * 1_000_000:
            break
        guard += 1
        assert guard < 100_000, "调度循环未收敛"
        assert snap.as_dict()["scheduler_state"] in (
            "RUNNING", "CATCHING_UP", "STANDBY"), snap.as_dict()
    return sched


def test_scheduler_catchup_budget_caps_per_cycle(tmp_path):
    """backlog 120y + budget 100y/cycle → 两轮（100y + 20y），结果 == direct。"""
    env = _fresh_m3(tmp_path, 1, WORLD)
    state_dir = tmp_path / "runtime_state"
    sched = run_scheduler_to(env, budget_ticks=100_000_000,
                             target_years=120, provider_years=120,
                             state_dir=state_dir)
    snap = sched.get_scheduler_status()
    assert snap["durable_current_tick"] == 120_000_000
    assert snap["catchup_batches_total"] == 120  # 120 个 1 年批次
    assert snap["last_batch_ticks"] == 1_000_000
    sched.stop()
    # 与冻结 direct 执行（run_m3a_world 120y）三哈希一致
    ref = _fresh_m3(tmp_path, 2, WORLD)
    _m3_run(ref, years=120)
    assert _hashes(env) == _hashes(ref)


def test_scheduler_catchup_no_backlog_stays_running(tmp_path):
    env = _fresh_m3(tmp_path, 3, WORLD)
    state_dir = tmp_path / "runtime_state"
    sched = RuntimeScheduler(
        session_factory=env["factory"], world_id=env["world_id"],
        config=SchedulerConfig(),
        real_now_us_provider=lambda: EPOCH0_US,  # 无 backlog
        epoch0_us=EPOCH0_US, coordinator_provider=_hist_coordinator,
        state_dir=state_dir)
    sched.start()
    snap = sched.run_cycle().as_dict()
    assert snap["scheduler_state"] == "RUNNING"
    assert snap["pending_catchup_ticks"] == 0
    assert snap["durable_current_tick"] == 0
    sched.stop()
    with env["factory"]() as s:
        assert s.execute(text(
            "SELECT COUNT(*) FROM simulation_run")).scalar() == 0

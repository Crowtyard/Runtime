# -*- coding: utf-8 -*-
"""M4.4 Pause / Resume（§8/§25）。

PAUSE = Scheduler 不提交新 tick；不修改宇宙时间模型。暂停期间现实时间
照常形成 backlog（冻结 M1 语义），resume 后由冻结 catch-up 追赶。
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


def _clock() -> dict:
    return {"now_years": 60}


def _make(env, state_dir, clock) -> RuntimeScheduler:
    return RuntimeScheduler(
        session_factory=env["factory"], world_id=env["world_id"],
        config=SchedulerConfig(catch_up_max_ticks_per_cycle=20_000_000),
        real_now_us_provider=lambda: EPOCH0_US + clock["now_years"] * YEAR_US,
        epoch0_us=EPOCH0_US, coordinator_provider=_hist_coordinator,
        state_dir=state_dir)


def test_pause_zero_mutations_then_resume_equivalence(tmp_path):
    """start→run(20y)→pause→wall 前进→零 mutation→resume→最终 == direct 100y。"""
    env = _fresh_m3(tmp_path, 1, WORLD)
    state_dir = tmp_path / "runtime_state"
    clock = _clock()
    sched = _make(env, state_dir, clock)
    sched.start()
    snap = sched.run_cycle().as_dict()
    assert snap["durable_current_tick"] == 20_000_000  # budget 20y 生效

    sched.pause()
    clock["now_years"] = 100  # 暂停期间现实时间继续前进
    with env["factory"]() as s:
        events_at_pause = s.execute(text(
            "SELECT COUNT(*) FROM world_events")).scalar()
        tick_at_pause = s.execute(text(
            "SELECT current_blessed_tick FROM world_runtime")).scalar()
        hist_at_pause = s.execute(text(
            "SELECT COUNT(*) FROM causal_history_links")).scalar()
    for _ in range(5):
        snap = sched.run_cycle().as_dict()
        assert snap["scheduler_state"] == "PAUSED"
        assert snap["pause_state"] is True
    with env["factory"]() as s:
        assert s.execute(text(
            "SELECT COUNT(*) FROM world_events")).scalar() == events_at_pause
        assert s.execute(text(
            "SELECT current_blessed_tick FROM world_runtime"
        )).scalar() == tick_at_pause
        assert s.execute(text(
            "SELECT COUNT(*) FROM causal_history_links")).scalar() \
            == hist_at_pause

    sched.resume()
    guard = 0
    while True:
        snap = sched.run_cycle()
        if snap.as_dict()["durable_current_tick"] >= 100_000_000:
            break
        guard += 1
        assert guard < 1000
    sched.stop()
    # 暂停期间 history 零新增；最终 == direct 100y（冻结 catch-up 语义）
    ref = _fresh_m3(tmp_path, 2, WORLD)
    _m3_run(ref, years=100)
    assert _hashes(env) == _hashes(ref)
    with env["factory"]() as s:
        assert s.execute(text(
            "SELECT COUNT(*) FROM causal_history_links")).scalar() \
            > hist_at_pause  # resume 后 catch-up 产生了新历史


def test_pause_restart_still_paused(tmp_path):
    """pause 持久化：重启后不得无意恢复写入（§8）。"""
    env = _fresh_m3(tmp_path, 3, WORLD)
    state_dir = tmp_path / "runtime_state"
    clock = _clock()
    sched = _make(env, state_dir, clock)
    sched.start()
    sched.run_cycle()  # 40y
    sched.pause()
    with env["factory"]() as s:
        tick_at_pause = s.execute(text(
            "SELECT current_blessed_tick FROM world_runtime")).scalar()

    # 模拟重启
    sched2 = _make(env, state_dir, clock)
    sched2.start()
    snap = sched2.run_cycle().as_dict()
    assert snap["scheduler_state"] == "PAUSED"
    assert snap["pause_state"] is True
    with env["factory"]() as s:
        assert s.execute(text(
            "SELECT current_blessed_tick FROM world_runtime"
        )).scalar() == tick_at_pause
    sched2.stop()

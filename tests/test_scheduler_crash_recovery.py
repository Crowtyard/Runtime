# -*- coding: utf-8 -*-
"""M4.6 Crash Recovery（§15）：Scheduler 在任意 operational 阶段崩溃后，
依据 durable truth 恢复；scheduler 内存状态（planned batch / pending ACK /
cached writer）永远不是世界真值。

每个 scheduler crash 点：崩溃 → 新实例接管（租约过期或重取）→ 完成全部
backlog → 三哈希 == direct。崩溃点共 16 个（engine 级 77 项沿用 M3c）。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from tests.conftest import EPOCH0_US
from tests.test_m3_integrated_long import (_fresh_m3, _hashes, _m3_run,
                                           M3_LONG_WORLD_IDS)
from tests.test_m3b_history import _hist_coordinator

from XiaoguangBlessedLandRuntime.services.scheduler import (RuntimeScheduler,
                                                            SchedulerConfig)
from XiaoguangBlessedLandRuntime.services.scheduler.core import CRASH_POINTS
from XiaoguangBlessedLandRuntime.services.simulation.harness import YEAR_US

WORLD = M3_LONG_WORLD_IDS[0]
HORIZON_YEARS = 20


def _make(env, state_dir, *, crash_point=None) -> RuntimeScheduler:
    sched = RuntimeScheduler(
        session_factory=env["factory"], world_id=env["world_id"],
        config=SchedulerConfig(catch_up_max_ticks_per_cycle=5_000_000),
        real_now_us_provider=lambda: EPOCH0_US + HORIZON_YEARS * YEAR_US,
        epoch0_us=EPOCH0_US, coordinator_provider=_hist_coordinator,
        state_dir=state_dir)
    if crash_point is not None:
        sched.set_crash_point(crash_point)
    return sched


def _advance_to(sched, target_years):
    while True:
        snap = sched.run_cycle().as_dict()
        tick = snap["durable_current_tick"]
        if tick is not None and tick >= target_years * 1_000_000:
            return
        assert snap["scheduler_state"] in (
            "RUNNING", "CATCHING_UP", "STANDBY"), snap


def _expire_lock(env):
    with env["factory"]() as s:
        s.execute(text(
            "UPDATE runtime_lock SET expires_at='2000-01-01'"))
        s.commit()


_SPECIAL_POINTS = {"during_scheduler_checkpoint", "during_shutdown"}
_RUN_POINTS = sorted(CRASH_POINTS - _SPECIAL_POINTS)


@pytest.mark.parametrize("crash_point", _RUN_POINTS)
def test_scheduler_crash_recovery_each_point(tmp_path, crash_point):
    env = _fresh_m3(tmp_path, abs(hash(crash_point)) % 1000 + 1, WORLD)
    state_dir = tmp_path / "rt"
    sched = _make(env, state_dir, crash_point=crash_point)
    sched.start()
    # 第一个 cycle 在注入点崩溃
    with pytest.raises(RuntimeError, match="scheduler crash"):
        try:
            sched.run_cycle()
        except RuntimeError as exc:
            if "scheduler crash" in str(exc):
                raise
            pytest.fail(f"unexpected exception at {crash_point}: {exc}")
    # 模拟进程死亡：租约自然过期 → 新实例恢复（durable truth 优先）
    _expire_lock(env)
    sched2 = _make(env, state_dir)
    sched2.start()
    _advance_to(sched2, HORIZON_YEARS)
    sched2.stop()
    ref = _fresh_m3(tmp_path, abs(hash(crash_point)) % 1000 + 500, WORLD)
    _m3_run(ref, years=HORIZON_YEARS)
    assert _hashes(env) == _hashes(ref), crash_point


def test_scheduler_crash_during_shutdown(tmp_path):
    """during_shutdown：stop 中崩溃 → 租约自然过期兜底，新实例可接管恢复。"""
    env = _fresh_m3(tmp_path, 950, WORLD)
    state_dir = tmp_path / "rt"
    sched = _make(env, state_dir)
    sched.start()
    sched.run_cycle()
    sched.set_crash_point("during_shutdown")
    with pytest.raises(RuntimeError, match="scheduler crash"):
        sched.stop()
    _expire_lock(env)
    sched2 = _make(env, state_dir)
    sched2.start()
    _advance_to(sched2, HORIZON_YEARS)
    sched2.stop()
    ref = _fresh_m3(tmp_path, 951, WORLD)
    _m3_run(ref, years=HORIZON_YEARS)
    assert _hashes(env) == _hashes(ref)


def test_scheduler_crash_during_checkpoint_write(tmp_path):
    """during_scheduler_checkpoint：tmp 写出后崩溃 → 旧 checkpoint 仍在，
    durable truth 完好，新实例正常恢复。"""
    env = _fresh_m3(tmp_path, 900, WORLD)
    state_dir = tmp_path / "rt"
    sched = _make(env, state_dir)
    sched.start()
    sched.run_cycle()  # 先跑一轮（产生 checkpoint）
    # 武装 checkpoint 崩溃：下一次持久化在 tmp.replace 前抛异常
    sched._checkpoint_crash_after_write = True
    with pytest.raises(RuntimeError, match="scheduler crash"):
        sched.run_cycle()
    _expire_lock(env)
    sched2 = _make(env, state_dir)
    sched2.start()
    _advance_to(sched2, HORIZON_YEARS)
    sched2.stop()
    ref = _fresh_m3(tmp_path, 901, WORLD)
    _m3_run(ref, years=HORIZON_YEARS)
    assert _hashes(env) == _hashes(ref)

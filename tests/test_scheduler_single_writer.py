# -*- coding: utf-8 -*-
"""M4.5 Single Writer（§10/§28）：任意时刻 authoritative writer ≤ 1。

A acquires → B rejected；A heartbeat → B 仍 rejected；A 崩溃（租约过期）→
B takeover；A 携带旧 token 返回 → mutation 全部被 fencing 拒绝。
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from tests.conftest import EPOCH0_US
from tests.test_m3_integrated_long import _fresh_m3, M3_LONG_WORLD_IDS
from tests.test_m3b_history import _hist_coordinator

from XiaoguangBlessedLandRuntime.services.scheduler import (RuntimeScheduler,
                                                            SchedulerConfig)
from XiaoguangBlessedLandRuntime.services.simulation.harness import YEAR_US

WORLD = M3_LONG_WORLD_IDS[0]


def _make(env, state_dir, *, budget=100_000_000, now_years=60) \
        -> RuntimeScheduler:
    return RuntimeScheduler(
        session_factory=env["factory"], world_id=env["world_id"],
        config=SchedulerConfig(catch_up_max_ticks_per_cycle=budget),
        real_now_us_provider=lambda: EPOCH0_US + now_years * YEAR_US,
        epoch0_us=EPOCH0_US, coordinator_provider=_hist_coordinator,
        state_dir=state_dir)


def test_single_writer_contention(tmp_path):
    env = _fresh_m3(tmp_path, 1, WORLD)
    state_dir = tmp_path / "rt"
    a = _make(env, state_dir / "a")
    b = _make(env, state_dir / "b")
    a.start()
    b.start()
    # A 取得 writer；B 被拒绝 → STANDBY，零 mutation
    sa = a.run_cycle().as_dict()
    assert sa["writer_owned"] is True
    assert sa["durable_current_tick"] == 60_000_000
    sb = b.run_cycle().as_dict()
    assert sb["scheduler_state"] == "STANDBY"
    assert sb["writer_owned"] is False
    with env["factory"]() as s:
        assert s.execute(text(
            "SELECT current_blessed_tick FROM world_runtime")).scalar() \
            == 60_000_000
    # A heartbeat（再跑 cycle，无 backlog → 续约）；B 仍被拒绝
    a.run_cycle()
    assert b.run_cycle().as_dict()["scheduler_state"] == "STANDBY"
    a.stop()
    b.stop()


def test_stale_writer_takeover_rejects_old_epoch(tmp_path):
    env = _fresh_m3(tmp_path, 2, WORLD)
    state_dir = tmp_path / "rt"
    a = _make(env, state_dir / "a", now_years=30)
    a.start()
    a.run_cycle()  # A 推进 30y，持有租约
    assert a.get_scheduler_status()["durable_current_tick"] == 30_000_000
    # A "崩溃"：进程死亡，租约自然过期（模拟 time jump）
    with env["factory"]() as s:
        s.execute(text(
            "UPDATE runtime_lock SET expires_at='2000-01-01'"))
        s.commit()
    # B takeover 并推进到 60y
    b = _make(env, state_dir / "b", now_years=60)
    b.start()
    b.run_cycle()
    assert b.get_scheduler_status()["durable_current_tick"] == 60_000_000
    assert b.get_scheduler_status()["lease_takeover_count"] == 1
    # A 复活（旧 token）：任何 mutation 被 fencing 拒绝 → RECOVERING，
    # stale writer 零写入
    a.run_cycle()
    snap = a.get_scheduler_status()
    assert snap["stale_writer_rejection_count"] == 1
    assert snap["writer_owned"] is False
    with env["factory"]() as s:
        assert s.execute(text(
            "SELECT current_blessed_tick FROM world_runtime")).scalar() \
            == 60_000_000
        assert s.execute(text(
            "SELECT COUNT(*) FROM runtime_lock")).scalar() == 1
    b.stop()

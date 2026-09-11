# -*- coding: utf-8 -*-
"""M4.5 Fencing Takeover（§11/§29）：≥4 次 takeover；stale writer mutations = 0。

每次：old epoch < new epoch（token 更替）；旧 writer 的 state/history/
checkpoint-as-truth mutation 全部失败；最终世界与无故障 direct 一致。
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


def _make(env, state_dir, *, now_years=40, budget=5_000_000) -> RuntimeScheduler:
    return RuntimeScheduler(
        session_factory=env["factory"], world_id=env["world_id"],
        config=SchedulerConfig(catch_up_max_ticks_per_cycle=budget),
        real_now_us_provider=lambda: EPOCH0_US + now_years * YEAR_US,
        epoch0_us=EPOCH0_US, coordinator_provider=_hist_coordinator,
        state_dir=state_dir)


def test_fencing_takeover_stress_4(tmp_path):
    env = _fresh_m3(tmp_path, 1, WORLD)
    state_dir = tmp_path / "rt"
    writers = []

    def advance_to(writer, target_years):
        while True:
            snap = writer.run_cycle().as_dict()
            tick = snap["durable_current_tick"]
            if tick is not None and tick >= target_years * 1_000_000:
                return
            assert snap["scheduler_state"] in (
                "RUNNING", "CATCHING_UP", "STANDBY"), snap

    def expire_lock():
        with env["factory"]() as s:
            s.execute(text(
                "UPDATE runtime_lock SET expires_at='2000-01-01'"))
            s.commit()

    # A 新取得 → 10y
    a = _make(env, state_dir / "a", now_years=40)
    a.start()
    advance_to(a, 10)
    # A 过期 → B 接管 → 20y
    expire_lock()
    b = _make(env, state_dir / "b", now_years=40)
    b.start()
    advance_to(b, 20)
    # A 复活（旧 token）→ 拒绝，零 mutation
    before_tick = _durable_tick(env)
    a.run_cycle()
    assert _durable_tick(env) == before_tick
    assert a.get_scheduler_status()["stale_writer_rejection_count"] == 1
    # B 过期 → C 接管 → 30y
    expire_lock()
    c = _make(env, state_dir / "c", now_years=40)
    c.start()
    advance_to(c, 30)
    before_tick = _durable_tick(env)
    b.run_cycle()
    assert _durable_tick(env) == before_tick
    # C 过期 → D 接管 → 40y
    expire_lock()
    d = _make(env, state_dir / "d", now_years=40)
    d.start()
    advance_to(d, 40)
    before_tick = _durable_tick(env)
    c.run_cycle()
    assert _durable_tick(env) == before_tick
    # D 过期 → E 接管（无 backlog，纯接管）
    expire_lock()
    e = _make(env, state_dir / "e", now_years=40)
    e.start()
    e.run_cycle()
    assert e.get_scheduler_status()["lease_takeover_count"] == 1
    before_tick = _durable_tick(env)
    d.run_cycle()
    assert _durable_tick(env) == before_tick
    # 总计：4 次 takeover（B/C/D/E），4 次 stale 拒绝（A/B/C/D）
    for w in (b, c, d, e):
        assert w.get_scheduler_status()["lease_takeover_count"] == 1
    for w in (a, b, c, d):
        assert w.get_scheduler_status()["stale_writer_rejection_count"] == 1
    e.stop()
    a.stop()
    # 最终与 direct 40y 完全一致；无残留租约
    ref = _fresh_m3(tmp_path, 2, WORLD)
    _m3_run(ref, years=40)
    assert _hashes(env) == _hashes(ref)
    with env["factory"]() as s:
        assert s.execute(text(
            "SELECT COUNT(*) FROM runtime_lock")).scalar() == 0  # stop 已释放


def _durable_tick(env) -> int | None:
    with env["factory"]() as s:
        return s.execute(text(
            "SELECT current_blessed_tick FROM world_runtime")).scalar()

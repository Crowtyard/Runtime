# -*- coding: utf-8 -*-
"""M4.6 Commit Ambiguity（§14）：unknown commit state ≠ safe to retry。

- 真 ACK lost（commit 已 durable）：RECOVERING → 读 durable truth →
  确认已提交 → 不重试、继续；最终无 duplicate。
- 假失败（commit 前异常）：durable truth 未推进 → FAILED（fail-closed），
  绝不盲重试。
- scheduler checkpoint ACK lost：checkpoint JSON 写后异常 → 旧 checkpoint
  或缺失均不改变 durable truth 恢复。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from tests.conftest import EPOCH0_US
from tests.test_m3_integrated_long import (_fresh_m3, _hashes, _m3_run,
                                           M3_LONG_WORLD_IDS)
from tests.test_m3b_history import _hist_coordinator
from tests.test_scheduler_ack_lost import _make as _make_base

from XiaoguangBlessedLandRuntime.services import fencing as fencing_mod
from XiaoguangBlessedLandRuntime.services.scheduler.adapter import \
    run_blessed_year

WORLD = M3_LONG_WORLD_IDS[0]


def _make(env, state_dir, *, now_years=12, budget=12_000_000):
    return _make_base(env, state_dir, now_years=now_years, budget=budget)


def test_unknown_commit_fail_closed_no_blind_retry(tmp_path, monkeypatch):
    """commit 前失败（durable 未推进）→ FAILED，绝不盲重试推进。"""
    env = _fresh_m3(tmp_path, 1, WORLD)
    state_dir = tmp_path / "rt"
    sched = _make(env, state_dir)
    sched.start()
    original = fencing_mod.WorldMutationContext.commit
    count = {"n": 0}

    def failing_commit(self):
        count["n"] += 1
        raise RuntimeError("commit failed before durable (simulated)")

    monkeypatch.setattr(fencing_mod.WorldMutationContext, "commit",
                        failing_commit)
    snap = sched.run_cycle().as_dict()
    assert snap["scheduler_state"] == "FAILED"
    assert snap["commit_ambiguity_count"] == 1
    with env["factory"]() as s:
        tick = s.execute(text(
            "SELECT current_blessed_tick FROM world_runtime")).scalar()
    assert tick in (0, None) or tick == 0  # 零推进（第一个 fenced 事务失败）
    monkeypatch.setattr(fencing_mod.WorldMutationContext, "commit", original)
    sched.stop()


def test_scheduler_checkpoint_ack_lost_recovery(tmp_path):
    """checkpoint 写出后异常（模拟 ACK lost）→ durable truth 完好，
    新实例继续且最终 == direct。"""
    env = _fresh_m3(tmp_path, 2, WORLD)
    state_dir = tmp_path / "rt"
    sched = _make(env, state_dir)
    sched.start()
    sched.run_cycle()  # 完成部分/全部 backlog + 写 checkpoint
    with env["factory"]() as s:
        tick_before = s.execute(text(
            "SELECT current_blessed_tick FROM world_runtime")).scalar()
    # 武装 checkpoint ACK lost：写出后抛异常（tmp 残留，正式 checkpoint 未替换）
    sched._checkpoint_crash_after_write = True
    with pytest.raises(RuntimeError, match="scheduler crash"):
        sched.run_cycle()
    with env["factory"]() as s:
        assert s.execute(text(
            "SELECT current_blessed_tick FROM world_runtime"
        )).scalar() == tick_before  # durable truth 不变
    # 新实例恢复（旧 checkpoint 可读则读，损坏则忽略；durable 优先）
    sched2 = _make(env, state_dir)
    sched2.start()
    snap = sched2.run_cycle().as_dict()
    assert snap["durable_current_tick"] == 12_000_000
    sched2.stop()
    ref = _fresh_m3(tmp_path, 3, WORLD)
    _m3_run(ref, years=12)
    assert _hashes(env) == _hashes(ref)


def test_commit_ambiguity_counters_and_no_duplicate_history(tmp_path,
                                                            monkeypatch):
    """真 ACK lost 路径（复用 ack harness 语义）不产生 duplicate tick/history。"""
    env = _fresh_m3(tmp_path, 4, WORLD)
    state_dir = tmp_path / "rt"
    ack_state = {"armed": False, "phase": 0}
    original = fencing_mod.WorldMutationContext.commit

    def patched(self):
        original(self)
        ack_state["phase"] += 1
        if ack_state["armed"] and ack_state["phase"] == 2:
            ack_state["armed"] = False
            raise RuntimeError("COMMIT ACK LOST (ambiguity)")

    monkeypatch.setattr(fencing_mod.WorldMutationContext, "commit", patched)
    counter = {"next_arm": 5, "count": 0}

    sched = _make(env, state_dir)
    sched.__class__ = type(
        "AmbSched", (sched.__class__,), {
            "_execute_batch": lambda self, plan, epoch0_us: _execute_armed(
                self, plan, epoch0_us, ack_state, counter)})
    sched.start()
    snap = sched.run_cycle().as_dict()
    assert snap["durable_current_tick"] == 12_000_000
    assert counter["count"] == 2  # 第 5、10 年
    sched.stop()
    ref = _fresh_m3(tmp_path, 5, WORLD)
    _m3_run(ref, years=12)
    assert _hashes(env) == _hashes(ref)
    for table in ("simulation_run", "world_events", "causal_history_links"):
        with env["factory"]() as s:
            a = s.execute(text(
                f'SELECT COUNT(*) FROM "{table}"')).scalar()
        with ref["factory"]() as s:
            b = s.execute(text(
                f'SELECT COUNT(*) FROM "{table}"')).scalar()
        assert a == b, table


def _execute_armed(sched, plan, epoch0_us, ack_state, counter):
    from XiaoguangBlessedLandRuntime.services.scheduler.adapter import \
        run_blessed_year
    executed = 0
    coordinator = None
    for year_index in plan.year_indices:
        if coordinator is None:
            coordinator = sched._coordinator_provider()
        if year_index == counter["next_arm"]:
            ack_state["armed"] = True
            ack_state["phase"] = 0
            counter["next_arm"] += 5
            counter["count"] += 1
        try:
            run_blessed_year(
                sched.session_factory, world_id=sched.world_id,
                year_index=year_index, coordinator=coordinator,
                lease=sched._lease, epoch0_us=epoch0_us,
                simulation_version=sched.simulation_version)
        except RuntimeError as exc:
            if not sched._recover_truth(year_index, exc):
                raise
        executed += 1_000_000
        sched._batches_total += 1
        sched._last_batch_ticks = 1_000_000
    return executed

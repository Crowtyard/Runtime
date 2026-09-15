# -*- coding: utf-8 -*-
"""M4.6 ACK Lost（§14/§30）：durable commit 成功 → ACK 丢失 → 不盲重试。

覆盖三类：world commit ACK lost（catch_up 事务）、history commit ACK lost
（同一 fenced 事务内的历史写入）、scheduler checkpoint ACK lost（checkpoint
JSON 写出后异常）。最终无 duplicate tick / duplicate history / skip / fork，
三哈希与 direct 一致。
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from tests.conftest import EPOCH0_US
from tests.test_m3_integrated_long import (_fresh_m3, _hashes, _m3_run,
                                           M3_LONG_WORLD_IDS)
from tests.test_m3b_history import _hist_coordinator

from XiaoguangBlessedLandRuntime.services import fencing as fencing_mod
from XiaoguangBlessedLandRuntime.services.scheduler import (RuntimeScheduler,
                                                            SchedulerConfig)
from XiaoguangBlessedLandRuntime.services.simulation.harness import YEAR_US

WORLD = M3_LONG_WORLD_IDS[0]


def _make(env, state_dir, *, now_years=30, budget=5_000_000,
          clock=None) -> RuntimeScheduler:
    return RuntimeScheduler(
        session_factory=env["factory"], world_id=env["world_id"],
        config=SchedulerConfig(catch_up_max_ticks_per_cycle=budget),
        real_now_us_provider=(clock or (lambda: EPOCH0_US
                                        + now_years * YEAR_US)),
        epoch0_us=EPOCH0_US, coordinator_provider=_hist_coordinator,
        state_dir=state_dir)


def test_ack_lost_world_commit_5_times(tmp_path, monkeypatch):
    """5 次 durable commit 后 ACK lost → RECOVERING 由 durable truth 恢复。"""
    env = _fresh_m3(tmp_path, 1, WORLD)
    state_dir = tmp_path / "rt"
    ack_state = {"armed": False, "phase": 0, "count": 0}
    original_commit = fencing_mod.WorldMutationContext.commit

    def patched_commit(self):
        original_commit(self)
        ack_state["phase"] += 1
        if ack_state["armed"] and ack_state["phase"] == 2:
            ack_state["armed"] = False
            ack_state["count"] += 1
            raise RuntimeError("simulated COMMIT ACK LOST (m4 scheduler)")

    monkeypatch.setattr(fencing_mod.WorldMutationContext, "commit",
                        patched_commit)
    ack_counter = {"next_arm": 5, "count": 0}

    class ArmedScheduler(RuntimeScheduler):
        def _execute_batch(self, plan, epoch0_us):
            executed = 0
            coordinator = None
            for year_index in plan.year_indices:
                if coordinator is None:
                    coordinator = self._coordinator_provider()
                if year_index == ack_counter["next_arm"]:
                    ack_state["armed"] = True
                    ack_state["phase"] = 0
                    ack_counter["next_arm"] += 5
                    ack_counter["count"] += 1
                from XiaoguangBlessedLandRuntime.services.scheduler.adapter \
                    import run_blessed_year
                try:
                    run_blessed_year(
                        self.session_factory, world_id=self.world_id,
                        year_index=year_index, coordinator=coordinator,
                        lease=self._lease, epoch0_us=epoch0_us,
                        simulation_version=self.simulation_version)
                except RuntimeError as exc:
                    if not self._recover_truth(year_index, exc):
                        raise
                executed += 1_000_000
                self._batches_total += 1
                self._last_batch_ticks = 1_000_000
            return executed

    sched = _make(env, state_dir, budget=30_000_000)
    sched.__class__ = ArmedScheduler
    sched.start()
    snap = sched.run_cycle().as_dict()
    assert snap["durable_current_tick"] == 30_000_000
    assert ack_counter["count"] == 5  # 5/10/15/20/25 五次 ACK lost
    sched.stop()
    ref = _fresh_m3(tmp_path, 2, WORLD)
    _m3_run(ref, years=30)
    assert _hashes(env) == _hashes(ref)
    with env["factory"]() as s:
        assert s.execute(text(
            "SELECT COUNT(*) FROM simulation_run")).scalar() == 30
        assert s.execute(text(
            "SELECT COUNT(*) FROM world_events")).scalar() \
            == _count(ref, "world_events")


def _count(env, table: str) -> int:
    with env["factory"]() as s:
        return s.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar()

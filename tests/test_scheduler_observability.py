# -*- coding: utf-8 -*-
"""M4.7 Observability（§18）：get_scheduler_status() 结构化快照。

read-only w.r.t. world semantics；DORMANT 时 durable_current_tick /
target_tick 为 NULL（不是 0）；各状态字段齐备。
"""
from __future__ import annotations

from pathlib import Path

from tests.conftest import EPOCH0_US
from tests.test_m3_integrated_long import (_fresh_m3, M3_LONG_WORLD_IDS)
from tests.test_m3b_history import _hist_coordinator
from tests.test_scheduler_lifecycle import make_scheduler

from XiaoguangBlessedLandRuntime.services.scheduler import (RuntimeScheduler,
                                                            SchedulerConfig)
from XiaoguangBlessedLandRuntime.services.simulation.harness import YEAR_US

WORLD = M3_LONG_WORLD_IDS[0]

REQUIRED_FIELDS = {
    "scheduler_state", "runtime_activation_state", "writer_owned",
    "writer_instance_id", "fencing_token", "last_scheduler_cycle",
    "last_successful_commit", "durable_current_tick", "target_tick",
    "pending_catchup_ticks", "last_batch_ticks", "catchup_batches_total",
    "recovery_count", "lease_takeover_count", "stale_writer_rejection_count",
    "commit_ambiguity_count", "last_error", "pause_state", "config",
}


def _make(env, state_dir, *, now_years=10, budget=10_000_000) \
        -> RuntimeScheduler:
    return RuntimeScheduler(
        session_factory=env["factory"], world_id=env["world_id"],
        config=SchedulerConfig(catch_up_max_ticks_per_cycle=budget),
        real_now_us_provider=lambda: EPOCH0_US + now_years * YEAR_US,
        epoch0_us=EPOCH0_US, coordinator_provider=_hist_coordinator,
        state_dir=state_dir)


def test_status_fields_complete_across_states(tmp_path):
    env = _fresh_m3(tmp_path, 1, WORLD)
    state_dir = tmp_path / "rt"
    sched = _make(env, state_dir)
    assert set(sched.get_scheduler_status()) == REQUIRED_FIELDS
    sched.start()
    sched.run_cycle()  # CATCHING_UP 批次
    snap = sched.get_scheduler_status()
    assert snap["durable_current_tick"] == 10_000_000
    assert snap["target_tick"] == 10_000_000
    assert snap["pending_catchup_ticks"] == 0
    assert snap["writer_owned"] is True
    assert snap["fencing_token"] is not None
    sched.pause()
    snap = sched.get_scheduler_status()
    assert snap["scheduler_state"] == "PAUSED"
    assert snap["pause_state"] is True
    assert snap["writer_owned"] is False
    sched.resume()
    sched.stop()
    assert sched.get_scheduler_status()["scheduler_state"] == "STOPPED"


def test_status_dormant_null_tick(tmp_path):
    from tests.test_scheduler_lifecycle import (fresh_scheduler_world,
                                                make_scheduler)
    env = fresh_scheduler_world(tmp_path, 2, activated=False)
    sched = make_scheduler(env, real_now_us_provider=lambda: EPOCH0_US)
    sched.start()
    sched.run_cycle()
    snap = sched.get_scheduler_status()
    assert snap["scheduler_state"] == "DORMANT"
    assert snap["runtime_activation_state"] == "NOT_ACTIVATED"
    assert snap["durable_current_tick"] is None
    assert snap["target_tick"] is None
    assert snap["pending_catchup_ticks"] == 0
    sched.stop()

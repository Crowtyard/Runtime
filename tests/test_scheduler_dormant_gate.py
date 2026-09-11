# -*- coding: utf-8 -*-
"""M4.2 NOT_ACTIVATED Dormancy Gate —— M4 第一重要验收测试。

使用当前正式世界形态（NOT_ACTIVATED / seed=NULL / tick=NULL / events=0）
启动 Scheduler 并运行多个 cycle，验证：
- scheduler_state = DORMANT
- 零 authoritative mutation、零 simulation 调用、零 history 写入、
  零 RNG 调用、零 World Seed 消费、零 Writer 租约
- 快照字段：durable_current_tick = NULL（不是 0）、target_tick = NULL、
  pending_catchup_ticks = 0

该测试作为 activation safety regression，任何后续阶段必须继续执行。
"""
from __future__ import annotations

import pytest
from sqlalchemy import select, text

from tests.conftest import EPOCH0_US
from tests.test_scheduler_lifecycle import (M4_WORLD_ID,
                                           fresh_scheduler_world,
                                           make_scheduler)

from XiaoguangBlessedLandRuntime.database.models_core import RuntimeLock


def _assert_formal_untouched(env):
    with env["factory"]() as s:
        row = s.execute(text(
            "SELECT runtime_status, world_seed_version, "
            "current_blessed_tick, last_committed_real_us "
            "FROM world_runtime")).mappings().one()
        assert row["runtime_status"] == "NOT_ACTIVATED"
        assert row["world_seed_version"] is None
        assert row["current_blessed_tick"] is None
        assert row["last_committed_real_us"] is None
        assert s.execute(text(
            "SELECT COUNT(*) FROM world_events")).scalar() == 0
        assert s.execute(text(
            "SELECT COUNT(*) FROM simulation_run")).scalar() == 0
        assert s.execute(text(
            "SELECT COUNT(*) FROM simulation_checkpoints")).scalar() == 0
        assert s.execute(select(RuntimeLock)).scalars().all() == []
        # history / 灾劫 / 领域表全部为 0
        for t in ("causal_history_links", "entity_history_index",
                  "history_state_changes", "history_episode_index",
                  "tribulation_episodes", "population_groups",
                  "resource_nodes", "households", "institutions",
                  "lineages", "ecology_state", "settlement_social_state"):
            assert s.execute(text(
                f'SELECT COUNT(*) FROM "{t}"')).scalar() == 0, t


def test_dormant_formal_world_zero_mutations(tmp_path):
    env = fresh_scheduler_world(tmp_path, 1, activated=False)
    engine_calls = []
    sched = make_scheduler(
        env,
        real_now_us_provider=lambda: EPOCH0_US + 500 * 86_400_000_000,
        coordinator_provider=lambda: engine_calls.append(1) or (_ for _ in ()).throw(
            AssertionError("engine 不得在未激活世界被调用")),
    )
    sched.start()
    for _ in range(5):
        snap = sched.run_cycle()
        assert snap.as_dict()["scheduler_state"] == "DORMANT"
        assert snap.as_dict()["durable_current_tick"] is None
        assert snap.as_dict()["target_tick"] is None
        assert snap.as_dict()["pending_catchup_ticks"] == 0
        assert snap.as_dict()["writer_owned"] is False
        assert snap.as_dict()["runtime_activation_state"] == "NOT_ACTIVATED"
    assert engine_calls == []
    _assert_formal_untouched(env)
    sched.stop()


def test_active_without_seed_still_dormant(tmp_path):
    """激活判定 = status + seed 双条件；ACTIVE 但 seed=NULL → 仍 DORMANT。"""
    env = fresh_scheduler_world(tmp_path, 2, activated=True, seed=False)
    sched = make_scheduler(env)
    sched.start()
    snap = sched.run_cycle()
    assert snap.as_dict()["scheduler_state"] == "DORMANT"
    with env["factory"]() as s:
        assert s.execute(select(RuntimeLock)).scalars().all() == []
        assert s.execute(text(
            "SELECT COUNT(*) FROM world_events")).scalar() == 0
    sched.stop()


def test_dormant_restart_cycles_still_zero(tmp_path):
    """重复 start/stop/run_cycle 依旧零 mutation（ACTIVATION TIME TRAP）。"""
    env = fresh_scheduler_world(tmp_path, 3, activated=False)
    for i in range(3):
        sched = make_scheduler(env)
        sched.start()
        sched.run_cycle()
        sched.run_cycle()
        sched.stop()
    _assert_formal_untouched(env)


def test_dormant_snapshot_semantics_null_not_zero(tmp_path):
    """§18：DORMANT 时 durable_current_tick 必须为 NULL，不是伪造的 0。"""
    env = fresh_scheduler_world(tmp_path, 4, activated=False)
    sched = make_scheduler(env)
    sched.start()
    snap = sched.run_cycle().as_dict()
    assert snap["durable_current_tick"] is None
    assert snap["target_tick"] is None
    sched.stop()

# -*- coding: utf-8 -*-
"""M4.1 Scheduler lifecycle 测试：状态机 / 幂等 start-stop / 配置校验 /
持久化 checkpoint（pause 位/计数器）。

全部使用 synthetic 临时世界；正式世界 / World Seed 零接触。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select, text

from tests.conftest import EPOCH0, EPOCH0_US, PROJECT_ROOT

from XiaoguangBlessedLandRuntime.database.db import (create_db_engine,
                                                     make_session_factory)
from XiaoguangBlessedLandRuntime.database.models_core import (RuntimeLock,
                                                              WorldRuntime)
from XiaoguangBlessedLandRuntime.domain.constants import RuntimeStatus
from XiaoguangBlessedLandRuntime.services.db_lifecycle import migrate_database
from XiaoguangBlessedLandRuntime.services.repositories import (
    RuntimeRepository, TimeRatioRepository)
from XiaoguangBlessedLandRuntime.services.scheduler import (RuntimeScheduler,
                                                            SchedulerConfig,
                                                            SchedulerState)
from XiaoguangBlessedLandRuntime.services.simulation.harness import YEAR_US
from XiaoguangBlessedLandRuntime.services.simulation.mini_world import \
    seed_mini_world

REPO = PROJECT_ROOT
M4_WORLD_ID = "M4SCHED-001"
SIM_VERSION = "0.3.0-m3a"


def fresh_scheduler_world(tmp_path: Path, i: int, *,
                          world_id: str = M4_WORLD_ID,
                          activated: bool = True,
                          seed: bool = True):
    """synthetic 调度测试世界。

    activated=True：ACTIVE + seed + tick=0 + cursor=EPOCH0（后半段生命周期）。
    activated=False：NOT_ACTIVATED + seed=NULL + tick=NULL（正式世界形态）。
    """
    db_path = tmp_path / f"m4_sched_{i}.db"
    url = "sqlite:///" + str(db_path).replace("\\", "/")
    migrate_database(url, project_root=REPO)
    engine = create_db_engine(url)
    factory = make_session_factory(engine)
    with factory() as s:
        if activated and seed:
            RuntimeRepository(s).create_not_activated(
                world_id=world_id, world_bible_version="1.0",
                simulation_version=SIM_VERSION,
                world_bible_manifest_hash="m4-test")
            row = s.execute(select(WorldRuntime)).scalar_one()
            row.runtime_status = RuntimeStatus.ACTIVE
            row.world_seed_version = "M4-TEST-SEED-001"
            row.current_blessed_tick = 0
            row.last_committed_real_us = EPOCH0_US
            row.time_rate_remainder = 0
            rate = TimeRatioRepository(s).add(
                world_id=world_id, real_effective_from=EPOCH0,
                rate_numerator=1_000_000, rate_denominator=86_400_000_000,
                reason="TEST", source="TEST")
            row.current_time_ratio_id = rate.ratio_id
            seed_mini_world(s, with_ecology=True, with_social=True,
                            with_tribulation=True, world_id=world_id)
        elif activated and not seed:
            RuntimeRepository(s).create_not_activated(
                world_id=world_id, world_bible_version="1.0",
                simulation_version=SIM_VERSION,
                world_bible_manifest_hash="m4-test")
            row = s.execute(select(WorldRuntime)).scalar_one()
            row.runtime_status = RuntimeStatus.ACTIVE
            # seed 保持 NULL：激活判定 = status + seed 双条件
        else:
            RuntimeRepository(s).create_not_activated(
                world_id=world_id, world_bible_version="1.0",
                simulation_version=SIM_VERSION,
                world_bible_manifest_hash="m4-test")
        s.commit()
    return {"url": url, "factory": factory, "db_path": db_path,
            "world_id": world_id}


def make_scheduler(env, **kw) -> RuntimeScheduler:
    defaults = dict(
        session_factory=env["factory"],
        world_id=env["world_id"],
        config=SchedulerConfig(),
        real_now_us_provider=lambda: EPOCH0_US + 10 * YEAR_US,
        epoch0_us=EPOCH0_US,
        coordinator_provider=lambda: (_ for _ in ()).throw(
            AssertionError("engine 不应被调用")),
        state_dir=Path(env["db_path"]).parent / "runtime_state",
    )
    defaults.update(kw)
    return RuntimeScheduler(**defaults)


# ---------------------------------------------------------------- 配置校验
def test_scheduler_config_validation():
    with pytest.raises(ValueError):
        SchedulerConfig(poll_interval_ms=0)
    with pytest.raises(ValueError):
        SchedulerConfig(catch_up_max_ticks_per_cycle=0)
    with pytest.raises(ValueError):
        SchedulerConfig(heartbeat_interval_ms=0)
    with pytest.raises(ValueError):
        SchedulerConfig(lease_ttl_ms=0)
    with pytest.raises(ValueError):
        SchedulerConfig(heartbeat_interval_ms=120_000, lease_ttl_ms=120_000)
    with pytest.raises(ValueError):
        SchedulerConfig(shutdown_grace_ms=-1)
    cfg = SchedulerConfig(lease_ttl_ms=121_000, heartbeat_interval_ms=120_000)
    assert cfg.lease_seconds() == 121
    assert cfg.batch_years_per_cycle() == 100


# ---------------------------------------------------------------- 生命周期
def test_start_stop_idempotent(tmp_path):
    env = fresh_scheduler_world(tmp_path, 1, activated=False)
    sched = make_scheduler(env)
    assert sched.start() is True
    assert sched.start() is False  # 不产生第二个循环
    assert sched.get_scheduler_status()["scheduler_state"] == "STARTING"
    sched.stop()
    sched.stop()  # 幂等
    assert sched.get_scheduler_status()["scheduler_state"] == "STOPPED"


def test_run_cycle_before_start_raises(tmp_path):
    env = fresh_scheduler_world(tmp_path, 2, activated=False)
    sched = make_scheduler(env)
    with pytest.raises(RuntimeError):
        sched.run_cycle()


def test_failed_state_fail_closed(tmp_path):
    env = fresh_scheduler_world(tmp_path, 3, activated=False)
    sched = make_scheduler(env)
    sched.start()
    sched._fail("diagnostic failure")
    assert sched.get_scheduler_status()["scheduler_state"] == "FAILED"
    with pytest.raises(RuntimeError):
        sched.run_cycle()


def test_stop_while_dormant(tmp_path):
    env = fresh_scheduler_world(tmp_path, 4, activated=False)
    sched = make_scheduler(env)
    sched.start()
    snap = sched.run_cycle()
    assert snap.as_dict()["scheduler_state"] == "DORMANT"
    sched.stop()
    assert sched.get_scheduler_status()["scheduler_state"] == "STOPPED"
    with env["factory"]() as s:
        assert s.execute(select(RuntimeLock)).scalars().all() == []


def test_checkpoint_persistence_restart_while_paused(tmp_path):
    env = fresh_scheduler_world(tmp_path, 5, activated=True)
    state_dir = Path(env["db_path"]).parent / "runtime_state"
    sched = make_scheduler(env, state_dir=state_dir,
                           real_now_us_provider=lambda: EPOCH0_US)
    sched.start()
    sched.run_cycle()  # 无 backlog → RUNNING（不触发引擎）
    sched.pause()
    assert sched.get_scheduler_status()["pause_state"] is True

    # 模拟 Runtime 重启：新实例加载持久化 checkpoint → pause 保持
    sched2 = make_scheduler(env, state_dir=state_dir)
    sched2.start()
    assert sched2.get_scheduler_status()["pause_state"] is True
    sched2.run_cycle()
    assert sched2.get_scheduler_status()["scheduler_state"] == "PAUSED"
    # resume 显式清除
    sched2.resume()
    assert sched2.get_scheduler_status()["pause_state"] is False
    sched2.stop()


def test_checkpoint_durable_truth_wins(tmp_path):
    """checkpoint 损坏/伪造时，durable truth 优先（不因 checkpoint 猜测世界真值）。"""
    env = fresh_scheduler_world(tmp_path, 6, activated=False)
    state_dir = Path(env["db_path"]).parent / "runtime_state"
    sched = make_scheduler(env, state_dir=state_dir)
    sched.start()
    sched.pause()
    # 破坏 checkpoint（模拟损坏）
    cp = state_dir / "scheduler_state.json"
    cp.write_text("{corrupt json", encoding="utf-8")
    sched2 = make_scheduler(env, state_dir=state_dir)
    sched2.start()  # 不得抛异常；损坏 checkpoint 被忽略
    assert sched2.get_scheduler_status()["pause_state"] is False
    sched2.stop()

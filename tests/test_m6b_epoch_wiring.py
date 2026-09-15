# -*- coding: utf-8 -*-
"""M6B-EW —— Runtime Epoch Wiring（OPTION A / owner §1–§4）。

要求：
- 未激活 → scheduler 保持既有 dormant/default operational 行为；
- 已激活 → scheduler 年锚 = **durable activation epoch anchor**；
  不得按当前时间重新生成，不得在 restart / 进程替换 / crash recovery 后改变；
- 激活后：tick = 0，cursor = anchor + 0×YEAR_US；此后 tick = k×10⁶、
  cursor = anchor + k×YEAR_US（完全服从冻结 M1 planner）；
- 持久化的 anchor/tick 不自洽 → fail closed，**不得偷偷 repair**。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select, text

from tests.conftest import EPOCH0_US, W
from tests.m6_activation_support import (
    M6_EPOCH0_US, build_synthetic_seed, new_synthetic_world,
    synthetic_request, world_counts)
from tests.test_m3b_history import _hist_coordinator

from XiaoguangBlessedLandRuntime.database.db import (
    create_db_engine, make_session_factory)
from XiaoguangBlessedLandRuntime.database.models_core import WorldRuntime
from XiaoguangBlessedLandRuntime.domain.constants import RuntimeStatus
from XiaoguangBlessedLandRuntime.services.activation import (
    activate_formal_world)
from XiaoguangBlessedLandRuntime.services.scheduler import (
    RuntimeScheduler, SchedulerConfig, SchedulerState)
from XiaoguangBlessedLandRuntime.services.scheduler.core import (
    DEFAULT_OPERATIONAL_EPOCH0_US)
from XiaoguangBlessedLandRuntime.services.simulation.harness import YEAR_US

#: 任意 UTC anchor（既不是 operational 默认锚，也不是年整点）
ARBITRARY_ANCHOR = M6_EPOCH0_US + 12_345


def _unactivated_world(tmp_path, tag: str = "u"):
    """未激活的合成世界（metadata + 自然态速率，无 activation）。"""
    env = new_synthetic_world(tmp_path / tag)
    env["anchor_us"] = None
    return env


def _activated_world(tmp_path, anchor: int = ARBITRARY_ANCHOR, tag: str = "a"):
    """经 M6 activation 服务激活的合成世界（tick=0，anchor 为给定 UTC instant）。"""
    env = new_synthetic_world(tmp_path / tag)
    seed_dir = build_synthetic_seed(tmp_path, name=f"seed_{tag}")
    out = activate_formal_world(env["factory"], request=synthetic_request(
        seed_dir, world_id=W, activation_anchor_us=anchor))
    assert out.outcome == "COMMITTED"
    env["anchor_us"] = anchor
    return env


def _dynamic_scheduler(env, *, now_us: int, tmp_path,
                       provider=None) -> RuntimeScheduler:
    """**不传** epoch0_us → OPTION A 动态模式（年锚来自 durable truth）。"""
    return RuntimeScheduler(
        session_factory=env["factory"], world_id=W,
        config=SchedulerConfig(),
        real_now_us_provider=lambda: now_us,
        coordinator_provider=(provider or _hist_coordinator),
        state_dir=tmp_path / "runtime_state")


def _row(factory) -> WorldRuntime:
    with factory() as s:
        return s.execute(select(WorldRuntime)).scalar_one()


# ------------------------------------------------------------------ EW-01
def test_m6b_ew01_unactivated_scheduler_keeps_default_and_dormant(tmp_path):
    """未激活 → 年锚沿用 operational 默认，scheduler DORMANT、零 mutation。"""
    env = _unactivated_world(tmp_path)
    sched = _dynamic_scheduler(env, now_us=M6_EPOCH0_US + 5 * YEAR_US,
                               tmp_path=tmp_path)
    row = _row(env["factory"])
    assert sched._effective_epoch0_us(row) == DEFAULT_OPERATIONAL_EPOCH0_US
    assert sched.epoch0_us == DEFAULT_OPERATIONAL_EPOCH0_US
    sched.start()
    snap = sched.run_cycle().as_dict()
    assert snap["scheduler_state"] == SchedulerState.DORMANT.value
    assert snap["runtime_activation_state"] == "NOT_ACTIVATED"
    assert snap["durable_current_tick"] is None
    sched.stop()
    counts = world_counts(env["factory"])
    assert counts["world_events"] == 0
    assert counts["simulation_runs"] == 0
    env["engine"].dispose()


# ------------------------------------------------------------------ EW-02
def test_m6b_ew02_activated_scheduler_reads_durable_anchor(tmp_path):
    """已激活 → scheduler 用 durable anchor 规划并推进（不是 2026-01-01 默认锚）。"""
    env = _activated_world(tmp_path)
    anchor = env["anchor_us"]
    assert anchor != DEFAULT_OPERATIONAL_EPOCH0_US
    sched = _dynamic_scheduler(env, now_us=anchor + 2 * YEAR_US,
                               tmp_path=tmp_path)
    row = _row(env["factory"])
    assert sched._effective_epoch0_us(row) == anchor     # durable 读取
    assert sched.epoch0_us == DEFAULT_OPERATIONAL_EPOCH0_US  # 属性仍是默认（未改语义）

    sched.start()
    for _ in range(3):
        snap = sched.run_cycle().as_dict()
        if snap["durable_current_tick"] == 2_000_000:
            break
    assert snap["durable_current_tick"] == 2_000_000
    assert snap["scheduler_state"] in ("RUNNING", "CATCHING_UP")
    assert snap["last_error"] is None
    sched.stop()

    row2 = _row(env["factory"])
    assert row2.current_blessed_tick == 2_000_000
    assert row2.last_committed_real_us == anchor + 2 * YEAR_US   # 年锚对齐
    env["engine"].dispose()


# ------------------------------------------------------------------ EW-03
def test_m6b_ew03_anchor_is_stable_across_restart_and_process_replacement(
        tmp_path):
    """restart / 进程替换（新 engine+session factory）读回完全相同的 anchor。"""
    env = _activated_world(tmp_path)
    anchor = env["anchor_us"]
    sched1 = _dynamic_scheduler(env, now_us=anchor, tmp_path=tmp_path)
    a1 = sched1._effective_epoch0_us(_row(env["factory"]))

    # restart：新 scheduler 实例（同库）
    sched2 = _dynamic_scheduler(env, now_us=anchor + 30 * YEAR_US,
                                tmp_path=tmp_path)
    a2 = sched2._effective_epoch0_us(_row(env["factory"]))

    # 进程替换：全新 engine / session factory 打开同一个库文件
    url = env["url"]
    engine2 = create_db_engine(url)
    factory2 = make_session_factory(engine2)
    sched3 = RuntimeScheduler(session_factory=factory2, world_id=W,
                              config=SchedulerConfig(),
                              real_now_us_provider=lambda: anchor,
                              coordinator_provider=_hist_coordinator,
                              state_dir=tmp_path / "rs2")
    with factory2() as s:
        row3 = s.execute(select(WorldRuntime)).scalar_one()
    a3 = sched3._effective_epoch0_us(row3)

    assert a1 == a2 == a3 == anchor
    engine2.dispose()
    env["engine"].dispose()


# ------------------------------------------------------------------ EW-04
def test_m6b_ew04_wall_clock_change_does_not_change_anchor(tmp_path):
    """不同现实时刻读同一世界 → anchor 恒定；读状态零写入。"""
    env = _activated_world(tmp_path)
    anchor = env["anchor_us"]
    before = world_counts(env["factory"])
    anchors = []
    for now_us in (anchor, anchor + 100 * YEAR_US, anchor - 999, EPOCH0_US):
        sched = _dynamic_scheduler(env, now_us=now_us, tmp_path=tmp_path)
        anchors.append(sched._effective_epoch0_us(_row(env["factory"])))
        sched.start()
        sched.get_scheduler_status()          # 只读快照
        sched.stop()
    assert set(anchors) == {anchor}
    assert world_counts(env["factory"]) == before
    env["engine"].dispose()


# ------------------------------------------------------------------ EW-05
def test_m6b_ew05_mismatched_persisted_anchor_fails_closed_without_repair(
        tmp_path):
    """tick 与 anchor 不自洽 → FAILED，且**绝不**偷偷 repair。"""
    env = _activated_world(tmp_path)
    anchor = env["anchor_us"]
    with env["factory"]() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        row.current_blessed_tick = 5_000_000            # 人为制造不自洽
        s.commit()
    before = _snapshot_row(env["factory"])

    sched = _dynamic_scheduler(env, now_us=anchor + 8 * YEAR_US,
                               tmp_path=tmp_path)
    sched.start()
    snap = sched.run_cycle().as_dict()
    assert snap["scheduler_state"] == SchedulerState.FAILED.value
    assert "年锚" in (snap["last_error"] or "") or \
        "anchor" in (snap["last_error"] or "").lower()
    after = _snapshot_row(env["factory"])
    assert after == before                              # 零写入、零 repair
    env["engine"].dispose()


def _snapshot_row(factory) -> dict:
    with factory() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        events = int(s.execute(text(
            "SELECT COUNT(*) FROM world_events")).scalar())
        runs = int(s.execute(text(
            "SELECT COUNT(*) FROM simulation_run")).scalar())
    return {"tick": row.current_blessed_tick,
            "cursor": row.last_committed_real_us,
            "status": row.runtime_status, "seed": row.world_seed_version,
            "events": events, "runs": runs}


# ------------------------------------------------------------------ EW-06
def test_m6b_ew06_missing_durable_anchor_fails_closed(tmp_path):
    """已激活但没有 durable anchor → FAILED（绝不回落到默认锚）。"""
    from XiaoguangBlessedLandRuntime.domain.constants import (
        EventSources, Scopes)
    from XiaoguangBlessedLandRuntime.services.repositories import (
        EventRepository)

    env = new_synthetic_world(tmp_path / "na")
    with env["factory"]() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        row.runtime_status = RuntimeStatus.ACTIVE
        row.world_seed_version = "1.0"
        row.current_blessed_tick = 0
        row.last_committed_real_us = M6_EPOCH0_US
        EventRepository(s).append(
            world_id=W, event_type="WORLD_SEED_ACTIVATED",
            source=EventSources.OWNER_INPUT, blessed_tick=0,
            scope=Scopes.WORLD, event_uid="a" * 32,
            effect={"note": "anchor deliberately absent"})
        s.commit()
    before = _snapshot_row(env["factory"])
    sched = _dynamic_scheduler(env, now_us=M6_EPOCH0_US + YEAR_US,
                               tmp_path=tmp_path)
    assert sched._effective_epoch0_us(_row(env["factory"])) is None
    sched.start()
    snap = sched.run_cycle().as_dict()
    assert snap["scheduler_state"] == SchedulerState.FAILED.value
    assert "anchor" in (snap["last_error"] or "").lower() or \
        "年锚" in (snap["last_error"] or "")
    assert _snapshot_row(env["factory"]) == before
    env["engine"].dispose()


# ------------------------------------------------------------------ EW-07
@pytest.mark.parametrize("years", [1, 3])
def test_m6b_ew07_scheduler_alignment_contract_after_activation(tmp_path,
                                                               years):
    """激活后 k 年：tick = k×10⁶、cursor = anchor + k×YEAR_US（冻结 M1 planner）。"""
    env = _activated_world(tmp_path, tag=f"al{years}")
    anchor = env["anchor_us"]
    sched = _dynamic_scheduler(env, now_us=anchor + years * YEAR_US,
                               tmp_path=tmp_path)
    sched.start()
    for _ in range(2 * years + 2):
        snap = sched.run_cycle().as_dict()
        if snap["durable_current_tick"] == years * 1_000_000:
            break
    assert snap["durable_current_tick"] == years * 1_000_000
    row = _row(env["factory"])
    assert row.current_blessed_tick == years * 1_000_000
    assert row.last_committed_real_us == anchor + years * YEAR_US
    sched.stop()
    env["engine"].dispose()

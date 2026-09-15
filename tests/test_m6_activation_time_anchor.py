# -*- coding: utf-8 -*-
"""M6A-TA —— 激活时间锚与"激活前现实时间"语义（A3 / owner §10、§11、§14）。

- A3：世界在 NOT_ACTIVATED 期间**不得**累积 offline catch-up debt；
  激活的现实锚 = 激活 canonical instant（年锚对齐），backlog ≡ 0；
- 速率行 ``blessed_effective_from_tick`` 由 NULL（未开始计）→ initial tick；
- §14：durable commit 之前 scheduler 保持 DORMANT；之后才允许离开 DORMANT。
"""
from __future__ import annotations

import pytest
from sqlalchemy import select, text

from tests.conftest import EPOCH0, EPOCH0_US, W
from tests.m6_activation_support import (
    M6_EPOCH0_US, build_synthetic_seed, synthetic_request, world_counts,
    year_tick)
from tests.test_scheduler_lifecycle import (
    M4_WORLD_ID, SIM_VERSION, fresh_scheduler_world, make_scheduler)

from XiaoguangBlessedLandRuntime.database.models_core import WorldRuntime
from XiaoguangBlessedLandRuntime.domain.errors import WorldNotActivated
from XiaoguangBlessedLandRuntime.services.activation import (
    activate_formal_world)
from XiaoguangBlessedLandRuntime.services.catchup import catch_up
from XiaoguangBlessedLandRuntime.services.repositories import (
    TimeRatioRepository)
from XiaoguangBlessedLandRuntime.services.scheduler import SchedulerState
from XiaoguangBlessedLandRuntime.services.simulation.harness import YEAR_US
from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease


def _activate(seed_dir, factory, *, world_id: str = W, **kw):
    return activate_formal_world(factory, request=synthetic_request(
        seed_dir, world_id=world_id, **kw))


# ------------------------------------------------------------------ TA-01
def test_m6ta01_anchor_is_the_activation_canonical_instant(tmp_path, m6_world):
    seed_dir = build_synthetic_seed(tmp_path)
    tick = year_tick(4)
    out = _activate(seed_dir, m6_world, initial_blessed_tick=tick,
                    epoch0_us=M6_EPOCH0_US)
    expected_anchor = M6_EPOCH0_US + 4 * YEAR_US
    assert out.activation_real_us == expected_anchor
    assert out.pre_activation_backlog_ticks == 0
    with m6_world() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        assert row.last_committed_real_us == expected_anchor
        assert row.current_blessed_tick == tick
    # 激活本身不推进世界（无 run / 无 checkpoint / 零 backlog）
    counts = world_counts(m6_world)
    assert counts["simulation_runs"] == 0
    assert counts["checkpoints"] == 0


# ------------------------------------------------------------------ TA-02
def test_m6ta02_pre_activation_window_is_never_backfilled(tmp_path, m6_world):
    """A3：metadata 播种（更早）到激活之间的现实时间不得变成福地历史。"""
    seed_dir = build_synthetic_seed(tmp_path)
    # 激活时刻晚于速率行起点（模拟"播种后过了很久才激活"）
    late_epoch0 = M6_EPOCH0_US + 30 * YEAR_US
    out = _activate(seed_dir, m6_world, initial_blessed_tick=0,
                    epoch0_us=late_epoch0)
    assert out.activation_real_us == late_epoch0
    with m6_world() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        assert row.current_blessed_tick == 0            # 未补算任何"过去"
        assert row.last_committed_real_us == late_epoch0
    assert world_counts(m6_world)["simulation_runs"] == 0


# ------------------------------------------------------------------ TA-03
def test_m6ta03_first_catchup_integrates_only_post_activation_time(
        tmp_path, m6_world):
    """激活后第一次 catch-up 只积分 [anchor, now]，绝不回溯。"""
    seed_dir = build_synthetic_seed(tmp_path)
    _activate(seed_dir, m6_world, initial_blessed_tick=0,
              epoch0_us=M6_EPOCH0_US)
    holder = m6_world()
    lease = WriterLease(holder, W, 120)
    lease.acquire()
    try:
        # now == anchor → 无需推进（delta 0；无 retroactive catch-up）
        r0 = catch_up(m6_world, world_id=W, now_real_us=M6_EPOCH0_US,
                      writer_id=lease.owner, fencing_token=lease.token)
        assert r0.skipped is True and r0.delta_ticks == 0

        # now == anchor + 1 现实天 → 自然态恰好 1 福地年
        r1 = catch_up(m6_world, world_id=W, now_real_us=M6_EPOCH0_US + YEAR_US,
                      writer_id=lease.owner, fencing_token=lease.token)
        assert r1.delta_ticks == year_tick(1)
        assert r1.new_blessed_tick == year_tick(1)
    finally:
        lease.release()
        holder.close()


# ------------------------------------------------------------------ TA-04
def test_m6ta04_rate_row_blessed_start_bound_at_activation(tmp_path, m6_world):
    with m6_world() as s:
        before = s.execute(text(
            "SELECT blessed_effective_from_tick FROM time_ratio_history"
        )).scalars().all()
    assert before == [None]                     # 未激活 = 尚未开始计

    seed_dir = build_synthetic_seed(tmp_path)
    tick = year_tick(2)
    _activate(seed_dir, m6_world, initial_blessed_tick=tick)
    with m6_world() as s:
        starts = s.execute(text(
            "SELECT blessed_effective_from_tick FROM time_ratio_history"
        )).scalars().all()
        row = s.execute(select(WorldRuntime)).scalar_one()
    assert starts == [tick]
    assert row.current_time_ratio_id is not None


# ------------------------------------------------------------------ TA-05
def test_m6ta05_no_catchup_possible_before_activation(tmp_path, m6_world):
    """未激活世界：任何推进入口都必须拒绝且零写入（guard 不变）。"""
    with m6_world() as s:
        for action in ("offline_catchup", "advance_world"):
            with pytest.raises(WorldNotActivated):
                from XiaoguangBlessedLandRuntime.services.guard import (
                    require_world_activated)
                require_world_activated(s, action)
    counts = world_counts(m6_world)
    assert counts["simulation_runs"] == 0
    assert counts["world_events"] == 0


# ------------------------------------------------------------------ TA-06
def test_m6ta06_scheduler_dormant_before_activation(tmp_path):
    """§14 前半：durable commit 之前 scheduler 必须保持 DORMANT、零 mutation。"""
    env = fresh_scheduler_world(tmp_path, 61, activated=False,
                               world_id=M4_WORLD_ID)
    sched = make_scheduler(env, coordinator_provider=None)
    sched.start()
    snap = sched.run_cycle().as_dict()
    assert snap["scheduler_state"] == SchedulerState.DORMANT.value
    assert snap["runtime_activation_state"] == "NOT_ACTIVATED"
    assert snap["durable_current_tick"] is None
    assert snap["target_tick"] is None
    assert snap["pending_catchup_ticks"] == 0
    assert snap["writer_owned"] is False
    with env["factory"]() as s:
        assert s.execute(text("SELECT COUNT(*) FROM world_events")).scalar() == 0
        assert s.execute(text("SELECT COUNT(*) FROM simulation_run")).scalar() == 0
    sched.stop()


# ------------------------------------------------------------------ TA-07
def test_m6ta07_scheduler_leaves_dormant_only_after_durable_commit(tmp_path):
    """§14 后半：durable commit 之后 scheduler 才允许离开 DORMANT。

    本仓库当前**没有** production 引擎注册表（coordinator 接线属后续里程碑），
    因此离开 DORMANT 的世界会在 batch 执行处 fail-closed —— 这仍然是
    "零部分推进"的正确行为：绝不在没有引擎时伪造世界推进。
    """
    env = fresh_scheduler_world(tmp_path, 62, activated=False,
                               world_id=M4_WORLD_ID)
    # 补齐 M6 激活前置：自然态速率行（现实起点 = 调度器年锚 EPOCH0）
    with env["factory"]() as s:
        TimeRatioRepository(s).add(
            world_id=M4_WORLD_ID, real_effective_from=EPOCH0,
            rate_numerator=1_000_000, rate_denominator=86_400_000_000,
            reason="TEST", source="TEST")
        s.commit()

    sched = make_scheduler(env, coordinator_provider=None)
    sched.start()
    assert sched.run_cycle().as_dict()["scheduler_state"] == \
        SchedulerState.DORMANT.value

    seed_dir = build_synthetic_seed(tmp_path)
    out = _activate(seed_dir, env["factory"], world_id=M4_WORLD_ID,
                    initial_blessed_tick=0, epoch0_us=EPOCH0_US,
                    simulation_version=SIM_VERSION)
    assert out.outcome == "COMMITTED"

    with env["factory"]() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        assert row.runtime_status == "ACTIVE"
        assert row.world_seed_version == "1.0"
    from XiaoguangBlessedLandRuntime.services.scheduler import RuntimeScheduler
    assert RuntimeScheduler._activated(row) is True

    # 世界已激活 → 不再 DORMANT；本仓库无引擎注册表 → 在该处 fail-closed
    with pytest.raises(Exception):  # noqa: B017  (RuntimeError: coordinator 未配置)
        for _ in range(3):
            sched.run_cycle()
    snap = sched.get_scheduler_status()
    assert snap["scheduler_state"] != SchedulerState.DORMANT.value
    assert snap["runtime_activation_state"] == "ACTIVE"
    assert snap["writer_owned"] is False           # 失败即释放租约
    # 但**绝不允许**部分推进：时钟与事件都不因这次失败而改变
    with env["factory"]() as s:
        row2 = s.execute(select(WorldRuntime)).scalar_one()
        assert row2.current_blessed_tick == 0
        assert row2.last_committed_real_us == EPOCH0_US
        assert s.execute(text("SELECT COUNT(*) FROM world_events")).scalar() == 1
        assert s.execute(text("SELECT COUNT(*) FROM simulation_run")).scalar() == 0
    sched.stop()


# ------------------------------------------------------------------ TA-08
def test_m6ta08_world_epoch_anchor_is_durable_and_readable(tmp_path, m6_world):
    """F2：激活确立的年锚必须可从 durable truth 读回（不是一次性 JSON 副作用）。

    Runtime 的 planner 必须用**同一个**年锚校验年锚不变量；本测试锁定
    ``read_world_epoch_anchor`` 先为 None（未激活）、激活后等于请求年锚。
    """
    from XiaoguangBlessedLandRuntime.services.durable_truth import (
        read_world_epoch_anchor)

    assert read_world_epoch_anchor(m6_world, world_id=W) is None
    seed_dir = build_synthetic_seed(tmp_path)
    tick = year_tick(3)
    _activate(seed_dir, m6_world, initial_blessed_tick=tick,
              epoch0_us=M6_EPOCH0_US)
    assert read_world_epoch_anchor(m6_world, world_id=W) == M6_EPOCH0_US
    # 年锚 + tick 必须自洽：cursor == epoch0 + year_index*YEAR_US
    with m6_world() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
    assert row.last_committed_real_us == M6_EPOCH0_US + 3 * YEAR_US

"""FENCING 必测用例 F1–F8（M1 第一硬门槛）。

覆盖：正常提交 / stale token 拒绝 / 租约互斥 / 过期 CAS 接管 / commit 前重验 /
stale checkpoint 拒绝 / stale run 终态拒绝 / 双 writer 单一时间线。
"""
from __future__ import annotations

import pytest
from sqlalchemy import select, text

from database.models_core import (RuntimeLock, SimulationCheckpoint,
                                  SimulationRun, WorldRuntime)
from domain.constants import RunStatus
from domain.errors import FencingViolation, WriterLockConflict
from services.fencing import WorldMutationContext
from services.repositories import CheckpointRepository
from services.run_lifecycle import SimulationRunRepository
from services.writer_lock import WriterLease

from tests.conftest import EPOCH0_US, W

DAY_US = 86_400_000_000


def _expire_lock(factory):
    with factory() as s:
        s.execute(text(
            "UPDATE runtime_lock SET expires_at = '2000-01-01 00:00:00+00:00'"))
        s.commit()


def _runtime_mutation(factory, writer_id, token):
    """一个最小世界状态写入（经统一 Mutation Guard）。"""
    with WorldMutationContext(factory(), world_id=W, writer_id=writer_id,
                              fencing_token=token) as ctx:
        row = ctx.session.execute(select(WorldRuntime)).scalar_one()
        row.last_committed_real_us = EPOCH0_US + 1
        ctx.commit()


def _cursor(factory):
    with factory() as s:
        return s.execute(select(WorldRuntime)).scalar_one().last_committed_real_us


def test_f1_commit_with_valid_token_passes(active_clock_factory, lease_helper):
    s, lease = lease_helper()
    try:
        _runtime_mutation(active_clock_factory, lease.owner, lease.token)
        assert _cursor(active_clock_factory) == EPOCH0_US + 1
    finally:
        lease.release()
        s.close()


def test_f2_stale_token_commit_fails(active_clock_factory, lease_helper):
    """Writer A token1；B 接管 token2 后，A commit → 必须失败、零写入。"""
    s1, lease1 = lease_helper()
    try:
        _expire_lock(active_clock_factory)
        s2 = active_clock_factory()
        lease2 = WriterLease(s2, W, 120)
        lease2.acquire()
        try:
            with pytest.raises(FencingViolation):
                _runtime_mutation(active_clock_factory, lease1.owner, lease1.token)
            assert _cursor(active_clock_factory) == EPOCH0_US  # A 零写入
            _runtime_mutation(active_clock_factory, lease2.owner, lease2.token)  # B 正常
        finally:
            lease2.release()
            s2.close()
    finally:
        s1.close()


def test_f3_second_writer_while_lease_live_fails(active_clock_factory, lease_helper):
    s1, lease1 = lease_helper()
    try:
        s2 = active_clock_factory()
        with pytest.raises(WriterLockConflict):
            WriterLease(s2, W, 120).acquire()
        s2.close()
    finally:
        lease1.release()
        s1.close()


def test_f4_expired_lease_cas_takeover_passes(active_clock_factory, lease_helper):
    s1, lease1 = lease_helper()
    s1.close()  # 模拟崩溃：租约残留
    _expire_lock(active_clock_factory)
    s2 = active_clock_factory()
    lease2 = WriterLease(s2, W, 120)
    lease2.acquire()  # CAS 接管成功
    try:
        with active_clock_factory() as s3:
            row = s3.execute(select(RuntimeLock)).scalar_one()
            assert row.lease_token == lease2.token
    finally:
        lease2.release()
        s2.close()


def test_f5_commit_time_fence_recheck(active_clock_factory, lease_helper):
    """事务开始时 token 有效、commit 前 token 已 stale → commit 必须失败、零写入。"""
    s, lease = lease_helper()
    try:
        with pytest.raises(FencingViolation):
            with WorldMutationContext(active_clock_factory(), world_id=W,
                                      writer_id=lease.owner,
                                      fencing_token=lease.token) as ctx:
                row = ctx.session.execute(select(WorldRuntime)).scalar_one()
                row.last_committed_real_us = EPOCH0_US + 7
                # 模拟 commit 前 fence 被替换
                ctx.session.execute(text(
                    "UPDATE runtime_lock SET lease_token='STOLEN' "
                    "WHERE world_id=:w"), {"w": W})
                ctx.commit()
        assert _cursor(active_clock_factory) == EPOCH0_US  # 零写入（整事务回滚）
    finally:
        lease.release()
        s.close()


def test_f6_stale_writer_cannot_write_checkpoint(active_clock_factory, lease_helper):
    s1, lease1 = lease_helper()
    try:
        _expire_lock(active_clock_factory)
        s2 = active_clock_factory()
        lease2 = WriterLease(s2, W, 120)
        lease2.acquire()
        try:
            with pytest.raises(FencingViolation):
                with WorldMutationContext(active_clock_factory(), world_id=W,
                                          writer_id=lease1.owner,
                                          fencing_token=lease1.token) as ctx:
                    CheckpointRepository(ctx.session).create(
                        world_id=W, blessed_tick=123, world_state_hash="x",
                        complete=True, last_committed_real_us=EPOCH0_US + 9,
                        writer_id=lease1.owner, fencing_token=lease1.token)
                    ctx.commit()
            with active_clock_factory() as s3:
                assert s3.execute(select(SimulationCheckpoint)).scalars().all() == []
        finally:
            lease2.release()
            s2.close()
    finally:
        s1.close()


def test_f7_stale_writer_cannot_finalize_run(active_clock_factory, lease_helper):
    s1, lease1 = lease_helper()
    try:
        with WorldMutationContext(active_clock_factory(), world_id=W,
                                  writer_id=lease1.owner,
                                  fencing_token=lease1.token) as ctx:
            run = SimulationRunRepository(ctx.session).create_run(
                world_id=W, simulation_version="0.1.0-dev",
                real_interval_start_us=EPOCH0_US,
                real_interval_end_us=EPOCH0_US + 1,
                blessed_tick_before=0, writer_id=lease1.owner,
                fencing_token=lease1.token)
            ctx.commit()
        _expire_lock(active_clock_factory)
        s2 = active_clock_factory()
        lease2 = WriterLease(s2, W, 120)
        lease2.acquire()
        try:
            # A（stale）试图提交 run 终态 → 拒绝
            with pytest.raises(FencingViolation):
                with WorldMutationContext(active_clock_factory(), world_id=W,
                                          writer_id=lease1.owner,
                                          fencing_token=lease1.token) as ctx:
                    r = SimulationRunRepository(ctx.session).get(run.run_id)
                    SimulationRunRepository(ctx.session).commit_run(
                        r, blessed_tick_after=1, blessed_tick_delta=1,
                        real_cursor_after_us=EPOCH0_US + 1)
                    ctx.commit()
            with active_clock_factory() as s3:
                r = s3.execute(select(SimulationRun).where(
                    SimulationRun.run_id == run.run_id)).scalar_one()
                assert r.status == RunStatus.RUNNING  # 未被 stale writer 改终态
            # B 接管后清理 stale RUNNING（Case G 恢复）
            with WorldMutationContext(active_clock_factory(), world_id=W,
                                      writer_id=lease2.owner,
                                      fencing_token=lease2.token) as ctx:
                SimulationRunRepository(ctx.session).fail_stale_running(
                    W, lease2.token)
                ctx.commit()
            with active_clock_factory() as s3:
                r = s3.execute(select(SimulationRun).where(
                    SimulationRun.run_id == run.run_id)).scalar_one()
                assert r.status == RunStatus.FAILED
        finally:
            lease2.release()
            s2.close()
    finally:
        s1.close()


def test_f8_two_writers_single_timeline(active_clock_factory, lease_helper):
    """并发两 Writer：最终 blessed time 只能增加一次（唯一时间线）。"""
    from services.catchup import catch_up
    s1, lease1 = lease_helper()
    try:
        _expire_lock(active_clock_factory)
        s2 = active_clock_factory()
        lease2 = WriterLease(s2, W, 120)
        lease2.acquire()
        try:
            # A（stale）重试 → fencing 拒绝
            with pytest.raises(FencingViolation):
                catch_up(active_clock_factory, world_id=W,
                         now_real_us=EPOCH0_US + DAY_US,
                         writer_id=lease1.owner, fencing_token=lease1.token)
            # B 正常推进一次
            res = catch_up(active_clock_factory, world_id=W,
                           now_real_us=EPOCH0_US + DAY_US,
                           writer_id=lease2.owner, fencing_token=lease2.token)
            assert res.skipped is False and res.delta_ticks == 1_000_000
            # B 重试同区间 → skip +0
            res2 = catch_up(active_clock_factory, world_id=W,
                            now_real_us=EPOCH0_US + DAY_US,
                            writer_id=lease2.owner, fencing_token=lease2.token)
            assert res2.skipped is True and res2.delta_ticks == 0
            with active_clock_factory() as s3:
                row = s3.execute(select(WorldRuntime)).scalar_one()
                assert row.current_blessed_tick == 1_000_000  # 只增加一次
                assert row.last_committed_real_us == EPOCH0_US + DAY_US
        finally:
            lease2.release()
            s2.close()
    finally:
        s1.close()


def test_mutation_context_rolls_back_without_explicit_commit(active_clock_factory,
                                                             lease_helper):
    s, lease = lease_helper()
    try:
        with WorldMutationContext(active_clock_factory(), world_id=W,
                                  writer_id=lease.owner,
                                  fencing_token=lease.token) as ctx:
            row = ctx.session.execute(select(WorldRuntime)).scalar_one()
            row.last_committed_real_us = EPOCH0_US + 42
            # 不调用 ctx.commit() → 必须回滚
        assert _cursor(active_clock_factory) == EPOCH0_US
    finally:
        lease.release()
        s.close()


def test_mutation_context_enter_fails_when_lease_expired(active_clock_factory,
                                                         lease_helper):
    s, lease = lease_helper()
    try:
        _expire_lock(active_clock_factory)
        with pytest.raises(FencingViolation):
            with WorldMutationContext(active_clock_factory(), world_id=W,
                                      writer_id=lease.owner,
                                      fencing_token=lease.token):
                pass
        assert _cursor(active_clock_factory) == EPOCH0_US
    finally:
        lease.release()
        s.close()

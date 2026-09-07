"""OFFLINE CATCH-UP / Crash Recovery / 幂等 / Checkpoint / Run 生命周期测试（M1）。"""
from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import select

from XiaoguangBlessedLandRuntime.database.models_core import (SimulationCheckpoint, SimulationRun,
                                  WorldEvent, WorldRuntime)
from XiaoguangBlessedLandRuntime.domain.blessed_time import epoch_us_to_datetime
from XiaoguangBlessedLandRuntime.domain.constants import RunStatus, SimulationVersion
from XiaoguangBlessedLandRuntime.domain.errors import FencingViolation, WorldNotActivated
from XiaoguangBlessedLandRuntime.services.catchup import catch_up
from XiaoguangBlessedLandRuntime.services.fencing import WorldMutationContext
from XiaoguangBlessedLandRuntime.services.repositories import CheckpointRepository, TimeRatioRepository
from XiaoguangBlessedLandRuntime.services.run_lifecycle import SimulationRunRepository

from tests.conftest import EPOCH0_US, W

DAY_US = 86_400_000_000
HOUR_US = 3_600_000_000


def _world(factory):
    with factory() as s:
        return s.execute(select(WorldRuntime)).scalar_one()


def test_catchup_30_days_natural(active_clock_factory, lease_helper):
    s, lease = lease_helper()
    try:
        res = catch_up(active_clock_factory, world_id=W,
                       now_real_us=EPOCH0_US + 30 * DAY_US,
                       writer_id=lease.owner, fencing_token=lease.token)
        assert res.skipped is False
        assert res.delta_ticks == 30_000_000
        assert res.new_blessed_tick == 30_000_000
        with active_clock_factory() as s2:
            row = s2.execute(select(WorldRuntime)).scalar_one()
            assert row.current_blessed_tick == 30_000_000
            assert row.last_committed_real_us == EPOCH0_US + 30 * DAY_US
            assert row.time_rate_remainder == 0
            # checkpoint 完整（crash 后仅依赖 DB 即可恢复）
            cp = s2.execute(select(SimulationCheckpoint)).scalar_one()
            assert cp.complete is True
            assert cp.checkpoint_blessed_tick == 30_000_000
            assert cp.last_committed_real_us == EPOCH0_US + 30 * DAY_US
            assert cp.rate_id is not None
            assert cp.rate_remainder == 0
            assert cp.simulation_version == SimulationVersion.CURRENT
            assert cp.last_committed_run_id == res.run_id
            assert cp.writer_id == lease.owner
            assert cp.fencing_token == lease.token
            # run 生命周期终态
            run = s2.execute(select(SimulationRun)).scalar_one()
            assert run.status == RunStatus.COMMITTED
            assert run.real_interval_start_us == EPOCH0_US
            assert run.real_interval_end_us == EPOCH0_US + 30 * DAY_US
            assert run.blessed_tick_before == 0
            assert run.blessed_tick_delta == 30_000_000
            assert run.real_cursor_after_us == EPOCH0_US + 30 * DAY_US
            # 仅基础设施事件（M1 不生成世界内容）
            events = s2.execute(select(WorldEvent)).scalars().all()
            assert [e.event_type for e in events] == ["TIME_ADVANCE"]
            assert [e.source for e in events] == ["SIMULATION"]
    finally:
        lease.release()
        s.close()


def test_catchup_365_days_natural(active_clock_factory, lease_helper):
    s, lease = lease_helper()
    try:
        res = catch_up(active_clock_factory, world_id=W,
                       now_real_us=EPOCH0_US + 365 * DAY_US,
                       writer_id=lease.owner, fencing_token=lease.token)
        assert res.delta_ticks == 365_000_000
        assert _world(active_clock_factory).current_blessed_tick == 365_000_000
    finally:
        lease.release()
        s.close()


def test_retry_same_interval_second_delta_zero(active_clock_factory, lease_helper):
    """相同区间重复执行：第一次 +1,000,000；第二次 retry +0。"""
    s, lease = lease_helper()
    try:
        r1 = catch_up(active_clock_factory, world_id=W,
                      now_real_us=EPOCH0_US + DAY_US,
                      writer_id=lease.owner, fencing_token=lease.token)
        r2 = catch_up(active_clock_factory, world_id=W,
                      now_real_us=EPOCH0_US + DAY_US,
                      writer_id=lease.owner, fencing_token=lease.token)
        assert r1.delta_ticks == 1_000_000
        assert r2.skipped is True and r2.delta_ticks == 0
        assert _world(active_clock_factory).current_blessed_tick == 1_000_000  # 不是 2,000,000
    finally:
        lease.release()
        s.close()


def test_catchup_authoritative_db_cursor(active_clock_factory, lease_helper):
    """权威游标在 DB：调用方传陈旧游标也不得重复累计同一现实区间。"""
    s, lease = lease_helper()
    try:
        catch_up(active_clock_factory, world_id=W,
                 now_real_us=EPOCH0_US + DAY_US,
                 writer_id=lease.owner, fencing_token=lease.token)
        res = catch_up(active_clock_factory, world_id=W,
                       now_real_us=EPOCH0_US + 2 * DAY_US,
                       last_real_cursor_us=EPOCH0_US,  # 陈旧调用方游标
                       writer_id=lease.owner, fencing_token=lease.token)
        assert res.delta_ticks == 1_000_000  # 只补 [1d, 2d]，不是 2,000,000
        assert _world(active_clock_factory).current_blessed_tick == 2_000_000
    finally:
        lease.release()
        s.close()


def test_chunked_restart_equals_whole(active_clock_factory, lease_helper):
    """24 × 1h 分块推进（每次全新 session=模拟重启，remainder 从 DB 恢复）
    == 一次整体推进 1,000,000。"""
    s, lease = lease_helper()
    try:
        total = 0
        for i in range(24):
            res = catch_up(active_clock_factory, world_id=W,
                           now_real_us=EPOCH0_US + (i + 1) * HOUR_US,
                           writer_id=lease.owner, fencing_token=lease.token)
            total += res.delta_ticks
        assert total == 1_000_000
        row = _world(active_clock_factory)
        assert row.current_blessed_tick == 1_000_000
        assert row.time_rate_remainder == 0
    finally:
        lease.release()
        s.close()


def test_remainder_persisted_across_restart(active_clock_factory, lease_helper):
    """重启后 remainder 从 DB 恢复：1s chunk 后 remainder=49,600,000,000，
    续推到完整一天，总 delta 与不重启完全一致。"""
    s, lease = lease_helper()
    try:
        r1 = catch_up(active_clock_factory, world_id=W,
                      now_real_us=EPOCH0_US + 1_000_000,
                      writer_id=lease.owner, fencing_token=lease.token)
        assert r1.delta_ticks == 11
        row = _world(active_clock_factory)
        assert row.time_rate_remainder == 49_600_000_000  # 持久化的进位
        assert row.current_blessed_tick == 11
        r2 = catch_up(active_clock_factory, world_id=W,
                      now_real_us=EPOCH0_US + DAY_US,
                      writer_id=lease.owner, fencing_token=lease.token)
        assert r1.delta_ticks + r2.delta_ticks == 1_000_000
        assert _world(active_clock_factory).current_blessed_tick == 1_000_000
    finally:
        lease.release()
        s.close()


def test_catchup_segments_four_rate_history(active_clock_factory, lease_helper):
    """DB 速率历史 A→B→C→D 四段：catch-up 必须按真实边界分段积分。"""
    s, lease = lease_helper()
    try:
        with active_clock_factory() as s2:
            tr = TimeRatioRepository(s2)
            tr.add(world_id=W, real_effective_from=epoch_us_to_datetime(
                       EPOCH0_US + 1 * DAY_US),
                   rate_numerator=500_000, rate_denominator=86_400_000_000,
                   reason="TEST-B", source="TEST")
            tr.add(world_id=W, real_effective_from=epoch_us_to_datetime(
                       EPOCH0_US + 2 * DAY_US),
                   rate_numerator=2_000_000, rate_denominator=86_400_000_000,
                   reason="TEST-C", source="TEST")
            tr.add(world_id=W, real_effective_from=epoch_us_to_datetime(
                       EPOCH0_US + 3 * DAY_US),
                   rate_numerator=250_000, rate_denominator=86_400_000_000,
                   reason="TEST-D", source="TEST")
            s2.commit()
        res = catch_up(active_clock_factory, world_id=W,
                       now_real_us=EPOCH0_US + 4 * DAY_US,
                       writer_id=lease.owner, fencing_token=lease.token)
        assert res.delta_ticks == 1_000_000 + 500_000 + 2_000_000 + 250_000
        row = _world(active_clock_factory)
        assert row.current_blessed_tick == 3_750_000
        assert row.time_rate_remainder == 0  # 整日分段整除
    finally:
        lease.release()
        s.close()


def test_crash_case_a_no_change_before_compute(active_clock_factory, lease_helper):
    """计算前 crash → 无变化。"""
    s, lease = lease_helper()
    try:
        with pytest.raises(RuntimeError):
            with WorldMutationContext(active_clock_factory(), world_id=W,
                                      writer_id=lease.owner,
                                      fencing_token=lease.token):
                raise RuntimeError("crash before compute")
        row = _world(active_clock_factory)
        assert row.current_blessed_tick == 0
        assert row.last_committed_real_us == EPOCH0_US
        with active_clock_factory() as s2:
            assert s2.execute(select(SimulationCheckpoint)).scalars().all() == []
    finally:
        lease.release()
        s.close()


def test_crash_case_b_after_compute_before_commit(active_clock_factory,
                                                  lease_helper):
    """计算后、commit 前 crash → 时钟/事件/checkpoint 全部无变化；run 置 FAILED。"""
    s, lease = lease_helper()
    try:
        def boom(session, info):  # noqa: ANN001, ANN202
            raise RuntimeError("crash after compute")

        with pytest.raises(RuntimeError):
            catch_up(active_clock_factory, world_id=W,
                     now_real_us=EPOCH0_US + DAY_US,
                     writer_id=lease.owner, fencing_token=lease.token,
                     simulate_fn=boom)
        row = _world(active_clock_factory)
        assert row.current_blessed_tick == 0
        assert row.last_committed_real_us == EPOCH0_US
        with active_clock_factory() as s2:
            assert s2.execute(select(WorldEvent)).scalars().all() == []
            assert s2.execute(select(SimulationCheckpoint)).scalars().all() == []
            runs = s2.execute(select(SimulationRun)).scalars().all()
            assert len(runs) == 1 and runs[0].status == RunStatus.FAILED
    finally:
        lease.release()
        s.close()


def test_crash_case_c_commit_done_client_retry(active_clock_factory, lease_helper):
    """commit 完成后客户端误以为失败 → retry 不重复累计。"""
    s, lease = lease_helper()
    try:
        catch_up(active_clock_factory, world_id=W,
                 now_real_us=EPOCH0_US + DAY_US,
                 writer_id=lease.owner, fencing_token=lease.token)
        r2 = catch_up(active_clock_factory, world_id=W,
                      now_real_us=EPOCH0_US + DAY_US,
                      writer_id=lease.owner, fencing_token=lease.token)
        assert r2.skipped is True and r2.delta_ticks == 0
        assert _world(active_clock_factory).current_blessed_tick == 1_000_000
    finally:
        lease.release()
        s.close()


def test_crash_case_d_checkpoint_half_written(active_clock_factory, lease_helper,
                                              monkeypatch):
    """Checkpoint 写入过程中 crash → 事务原子，不存在半 checkpoint。"""
    s, lease = lease_helper()
    try:
        original = CheckpointRepository.create

        def boom_create(self, **kw):  # noqa: ANN001, ANN202
            original(self, **kw)  # 先插入半 checkpoint
            raise RuntimeError("crash during checkpoint write")

        monkeypatch.setattr(CheckpointRepository, "create", boom_create)
        with pytest.raises(RuntimeError):
            catch_up(active_clock_factory, world_id=W,
                     now_real_us=EPOCH0_US + DAY_US,
                     writer_id=lease.owner, fencing_token=lease.token)
        row = _world(active_clock_factory)
        assert row.current_blessed_tick == 0
        with active_clock_factory() as s2:
            assert s2.execute(select(SimulationCheckpoint)).scalars().all() == []
            runs = s2.execute(select(SimulationRun)).scalars().all()
            assert len(runs) == 1 and runs[0].status == RunStatus.FAILED
    finally:
        lease.release()
        s.close()


def test_crash_case_e_old_writer_recovery_rejected(active_clock_factory,
                                                   lease_helper):
    """旧 Writer crash 后恢复：stale token 的 mutation 被 fencing 拒绝。"""
    from XiaoguangBlessedLandRuntime.services.catchup import catch_up as _cu
    from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease
    s1, lease1 = lease_helper()
    try:
        with active_clock_factory() as s2:
            s2.execute(sa.text(
                "UPDATE runtime_lock SET expires_at='2000-01-01 00:00:00+00:00'"))
            s2.commit()
        s2 = active_clock_factory()
        lease2 = WriterLease(s2, W, 120)
        lease2.acquire()
        try:
            with pytest.raises(FencingViolation):
                _cu(active_clock_factory, world_id=W,
                    now_real_us=EPOCH0_US + DAY_US,
                    writer_id=lease1.owner, fencing_token=lease1.token)
            assert _world(active_clock_factory).current_blessed_tick == 0
        finally:
            lease2.release()
            s2.close()
    finally:
        s1.close()


def test_crash_case_f_takeover_single_timeline(active_clock_factory, lease_helper):
    """新 Writer 接管旧 Writer → 唯一时间线（时间只推进一次）。"""
    from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease
    s1, lease1 = lease_helper()
    s1.close()  # A 崩溃
    with active_clock_factory() as s2:
        s2.execute(sa.text(
            "UPDATE runtime_lock SET expires_at='2000-01-01 00:00:00+00:00'"))
        s2.commit()
    s2 = active_clock_factory()
    lease2 = WriterLease(s2, W, 120)
    lease2.acquire()
    try:
        res = catch_up(active_clock_factory, world_id=W,
                       now_real_us=EPOCH0_US + DAY_US,
                       writer_id=lease2.owner, fencing_token=lease2.token)
        assert res.delta_ticks == 1_000_000
        row = _world(active_clock_factory)
        assert row.current_blessed_tick == 1_000_000
        assert row.last_committed_real_us == EPOCH0_US + DAY_US
    finally:
        lease2.release()
        s2.close()


def test_crash_case_g_stale_running_recovered(active_clock_factory, lease_helper):
    """stale RUNNING run：新 writer 明确 FAIL 后重试，不重复时间。"""
    from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease
    s1, lease1 = lease_helper()
    try:
        with WorldMutationContext(active_clock_factory(), world_id=W,
                                  writer_id=lease1.owner,
                                  fencing_token=lease1.token) as ctx:
            run = SimulationRunRepository(ctx.session).create_run(
                world_id=W, simulation_version=SimulationVersion.CURRENT,
                real_interval_start_us=EPOCH0_US,
                real_interval_end_us=EPOCH0_US + DAY_US,
                blessed_tick_before=0, writer_id=lease1.owner,
                fencing_token=lease1.token)
            ctx.commit()
        with active_clock_factory() as s2:
            s2.execute(sa.text(
                "UPDATE runtime_lock SET expires_at='2000-01-01 00:00:00+00:00'"))
            s2.commit()
        s2 = active_clock_factory()
        lease2 = WriterLease(s2, W, 120)
        lease2.acquire()
        try:
            res = catch_up(active_clock_factory, world_id=W,
                           now_real_us=EPOCH0_US + DAY_US,
                           writer_id=lease2.owner, fencing_token=lease2.token)
            assert res.delta_ticks == 1_000_000
            with active_clock_factory() as s3:
                r = s3.execute(select(SimulationRun).where(
                    SimulationRun.run_id == run.run_id)).scalar_one()
                assert r.status == RunStatus.FAILED
                committed = s3.execute(select(SimulationRun).where(
                    SimulationRun.status == RunStatus.COMMITTED)).scalars().all()
                assert len(committed) == 1  # 只推进一次
        finally:
            lease2.release()
            s2.close()
    finally:
        s1.close()


def test_catchup_not_activated_rejected(seeded_session_factory):
    """NOT_ACTIVATED 正式世界不得自动推进（先于 fencing 拒绝）。"""
    with pytest.raises(WorldNotActivated):
        catch_up(seeded_session_factory, world_id=W,
                 now_real_us=EPOCH0_US + 1,
                 writer_id="x", fencing_token="y")
    with seeded_session_factory() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        assert row.current_blessed_tick is None
        assert row.last_committed_real_us is None


def test_catchup_uninitialized_clock_rejected(activated_session_factory):
    """ACTIVE 但时钟未初始化（cursor NULL）→ 拒绝（不静默初始化世界时钟）。"""
    with pytest.raises(WorldNotActivated):
        catch_up(activated_session_factory, world_id=W,
                 now_real_us=EPOCH0_US + 1,
                 writer_id="x", fencing_token="y")


def test_committed_interval_unique_index(active_clock_factory, lease_helper):
    """DB 层幂等防线：同区间第二个 COMMITTED run 违反唯一索引。"""
    s, lease = lease_helper()
    try:
        with active_clock_factory() as s2:
            s2.add(SimulationRun(
                run_id="C1", world_id=W, simulation_version="0.1.0-dev",
                status=RunStatus.COMMITTED, seed_context={},
                real_interval_start_us=1, real_interval_end_us=2))
            s2.add(SimulationRun(
                run_id="C2", world_id=W, simulation_version="0.1.0-dev",
                status=RunStatus.COMMITTED, seed_context={},
                real_interval_start_us=1, real_interval_end_us=2))
            with pytest.raises(sa.exc.IntegrityError):
                s2.commit()
            s2.rollback()
            # NULL 区间行（legacy run_atomic_tick）不受影响
            s2.add(SimulationRun(
                run_id="L1", world_id=W, simulation_version="0.1.0-dev",
                status=RunStatus.COMMITTED, seed_context={}))
            s2.add(SimulationRun(
                run_id="L2", world_id=W, simulation_version="0.1.0-dev",
                status=RunStatus.COMMITTED, seed_context={}))
            s2.commit()
    finally:
        lease.release()
        s.close()


def test_run_lifecycle_commit_and_fields(active_clock_factory, lease_helper):
    s, lease = lease_helper()
    try:
        with WorldMutationContext(active_clock_factory(), world_id=W,
                                  writer_id=lease.owner,
                                  fencing_token=lease.token) as ctx:
            run = SimulationRunRepository(ctx.session).create_run(
                world_id=W, simulation_version=SimulationVersion.CURRENT,
                real_interval_start_us=EPOCH0_US,
                real_interval_end_us=EPOCH0_US + 5,
                blessed_tick_before=0, writer_id=lease.owner,
                fencing_token=lease.token, status=RunStatus.PENDING)
            ctx.commit()
        assert run.status == RunStatus.PENDING
        with WorldMutationContext(active_clock_factory(), world_id=W,
                                  writer_id=lease.owner,
                                  fencing_token=lease.token) as ctx2:
            r = SimulationRunRepository(ctx2.session).get(run.run_id)
            SimulationRunRepository(ctx2.session).commit_run(
                r, blessed_tick_after=5, blessed_tick_delta=5,
                real_cursor_after_us=EPOCH0_US + 5)
            ctx2.commit()
        with active_clock_factory() as s3:
            r3 = s3.execute(select(SimulationRun).where(
                SimulationRun.run_id == run.run_id)).scalar_one()
            assert r3.status == RunStatus.COMMITTED
            assert r3.committed_until_tick == 5
            assert r3.blessed_tick_delta == 5
            assert r3.real_cursor_after_us == EPOCH0_US + 5
            assert r3.writer_id == lease.owner
            assert r3.fencing_token == lease.token
    finally:
        lease.release()
        s.close()

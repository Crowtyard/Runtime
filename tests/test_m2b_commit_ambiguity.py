# -*- coding: utf-8 -*-
"""M2B_COMMIT_AMBIGUITY_HARDENING：CA1–CA13（真实 COMMIT ACK LOST 语义）。

关键区分：
- PRE_COMMIT 崩溃（R1–R8 矩阵，test_m2b_resource_economy.py）：异常发生在
  DB commit 之前 → 事务回滚 → 零 durable 残留。
- COMMIT ACK LOST（本文件）：DB commit 已 durable 成功，仅调用方未收到
  success 确认（模拟：WorldMutationContext.commit 先执行真实 commit，再抛
  RuntimeError）→ DB 状态必须已经是 COMMITTED；重启同区间必须识别
  ALREADY_COMMITTED 并零追加变更。

全部运行于 tmp 临时库；正式 DB 零接触。
"""
from __future__ import annotations

import re

import pytest
from sqlalchemy import select, text

from tests.conftest import EPOCH0_US, PROJECT_ROOT

from XiaoguangBlessedLandRuntime.database.models_core import (SimulationCheckpoint,
                                                              WorldEvent,
                                                              WorldRuntime)
from XiaoguangBlessedLandRuntime.database.models_world import (
    PopulationGroup, ResourceNode, ResourceStock)
from XiaoguangBlessedLandRuntime.services import fencing as fencing_mod
from XiaoguangBlessedLandRuntime.services.catchup import catch_up
from XiaoguangBlessedLandRuntime.services.simulation.coordinator import (
    SimulationCoordinator)
from XiaoguangBlessedLandRuntime.services.simulation.economy import EconomyEngine
from XiaoguangBlessedLandRuntime.services.simulation.harness import YEAR_US
from XiaoguangBlessedLandRuntime.services.simulation.mini_world import (
    MINI_WORLD_ID, MINI_ORE_RESERVE_UNITS, MINI_SCALE)
from XiaoguangBlessedLandRuntime.services.simulation.population import (
    PopulationGroupEngine)
from XiaoguangBlessedLandRuntime.services.simulation.recovery import (
    latest_authoritative_world_checkpoint)
from XiaoguangBlessedLandRuntime.services.simulation.resource import ResourceEngine
from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease

REPO = PROJECT_ROOT
SIM_VERSION = "0.2.0-preflight"
ACK_LOST_MSG = "simulated COMMIT ACK LOST (post-durable-commit)"


def _fresh_env(tmp_path, i: int):
    from tests.test_preflight_pf import _fresh_env as _fe
    return _fe(tmp_path, i)


def _engines():
    return [PopulationGroupEngine(), ResourceEngine(), EconomyEngine()]


def _patch_ack_loss(monkeypatch, raise_on_nth: int | None) -> dict:
    """测试专用注入：WorldMutationContext.commit 先执行真实 commit（durable
    成功后）再按计数抛 RuntimeError —— 等价于「DB COMMIT SUCCESS + ACK LOST」。

    raise_on_nth=None 时只记录计数、不抛（后续同进程重启的提交路径）。
    """
    original = fencing_mod.WorldMutationContext.commit
    state = {"calls": 0, "raise_on": raise_on_nth}

    def patched(self):
        original(self)  # 真实 durable commit 先发生
        state["calls"] += 1
        if state["calls"] == state["raise_on"]:
            raise RuntimeError(ACK_LOST_MSG)

    monkeypatch.setattr(fencing_mod.WorldMutationContext, "commit", patched)
    return state


def _run_ack_lost_interval(env, *, lease: WriterLease) -> None:
    """执行 1 年 catch_up；期望在第 2 次 commit（世界提交）durable 后抛
    ACK LOST。返回前不释放租约（模拟 Writer 死亡）。"""
    factory = env["factory"]
    coordinator = SimulationCoordinator(_engines())

    def step(s, info):
        return coordinator.run_step(
            s, world_id=MINI_WORLD_ID,
            blessed_start_tick=info["new_blessed_tick"] - info["delta_ticks"],
            blessed_end_tick=info["new_blessed_tick"],
            real_interval_start_us=info["real_interval_start_us"],
            real_interval_end_us=info["real_interval_end_us"],
            step_index=1)

    with pytest.raises(RuntimeError, match=re.escape(ACK_LOST_MSG)):
        catch_up(factory, world_id=MINI_WORLD_ID,
                 now_real_us=EPOCH0_US + YEAR_US,
                 writer_id=lease.owner, fencing_token=lease.token,
                 simulation_version=SIM_VERSION, simulate_fn=step)


def _committed_evidence(factory) -> dict:
    """读取 durable DB evidence（ALREADY_COMMITTED 判定依据）。"""
    with factory() as s:
        runtime = s.execute(select(WorldRuntime)).scalar_one()
        world = latest_authoritative_world_checkpoint(s, MINI_WORLD_ID)
        run_row = s.execute(text(
            "SELECT status, writer_id, fencing_token, real_interval_start_us,"
            " real_interval_end_us, committed_until_tick FROM simulation_run"
            " ORDER BY started_at DESC LIMIT 1")).mappings().first()
        node = s.execute(select(ResourceNode)).scalar_one()
        stocks = {r.id: r.quantity for r in s.execute(
            select(ResourceStock)).scalars()}
        cum = {r.id: (r.cum_extracted_minor, r.cum_produced_minor,
                      r.cum_consumed_minor, r.cum_imported_minor,
                      r.cum_exported_minor) for r in s.execute(
            select(ResourceStock)).scalars()}
        pop = sum(g.count for g in s.execute(
            select(PopulationGroup)).scalars())
        events = {e.event_uid for e in s.execute(select(WorldEvent)).scalars()}
        ckpts = [c for c in s.execute(
            select(SimulationCheckpoint)).scalars()]
        world_count = len([c for c in ckpts
                           if c.meta.get("checkpoint_kind")
                           == "WORLD_COMMITTED"])
        time_count = len([c for c in ckpts
                          if c.meta.get("checkpoint_kind")
                          == "TIME_COMMITTED"])
        return {
            "tick": runtime.current_blessed_tick,
            "cursor": runtime.last_committed_real_us,
            "reserve": node.remaining_reserve,
            "stocks": stocks, "cum": cum, "population": pop,
            "events": events, "world_ckpts": world_count,
            "time_ckpts": time_count,
            "run_status": run_row["status"] if run_row else None,
            "run_writer": run_row["writer_id"] if run_row else None,
            "run_token": run_row["fencing_token"] if run_row else None,
            "world_hash": world.world_state_hash if world else None,
            "event_hash": world.meta.get("event_stream_hash") if world else None,
        }


def _setup_ack_lost(tmp_path, i, monkeypatch):
    """构造：Writer A 执行 1 年区间 → DB commit durable 成功 → ACK 丢失。"""
    env = _fresh_env(tmp_path, i)
    factory = env["factory"]
    s1 = factory()
    lease = WriterLease(s1, MINI_WORLD_ID, 120)
    lease.acquire()
    state = _patch_ack_loss(monkeypatch, raise_on_nth=2)
    _run_ack_lost_interval(env, lease=lease)
    assert state["calls"] >= 2
    return {"env": env, "factory": factory, "lease": lease, "s1": s1}


def _same_writer_restart(ctx):
    """同 writer/token 重启同区间（模拟进程重启后的再次请求）。"""
    return catch_up(ctx["factory"], world_id=MINI_WORLD_ID,
                    now_real_us=EPOCH0_US + YEAR_US,
                    writer_id=ctx["lease"].owner,
                    fencing_token=ctx["lease"].token,
                    simulation_version=SIM_VERSION)


def _close(ctx):
    ctx["lease"].release()
    ctx["s1"].close()


# ---------------------------------------------------------------- CA1
def test_ca1_existing_r8_true_semantics_pre_commit(tmp_path):
    """CA1：原 R8 注入点（after_checkpoint）真实语义 = PRE_COMMIT ——
    DB commit 未发生，durable 状态必须全空；与 CA2 的 ACK LOST（durable
    已提交）形成明确对照。"""
    src = (REPO / "tests" / "test_m2b_resource_economy.py").read_text(
        encoding="utf-8")
    assert "R8-pre-commit-after-world-checkpoint-staged" in src
    env = _fresh_env(tmp_path, 1)
    factory = env["factory"]
    s1 = factory()
    lease = WriterLease(s1, MINI_WORLD_ID, 120)
    lease.acquire()
    coordinator = SimulationCoordinator(_engines())
    with pytest.raises(RuntimeError, match="after_checkpoint"):
        catch_up(factory, world_id=MINI_WORLD_ID,
                 now_real_us=EPOCH0_US + YEAR_US,
                 writer_id=lease.owner, fencing_token=lease.token,
                 simulation_version=SIM_VERSION,
                 simulate_fn=lambda s, info: coordinator.run_step(
                     s, world_id=MINI_WORLD_ID,
                     blessed_start_tick=info["new_blessed_tick"]
                     - info["delta_ticks"],
                     blessed_end_tick=info["new_blessed_tick"],
                     real_interval_start_us=info["real_interval_start_us"],
                     real_interval_end_us=info["real_interval_end_us"],
                     step_index=1, crash_after="after_checkpoint"))
    with factory() as s:
        assert s.execute(select(WorldRuntime)).scalar_one() \
            .current_blessed_tick == 0
        assert s.execute(text(
            "SELECT COUNT(*) FROM world_events")).scalar() == 0
        assert s.execute(text(
            "SELECT COUNT(*) FROM simulation_checkpoints")).scalar() == 0
    lease.release()
    s1.close()


# ------------------------------------------------------- CA2–CA12
def test_ca2_db_state_already_committed_after_ack_loss(tmp_path, monkeypatch):
    """CA2：DB commit success 后 ACK loss → DB state 必须已经 COMMITTED
    （不得期望 tick=0 / reserve unchanged）。"""
    ctx = _setup_ack_lost(tmp_path, 2, monkeypatch)
    ev = _committed_evidence(ctx["factory"])
    assert ev["tick"] == 1_000_000
    assert ev["cursor"] == EPOCH0_US + YEAR_US
    assert ev["run_status"] == "COMMITTED"
    assert ev["reserve"] < MINI_ORE_RESERVE_UNITS * MINI_SCALE
    assert ev["population"] != 400
    assert len(ev["events"]) > 0
    assert ev["world_ckpts"] == 1 and ev["time_ckpts"] == 1
    _close(ctx)


def test_ca3_restart_same_interval_zero_additional_mutation(tmp_path,
                                                            monkeypatch):
    """CA3：同 world_id/simulation_version/real interval 重启 → 识别
    ALREADY_COMMITTED（committed clock cursor + committed run 行 +
    WORLD_COMMITTED checkpoint），零追加变更。"""
    ctx = _setup_ack_lost(tmp_path, 3, monkeypatch)
    before = _committed_evidence(ctx["factory"])
    res = _same_writer_restart(ctx)
    assert res.skipped is True
    assert res.delta_ticks == 0
    after = _committed_evidence(ctx["factory"])
    assert after["tick"] == before["tick"]
    assert after["cursor"] == before["cursor"]
    assert after["population"] == before["population"]
    assert after["reserve"] == before["reserve"]
    assert after["stocks"] == before["stocks"]
    assert after["run_status"] == "COMMITTED"
    _close(ctx)


def test_ca4_no_duplicate_extraction(tmp_path, monkeypatch):
    ctx = _setup_ack_lost(tmp_path, 4, monkeypatch)
    before = _committed_evidence(ctx["factory"])
    _same_writer_restart(ctx)
    after = _committed_evidence(ctx["factory"])
    assert after["reserve"] == before["reserve"]
    assert {k: v[0] for k, v in after["cum"].items()} \
        == {k: v[0] for k, v in before["cum"].items()}
    _close(ctx)


def test_ca5_no_duplicate_production(tmp_path, monkeypatch):
    ctx = _setup_ack_lost(tmp_path, 5, monkeypatch)
    before = _committed_evidence(ctx["factory"])
    _same_writer_restart(ctx)
    after = _committed_evidence(ctx["factory"])
    assert {k: v[1] for k, v in after["cum"].items()} \
        == {k: v[1] for k, v in before["cum"].items()}
    _close(ctx)


def test_ca6_no_duplicate_consumption(tmp_path, monkeypatch):
    ctx = _setup_ack_lost(tmp_path, 6, monkeypatch)
    before = _committed_evidence(ctx["factory"])
    _same_writer_restart(ctx)
    after = _committed_evidence(ctx["factory"])
    assert {k: v[2] for k, v in after["cum"].items()} \
        == {k: v[2] for k, v in before["cum"].items()}
    _close(ctx)


def test_ca7_no_duplicate_transfer(tmp_path, monkeypatch):
    ctx = _setup_ack_lost(tmp_path, 7, monkeypatch)
    before = _committed_evidence(ctx["factory"])
    _same_writer_restart(ctx)
    after = _committed_evidence(ctx["factory"])
    assert {k: (v[3], v[4]) for k, v in after["cum"].items()} \
        == {k: (v[3], v[4]) for k, v in before["cum"].items()}
    _close(ctx)


def test_ca8_no_duplicate_domain_events(tmp_path, monkeypatch):
    ctx = _setup_ack_lost(tmp_path, 8, monkeypatch)
    before = _committed_evidence(ctx["factory"])
    _same_writer_restart(ctx)
    after = _committed_evidence(ctx["factory"])
    assert after["events"] == before["events"]
    assert len(before["events"]) > 0
    _close(ctx)


def test_ca9_no_duplicate_world_committed_checkpoint(tmp_path, monkeypatch):
    ctx = _setup_ack_lost(tmp_path, 9, monkeypatch)
    before = _committed_evidence(ctx["factory"])
    assert before["world_ckpts"] == 1
    _same_writer_restart(ctx)
    after = _committed_evidence(ctx["factory"])
    assert after["world_ckpts"] == 1
    assert after["time_ckpts"] == 1
    _close(ctx)


def test_ca10_tick_not_advanced_twice(tmp_path, monkeypatch):
    ctx = _setup_ack_lost(tmp_path, 10, monkeypatch)
    before = _committed_evidence(ctx["factory"])
    assert before["tick"] == 1_000_000
    _same_writer_restart(ctx)
    after = _committed_evidence(ctx["factory"])
    assert after["tick"] == 1_000_000
    _close(ctx)


def test_ca11_state_hash_stable(tmp_path, monkeypatch):
    ctx = _setup_ack_lost(tmp_path, 11, monkeypatch)
    before = _committed_evidence(ctx["factory"])
    assert before["world_hash"] and len(before["world_hash"]) == 64
    _same_writer_restart(ctx)
    after = _committed_evidence(ctx["factory"])
    assert after["world_hash"] == before["world_hash"]
    _close(ctx)


def test_ca12_event_stream_hash_stable(tmp_path, monkeypatch):
    ctx = _setup_ack_lost(tmp_path, 12, monkeypatch)
    before = _committed_evidence(ctx["factory"])
    assert before["event_hash"] and len(before["event_hash"]) == 64
    _same_writer_restart(ctx)
    after = _committed_evidence(ctx["factory"])
    assert after["event_hash"] == before["event_hash"]
    _close(ctx)


# ---------------------------------------------------------------- CA13
def test_ca13_new_writer_takeover_still_detects_committed(tmp_path,
                                                          monkeypatch):
    """CA13：A commit 成功 + ACK lost + A 死亡 → B 以新 fencing token 接管
    → 同区间请求 → ALREADY_COMMITTED（不重跑）；token 变化不破坏幂等识别。"""
    ctx = _setup_ack_lost(tmp_path, 13, monkeypatch)
    before = _committed_evidence(ctx["factory"])
    a_token = before["run_token"]

    # A 死亡：租约过期（不释放 —— 模拟进程死亡）；B CAS 接管（新 token）
    with ctx["factory"]() as s:
        s.execute(text("UPDATE runtime_lock SET expires_at = '2000-01-01'"))
        s.commit()
    s2 = ctx["factory"]()
    lease_b = WriterLease(s2, MINI_WORLD_ID, 120)
    lease_b.acquire()
    assert lease_b.token != a_token

    res = catch_up(ctx["factory"], world_id=MINI_WORLD_ID,
                   now_real_us=EPOCH0_US + YEAR_US,
                   writer_id=lease_b.owner, fencing_token=lease_b.token,
                   simulation_version=SIM_VERSION)
    assert res.skipped is True
    assert res.delta_ticks == 0
    after = _committed_evidence(ctx["factory"])
    assert after["tick"] == before["tick"] == 1_000_000
    assert after["population"] == before["population"]
    assert after["reserve"] == before["reserve"]
    assert after["stocks"] == before["stocks"]
    assert after["events"] == before["events"]
    assert after["world_ckpts"] == 1
    assert after["world_hash"] == before["world_hash"]
    assert after["event_hash"] == before["event_hash"]
    # committed run 行保留 A 的记录 —— 幂等识别不依赖当前 fencing token
    assert after["run_status"] == "COMMITTED"
    assert after["run_writer"] == ctx["lease"].owner
    assert after["run_token"] == a_token
    lease_b.release()
    s2.close()
    _close(ctx)

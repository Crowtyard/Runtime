"""M6D.3 — Query Service checkpoint fingerprint regression (owner ruling E).

Guards the minimal production fix that restores the query layer's checkpoint hashes:

  services/query/world_query_service.py::_fingerprint used
  SimulationCheckpoint.blessed_tick (non-existent column; the model column is
  checkpoint_blessed_tick), so the lookup raised and a broad ``except Exception``
  swallowed it -> world_state_hash / event_stream_hash / causal_history_hash were
  always None even with checkpoint rows present.

Owner-required coverage:
  1. with legitimate SimulationCheckpoint rows, all three hashes are not None
  2. checkpoint ordering follows checkpoint_blessed_tick
  3. the fingerprint is deterministic regardless of insertion order
  4. restart / new session leaves the fingerprint hashes unchanged
  5. the query actual path reads the real DB (never a baseline artifact)

The broad-exception policy itself is deliberately NOT changed here: it stays
QUERY_SERVICE_BROAD_EXCEPTION_TECH_DEBT = OPEN_NON_BLOCKING.
"""
from __future__ import annotations

from sqlalchemy import select, text

from tests.test_m3a_tribulation import _fresh_m3a, _run
from XiaoguangBlessedLandRuntime.database.models_core import SimulationCheckpoint
from XiaoguangBlessedLandRuntime.services.query import WorldQueryService
from XiaoguangBlessedLandRuntime.services.simulation.mini_world import (
    MINI_WORLD_ID)


def _world(tmp_path, seed: int = 901, years: int = 10):
    env = _fresh_m3a(tmp_path, seed)
    _run(env, years=years)
    svc = WorldQueryService(session_factory=env["factory"],
                            world_id=MINI_WORLD_ID)
    return env, svc


def test_qfp1_fingerprint_hashes_populated(tmp_path):
    """有合法 checkpoint rows 时三个 hash 必须非 None（修复前恒为 None）。"""
    env, svc = _world(tmp_path)
    with env["factory"]() as s:
        rows = s.execute(select(SimulationCheckpoint)).scalars().all()
    assert rows, "fixture must have committed checkpoints"
    fp = svc._fingerprint()
    assert fp["world_state_hash"] is not None, fp
    assert fp["event_stream_hash"] is not None, fp
    assert fp["causal_history_hash"] is not None, fp
    assert fp["checkpoints"] == len(rows)


def test_qfp2_checkpoint_order_follows_checkpoint_blessed_tick(tmp_path):
    """顺序必须按 checkpoint_blessed_tick（不是 rowid / 插入顺序）。"""
    env, svc = _world(tmp_path)
    with env["factory"]() as s:
        ticks = [r[0] for r in s.execute(text(
            "SELECT checkpoint_blessed_tick FROM simulation_checkpoints "
            "ORDER BY checkpoint_blessed_tick")).all()]
        newest = s.execute(
            select(SimulationCheckpoint)
            .order_by(SimulationCheckpoint.checkpoint_blessed_tick.desc())
            .limit(1)).scalar_one()
    assert ticks == sorted(ticks)
    fp = svc._fingerprint()
    assert fp["tick"] == max(ticks)
    assert fp["world_state_hash"] == newest.world_state_hash


def test_qfp3_fingerprint_deterministic_under_insertion_order(tmp_path):
    """插入顺序变化不得改变 fingerprint（顺序由 checkpoint_blessed_tick 决定）。"""
    env, svc = _world(tmp_path)
    before = svc._fingerprint()
    # 复制最新 checkpoint 行（相同 tick 的重复行）→ 不得改变被选中的 hash
    with env["factory"]() as s:
        newest = s.execute(
            select(SimulationCheckpoint)
            .order_by(SimulationCheckpoint.checkpoint_blessed_tick.desc())
            .limit(1)).scalar_one()
        clone = SimulationCheckpoint(
            world_id=newest.world_id,
            checkpoint_blessed_tick=newest.checkpoint_blessed_tick,
            world_state_hash=newest.world_state_hash,
            complete=newest.complete, meta=dict(newest.meta or {}),
            last_committed_real_us=newest.last_committed_real_us,
            rate_id=newest.rate_id, rate_remainder=newest.rate_remainder,
            simulation_version=newest.simulation_version)
        s.add(clone)
        s.commit()
    after = svc._fingerprint()
    assert after["world_state_hash"] == before["world_state_hash"]
    assert after["tick"] == before["tick"]


def test_qfp4_fingerprint_stable_across_restart_session(tmp_path):
    """新 session / restart 后 fingerprint hashes 不变。"""
    env, svc = _world(tmp_path)
    first = svc._fingerprint()
    fresh = WorldQueryService(session_factory=env["factory"],
                              world_id=MINI_WORLD_ID)
    second = fresh._fingerprint()
    assert second["world_state_hash"] == first["world_state_hash"]
    assert second["event_stream_hash"] == first["event_stream_hash"]
    assert second["causal_history_hash"] == first["causal_history_hash"]
    assert second["tick"] == first["tick"]


def test_qfp5_actual_path_reads_real_db_not_baseline(tmp_path):
    """actual 路径独立读真实 DB：改 DB 行 → fingerprint 随之变化（与任何 baseline 无关）。"""
    env, svc = _world(tmp_path)
    first = svc._fingerprint()
    with env["factory"]() as s:
        newest = s.execute(
            select(SimulationCheckpoint)
            .order_by(SimulationCheckpoint.checkpoint_blessed_tick.desc())
            .limit(1)).scalar_one()
        newest.world_state_hash = "f" * 64
        s.commit()
    mutated = svc._fingerprint()
    assert mutated["world_state_hash"] == "f" * 64
    assert mutated["world_state_hash"] != first["world_state_hash"]

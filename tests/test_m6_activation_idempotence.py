# -*- coding: utf-8 -*-
"""M6A-AI —— 激活幂等（A6/A7 / owner §9）。

要求：第二次 activate 必须
``NO SECOND WORLD / NO SECOND SEED CONSUMPTION / NO RESET / NO NEW ANCHOR /
NO SECOND GENESIS``，即 ``ACTIVATION_IDEMPOTENCE = PASS``。
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from tests.conftest import W
from tests.m6_activation_support import (
    M6_EPOCH0_US, build_synthetic_seed, genesis_event, synthetic_request,
    world_counts, year_tick)

from XiaoguangBlessedLandRuntime.database.models_core import WorldRuntime
from XiaoguangBlessedLandRuntime.domain.errors import ActivationRefused
from XiaoguangBlessedLandRuntime.services.activation import (
    OUTCOME_ALREADY_COMMITTED, OUTCOME_COMMITTED, activate_formal_world)


def _activate(seed_dir, factory, **kw):
    return activate_formal_world(
        factory, request=synthetic_request(seed_dir, **kw))


def _snapshot(factory) -> dict:
    with factory() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        return {
            "runtime_status": row.runtime_status,
            "world_seed_version": row.world_seed_version,
            "current_blessed_tick": row.current_blessed_tick,
            "last_committed_real_us": row.last_committed_real_us,
            "current_time_ratio_id": row.current_time_ratio_id,
            "time_rate_remainder": row.time_rate_remainder,
            "created_at": row.created_at,
        }


# ------------------------------------------------------------------ AI-01
def test_m6ai01_second_activation_is_idempotent(tmp_path, m6_world):
    seed_dir = build_synthetic_seed(tmp_path)
    first = _activate(seed_dir, m6_world)
    assert first.outcome == OUTCOME_COMMITTED and first.written is True

    before = _snapshot(m6_world)
    counts_before = world_counts(m6_world)

    second = _activate(seed_dir, m6_world)
    assert second.outcome == OUTCOME_ALREADY_COMMITTED
    assert second.written is False                     # 零写入
    assert second.seed_consumption_count == 1
    assert world_counts(m6_world) == counts_before     # 无第二个世界 / 无第二个 genesis
    assert _snapshot(m6_world) == before               # 无 reset / 无新 anchor


# ------------------------------------------------------------------ AI-02
def test_m6ai02_second_activation_does_not_reset_advanced_clock(
        tmp_path, m6_world):
    """世界已推进后再 activate：绝不回拨 tick / 现实锚。"""
    seed_dir = build_synthetic_seed(tmp_path)
    _activate(seed_dir, m6_world)                 # canon：tick = 0
    advanced_tick = year_tick(9)
    advanced_cursor = M6_EPOCH0_US + 9 * 86_400_000_000
    with m6_world() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        row.current_blessed_tick = advanced_tick
        row.last_committed_real_us = advanced_cursor
        s.commit()

    out = _activate(seed_dir, m6_world)
    assert out.outcome == OUTCOME_ALREADY_COMMITTED
    with m6_world() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        assert row.current_blessed_tick == advanced_tick      # 未 reset
        assert row.last_committed_real_us == advanced_cursor  # 未重写 anchor
    assert world_counts(m6_world)["genesis_events"] == 1


# ------------------------------------------------------------------ AI-03
def test_m6ai03_second_activation_with_other_seed_refused(tmp_path, m6_world):
    """A6：同一世界不得换一个 Seed 再激活（禁止二次消费）。"""
    seed_a = build_synthetic_seed(tmp_path, name="seed_a", marker="SEED_A")
    seed_b = build_synthetic_seed(tmp_path, name="seed_b", marker="SEED_B")
    _activate(seed_a, m6_world)
    with pytest.raises(ActivationRefused):
        _activate(seed_b, m6_world)
    assert world_counts(m6_world)["genesis_events"] == 1


# ------------------------------------------------------------------ AI-04
def test_m6ai04_repeated_activation_never_creates_second_genesis(
        tmp_path, m6_world):
    seed_dir = build_synthetic_seed(tmp_path)
    outcomes = [_activate(seed_dir, m6_world) for _ in range(5)]
    assert outcomes[0].outcome == OUTCOME_COMMITTED
    assert all(o.outcome == OUTCOME_ALREADY_COMMITTED for o in outcomes[1:])
    counts = world_counts(m6_world)
    assert counts["world_runtime_rows"] == 1
    assert counts["active_worlds"] == 1
    assert counts["genesis_events"] == 1
    assert counts["world_events"] == 1
    ev = genesis_event(m6_world)
    assert ev.event_uid == outcomes[0].genesis_event_uid


# ------------------------------------------------------------------ AI-05
def test_m6ai05_seed_consumption_count_never_exceeds_one(tmp_path, m6_world):
    """§8：WORLD_SEED_CONSUMPTION_COUNT <= 1（成功激活后恒为 1）。"""
    seed_dir = build_synthetic_seed(tmp_path)
    for _ in range(3):
        out = _activate(seed_dir, m6_world)
        assert out.seed_consumption_count <= 1
    assert _activate(seed_dir, m6_world).seed_consumption_count == 1

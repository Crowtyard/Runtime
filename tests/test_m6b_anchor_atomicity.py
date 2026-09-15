# -*- coding: utf-8 -*-
"""M6B-AA —— Anchor / Seed / World 原子性与并发（owner §12–§16）。

- §14 ACTIVATION_ATOMIC_FIELDS：六个字段属于**同一个** authoritative transaction，
  任何字段都不得单独提交（崩溃注入下要么全无、要么全有）；
- §13 一次 activation operation 只确定一次 anchor：ACK lost / crash 后重试必须复用
  同一个 anchor，**绝不**用 now() 生成第二个；
- §15 并发 Activator（**不同 anchor**）：winner 恰好 1 个，loser 不得覆盖 anchor；
- §16 8 点崩溃矩阵 + anchor 检查（duplication / mutation / loss）。
"""
from __future__ import annotations

import json
import threading

import pytest
from sqlalchemy import select, text

from tests.conftest import W
from tests.m6_activation_support import (
    M6_EPOCH0_US, build_synthetic_seed, new_synthetic_world,
    synthetic_request, world_counts)
from tests.test_m6_activation_crash_recovery import (
    CRASH_POINTS, _injected_dbapi_error, _install)

from XiaoguangBlessedLandRuntime.database.models_core import WorldRuntime
from XiaoguangBlessedLandRuntime.domain.errors import ActivationRefused
from XiaoguangBlessedLandRuntime.services.activation import (
    OUTCOME_ALREADY_COMMITTED, OUTCOME_COMMITTED, activate_formal_world)
from XiaoguangBlessedLandRuntime.services.activation.service import (
    _activation_operation_id, _genesis_uid)
from XiaoguangBlessedLandRuntime.services.durable_truth import (
    read_world_epoch_anchor)

ANCHOR_A = M6_EPOCH0_US + 111
ANCHOR_B = M6_EPOCH0_US + 222_222


def _activate(env, seed_dir, *, anchor: int, world_id: str = W):
    return activate_formal_world(env["factory"], request=synthetic_request(
        seed_dir, world_id=world_id, activation_anchor_us=anchor))


def _atomic_fields(factory) -> dict:
    """六个原子字段的 durable 取值（缺一即视为"未提交"）。"""
    with factory() as s:
        row = s.execute(select(WorldRuntime)).scalar_one_or_none()
        rates = s.execute(text(
            "SELECT blessed_effective_from_tick FROM time_ratio_history"
        )).scalars().all()
        genesis = s.execute(text(
            "SELECT effect FROM world_events WHERE event_type='WORLD_SEED_ACTIVATED'"
        )).all()
    if row is None:
        return {"committed": False}
    raw_effect = genesis[0][0] if genesis else None
    if isinstance(raw_effect, str):
        raw_effect = json.loads(raw_effect)
    effect = dict(raw_effect or {})
    fields = {
        "runtime_status": row.runtime_status,
        "world_seed_version": row.world_seed_version,
        "current_blessed_tick": row.current_blessed_tick,
        "last_committed_real_us": row.last_committed_real_us,
        "rate_blessed_start": (rates[0] if rates else None),
        "genesis_anchor_us": effect.get("activation_anchor_us"),
        "genesis_count": len(genesis),
    }
    fields["committed"] = (
        row.runtime_status == "ACTIVE"
        and row.world_seed_version is not None
        and row.current_blessed_tick is not None
        and row.last_committed_real_us is not None
        and rates and rates[0] is not None
        and len(genesis) == 1)
    return fields


# ------------------------------------------------------------------ AA-01
def test_m6baa01_activation_atomic_fields_all_committed_together(tmp_path):
    """§14：成功激活后六个字段必须同时成立且互相自洽。"""
    env = new_synthetic_world(tmp_path / "w")
    seed_dir = build_synthetic_seed(tmp_path)
    before = _atomic_fields(env["factory"])
    assert before["committed"] is False

    out = _activate(env, seed_dir, anchor=ANCHOR_A)
    assert out.outcome == OUTCOME_COMMITTED
    f = _atomic_fields(env["factory"])
    assert f["committed"] is True
    assert f["runtime_status"] == "ACTIVE"
    assert f["world_seed_version"] == "1.0"
    assert f["current_blessed_tick"] == 0                 # OWNER_CANON_DECISION_1
    assert f["last_committed_real_us"] == ANCHOR_A
    assert f["rate_blessed_start"] == 0
    assert f["genesis_anchor_us"] == ANCHOR_A
    assert f["genesis_count"] == 1
    env["engine"].dispose()


@pytest.mark.parametrize("point", CRASH_POINTS)
def test_m6baa02_no_field_is_committed_separately(tmp_path, monkeypatch, point):
    """§14/§16：提交前崩溃 → 六个字段**一个都不得**出现（无单独提交）。"""
    env = new_synthetic_world(tmp_path / point)
    seed_dir = build_synthetic_seed(tmp_path, name=f"seed_{point.replace('_','')}")
    expected_exc = _install(monkeypatch, point, tmp_path)
    if expected_exc is not None:
        with pytest.raises(expected_exc):
            _activate(env, seed_dir, anchor=ANCHOR_A)
    else:
        out = _activate(env, seed_dir, anchor=ANCHOR_A)   # ACK 丢失：已 durable 提交
        assert out.outcome == OUTCOME_COMMITTED

    f = _atomic_fields(env["factory"])
    if f["committed"]:
        # 只允许"全部提交"，且 anchor 必须恰好是本次请求的那个（不重复/不漂移/不丢失）
        assert f["genesis_count"] == 1
        assert f["genesis_anchor_us"] == ANCHOR_A
        assert f["last_committed_real_us"] == ANCHOR_A
        assert f["current_blessed_tick"] == 0
        assert read_world_epoch_anchor(env["factory"], world_id=W) == ANCHOR_A
    else:
        assert f.get("runtime_status", "NOT_ACTIVATED") == "NOT_ACTIVATED"
        assert f.get("world_seed_version") is None
        assert f.get("current_blessed_tick") is None
        assert f.get("last_committed_real_us") is None
        assert f.get("genesis_count", 0) == 0
        assert f.get("rate_blessed_start") is None
        assert read_world_epoch_anchor(env["factory"], world_id=W) is None
    env["engine"].dispose()


# ------------------------------------------------------------------ AA-03
def test_m6baa03_retry_must_reuse_the_same_anchor(tmp_path):
    """§13：ACK lost / crash 后的重试必须复用同一 anchor；换 anchor 一律拒绝。"""
    env = new_synthetic_world(tmp_path / "w")
    seed_dir = build_synthetic_seed(tmp_path)
    first = _activate(env, seed_dir, anchor=ANCHOR_A)
    assert first.outcome == OUTCOME_COMMITTED

    # 同一 anchor 重试 → 幂等（零写入），anchor 不变
    again = _activate(env, seed_dir, anchor=ANCHOR_A)
    assert again.outcome == OUTCOME_ALREADY_COMMITTED
    assert again.written is False
    assert read_world_epoch_anchor(env["factory"], world_id=W) == ANCHOR_A

    # 不同 anchor（例如"重试时重新 now()"）→ 拒绝，anchor 绝不被覆盖
    with pytest.raises(ActivationRefused) as ei:
        _activate(env, seed_dir, anchor=ANCHOR_B)
    assert "anchor" in ei.value.message.lower() or "anchor" in str(ei.value.detail)
    assert read_world_epoch_anchor(env["factory"], world_id=W) == ANCHOR_A
    with env["factory"]() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        assert row.last_committed_real_us == ANCHOR_A
    env["engine"].dispose()


# ------------------------------------------------------------------ AA-04
def test_m6baa04_concurrent_activators_with_different_anchors(tmp_path):
    """§15：两个 Activator（不同 anchor）→ winner=1，库中只有 winner 的 anchor。"""
    env = new_synthetic_world(tmp_path / "w")
    seed_dir = build_synthetic_seed(tmp_path)
    results: list[dict] = []
    barrier = threading.Barrier(2)

    def worker(tag: str, anchor: int) -> None:
        barrier.wait()
        try:
            out = _activate(env, seed_dir, anchor=anchor)
            results.append({"tag": tag, "anchor": anchor, "outcome": out.outcome,
                            "written": out.written, "error": None})
        except Exception as exc:  # noqa: BLE001
            results.append({"tag": tag, "anchor": anchor, "outcome": None,
                            "written": False, "error": type(exc).__name__})

    threads = [threading.Thread(target=worker, args=("A", ANCHOR_A)),
               threading.Thread(target=worker, args=("B", ANCHOR_B))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)

    winners = [r for r in results if r["written"]]
    assert len(winners) == 1, results                      # exactly one winner
    for r in results:
        assert r["error"] in (None, "ActivationRefused",
                              "ActivationOutcomeUnknown"), results

    winner_anchor = winners[0]["anchor"]
    durable = read_world_epoch_anchor(env["factory"], world_id=W)
    assert durable == winner_anchor                        # loser 未覆盖 anchor
    counts = world_counts(env["factory"])
    assert counts["world_runtime_rows"] == 1
    assert counts["active_worlds"] == 1
    assert counts["genesis_events"] == 1                   # one genesis
    assert counts["seed_consumption_count"] == 1           # one seed consumption
    with env["factory"]() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        assert row.last_committed_real_us == winner_anchor
        assert row.current_blessed_tick == 0
    env["engine"].dispose()


# ------------------------------------------------------------------ AA-05
def test_m6baa05_commit_ack_lost_does_not_duplicate_anchor(tmp_path,
                                                           monkeypatch):
    """§16：commit 后 ACK 丢失 → reconcile 成功，anchor 恰好一个、不重复。"""
    from XiaoguangBlessedLandRuntime.services.fencing import (
        WorldMutationContext)

    env = new_synthetic_world(tmp_path / "w")
    seed_dir = build_synthetic_seed(tmp_path)
    real_commit = WorldMutationContext.commit

    def commit_then_die(self):
        real_commit(self)
        raise _injected_dbapi_error()

    monkeypatch.setattr(WorldMutationContext, "commit", commit_then_die)
    out = _activate(env, seed_dir, anchor=ANCHOR_A)
    assert out.outcome == OUTCOME_COMMITTED
    assert out.commit_outcome_was_ambiguous is True
    monkeypatch.undo()

    f = _atomic_fields(env["factory"])
    assert f["committed"] is True
    assert f["genesis_count"] == 1
    assert read_world_epoch_anchor(env["factory"], world_id=W) == ANCHOR_A
    # 重试：仍是同一个 anchor（不重复、不漂移）
    assert _activate(env, seed_dir, anchor=ANCHOR_A).outcome == \
        OUTCOME_ALREADY_COMMITTED
    assert _atomic_fields(env["factory"])["genesis_count"] == 1
    env["engine"].dispose()


# ------------------------------------------------------------------ AA-06
def test_m6baa06_genesis_integrity(tmp_path):
    """§12：genesis 唯一、uid 确定性、cause 含 activation operation identity、
    无孤儿 / 无环 / 无非法引用。"""
    env = new_synthetic_world(tmp_path / "w")
    seed_dir = build_synthetic_seed(tmp_path)
    req = synthetic_request(seed_dir, world_id=W, activation_anchor_us=ANCHOR_A)
    out = _activate(env, seed_dir, anchor=ANCHOR_A)

    with env["factory"]() as s:
        events = s.execute(text(
            "SELECT event_uid, event_type, blessed_tick, parent_event_ref, "
            "cause, effect, world_id FROM world_events")).all()
        links = int(s.execute(text(
            "SELECT COUNT(*) FROM causal_history_links")).scalar())
        orphan_parents = int(s.execute(text(
            "SELECT COUNT(*) FROM world_events e WHERE e.parent_event_ref IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM world_events p "
            "                WHERE p.event_uid = e.parent_event_ref)")).scalar())
        bad_world = int(s.execute(text(
            "SELECT COUNT(*) FROM world_events WHERE world_id != :w"),
            {"w": W}).scalar())
        self_parent = int(s.execute(text(
            "SELECT COUNT(*) FROM world_events WHERE parent_event_ref = event_uid"
        )).scalar())

    assert len(events) == 1                                   # 唯一 genesis
    uid, etype, tick, parent, cause, effect, world = events[0]
    assert etype == "WORLD_SEED_ACTIVATED"
    assert tick == 0
    assert parent is None                                     # 无父 → 无环
    assert world == W                                         # 无非法引用
    assert uid == _genesis_uid(req)                           # uid 确定性
    assert out.genesis_event_uid == uid
    cause = json.loads(cause) if isinstance(cause, str) else cause
    effect = json.loads(effect) if isinstance(effect, str) else effect
    assert cause["activation_operation_id"] == _activation_operation_id(
        req, _seed_pkg(seed_dir))
    assert effect["activation_anchor_us"] == ANCHOR_A
    assert links == 0 and orphan_parents == 0 and bad_world == 0 \
        and self_parent == 0
    env["engine"].dispose()


def _seed_pkg(seed_dir):  # noqa: ANN001
    from XiaoguangBlessedLandRuntime.services.activation import load_seed_package
    return load_seed_package(seed_dir)

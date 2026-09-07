# -*- coding: utf-8 -*-
"""M2_PREFLIGHT_HARDENING_PATCH 测试：HP1–HP10。

Event UID 强度/确定性/event_type 参与身份、state hash 与 event stream hash
分离、checkpoint 语义确定性、权威恢复规则、旧时间模型废弃标注与零生产使用。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import select, text

from tests.conftest import BIBLE_DIR, PROJECT_ROOT

from XiaoguangBlessedLandRuntime.database.models_core import SimulationCheckpoint
from XiaoguangBlessedLandRuntime.services.simulation.contracts import (
    ENGINE_ORDER, EngineResult, DomainEventDraft)
from XiaoguangBlessedLandRuntime.services.simulation.coordinator import (
    SimulationCoordinator)
from XiaoguangBlessedLandRuntime.services.simulation.event_stream import (
    EVENT_UID_HEX_LEN, deterministic_event_uid, empty_event_stream_hash,
    step_event_stream_hash)
from XiaoguangBlessedLandRuntime.services.simulation.harness import (
    run_mini_world_120y)
from XiaoguangBlessedLandRuntime.services.simulation.recovery import (
    count_checkpoints_by_kind, latest_authoritative_world_checkpoint)

REPO = PROJECT_ROOT
KB_RD = BIBLE_DIR.parent / "runtime_design"
SIM_DIR = REPO / "services" / "simulation"


def _uid(**kw):
    base = dict(world_id="W", simulation_version="0.2.0-preflight",
                real_start_us=1, real_end_us=2, engine_id="DEMOGRAPHY",
                event_type="E", seq=0)
    base.update(kw)
    return deterministic_event_uid(**base)


def test_hp1_event_uid_128bit():
    uid = _uid()
    assert len(uid) == EVENT_UID_HEX_LEN == 32  # 128-bit
    assert re.fullmatch(r"[0-9a-f]{32}", uid)


def test_hp2_event_uid_deterministic():
    assert _uid() == _uid()
    assert _uid(seq=5) == _uid(seq=5)
    assert _uid() != _uid(seq=1)


def test_hp3_event_type_participates_in_identity():
    assert _uid(event_type="A") != _uid(event_type="B")
    assert _uid(engine_id="DEMOGRAPHY") != _uid(engine_id="RESOURCE")


def test_hp4_state_hash_and_event_hash_separation(mini_world_env):
    from XiaoguangBlessedLandRuntime.services.simulation.contracts import (
        DeterministicFakeEngine)
    factory = mini_world_env["factory"]
    report = run_mini_world_120y(factory, engines=[
        DeterministicFakeEngine(eid, 1) for eid in ENGINE_ORDER], years=1)
    assert len(report.final_state_hash) == 64
    with factory() as s:
        ckpt = latest_authoritative_world_checkpoint(s, "MINIWORLD-TEST-001")
        assert ckpt is not None
        assert ckpt.meta["checkpoint_kind"] == "WORLD_COMMITTED"
        assert ckpt.meta["phase"] == "COMMITTED"
        assert len(ckpt.meta["event_stream_hash"]) == 64
        assert ckpt.world_state_hash != ckpt.meta["event_stream_hash"]


def test_hp5_same_replay_same_two_hashes(mini_world_env, tmp_path):
    from XiaoguangBlessedLandRuntime.services.simulation.contracts import (
        DeterministicFakeEngine)
    from tests.test_preflight_pf import _fresh_env
    engines = [DeterministicFakeEngine(eid, 2) for eid in ENGINE_ORDER]
    env_b = _fresh_env(tmp_path, 21)
    a = run_mini_world_120y(mini_world_env["factory"], engines=engines, years=3)
    b = run_mini_world_120y(env_b["factory"], engines=engines, years=3)
    assert a.final_state_hash == b.final_state_hash
    assert a.final_state_hash and b.final_state_hash
    with mini_world_env["factory"]() as s:
        ha = latest_authoritative_world_checkpoint(
            s, "MINIWORLD-TEST-001").meta["event_stream_hash"]
    with env_b["factory"]() as s:
        hb = latest_authoritative_world_checkpoint(
            s, "MINIWORLD-TEST-001").meta["event_stream_hash"]
    assert ha == hb


class _SeqEngine:
    """发射两个事件（无状态变更）；order 控制发射顺序（HP6 用）。"""

    def __init__(self, order: str):
        self.engine_id = "SOCIAL"
        self.engine_version = "seq-1"
        self.order = order

    def simulate(self, ctx):
        events = [
            DomainEventDraft(engine_id="SOCIAL", event_type="EV_A",
                             effect={"n": 1}),
            DomainEventDraft(engine_id="SOCIAL", event_type="EV_B",
                             effect={"n": 2}),
        ]
        if self.order == "ba":
            events = [events[1], events[0]]
        return EngineResult(engine_id="SOCIAL", engine_version="seq-1",
                            domain_events=events)


def test_hp6_different_event_sequence_different_event_hash(mini_world_env,
                                                           tmp_path):
    """最终 State 相同、事件序列不同 → state hash 相同、event hash 必不同。"""
    from tests.test_preflight_pf import _fresh_env
    env_b = _fresh_env(tmp_path, 22)
    a = run_mini_world_120y(mini_world_env["factory"],
                            engines=[_SeqEngine("ab")], years=1)
    b = run_mini_world_120y(env_b["factory"],
                            engines=[_SeqEngine("ba")], years=1)
    assert a.final_state_hash == b.final_state_hash  # 状态一致
    with mini_world_env["factory"]() as s:
        ha = latest_authoritative_world_checkpoint(
            s, "MINIWORLD-TEST-001").meta["event_stream_hash"]
    with env_b["factory"]() as s:
        hb = latest_authoritative_world_checkpoint(
            s, "MINIWORLD-TEST-001").meta["event_stream_hash"]
    assert ha != hb  # 事件流不同


def test_hp7_checkpoint_semantics_deterministic(mini_world_env):
    factory = mini_world_env["factory"]
    run_mini_world_120y(factory, years=5)
    with factory() as s:
        counts = count_checkpoints_by_kind(s, "MINIWORLD-TEST-001")
    assert counts == {"time_committed": 5, "world_committed": 5}


def test_hp8_recovery_uses_authoritative_checkpoint_only(mini_world_env):
    factory = mini_world_env["factory"]
    run_mini_world_120y(factory, years=3)
    with factory() as s:
        authoritative = latest_authoritative_world_checkpoint(
            s, "MINIWORLD-TEST-001")
        all_complete = s.execute(
            select(SimulationCheckpoint).where(
                SimulationCheckpoint.complete.is_(True))
            .order_by(SimulationCheckpoint.checkpoint_blessed_tick.desc())
        ).scalars().all()
    assert authoritative is not None
    assert authoritative.meta["checkpoint_kind"] == "WORLD_COMMITTED"
    # 最新 complete 行是 M1 CATCHUP 或 M2 同 tick；权威恢复必须取 WORLD_COMMITTED
    assert authoritative.meta["kind"] == "M2_PREFLIGHT"
    assert authoritative.checkpoint_blessed_tick == 3_000_000
    # 全部 complete 行中 CATCHUP 行不得被当作权威（函数按 kind 过滤）
    assert len(all_complete) == 6  # 3 CATCHUP + 3 WORLD_COMMITTED


def test_hp9_old_time_model_marked_deprecated():
    doc = (KB_RD / "04_time_engine.md").read_text(encoding="utf-8")
    assert "DEPRECATED_RUNTIME_TIME_MODEL" in doc
    doc5 = (KB_RD / "05_offline_catchup.md").read_text(encoding="utf-8")
    assert "DEPRECATED_RUNTIME_TIME_MODEL" in doc5
    register = (REPO / "runtime_design" /
                "DEPRECATED_RUNTIME_TIME_MODEL.md").read_text(encoding="utf-8")
    assert "04_time_engine.md" in register
    assert "05_offline_catchup.md" in register


def test_hp10_no_production_code_uses_deprecated_time_formula():
    for base in ("domain", "services", "database", "config", "plugin_shell"):
        for py in (REPO / base).rglob("*.py"):
            if "alembic" in py.parts and "versions" in py.parts:
                continue  # 历史 migration 链合法引用旧列名（仅迁移历史）
            src = py.read_text(encoding="utf-8")
            assert "ratio_value" not in src, py
            assert "blessed_elapsed(" not in src, py
            assert "blessed_from_real(" not in src, py
            assert "福地年.月" not in src, py
            assert re.search(r"\b365\.0\b", src) is None, py


# mini_world 环境复用（与 PF 套件一致的构建方式）
@pytest.fixture()
def mini_world_env(tmp_path, real_bible_dir):
    from tests.test_preflight_pf import _fresh_env
    return _fresh_env(tmp_path, 20)


def test_event_stream_hash_chain_unit():
    """增量链单元：不同 prev/顺序产生不同哈希；相同输入恒等。"""
    e = [{"event_uid": "u1", "blessed_tick": 1, "event_type": "A",
          "source": "SIMULATION", "cause": {}, "effect": {}, "severity": 0.0,
          "scope": "WORLD"}]
    h0 = empty_event_stream_hash("W", "v")
    h1 = step_event_stream_hash(h0, world_id="W", simulation_version="v",
                                events=e)
    h1b = step_event_stream_hash(h0, world_id="W", simulation_version="v",
                                 events=e)
    assert h1 == h1b
    e2 = [dict(e[0], event_type="B")]
    h2 = step_event_stream_hash(h0, world_id="W", simulation_version="v",
                                events=e2)
    assert h1 != h2

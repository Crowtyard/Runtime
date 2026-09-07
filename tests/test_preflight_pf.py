# -*- coding: utf-8 -*-
"""M2_PREFLIGHT PF1–PF19 测试矩阵。

契约/快照/暂存/顺序/RNG/事件纪律/哈希/120y harness/崩溃/零 LLM/零网络/
零 wall-clock/确定性。所有世界运行只发生于 tmp_path 临时库。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import select, text

from tests.conftest import EPOCH0, EPOCH0_US, PROJECT_ROOT

from XiaoguangBlessedLandRuntime.database.db import (create_db_engine,
                                                     make_session_factory)
from XiaoguangBlessedLandRuntime.database.models_core import (
    SimulationCheckpoint, WorldEvent, WorldRuntime)
from XiaoguangBlessedLandRuntime.database.models_world import (EcologicalRegion,
                                                               Settlement)
from XiaoguangBlessedLandRuntime.domain.constants import (RuntimeStatus,
                                                          SimulationVersion)
from XiaoguangBlessedLandRuntime.domain.errors import (FencingViolation,
                                                       IntegrityError)
from XiaoguangBlessedLandRuntime.services.catchup import catch_up
from XiaoguangBlessedLandRuntime.services.db_lifecycle import migrate_database
from XiaoguangBlessedLandRuntime.services.fencing import WorldMutationContext
from XiaoguangBlessedLandRuntime.services.repositories import (
    RuntimeRepository, TimeRatioRepository)
from XiaoguangBlessedLandRuntime.services.simulation.contracts import (
    ENGINE_ORDER, PREFLIGHT_SIMULATION_VERSION, DeterministicFakeEngine,
    EngineResult, NoOpEngine, StateChange)
from XiaoguangBlessedLandRuntime.services.simulation.coordinator import (
    SimulationCoordinator)
from XiaoguangBlessedLandRuntime.services.simulation.harness import (
    YEAR_US, run_mini_world_120y)
from XiaoguangBlessedLandRuntime.services.simulation.mini_world import (
    MINI_WORLD_ID, seed_mini_world)
from XiaoguangBlessedLandRuntime.services.simulation.snapshot import (
    read_snapshot)
from XiaoguangBlessedLandRuntime.services.simulation.state_hash import (
    world_state_hash_v2)
from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease

REPO = PROJECT_ROOT
SIM_DIR = REPO / "services" / "simulation"


# ---------------------------------------------------------------- helpers
class MutatorEngine:
    """测试引擎：propose 一条 ECOLOGY 变更（PF10/所有权用）。"""
    engine_id = "ECOLOGY"
    engine_version = "mutator-1"

    def simulate(self, ctx):
        return EngineResult(
            engine_id="ECOLOGY", engine_version="mutator-1",
            proposed_changes=[StateChange(
                table="ecological_regions", entity_id=1, field="carrying_capacity",
                old_value=1000, new_value=777)])


class WrongOwnerEngine:
    """测试引擎：propose 不属于自己的表（所有权违约）。"""
    engine_id = "ECOLOGY"
    engine_version = "wrong-1"

    def simulate(self, ctx):
        return EngineResult(
            engine_id="ECOLOGY", engine_version="wrong-1",
            proposed_changes=[StateChange(
                table="settlements", entity_id=1, field="state",
                old_value="STABLE", new_value="X")])


@pytest.fixture()
def mini_world_env(tmp_path):
    """tmp 临时库上的 ACTIVE mini_world（TEST-ONLY；与正式世界完全隔离）。"""
    db_path = tmp_path / "mini_world.db"
    url = "sqlite:///" + str(db_path).replace("\\", "/")
    migrate_database(url, project_root=REPO)
    engine = create_db_engine(url)
    factory = make_session_factory(engine)
    with factory() as s:
        RuntimeRepository(s).create_not_activated(
            world_id=MINI_WORLD_ID, world_bible_version="1.0",
            simulation_version=PREFLIGHT_SIMULATION_VERSION,
            world_bible_manifest_hash="mini-test-hash")
        row = s.execute(select(WorldRuntime)).scalar_one()
        row.runtime_status = RuntimeStatus.ACTIVE
        row.world_seed_version = "MINI-TEST-SEED-001"
        row.current_blessed_tick = 0
        row.last_committed_real_us = EPOCH0_US
        row.time_rate_remainder = 0
        rate = TimeRatioRepository(s).add(
            world_id=MINI_WORLD_ID, real_effective_from=EPOCH0,
            rate_numerator=1_000_000, rate_denominator=86_400_000_000,
            reason="TEST", source="TEST")
        row.current_time_ratio_id = rate.ratio_id
        seed_mini_world(s)
        s.commit()
    return {"url": url, "factory": factory, "db_path": db_path}


def _fakes(draws: int = 3):
    return [DeterministicFakeEngine(eid, draws) for eid in ENGINE_ORDER]


def _one_year(factory, *, lease, coordinator, crash_after=None):
    res = catch_up(
        factory, world_id=MINI_WORLD_ID, now_real_us=EPOCH0_US + YEAR_US,
        writer_id=lease.owner, fencing_token=lease.token,
        simulation_version=PREFLIGHT_SIMULATION_VERSION,
        simulate_fn=lambda s, info: coordinator.run_step(
            s, world_id=MINI_WORLD_ID,
            blessed_start_tick=info["new_blessed_tick"] - info["delta_ticks"],
            blessed_end_tick=info["new_blessed_tick"],
            real_interval_start_us=info["real_interval_start_us"],
            real_interval_end_us=info["real_interval_end_us"],
            step_index=1, crash_after=crash_after))
    return res


# ---------------------------------------------------------------- PF 测试
def test_pf1_mini_world_isolated_from_formal_db(mini_world_env, tmp_path):
    src = (SIM_DIR / "mini_world.py").read_text(encoding="utf-8")
    assert "XIAOGUANG_CROW_KB" not in src  # 不读取正式 Seed Package 路径
    assert not re.search(r"[A-Z]:\\", src)  # 无本机绝对路径
    assert mini_world_env["db_path"].parent == tmp_path  # 只在 tmp 库


def test_pf2_simulation_package_never_opens_a_db_itself():
    for py in SIM_DIR.rglob("*.py"):
        src = py.read_text(encoding="utf-8")
        assert "create_db_engine" not in src, py
        assert "make_session_factory" not in src, py


def test_pf3_not_activated_preserved_versions():
    # 正式世界语义版本不被 Preflight 触碰
    assert SimulationVersion.CURRENT == "0.1.0-dev"
    assert PREFLIGHT_SIMULATION_VERSION == "0.2.0-preflight"


def test_pf4_engine_order_deterministic():
    assert ENGINE_ORDER == ("DEMOGRAPHY", "RESOURCE", "ECONOMY",
                            "ECOLOGY", "SOCIAL")  # 恢复自 04 §4
    with pytest.raises(IntegrityError):
        SimulationCoordinator([NoOpEngine("RESOURCE"),
                               NoOpEngine("DEMOGRAPHY")])  # 顺序违约
    with pytest.raises(ValueError):
        NoOpEngine("UNKNOWN")


def test_pf5_same_inputs_same_output_hash(mini_world_env, tmp_path):
    reports = []
    for i in range(2):
        env = mini_world_env if i == 0 else _fresh_env(tmp_path, i)
        rep = run_mini_world_120y(env["factory"], engines=_fakes(),
                                  years=5)
        reports.append(rep)
    a, b = reports
    assert a.final_blessed_tick == b.final_blessed_tick == 5_000_000
    assert a.final_state_hash == b.final_state_hash
    assert a.engine_metrics == b.engine_metrics


def test_pf6_rng_replay_equivalence(mini_world_env, tmp_path):
    a = run_mini_world_120y(mini_world_env["factory"], engines=_fakes(),
                            years=2)
    b = run_mini_world_120y(_fresh_env(tmp_path, 3)["factory"],
                            engines=_fakes(), years=2)
    assert a.engine_metrics == b.engine_metrics
    assert a.final_state_hash == b.final_state_hash


def test_pf7_engine_rng_independence(mini_world_env, tmp_path):
    base = [DeterministicFakeEngine(eid, 3) for eid in ENGINE_ORDER]
    changed = [DeterministicFakeEngine("DEMOGRAPHY", 7),
               *[DeterministicFakeEngine(eid, 3)
                 for eid in ENGINE_ORDER if eid != "DEMOGRAPHY"]]
    a = run_mini_world_120y(mini_world_env["factory"], engines=base, years=2)
    b = run_mini_world_120y(_fresh_env(tmp_path, 4)["factory"],
                            engines=changed, years=2)
    for eid in ("RESOURCE", "ECONOMY", "ECOLOGY", "SOCIAL"):
        assert a.engine_metrics[eid] == b.engine_metrics[eid], eid
    assert a.engine_metrics["DEMOGRAPHY"] != b.engine_metrics["DEMOGRAPHY"]


def test_pf8_retry_no_duplicate_events_and_deterministic_uid(mini_world_env,
                                                             tmp_path):
    factory = mini_world_env["factory"]
    rep = run_mini_world_120y(factory, engines=_fakes(), years=1)
    with factory() as s:
        uids_a = {e.event_uid for e in s.execute(
            select(WorldEvent).where(
                WorldEvent.event_type == "FAKE_STEP")).scalars()}
    retry = run_mini_world_120y(factory, engines=_fakes(), years=1)
    assert retry.steps == 1 and retry.final_blessed_tick == 1_000_000
    with factory() as s:
        uids_b = {e.event_uid for e in s.execute(
            select(WorldEvent).where(
                WorldEvent.event_type == "FAKE_STEP")).scalars()}
    assert uids_a == uids_b  # 重试未新增事件（且 uid 确定性）
    env_c = _fresh_env(tmp_path, 5)
    fresh = run_mini_world_120y(env_c["factory"], engines=_fakes(), years=1)
    with env_c["factory"]() as s:
        uids_c = {e.event_uid for e in s.execute(
            select(WorldEvent).where(
                WorldEvent.event_type == "FAKE_STEP")).scalars()}
    assert uids_a == uids_c  # 不同库同输入 → 同事件 identity


def test_pf9_engines_cannot_commit():
    contracts_src = (SIM_DIR / "contracts.py").read_text(encoding="utf-8")
    assert "session.commit" not in contracts_src
    assert "def simulate(self, ctx" in contracts_src  # 引擎无 session 参数
    for py in SIM_DIR.rglob("*.py"):
        assert "session.commit" not in py.read_text(encoding="utf-8"), py


def test_pf10_stale_writer_cannot_commit_staged_mutation(mini_world_env):
    factory = mini_world_env["factory"]
    s1 = factory()
    lease = WriterLease(s1, MINI_WORLD_ID, 120)
    lease.acquire()
    coordinator = SimulationCoordinator([MutatorEngine()])
    with WorldMutationContext(factory(), world_id=MINI_WORLD_ID,
                              writer_id=lease.owner,
                              fencing_token=lease.token) as ctx:
        coordinator.run_step(
            ctx.session, world_id=MINI_WORLD_ID,
            blessed_start_tick=0, blessed_end_tick=1_000_000,
            real_interval_start_us=0, real_interval_end_us=YEAR_US)
        # 模拟接管：fence 被替换
        ctx.session.execute(text("UPDATE runtime_lock SET lease_token='STOLEN'"))
        with pytest.raises(FencingViolation):
            ctx.commit()
    with factory() as s:
        eco = s.execute(select(EcologicalRegion)).scalar_one()
        assert eco.carrying_capacity == 1000  # 零写入
    lease.release()
    s1.close()


def test_pf_ownership_violation_rejected(mini_world_env):
    factory = mini_world_env["factory"]
    s1 = factory()
    lease = WriterLease(s1, MINI_WORLD_ID, 120)
    lease.acquire()
    coordinator = SimulationCoordinator([WrongOwnerEngine()])
    with pytest.raises(IntegrityError):
        with WorldMutationContext(factory(), world_id=MINI_WORLD_ID,
                                  writer_id=lease.owner,
                                  fencing_token=lease.token) as ctx:
            coordinator.run_step(
                ctx.session, world_id=MINI_WORLD_ID,
                blessed_start_tick=0, blessed_end_tick=1_000_000,
                real_interval_start_us=0, real_interval_end_us=YEAR_US)
            ctx.commit()
    lease.release()
    s1.close()


def test_pf11_pf12_zero_llm_zero_network(mini_world_env, monkeypatch):
    import socket

    def _boom(*a, **k):
        raise AssertionError("simulation core 触碰网络/LLM 传输")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr("urllib.request.urlopen", _boom, raising=False)
    monkeypatch.setattr("http.client.HTTPConnection", _boom, raising=False)
    rep = run_mini_world_120y(mini_world_env["factory"], years=3)
    assert rep.final_blessed_tick == 3_000_000


def test_pf13_no_wall_clock_in_simulation_core():
    pattern = re.compile(
        r"\b(datetime\.now|time\.time|time\.monotonic|perf_counter"
        r"|time_ns|date\.today)\s*\(")
    for py in SIM_DIR.rglob("*.py"):
        src = py.read_text(encoding="utf-8")
        assert not pattern.search(src), py


def test_pf14_noop_pipeline_runs_120_years(mini_world_env):
    rep = run_mini_world_120y(mini_world_env["factory"], years=120)
    assert rep.steps == 120
    assert rep.runs == 120
    assert rep.final_blessed_tick == 120_000_000
    assert rep.checkpoints == 240  # 120 M1 + 120 M2
    assert rep.events == 120      # 仅 TIME_ADVANCE（NoOp 无领域事件）
    assert rep.population["end"] == 400
    assert len(rep.final_state_hash) == 64
    assert rep.engine_metrics["DEMOGRAPHY"] == {"steps": 120}


def test_pf15_one_shot_equals_chunked_replay(mini_world_env, tmp_path):
    a = run_mini_world_120y(mini_world_env["factory"], engines=_fakes(),
                            years=120)
    b = run_mini_world_120y(_fresh_env(tmp_path, 6)["factory"],
                            engines=_fakes(), years=120,
                            restart_every_years=30)
    assert a.final_blessed_tick == b.final_blessed_tick
    assert a.final_state_hash == b.final_state_hash
    assert a.engine_metrics == b.engine_metrics
    assert a.events == b.events


def test_pf16_restart_resume_hash_equivalent(mini_world_env, tmp_path):
    one = run_mini_world_120y(mini_world_env["factory"], engines=_fakes(),
                              years=120)
    env2 = _fresh_env(tmp_path, 7)
    part1 = run_mini_world_120y(env2["factory"], engines=_fakes(), years=60)
    assert part1.final_blessed_tick == 60_000_000
    part2 = run_mini_world_120y(env2["factory"], engines=_fakes(),
                                years=60, start_year=60)
    assert part2.final_blessed_tick == 120_000_000
    assert part2.final_state_hash == one.final_state_hash


@pytest.mark.parametrize("crash_after", [
    "before_snapshot", "engine:RESOURCE", "after_engines",
    "before_checkpoint", "after_checkpoint"])
def test_pf17_crash_boundaries_recover(mini_world_env, crash_after):
    factory = mini_world_env["factory"]
    s1 = factory()
    lease = WriterLease(s1, MINI_WORLD_ID, 120)
    lease.acquire()
    coordinator = SimulationCoordinator(
        [DeterministicFakeEngine("DEMOGRAPHY", 1), *[
            NoOpEngine(eid) for eid in ENGINE_ORDER if eid != "DEMOGRAPHY"]])
    with pytest.raises(RuntimeError):
        _one_year(factory, lease=lease, coordinator=coordinator,
                  crash_after=crash_after)
    with factory() as s:
        assert s.execute(select(WorldRuntime)).scalar_one().current_blessed_tick == 0
        m2 = s.execute(select(SimulationCheckpoint).where(
            text("json_extract(meta, '$.kind') = 'M2_PREFLIGHT'")
        )).scalars().all()
        assert m2 == []
        assert s.execute(select(WorldEvent).where(
            WorldEvent.event_type == "FAKE_STEP")).scalars().all() == []
    # 干净重试成功
    _one_year(factory, lease=lease, coordinator=coordinator)
    with factory() as s:
        assert s.execute(select(WorldRuntime)).scalar_one().current_blessed_tick == 1_000_000
        m2 = s.execute(select(SimulationCheckpoint).where(
            text("json_extract(meta, '$.kind') = 'M2_PREFLIGHT'")
        )).scalars().all()
        assert len(m2) == 1
        assert len(s.execute(select(WorldEvent).where(
            WorldEvent.event_type == "FAKE_STEP")).scalars().all()) == 1
    lease.release()
    s1.close()


def test_pf18_hash_canonical_ordering_stable(mini_world_env, tmp_path):
    factory = mini_world_env["factory"]
    with factory() as s:
        snap1 = read_snapshot(s, MINI_WORLD_ID)
        h1 = world_state_hash_v2(
            snapshot=snap1,
            simulation_version=PREFLIGHT_SIMULATION_VERSION,
            pipeline_version="m2-preflight-1",
            engine_versions={"DEMOGRAPHY": "fake-1"})
    # 第二个库以不同插入顺序建实体 → 哈希必须一致
    env2 = _fresh_env(tmp_path, 8)
    with env2["factory"]() as s:
        for row in s.execute(select(Settlement)).scalars():
            s.delete(row)
        for spec in reversed([  # 逆序插入
            {"working_name": "TEST-MAIN-A", "settlement_type": "MAIN",
             "region_ref": "TEST-REGION-1", "state": "STABLE",
             "population_capacity": 500},
            {"working_name": "TEST-SATELLITE-B", "settlement_type": "SATELLITE",
             "region_ref": "TEST-REGION-2", "state": "STABLE",
             "population_capacity": 200}]):
            s.add(Settlement(world_id=MINI_WORLD_ID, **spec))
        s.commit()
        snap2 = read_snapshot(s, MINI_WORLD_ID)
        h2 = world_state_hash_v2(
            snapshot=snap2,
            simulation_version=PREFLIGHT_SIMULATION_VERSION,
            pipeline_version="m2-preflight-1",
            engine_versions={"DEMOGRAPHY": "fake-1"})
    assert h1 == h2


def test_pf19_plugin_load_does_not_run_mini_world():
    for rel in ("main.py", "plugin_shell"):
        p = REPO / rel
        files = p.rglob("*.py") if p.is_dir() else [p]
        for f in files:
            src = f.read_text(encoding="utf-8")
            assert "mini_world" not in src, f
            assert "run_mini_world" not in src, f


# ---------------------------------------------------------------- 环境助手
def _fresh_env(tmp_path, i: int):
    db_path = tmp_path / f"mini_{i}.db"
    url = "sqlite:///" + str(db_path).replace("\\", "/")
    migrate_database(url, project_root=REPO)
    engine = create_db_engine(url)
    factory = make_session_factory(engine)
    with factory() as s:
        RuntimeRepository(s).create_not_activated(
            world_id=MINI_WORLD_ID, world_bible_version="1.0",
            simulation_version=PREFLIGHT_SIMULATION_VERSION,
            world_bible_manifest_hash="mini-test-hash")
        row = s.execute(select(WorldRuntime)).scalar_one()
        row.runtime_status = RuntimeStatus.ACTIVE
        row.world_seed_version = "MINI-TEST-SEED-001"
        row.current_blessed_tick = 0
        row.last_committed_real_us = EPOCH0_US
        row.time_rate_remainder = 0
        rate = TimeRatioRepository(s).add(
            world_id=MINI_WORLD_ID, real_effective_from=EPOCH0,
            rate_numerator=1_000_000, rate_denominator=86_400_000_000,
            reason="TEST", source="TEST")
        row.current_time_ratio_id = rate.ratio_id
        seed_mini_world(s)
        s.commit()
    return {"url": url, "factory": factory, "db_path": db_path}

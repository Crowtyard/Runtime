# -*- coding: utf-8 -*-
"""M2a Population Group Engine 测试：PA1–PA35 + 120 年基线产物。

全部运行于 tmp 临时库（mini_world）；正式 DB 零接触（zz 守护 + PA34）。
"""
from __future__ import annotations

from tests.formal_db import readonly_connect as formal_readonly_connect  # noqa: E402

import json
import re
import socket
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

import pytest
from sqlalchemy import select, text

from tests.conftest import EPOCH0, EPOCH0_US, PROJECT_ROOT
from tests.golden_baseline import (assert_deterministic_equal, dump_artifact,
                                   golden_bytes_guard, load_artifact,
                                   update_mode_enabled)

from XiaoguangBlessedLandRuntime.database.models_core import (SimulationCheckpoint,
                                                              WorldEvent,
                                                              WorldRuntime)
from XiaoguangBlessedLandRuntime.database.models_world import (Person,
                                                               PopulationGroup,
                                                               Settlement)
from XiaoguangBlessedLandRuntime.domain.errors import FencingViolation
from XiaoguangBlessedLandRuntime.services.catchup import catch_up
from XiaoguangBlessedLandRuntime.services.fencing import WorldMutationContext
from XiaoguangBlessedLandRuntime.services.simulation.contracts import (
    ENGINE_ORDER, DeterministicFakeEngine, Engine)
from XiaoguangBlessedLandRuntime.services.simulation.coordinator import (
    SimulationCoordinator)
from XiaoguangBlessedLandRuntime.services.simulation.harness import (
    YEAR_US, run_mini_world_120y)
from XiaoguangBlessedLandRuntime.services.simulation.mini_world import (
    MINI_WORLD_ID, MINI_SPECIES)
from XiaoguangBlessedLandRuntime.services.simulation.population import (
    ENGINE_VERSION, DemographyProfileUnconfigured, PopulationGroupEngine,
    PopulationModifiers, SpeciesDemographyProfile, SPECIES_PROFILES)
from XiaoguangBlessedLandRuntime.services.simulation.recovery import (
    latest_authoritative_world_checkpoint)
from XiaoguangBlessedLandRuntime.services.simulation.state_hash import (
    world_state_hash_v2)
from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease

REPO = PROJECT_ROOT
BASELINE_PATH = REPO / "tests" / "baselines" / \
    "m2a_population_miniworld_120y_v1.json"
SIM_DIR = REPO / "services" / "simulation"

# GB2：本模块每个测试前后 golden baseline 字节必须不变
_golden_bytes_guard = golden_bytes_guard(BASELINE_PATH)


def _fresh_env(tmp_path, i: int):
    from tests.test_preflight_pf import _fresh_env as _fe
    return _fe(tmp_path, i)


def _pop_engine(**kw):
    return PopulationGroupEngine(**kw)


def _group_sums(factory):
    with factory() as s:
        rows = s.execute(select(PopulationGroup)).scalars().all()
        by_settlement: dict[str, int] = {}
        for r in rows:
            by_settlement[r.settlement_ref] = \
                by_settlement.get(r.settlement_ref, 0) + r.count
        return by_settlement


# ------------------------------------------------------------------- PA1-PA15
def test_pa1_engine_implements_frozen_protocol():
    engine = _pop_engine()
    assert engine.engine_id == "DEMOGRAPHY"
    assert engine.engine_version == "m2a-1"
    assert callable(engine.simulate)
    result_type_ok = all(hasattr(engine, a) for a in
                         ("engine_id", "engine_version", "simulate"))
    assert result_type_ok


def test_pa2_no_direct_db_commit():
    src = (SIM_DIR / "population.py").read_text(encoding="utf-8")
    assert "session.commit" not in src
    assert "session.begin" not in src


def test_pa3_deterministic_same_input_replay(tmp_path):
    a = run_mini_world_120y(_fresh_env(tmp_path, 1)["factory"],
                            engines=[_pop_engine()], years=5)
    b = run_mini_world_120y(_fresh_env(tmp_path, 2)["factory"],
                            engines=[_pop_engine()], years=5)
    assert a.final_state_hash == b.final_state_hash
    assert a.engine_metrics == b.engine_metrics


def test_pa4_demography_rng_substream_deterministic(tmp_path):
    base = [_pop_engine(), *[DeterministicFakeEngine(eid, 3)
                             for eid in ENGINE_ORDER[1:]]]
    a = run_mini_world_120y(_fresh_env(tmp_path, 3)["factory"],
                            engines=base, years=2)
    b = run_mini_world_120y(_fresh_env(tmp_path, 4)["factory"],
                            engines=base, years=2)
    assert a.engine_metrics["RESOURCE"] == b.engine_metrics["RESOURCE"]
    assert a.engine_metrics["DEMOGRAPHY"] == b.engine_metrics["DEMOGRAPHY"]


def test_pa5_age_cohorts_sum_equals_population(tmp_path):
    env = _fresh_env(tmp_path, 5)
    report = run_mini_world_120y(env["factory"], engines=[_pop_engine()],
                                 years=10)
    sums = _group_sums(env["factory"])
    assert sum(sums.values()) == report.population["end"]


def test_pa6_births_deterministic(tmp_path):
    a = run_mini_world_120y(_fresh_env(tmp_path, 6)["factory"],
                            engines=[_pop_engine()], years=5)
    b = run_mini_world_120y(_fresh_env(tmp_path, 7)["factory"],
                            engines=[_pop_engine()], years=5)
    assert a.engine_metrics["DEMOGRAPHY"]["births"] == \
        b.engine_metrics["DEMOGRAPHY"]["births"]


def test_pa7_deaths_deterministic(tmp_path):
    a = run_mini_world_120y(_fresh_env(tmp_path, 8)["factory"],
                            engines=[_pop_engine()], years=5)
    b = run_mini_world_120y(_fresh_env(tmp_path, 9)["factory"],
                            engines=[_pop_engine()], years=5)
    assert a.engine_metrics["DEMOGRAPHY"]["deaths"] == \
        b.engine_metrics["DEMOGRAPHY"]["deaths"]


def test_pa8_migration_deterministic(tmp_path):
    a = run_mini_world_120y(_fresh_env(tmp_path, 10)["factory"],
                            engines=[_pop_engine()], years=5)
    b = run_mini_world_120y(_fresh_env(tmp_path, 11)["factory"],
                            engines=[_pop_engine()], years=5)
    assert a.engine_metrics["DEMOGRAPHY"]["emigration"] == \
        b.engine_metrics["DEMOGRAPHY"]["emigration"]
    assert a.engine_metrics["DEMOGRAPHY"]["immigration"] == \
        b.engine_metrics["DEMOGRAPHY"]["immigration"]


def test_pa9_population_conservation(tmp_path):
    env = _fresh_env(tmp_path, 12)
    report = run_mini_world_120y(env["factory"], engines=[_pop_engine()],
                                 years=20)
    m = report.engine_metrics["DEMOGRAPHY"]
    assert report.population["end"] == (
        report.population["start"] + m["births"] - m["deaths"]
        + m["immigration"] - m["emigration"])


def test_pa10_no_negative_population(tmp_path):
    env = _fresh_env(tmp_path, 13)
    run_mini_world_120y(env["factory"], engines=[_pop_engine()], years=120)
    with env["factory"]() as s:
        for g in s.execute(select(PopulationGroup)).scalars():
            assert g.count >= 0


def test_pa11_no_fractional_authoritative_persons(tmp_path):
    env = _fresh_env(tmp_path, 14)
    run_mini_world_120y(env["factory"], engines=[_pop_engine()], years=30)
    with env["factory"]() as s:
        for g in s.execute(select(PopulationGroup)).scalars():
            assert isinstance(g.count, int)
            assert g.count == int(g.count)


def test_pa12_different_species_profiles_supported(tmp_path):
    profile = SpeciesDemographyProfile(
        species_id="TEST_SPECIES_002", cohort_buckets=20,
        fertile_min_age=8, fertile_max_age=17,
        birth_rate=Fraction(1, 20),
        mortality_by_bucket=tuple(Fraction(1, 120) for _ in range(20)),
        emigration_rate=Fraction(1, 200),
        migration_weights=(Fraction(1, 2), Fraction(1, 2)))
    engine = _pop_engine(profiles={"TEST_SPECIES_002": profile})
    env = _fresh_env(tmp_path, 15)
    with env["factory"]() as s:
        for g in s.execute(select(PopulationGroup)).scalars():
            g.species = "TEST_SPECIES_002"
        s.commit()
    # 结构上可运行（buckets 20 与行 bucket 15..39 超出 → 收敛到末位；不报错）
    report = run_mini_world_120y(env["factory"], engines=[engine], years=2)
    assert report.final_blessed_tick == 2_000_000


def test_pa13_formal_species_remain_unconfigured():
    assert "HUMAN" not in SPECIES_PROFILES
    with pytest.raises(DemographyProfileUnconfigured):
        _pop_engine()._profile_of("HUMAN")


def test_pa14_aggregate_birth_creates_no_persistent_person(tmp_path):
    env = _fresh_env(tmp_path, 16)
    run_mini_world_120y(env["factory"], engines=[_pop_engine()], years=120)
    with env["factory"]() as s:
        assert s.execute(select(Person)).scalars().all() == []


def test_pa15_aggregate_death_deletes_no_individual_npcs(tmp_path):
    env = _fresh_env(tmp_path, 17)
    run_mini_world_120y(env["factory"], engines=[_pop_engine()], years=120)
    with env["factory"]() as s:
        assert s.execute(select(Person)).scalars().all() == []
        types = {e.event_type for e in s.execute(select(WorldEvent)).scalars()}
        assert types <= {"TIME_ADVANCE", "POPULATION_BIRTHS",
                         "POPULATION_DEATHS", "POPULATION_MIGRATION"}


# ------------------------------------------------------- PA16-PA22（事件/哈希）
def test_pa16_event_uid_deterministic(tmp_path):
    a = run_mini_world_120y(_fresh_env(tmp_path, 18)["factory"],
                            engines=[_pop_engine()], years=1)
    b = run_mini_world_120y(_fresh_env(tmp_path, 19)["factory"],
                            engines=[_pop_engine()], years=1)
    assert a.final_state_hash == b.final_state_hash
    assert a.events == b.events


def test_pa17_event_payload_changes_event_stream_hash(tmp_path):
    env_base = _fresh_env(tmp_path, 20)
    env_heavy = _fresh_env(tmp_path, 21)
    base = run_mini_world_120y(env_base["factory"],
                               engines=[_pop_engine()], years=2)
    heavy = run_mini_world_120y(
        env_heavy["factory"],
        engines=[_pop_engine(modifiers=PopulationModifiers(
            external_mortality_modifier=Fraction(1, 10)))], years=2)
    assert base.final_state_hash != heavy.final_state_hash  # 人口不同
    with env_base["factory"]() as s:
        h_base = latest_authoritative_world_checkpoint(
            s, MINI_WORLD_ID).meta["event_stream_hash"]
    with env_heavy["factory"]() as s:
        h_heavy = latest_authoritative_world_checkpoint(
            s, MINI_WORLD_ID).meta["event_stream_hash"]
    assert h_base != h_heavy  # 事件 payload 不同 → 事件流哈希不同


def test_pa18_same_state_different_event_history(tmp_path):
    from tests.test_hardening_hp import _SeqEngine
    env_a = _fresh_env(tmp_path, 22)
    env_b = _fresh_env(tmp_path, 23)
    a = run_mini_world_120y(env_a["factory"],
                            engines=[_pop_engine(), _SeqEngine("ab")], years=1)
    b = run_mini_world_120y(env_b["factory"],
                            engines=[_pop_engine(), _SeqEngine("ba")], years=1)
    assert a.final_state_hash == b.final_state_hash
    with env_a["factory"]() as s:
        ha = latest_authoritative_world_checkpoint(
            s, MINI_WORLD_ID).meta["event_stream_hash"]
    with env_b["factory"]() as s:
        hb = latest_authoritative_world_checkpoint(
            s, MINI_WORLD_ID).meta["event_stream_hash"]
    assert ha != hb


def test_pa19_population_included_in_state_hash(tmp_path):
    env_a = _fresh_env(tmp_path, 24)
    env_b = _fresh_env(tmp_path, 25)
    with env_a["factory"]() as s:
        ha = _hash_of(s)
    with env_b["factory"]() as s:
        g = s.execute(select(PopulationGroup)).scalars().first()
        g.count += 5
        s.commit()
        hb = _hash_of(s)
    assert ha != hb


def test_pa20_hash_independent_of_db_row_order(tmp_path):
    env_a = _fresh_env(tmp_path, 26)
    env_b = _fresh_env(tmp_path, 27)
    with env_a["factory"]() as s:
        ha = _hash_of(s)
    with env_b["factory"]() as s:
        rows = s.execute(select(PopulationGroup)).scalars().all()
        for r in rows:
            s.delete(r)
        s.flush()
        for r in reversed(rows):  # 逆序重插（不同 id 顺序）
            s.add(PopulationGroup(
                world_id=r.world_id, species=r.species,
                settlement_ref=r.settlement_ref, age_cohort=r.age_cohort,
                occupation_group=r.occupation_group, count=r.count,
                age_advance_carry_ticks=r.age_advance_carry_ticks,
                species_profile_ref=r.species_profile_ref,
                demography_version=r.demography_version))
        s.commit()
        hb = _hash_of(s)
    assert ha == hb


def test_pa21_retry_zero_duplicate_demography(tmp_path):
    env = _fresh_env(tmp_path, 28)
    a = run_mini_world_120y(env["factory"], engines=[_pop_engine()], years=1)
    sums = _group_sums(env["factory"])
    b = run_mini_world_120y(env["factory"], engines=[_pop_engine()], years=1)
    assert b.final_blessed_tick == a.final_blessed_tick
    assert _group_sums(env["factory"]) == sums  # 无重复出生/死亡/迁移


def test_pa22_retry_zero_duplicate_events(tmp_path):
    env = _fresh_env(tmp_path, 29)
    run_mini_world_120y(env["factory"], engines=[_pop_engine()], years=1)
    with env["factory"]() as s:
        uids = {e.event_uid for e in s.execute(select(WorldEvent)).scalars()}
    run_mini_world_120y(env["factory"], engines=[_pop_engine()], years=1)
    with env["factory"]() as s:
        assert {e.event_uid for e in s.execute(
            select(WorldEvent)).scalars()} == uids


# ----------------------------------------------------- PA23-PA26（fencing/崩溃）
def test_pa23_stale_writer_cannot_commit_population(tmp_path):
    env = _fresh_env(tmp_path, 30)
    factory = env["factory"]
    s1 = factory()
    lease = WriterLease(s1, MINI_WORLD_ID, 120)
    lease.acquire()
    coordinator = SimulationCoordinator([_pop_engine()])
    with pytest.raises(FencingViolation):
        with WorldMutationContext(factory(), world_id=MINI_WORLD_ID,
                                  writer_id=lease.owner,
                                  fencing_token=lease.token) as ctx:
            coordinator.run_step(
                ctx.session, world_id=MINI_WORLD_ID,
                blessed_start_tick=0, blessed_end_tick=1_000_000,
                real_interval_start_us=EPOCH0_US,
                real_interval_end_us=EPOCH0_US + YEAR_US)
            ctx.session.execute(text(
                "UPDATE runtime_lock SET lease_token='STOLEN'"))
            ctx.commit()
    assert _group_sums(factory) == {"TEST-MAIN-A": 300, "TEST-SATELLITE-B": 100}
    lease.release()
    s1.close()


def test_pa24_crash_between_time_and_world_committed(tmp_path):
    """C9：TIME_COMMITTED 与 WORLD_COMMITTED 同事务 —— 崩溃后两者都不存在。"""
    env = _fresh_env(tmp_path, 31)
    factory = env["factory"]
    s1 = factory()
    lease = WriterLease(s1, MINI_WORLD_ID, 120)
    lease.acquire()
    coordinator = SimulationCoordinator([_pop_engine()])
    with pytest.raises(RuntimeError):
        catch_up(factory, world_id=MINI_WORLD_ID,
                 now_real_us=EPOCH0_US + YEAR_US,
                 writer_id=lease.owner, fencing_token=lease.token,
                 simulation_version="0.2.0-preflight",
                 simulate_fn=lambda s, info: coordinator.run_step(
                     s, world_id=MINI_WORLD_ID,
                     blessed_start_tick=info["new_blessed_tick"]
                     - info["delta_ticks"],
                     blessed_end_tick=info["new_blessed_tick"],
                     real_interval_start_us=info["real_interval_start_us"],
                     real_interval_end_us=info["real_interval_end_us"],
                     step_index=1, crash_after="before_checkpoint"))
    with factory() as s:
        assert s.execute(select(WorldRuntime)).scalar_one().current_blessed_tick == 0
        assert _group_sums(factory) == {"TEST-MAIN-A": 300,
                                        "TEST-SATELLITE-B": 100}
        assert latest_authoritative_world_checkpoint(s, MINI_WORLD_ID) is None
    # 重试 → 一致
    catch_up(factory, world_id=MINI_WORLD_ID,
             now_real_us=EPOCH0_US + YEAR_US,
             writer_id=lease.owner, fencing_token=lease.token,
             simulation_version="0.2.0-preflight",
             simulate_fn=lambda s, info: coordinator.run_step(
                 s, world_id=MINI_WORLD_ID,
                 blessed_start_tick=info["new_blessed_tick"]
                 - info["delta_ticks"],
                 blessed_end_tick=info["new_blessed_tick"],
                 real_interval_start_us=info["real_interval_start_us"],
                 real_interval_end_us=info["real_interval_end_us"],
                 step_index=1))
    with factory() as s:
        assert s.execute(select(WorldRuntime)).scalar_one().current_blessed_tick \
            == 1_000_000
    lease.release()
    s1.close()


@pytest.mark.parametrize("crash_after", [
    "before_snapshot", "engine:DEMOGRAPHY", "after_engines",
    "before_apply", "before_checkpoint", "after_checkpoint"])
def test_pa25_crash_matrix_c1_c10(tmp_path, crash_after):
    env = _fresh_env(tmp_path, 32 + hash(crash_after) % 50)
    factory = env["factory"]
    s1 = factory()
    lease = WriterLease(s1, MINI_WORLD_ID, 120)
    lease.acquire()
    coordinator = SimulationCoordinator([_pop_engine()])

    def step(s, info, _ca=None):
        return coordinator.run_step(
            s, world_id=MINI_WORLD_ID,
            blessed_start_tick=info["new_blessed_tick"] - info["delta_ticks"],
            blessed_end_tick=info["new_blessed_tick"],
            real_interval_start_us=info["real_interval_start_us"],
            real_interval_end_us=info["real_interval_end_us"],
            step_index=1, crash_after=_ca)

    with pytest.raises(RuntimeError):
        catch_up(factory, world_id=MINI_WORLD_ID,
                 now_real_us=EPOCH0_US + YEAR_US,
                 writer_id=lease.owner, fencing_token=lease.token,
                 simulation_version="0.2.0-preflight",
                 simulate_fn=lambda s, info: step(s, info, crash_after))
    with factory() as s:
        assert s.execute(select(WorldRuntime)).scalar_one().current_blessed_tick == 0
        assert _group_sums(factory) == {"TEST-MAIN-A": 300,
                                        "TEST-SATELLITE-B": 100}
    # 干净重跑 == 一次成功（确定性）
    catch_up(factory, world_id=MINI_WORLD_ID,
             now_real_us=EPOCH0_US + YEAR_US,
             writer_id=lease.owner, fencing_token=lease.token,
             simulation_version="0.2.0-preflight",
             simulate_fn=step)
    with factory() as s:
        assert s.execute(select(WorldRuntime)).scalar_one().current_blessed_tick \
            == 1_000_000
    clean = run_mini_world_120y(_fresh_env(tmp_path, 90)["factory"],
                                engines=[_pop_engine()], years=1)
    with factory() as s:
        world = latest_authoritative_world_checkpoint(s, MINI_WORLD_ID)
        assert world is not None
    assert clean.final_state_hash == _hash_of_latest(factory)
    lease.release()
    s1.close()


def test_pa26_restart_resume_deterministic(tmp_path):
    one = run_mini_world_120y(_fresh_env(tmp_path, 40)["factory"],
                              engines=[_pop_engine()], years=120)
    env = _fresh_env(tmp_path, 41)
    part1 = run_mini_world_120y(env["factory"], engines=[_pop_engine()],
                                years=60)
    part2 = run_mini_world_120y(env["factory"], engines=[_pop_engine()],
                                years=60, start_year=60)
    assert part2.final_state_hash == one.final_state_hash
    assert part2.population["end"] == one.population["end"]
    combined = {k: part1.engine_metrics["DEMOGRAPHY"][k]
                + part2.engine_metrics["DEMOGRAPHY"][k]
                for k in ("births", "deaths", "immigration", "emigration")}
    assert combined == {k: one.engine_metrics["DEMOGRAPHY"][k]
                        for k in ("births", "deaths", "immigration",
                                  "emigration")}


# ------------------------------------------- PA27-PA29（120y 真实基线）
def test_pa27_120y_real_baseline(tmp_path):
    start = datetime.now(timezone.utc)
    env = _fresh_env(tmp_path, 42)
    report = run_mini_world_120y(env["factory"], engines=[_pop_engine()],
                                 years=120)
    wall = (datetime.now(timezone.utc) - start).total_seconds()
    assert report.steps == 120
    assert report.runs == 120
    assert report.checkpoints == 240
    assert report.final_blessed_tick == 120_000_000
    assert report.population["end"] > 0
    assert report.engine_metrics["DEMOGRAPHY"]["births"] > 0
    assert report.engine_metrics["DEMOGRAPHY"]["deaths"] > 0
    # candidate 与 committed golden 比较（telemetry 剥离）；普通 pytest 只读
    artifact = _build_baseline(env, report, wall)
    golden = load_artifact(BASELINE_PATH)
    assert_deterministic_equal(
        golden, artifact, label="m2a_population_miniworld_120y_v1",
        golden_path=BASELINE_PATH)
    if update_mode_enabled():  # 显式更新：scripts/update_baselines.py
        dump_artifact(artifact, BASELINE_PATH)
    assert BASELINE_PATH.exists()


def test_pa28_120y_no_invariant_violation(tmp_path):
    env = _fresh_env(tmp_path, 43)
    report = run_mini_world_120y(env["factory"], engines=[_pop_engine()],
                                 years=120)
    m = report.engine_metrics["DEMOGRAPHY"]
    assert m["births"] >= 0 and m["deaths"] >= 0
    assert m["immigration"] >= 0 and m["emigration"] >= 0
    assert report.population["end"] == (
        report.population["start"] + m["births"] - m["deaths"]
        + m["immigration"] - m["emigration"])
    with env["factory"]() as s:
        cohorts = {}
        for g in s.execute(select(PopulationGroup)).scalars():
            assert g.count >= 0
            cohorts[g.settlement_ref] = cohorts.get(g.settlement_ref, 0) + g.count
        # 结构未崩坏：末位（老龄）与首位（儿童）bucket 均存在且非负
        buckets = {int(g.age_cohort) for g in s.execute(
            select(PopulationGroup)).scalars()}
        assert 0 in buckets and 39 in buckets
    # 不灭绝、不爆炸（TEST 参数下）
    assert 0.5 * report.population["start"] <= report.population["end"] \
        <= 750


def test_pa29_one_shot_equals_chunked(tmp_path):
    one = run_mini_world_120y(_fresh_env(tmp_path, 44)["factory"],
                              engines=[_pop_engine()], years=120)
    chunk = run_mini_world_120y(_fresh_env(tmp_path, 45)["factory"],
                                engines=[_pop_engine()], years=120,
                                restart_every_years=30)
    assert one.final_state_hash == chunk.final_state_hash
    assert one.population == chunk.population
    assert one.engine_metrics == chunk.engine_metrics


# ------------------------------------------- PA30-PA35（边界与保护）
def test_pa30_pa31_zero_llm_zero_network(tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("simulation core 触碰网络/LLM 传输")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr("urllib.request.urlopen", _boom, raising=False)
    monkeypatch.setattr("http.client.HTTPConnection", _boom, raising=False)
    rep = run_mini_world_120y(_fresh_env(tmp_path, 46)["factory"],
                              engines=[_pop_engine()], years=5)
    assert rep.final_blessed_tick == 5_000_000


def test_pa32_no_wall_clock_for_simulation_truth():
    pattern = re.compile(
        r"\b(datetime\.now|time\.time|time\.monotonic|perf_counter"
        r"|time_ns|date\.today)\s*\(")
    src = (SIM_DIR / "population.py").read_text(encoding="utf-8")
    assert not pattern.search(src)


def test_pa33_world_seed_not_consumed():
    for py in SIM_DIR.rglob("*.py"):
        src = py.read_text(encoding="utf-8")
        assert "world_seed" not in src, py
        assert "04_population_baseline" not in src, py


def test_pa34_pa35_formal_db_protected(formal_db_guard):
    import hashlib
    import os
    path = os.environ.get("BLR_FORMAL_DB_PATH", "")
    if not path or formal_db_guard is None:
        pytest.skip("BLR_FORMAL_DB_PATH 未设置")
    after = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    assert after == formal_db_guard
    import sqlite3
    conn = formal_readonly_connect(path)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM population_groups").fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM world_runtime").fetchone()[0] == 0, \
            "canonical NOT_ACTIVATED = world_runtime 0 行"
        
    finally:
        conn.close()


# ------------------------------------------------------------------ 工具
def _hash_of(s) -> str:
    from XiaoguangBlessedLandRuntime.services.simulation.snapshot import \
        read_snapshot
    snap = read_snapshot(s, MINI_WORLD_ID)
    return world_state_hash_v2(
        snapshot=snap, simulation_version="0.2.0-preflight",
        pipeline_version="m2-preflight-1",
        engine_versions={"DEMOGRAPHY": ENGINE_VERSION})


def _hash_of_latest(factory) -> str:
    with factory() as s:
        return latest_authoritative_world_checkpoint(
            s, MINI_WORLD_ID).world_state_hash


def _write_baseline(env, report, wall_seconds: float) -> None:
    """显式更新入口：仅 BLR_UPDATE_GOLDEN_BASELINES=1 时写 golden。"""
    dump_artifact(_build_baseline(env, report, wall_seconds), BASELINE_PATH)


def _build_baseline(env, report, wall_seconds: float) -> dict:
    with env["factory"]() as s:
        latest = latest_authoritative_world_checkpoint(s, MINI_WORLD_ID)
        event_hash = latest.meta["event_stream_hash"]
        groups = [{"settlement": g.settlement_ref, "age_cohort": g.age_cohort,
                   "count": g.count}
                  for g in s.execute(select(PopulationGroup)).scalars()]
    artifact = {
        "fixture_version": "mini_world_v1",
        "simulation_version": "0.2.0-preflight",
        "population_engine_version": ENGINE_VERSION,
        "rng_schema_version": "m1-derive-seed-v1",
        "state_hash_schema_version": 2,
        "event_hash_schema_version": 1,
        "event_uid_schema_version": 1,
        "initial_state": {"population": 400, "settlements": 2,
                          "species": MINI_SPECIES},
        "final_state": {"population": report.population["end"],
                        "settlement_sums": _group_sums(env["factory"]),
                        "cohorts": groups},
        "metrics": {
            "births": report.engine_metrics["DEMOGRAPHY"]["births"],
            "deaths": report.engine_metrics["DEMOGRAPHY"]["deaths"],
            "immigration": report.engine_metrics["DEMOGRAPHY"]["immigration"],
            "emigration": report.engine_metrics["DEMOGRAPHY"]["emigration"],
            "population_start": report.population["start"],
            "population_end": report.population["end"],
            "event_count": report.events,
        },
        "final_world_state_hash": report.final_state_hash,
        "final_event_stream_hash": event_hash,
        "runs": report.runs,
        "steps": report.steps,
        "checkpoints": report.checkpoints,
        # 仅性能指标，不参与确定性哈希语义
        "performance": {"wall_seconds": round(wall_seconds, 3)},
    }
    return artifact


def test_baseline_artifact_reproducible(tmp_path):
    """同输入重跑必须复现基线哈希（baseline v1 冻结）。"""
    artifact = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    env = _fresh_env(tmp_path, 91)
    report = run_mini_world_120y(env["factory"], engines=[_pop_engine()],
                                 years=120)
    assert report.final_state_hash == artifact["final_world_state_hash"]
    with env["factory"]() as s:
        event_hash = latest_authoritative_world_checkpoint(
            s, MINI_WORLD_ID).meta["event_stream_hash"]
    assert event_hash == artifact["final_event_stream_hash"]
    assert report.engine_metrics["DEMOGRAPHY"]["births"] == \
        artifact["metrics"]["births"]

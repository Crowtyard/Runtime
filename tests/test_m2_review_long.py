# -*- coding: utf-8 -*-
"""M2 Integrated Completion Review —— 长时程压力测试（LT1–LT9）。

LONG_HORIZON_SYNTHETIC_WORLD（TEST_FIXTURE_ONLY）：5 个固定 deterministic
seeds × 1000 福地年 + 1 个 5000 年 endurance。全部真实引擎，tmp 临时库，
正式 DB / World Seed 零接触。运行时间较长（专用执行）。

seeds = world_id（RNG 派生含 world_id → 不同世界 = 不同确定性随机轨迹）。
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select, text

from tests.conftest import EPOCH0, EPOCH0_US, PROJECT_ROOT

from XiaoguangBlessedLandRuntime.database.models_core import (SimulationCheckpoint,
                                                              SimulationRun,
                                                              WorldEvent,
                                                              WorldRuntime)
from XiaoguangBlessedLandRuntime.database.models_world import (
    EcologyState, Household, Institution, Lineage, PopulationGroup,
    ResourceNode, ResourceStock, SettlementSocialState)
from XiaoguangBlessedLandRuntime.domain.errors import FencingViolation
from XiaoguangBlessedLandRuntime.services import fencing as fencing_mod
from XiaoguangBlessedLandRuntime.services.catchup import catch_up
from XiaoguangBlessedLandRuntime.services.simulation.coordinator import (
    SimulationCoordinator)
from XiaoguangBlessedLandRuntime.services.simulation.ecology import (
    ECOLOGY_STATE_SCALE, EcologyEngine)
from XiaoguangBlessedLandRuntime.services.simulation.economy import EconomyEngine
from XiaoguangBlessedLandRuntime.services.simulation.harness import (
    YEAR_US, run_mini_world_120y)
from XiaoguangBlessedLandRuntime.services.simulation.population import (
    PopulationGroupEngine)
from XiaoguangBlessedLandRuntime.services.simulation.recovery import (
    latest_authoritative_world_checkpoint)
from XiaoguangBlessedLandRuntime.services.simulation.resource import ResourceEngine
from XiaoguangBlessedLandRuntime.services.simulation.social import (
    SOCIAL_STATE_SCALE, SocialEngine)
from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease

REPO = PROJECT_ROOT
SIM_VERSION = "0.2.0-preflight"
LONG_WORLD_IDS = [f"LONGHORIZON-{n:03d}" for n in range(1, 6)]
BASELINE_DIR = REPO / "tests" / "baselines" / "m2_integrated_1000y_v1"
SUMMARY_PATH = BASELINE_DIR / "summary.json"


def _engines():
    return [PopulationGroupEngine(), ResourceEngine(), EconomyEngine(),
            EcologyEngine(), SocialEngine()]


def _fresh_long(tmp_path, i: int, world_id: str):
    from XiaoguangBlessedLandRuntime.database.db import (create_db_engine,
                                                         make_session_factory)
    from XiaoguangBlessedLandRuntime.database.models_core import WorldRuntime
    from XiaoguangBlessedLandRuntime.domain.constants import RuntimeStatus
    from XiaoguangBlessedLandRuntime.services.db_lifecycle import \
        migrate_database
    from XiaoguangBlessedLandRuntime.services.repositories import (
        RuntimeRepository, TimeRatioRepository)
    from XiaoguangBlessedLandRuntime.services.simulation.mini_world import \
        seed_mini_world
    db_path = tmp_path / f"long_{i}_{world_id}.db"
    url = "sqlite:///" + str(db_path).replace("\\", "/")
    migrate_database(url, project_root=REPO)
    engine = create_db_engine(url)
    factory = make_session_factory(engine)
    with factory() as s:
        RuntimeRepository(s).create_not_activated(
            world_id=world_id, world_bible_version="1.0",
            simulation_version=SIM_VERSION, world_bible_manifest_hash="long")
        row = s.execute(select(WorldRuntime)).scalar_one()
        row.runtime_status = RuntimeStatus.ACTIVE
        row.world_seed_version = "LONG-TEST-SEED-001"
        row.current_blessed_tick = 0
        row.last_committed_real_us = EPOCH0_US
        row.time_rate_remainder = 0
        rate = TimeRatioRepository(s).add(
            world_id=world_id, real_effective_from=EPOCH0,
            rate_numerator=1_000_000, rate_denominator=86_400_000_000,
            reason="TEST", source="TEST")
        row.current_time_ratio_id = rate.ratio_id
        seed_mini_world(s, with_ecology=True, with_social=True,
                        world_id=world_id)
        s.commit()
    return {"url": url, "factory": factory, "db_path": db_path,
            "world_id": world_id}


def _invariant_check(env) -> dict:
    """长时程全不变量审计（返回违规清单；空 = clean）。"""
    issues: list[str] = []
    world_id = env["world_id"]
    with env["factory"]() as s:
        # 人口：非负、cohort 一致、守恒
        total = 0
        for g in s.execute(select(PopulationGroup)).scalars():
            if g.count < 0 or not isinstance(g.count, int):
                issues.append(f"pop negative/non-int {g.id}")
            total += g.count
        if total <= 0:
            issues.append("population extinct (unexplained)")
        if total > 10_000_000:
            issues.append(f"population explosion {total}")
        # 家庭归属 full-coverage
        for key_sref in ("TEST-MAIN-A", "TEST-SATELLITE-B"):
            rep = sum(h.represented_population for h in s.execute(
                select(Household).where(Household.settlement_ref == key_sref,
                                        Household.state == "ACTIVE")
            ).scalars())
            pop = sum(g.count for g in s.execute(
                select(PopulationGroup).where(
                    PopulationGroup.settlement_ref == key_sref)).scalars())
            if rep != pop:
                issues.append(f"coverage drift {key_sref}: {rep} != {pop}")
        # 家庭/家系/机构规模有界
        if len(s.execute(select(Household)).scalars().all()) > 10_000:
            issues.append("household explosion")
        if len(s.execute(select(Lineage)).scalars().all()) > 2_000:
            issues.append("lineage explosion")
        if len(s.execute(select(Institution)).scalars().all()) > 100:
            issues.append("institution explosion")
        for lg in s.execute(select(Lineage)).scalars():
            if lg.represented_population < 0 or lg.household_count < 0:
                issues.append(f"lineage negative {lg.lineage_id}")
        for i in s.execute(select(Institution)).scalars():
            if i.state not in ("ACTIVE", "DECLINING", "DORMANT", "DISSOLVED"):
                issues.append(f"institution state {i.state}")
        # 资源：非负、ceiling、carry 有界
        for n in s.execute(select(ResourceNode)).scalars():
            if (n.remaining_reserve or 0) < 0:
                issues.append(f"reserve negative {n.kind}")
            if n.reserve_ceiling_minor is not None \
                    and (n.remaining_reserve or 0) > n.reserve_ceiling_minor:
                issues.append(f"reserve over ceiling {n.kind}")
            if not (0 <= n.extraction_carry < 1_000_000):
                issues.append(f"extraction carry {n.extraction_carry}")
            if not (0 <= n.regeneration_carry < 1_000_000):
                issues.append(f"regen carry {n.regeneration_carry}")
        # 库存与 ledger
        for r in s.execute(select(ResourceStock)).scalars():
            if r.quantity < 0:
                issues.append(f"stock negative {r.id}")
            if not (0 <= r.consumption_carry < 6_000_000):
                issues.append(f"consumption carry {r.consumption_carry}")
        # 生态有界
        for st in s.execute(select(EcologyState)).scalars():
            if not (0 <= st.habitat_quality <= ECOLOGY_STATE_SCALE):
                issues.append(f"quality out of range {st.zone_ref}")
            if not (0 <= st.ecological_stress <= ECOLOGY_STATE_SCALE):
                issues.append(f"stress out of range {st.zone_ref}")
            if st.degradation_carry < 0 or st.recovery_carry < 0:
                issues.append(f"ecology carry {st.zone_ref}")
        # 社会有界
        for r in s.execute(select(SettlementSocialState)).scalars():
            if not (0 <= r.social_stress <= SOCIAL_STATE_SCALE):
                issues.append(f"social stress range {r.settlement_ref}")
        # 事件 UID 无碰撞
        uids = [e.event_uid for e in s.execute(select(WorldEvent)).scalars()]
        if len(set(uids)) != len(uids):
            issues.append("event uid collision")
        for u in uids:
            if len(u) != 32:
                issues.append("event uid width")
        # 实体 ID 无碰撞
        ids = [h.household_id for h in s.execute(select(Household)).scalars()]
        ids += [lg.lineage_id for lg in s.execute(select(Lineage)).scalars()
                if lg.lineage_id]
        ids += [i.institution_id for i in s.execute(select(Institution))
                .scalars() if i.institution_id]
        if len(set(ids)) != len(ids):
            issues.append("entity id collision")
    return {"issues": issues, "clean": not issues}


def _row_counts(env) -> dict:
    world_id = env["world_id"]
    conn_engine = None
    from XiaoguangBlessedLandRuntime.database.db import create_db_engine
    conn_engine = create_db_engine(env["url"])
    with conn_engine.connect() as c:
        counts = {}
        for t in ("world_events", "population_groups", "households",
                  "lineages", "institutions", "resource_nodes",
                  "resource_stocks", "ecology_state", "ecology_feedback_state",
                  "settlement_social_state", "social_feedback_state",
                  "simulation_checkpoints", "simulation_run"):
            counts[t] = c.execute(text(
                f'SELECT COUNT(*) FROM "{t}"')).scalar()
        counts["world_id"] = world_id
        return counts


def _db_size_mb(env) -> float:
    return env["db_path"].stat().st_size / (1024 * 1024)


def _final_hashes(env) -> dict:
    with env["factory"]() as s:
        world = latest_authoritative_world_checkpoint(s, env["world_id"])
        return {"world_state_hash": world.world_state_hash,
                "event_stream_hash": world.meta["event_stream_hash"]}


def _final_metrics(env) -> dict:
    """终态聚合指标（含震荡审计：min/max 见证值）。"""
    with env["factory"]() as s:
        pop = {g.settlement_ref: 0 for g in s.execute(
            select(PopulationGroup)).scalars()}
        for g in s.execute(select(PopulationGroup)).scalars():
            pop[g.settlement_ref] = pop.get(g.settlement_ref, 0) + g.count
        hhs = s.execute(select(Household)).scalars().all()
        lgs = s.execute(select(Lineage)).scalars().all()
        insts = s.execute(select(Institution)).scalars().all()
        social = {r.settlement_ref: r for r in s.execute(
            select(SettlementSocialState)).scalars()}
        ecol = {r.zone_ref: r for r in s.execute(select(EcologyState))
                .scalars()}
        events = s.execute(select(WorldEvent)).scalars().all()
        return {
            "population_by_settlement": pop,
            "households_active": len([h for h in hhs
                                      if h.state == "ACTIVE"]),
            "households_total": len(hhs),
            "max_household_generation": max((h.generation for h in hhs),
                                            default=0),
            "lineages_total": len(lgs),
            "lineages_active": len([lg for lg in lgs
                                    if lg.status == "ACTIVE"]),
            "lineages_extinct": len([lg for lg in lgs
                                     if lg.status == "EXTINCT"]),
            "max_lineage_generation": max((lg.generation for lg in lgs),
                                          default=0),
            "institutions_total": len(insts),
            "institutions_dissolved": len([i for i in insts
                                           if i.state == "DISSOLVED"]),
            "social_stress": {k: v.social_stress for k, v in social.items()},
            "stress_min_seen": {k: v.stress_min_seen for k, v in social.items()},
            "stress_max_seen": {k: v.stress_max_seen for k, v in social.items()},
            "quality_min_seen": {k: v.quality_min_seen for k, v in ecol.items()},
            "quality_max_seen": {k: v.quality_max_seen for k, v in ecol.items()},
            "event_count": len(events),
        }


# ============================ 长时程 driver（crash/fencing 注入） ============
def _crash_schedule(years: int, n: int, offset: int = 0) -> dict[int, str]:
    kinds = ["mid:SOCIAL_HOUSEHOLD", "mid:SOCIAL_LINEAGE",
             "engine:ECOLOGY", "mid:ECONOMY", "before_checkpoint",
             "after_engines", "during_apply", "mid:SOCIAL_INSTITUTION",
             "engine:SOCIAL", "mid:SOCIAL"]
    schedule: dict[int, str] = {}
    y = 7 + offset
    for i in range(n):
        y = (y * 37 + offset * 13 + 101) % (years - 10) + 5
        schedule[y] = kinds[i % len(kinds)]
    return schedule


def _run_with_adversity(env, years, *, crash_schedule=None, ack_years=(),
                        fence_years=(), monkeypatch=None) -> dict:
    """逐年度推进（真实 5 引擎），注入 crash / ack-lost / fencing。

    返回 {"world_state_hash", "event_stream_hash", "fencing_violations",
    "crashes", "ack_losses"}。所有注入确定性（schedule 由参数给定）。
    """
    factory = env["factory"]
    world_id = env["world_id"]
    s1 = factory()
    lease = WriterLease(s1, world_id, 100_000)
    lease.acquire()
    writer_id, token = lease.owner, lease.token
    coordinator = SimulationCoordinator(_engines())

    def step(s, info, _i, _ca=None):
        return coordinator.run_step(
            s, world_id=world_id,
            blessed_start_tick=info["new_blessed_tick"] - info["delta_ticks"],
            blessed_end_tick=info["new_blessed_tick"],
            real_interval_start_us=info["real_interval_start_us"],
            real_interval_end_us=info["real_interval_end_us"],
            step_index=_i, crash_after=_ca)

    stats = {"crashes": 0, "ack_losses": 0, "fencing_violations": 0}
    # ack-lost 注入：commit 成功后第 2 次 commit 抛（durable 已提交）
    ack_state = {"armed": False, "phase": 0}
    original_commit = fencing_mod.WorldMutationContext.commit

    def patched_commit(self):
        original_commit(self)
        ack_state["phase"] += 1
        if ack_state["armed"] and ack_state["phase"] == 2:
            ack_state["armed"] = False
            raise RuntimeError("simulated COMMIT ACK LOST (endurance)")

    if monkeypatch is not None:
        monkeypatch.setattr(fencing_mod.WorldMutationContext, "commit",
                            patched_commit)

    for year in range(1, years + 1):
        now_us = EPOCH0_US + year * YEAR_US
        ack_state["phase"] = 0
        if year in fence_years:
            with factory() as s:
                s.execute(text(
                    "UPDATE runtime_lock SET expires_at='2000-01-01'"))
                s.commit()
            with pytest.raises(FencingViolation):
                catch_up(factory, world_id=world_id, now_real_us=now_us,
                         writer_id=writer_id, fencing_token=token,
                         simulation_version=SIM_VERSION,
                         simulate_fn=lambda s, info, _y=year:
                         step(s, info, _y))
            stats["fencing_violations"] += 1
            # B takeover：新 token 接管后续运行
            lease_b = WriterLease(factory(), world_id, 100_000)
            lease_b.acquire()
            writer_id, token = lease_b.owner, lease_b.token
            lease.release()
            lease = lease_b
        if year in ack_years:
            ack_state["armed"] = True
            with pytest.raises(RuntimeError, match="ACK LOST"):
                catch_up(factory, world_id=world_id, now_real_us=now_us,
                         writer_id=writer_id, fencing_token=token,
                         simulation_version=SIM_VERSION,
                         simulate_fn=lambda s, info, _y=year:
                         step(s, info, _y))
            stats["ack_losses"] += 1
            # durable 已提交 → 本年度不再重试
            continue
        ca = (crash_schedule or {}).get(year)
        if ca:
            with pytest.raises(RuntimeError):
                catch_up(factory, world_id=world_id, now_real_us=now_us,
                         writer_id=writer_id, fencing_token=token,
                         simulation_version=SIM_VERSION,
                         simulate_fn=lambda s, info, _y=year, _c=ca:
                         step(s, info, _y, _c))
            stats["crashes"] += 1
            # 干净重试
            catch_up(factory, world_id=world_id, now_real_us=now_us,
                     writer_id=writer_id, fencing_token=token,
                     simulation_version=SIM_VERSION,
                     simulate_fn=lambda s, info, _y=year:
                     step(s, info, _y))
            continue
        catch_up(factory, world_id=world_id, now_real_us=now_us,
                 writer_id=writer_id, fencing_token=token,
                 simulation_version=SIM_VERSION,
                 simulate_fn=lambda s, info, _y=year: step(s, info, _y))

    lease.release()
    s1.close()
    hashes = _final_hashes(env)
    return {**hashes, **stats}


# ============================ 测试 ============================
@pytest.mark.parametrize("world_id", LONG_WORLD_IDS)
def test_lt1_1000y_five_seeds(tmp_path, world_id):
    env = _fresh_long(tmp_path, 1, world_id)
    t0 = time.perf_counter()
    rep = run_mini_world_120y(env["factory"], engines=_engines(),
                              world_id=world_id, years=1000)
    wall = time.perf_counter() - t0
    assert rep.steps == 1000 and rep.checkpoints == 2000
    assert rep.final_blessed_tick == 1_000_000_000
    audit = _invariant_check(env)
    assert audit["clean"], (world_id, audit["issues"])
    # 记录（供基线产物；重复运行相同）
    record = {
        "world_id": world_id,
        "years": 1000,
        "wall_seconds": round(wall, 3),
        "db_size_mb": round(_db_size_mb(env), 3),
        "row_counts": _row_counts(env),
        "final_metrics": _final_metrics(env),
        "final_hashes": _final_hashes(env),
        "runs": rep.runs, "steps": rep.steps,
        "checkpoints": rep.checkpoints,
        "population": rep.population,
        "resource": rep.resource,
        "economy": rep.economy,
        "ecology": rep.ecology,
        "social": rep.social,
        "engine_metrics": rep.engine_metrics,
        "invariant_issues": audit["issues"],
    }
    _write_seed_baseline(record)


def test_lt2_seed_001_determinism_double_run(tmp_path):
    world_id = LONG_WORLD_IDS[0]
    a = _fresh_long(tmp_path, 2, world_id)
    b = _fresh_long(tmp_path, 3, world_id)
    ra = run_mini_world_120y(a["factory"], engines=_engines(),
                             world_id=world_id, years=1000)
    rb = run_mini_world_120y(b["factory"], engines=_engines(),
                             world_id=world_id, years=1000)
    assert ra.final_state_hash == rb.final_state_hash
    assert _final_hashes(a)["event_stream_hash"] \
        == _final_hashes(b)["event_stream_hash"]
    assert _final_metrics(a) == _final_metrics(b)
    assert _row_counts(a) == _row_counts(b)


def test_lt3_chunked_replay_1000y(tmp_path):
    world_id = LONG_WORLD_IDS[0]
    one = _fresh_long(tmp_path, 4, world_id)
    rep1 = run_mini_world_120y(one["factory"], engines=_engines(),
                               world_id=world_id, years=1000)
    for chunk, idx in ((100, 5), (250, 6)):
        env = _fresh_long(tmp_path, idx, world_id)
        repc = run_mini_world_120y(env["factory"], engines=_engines(),
                                   world_id=world_id, years=1000,
                                   restart_every_years=chunk)
        assert repc.final_state_hash == rep1.final_state_hash
        assert repc.final_blessed_tick == rep1.final_blessed_tick
        assert _final_hashes(env) == _final_hashes(one)


def test_lt4_restart_every_10y_100_restarts(tmp_path):
    world_id = LONG_WORLD_IDS[0]
    one = _fresh_long(tmp_path, 7, world_id)
    rep1 = run_mini_world_120y(one["factory"], engines=_engines(),
                               world_id=world_id, years=1000)
    env = _fresh_long(tmp_path, 8, world_id)
    repc = run_mini_world_120y(env["factory"], engines=_engines(),
                               world_id=world_id, years=1000,
                               restart_every_years=10)
    assert repc.final_state_hash == rep1.final_state_hash
    assert repc.runs == 1000
    assert _final_hashes(env) == _final_hashes(one)


def test_lt5_crash_endurance_50_crashes(tmp_path, monkeypatch):
    world_id = LONG_WORLD_IDS[0]
    schedule = _crash_schedule(1000, 50)
    ack_years = sorted(schedule.keys())[::10][:5]  # 5 次 ack lost
    clean = _fresh_long(tmp_path, 9, world_id)
    rep = run_mini_world_120y(clean["factory"], engines=_engines(),
                              world_id=world_id, years=1000)
    env = _fresh_long(tmp_path, 10, world_id)
    res = _run_with_adversity(env, 1000, crash_schedule=schedule,
                              ack_years=set(ack_years),
                              monkeypatch=monkeypatch)
    assert res["crashes"] >= 45
    assert res["ack_losses"] == 5
    assert res["world_state_hash"] == rep.final_state_hash
    assert res["event_stream_hash"] \
        == _final_hashes(clean)["event_stream_hash"]
    assert _final_metrics(env) == _final_metrics(clean)


def test_lt6_fencing_endurance_takeovers(tmp_path):
    world_id = LONG_WORLD_IDS[0]
    clean = _fresh_long(tmp_path, 11, world_id)
    rep = run_mini_world_120y(clean["factory"], engines=_engines(),
                              world_id=world_id, years=1000)
    env = _fresh_long(tmp_path, 12, world_id)
    res = _run_with_adversity(env, 1000, fence_years={200, 400, 600, 800})
    assert res["fencing_violations"] == 4
    assert res["world_state_hash"] == rep.final_state_hash
    assert res["event_stream_hash"] \
        == _final_hashes(clean)["event_stream_hash"]


def test_lt7_5000y_endurance(tmp_path):
    world_id = LONG_WORLD_IDS[0]
    env = _fresh_long(tmp_path, 13, world_id)
    t0 = time.perf_counter()
    rep = run_mini_world_120y(env["factory"], engines=_engines(),
                              world_id=world_id, years=5000)
    wall = time.perf_counter() - t0
    assert rep.steps == 5000 and rep.final_blessed_tick == 5_000_000_000
    audit = _invariant_check(env)
    assert audit["clean"], audit["issues"]
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    summary["endurance_5000y"] = {
        "world_id": world_id, "wall_seconds": round(wall, 3),
        "db_size_mb": round(_db_size_mb(env), 3),
        "row_counts": _row_counts(env),
        "final_metrics": _final_metrics(env),
        "final_hashes": _final_hashes(env),
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                            encoding="utf-8")


def test_lt8_baseline_artifacts_and_summary(tmp_path):
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    assert BASELINE_DIR.exists()
    files = sorted(BASELINE_DIR.glob("seed_*.json"))
    assert len(files) == 5
    # seed_001 复现：重跑对照产物哈希
    artifact = json.loads((BASELINE_DIR / "seed_001.json").read_text(
        encoding="utf-8"))
    env = _fresh_long(tmp_path, 14, LONG_WORLD_IDS[0])
    rep = run_mini_world_120y(env["factory"], engines=_engines(),
                              world_id=LONG_WORLD_IDS[0], years=1000)
    assert rep.final_state_hash == artifact["final_hashes"]["world_state_hash"]
    assert _final_hashes(env)["event_stream_hash"] \
        == artifact["final_hashes"]["event_stream_hash"]
    # summary 存在且覆盖 5 seeds
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    assert set(summary["seeds"].keys()) == set(LONG_WORLD_IDS)


def test_lt9_db_growth_recorded(tmp_path):
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    assert "db_growth" in summary
    g = summary["db_growth"]
    assert g["unit"] == "MB per 100 blessed years"
    # 增长可理解：1000 年每 seed DB < 200MB（聚合模型规模可控）
    for seed, mb in g["size_mb_1000y"].items():
        assert mb < 200, (seed, mb)


# ============================ 产物写入 ============================
def _write_seed_baseline(record: dict) -> None:
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    seed_no = record["world_id"].split("-")[1]
    path = BASELINE_DIR / f"seed_{seed_no}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    _refresh_summary()


def _refresh_summary() -> None:
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    seeds = {}
    for p in sorted(BASELINE_DIR.glob("seed_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        seeds[d["world_id"]] = {
            "final_hashes": d["final_hashes"],
            "wall_seconds": d["wall_seconds"],
            "db_size_mb": d["db_size_mb"],
            "final_metrics": d["final_metrics"],
            "row_counts": d["row_counts"],
        }
    growth = {
        "unit": "MB per 100 blessed years",
        "size_mb_1000y": {k: v["db_size_mb"] for k, v in seeds.items()},
        "per_100y": {k: round(v["db_size_mb"] / 10, 4)
                     for k, v in seeds.items()},
    }
    summary = {
        "fixture_version": "mini_world_v1",
        "simulation_version": SIM_VERSION,
        "long_horizon": "LONG_HORIZON_SYNTHETIC_WORLD (TEST_FIXTURE_ONLY, not Canon)",
        "engine_versions": {"DEMOGRAPHY": "m2a-1",
                            "RESOURCE": "m2b-resource-1",
                            "ECONOMY": "m2b-economy-1",
                            "ECOLOGY": "m2c-ecology-1",
                            "SOCIAL": "m2d-social-1"},
        "world_state_hash_schema_version": 5,
        "event_stream_hash_schema_version": 1,
        "event_uid_schema_version": 1,
        "social_entity_id_schema_version": "social-v2",
        "seeds": seeds,
        "db_growth": growth,
    }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                            encoding="utf-8")

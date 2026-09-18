# -*- coding: utf-8 -*-
"""M3 Integrated Completion Review —— 长时程集成压力测试（M3c，官方版）。

M3_INTEGRATED_LONG_HORIZON（TEST_FIXTURE_ONLY）：5 个固定 deterministic
seeds × 1000 福地年 + seed_001 5000 年 endurance。
真实全 pipeline：TIME→DEMOGRAPHY→RESOURCE→ECONOMY→ECOLOGY→SOCIAL→
TRIBULATION→DOMAIN IMPACT ADAPTERS→CAUSAL HISTORY INDEXING（无 Fake/NoOp）。
tmp 临时库；正式 DB / World Seed 零接触。运行时间较长（专用执行）。

Golden Baseline 政策（tests/GOLDEN_BASELINES.md，GB1-GB10）：
- 普通 pytest 只读 tests/baselines/；candidate 只写 tmp 或
  M3C_CANDIDATE_DIR（repo-external，正式验收用）；
- committed golden 存在时，candidate 必须逐字段复现（telemetry 剥离），
  否则 FAIL（GB10）；
- 写 committed golden 仅限显式更新模式（BLR_UPDATE_GOLDEN_BASELINES=1，
  scripts/update_baselines.py）。
"""
from __future__ import annotations

import json
import os
import re
import statistics
import time
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from tests.conftest import EPOCH0_US, PROJECT_ROOT
from tests.golden_baseline import (assert_deterministic_equal, dump_artifact,
                                   golden_bytes_guard, load_artifact,
                                   update_mode_enabled)
from tests.test_m3b_history import _hist_coordinator

from XiaoguangBlessedLandRuntime.database.models_core import (WorldEvent,
                                                              WorldRuntime)
from XiaoguangBlessedLandRuntime.database.models_world import (
    CausalHistoryLink, EcologyState, EntityHistoryIndex, HistoryEpisodeIndex,
    HistoryStateChange, Household, Institution, Lineage, PopulationGroup,
    ResourceNode, ResourceStock, ResourceSuccessionCandidate,
    SettlementSocialState, TribulationEpisode, TribulationRecoveryState)
from XiaoguangBlessedLandRuntime.domain.errors import FencingViolation
from XiaoguangBlessedLandRuntime.services import fencing as fencing_mod
from XiaoguangBlessedLandRuntime.services.catchup import catch_up
from XiaoguangBlessedLandRuntime.services.history.metrics import (
    duplicate_semantic_links_audit, episode_state_audit,
    transitive_materialization_audit)
from XiaoguangBlessedLandRuntime.services.history.service import HistoryService
from XiaoguangBlessedLandRuntime.services.simulation.m3a_runner import \
    run_m3a_world
from XiaoguangBlessedLandRuntime.services.simulation.mini_world import \
    MINI_WORLD_ID
from XiaoguangBlessedLandRuntime.services.simulation.recovery import \
    latest_authoritative_world_checkpoint
from XiaoguangBlessedLandRuntime.services.simulation.tribulation import \
    M3A_SIMULATION_VERSION
from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease

REPO = PROJECT_ROOT
SIM_VERSION = M3A_SIMULATION_VERSION
M3_LONG_WORLD_IDS = [f"M3LONG-{n:03d}" for n in range(1, 6)]
BASELINE_DIR = REPO / "tests" / "baselines" / "m3_integrated_1000y_v1"
SUMMARY_PATH = BASELINE_DIR / "summary.json"
ENDURANCE_PATH = REPO / "tests" / "baselines" / \
    "m3_integrated_5000y_seed001_v1.json"

# GB2：本模块拥有的 committed golden 文件，每个测试前后字节必须不变
_golden_bytes_guard = golden_bytes_guard(
    *[BASELINE_DIR / f"seed_{n:03d}.json" for n in range(1, 6)],
    SUMMARY_PATH, ENDURANCE_PATH)

# 正式验收运行：candidate 产物目录（repo-external，绝不写 tests/baselines/）
CANDIDATE_DIR = Path(os.environ["M3C_CANDIDATE_DIR"]) \
    if os.environ.get("M3C_CANDIDATE_DIR") else None

# 同进程内 lt1 生成的参考记录（跨测试引用，避免依赖"刚写入的 golden 文件"）
_SEED_RECORDS: dict[str, dict] = {}


def _dump_candidate(name: str, artifact: dict) -> None:
    if CANDIDATE_DIR is None:
        return
    p = CANDIDATE_DIR / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(artifact, ensure_ascii=False, indent=1),
                 encoding="utf-8")


def _seed_reference(seed_no: str) -> dict:
    """seed 参考记录：同进程 lt1 缓存 → candidate 目录 → committed golden。

    三者都没有 → 显式失败（核心等价性证据不得静默缺失/跳过）。
    """
    if seed_no in _SEED_RECORDS:
        return _SEED_RECORDS[seed_no]
    if CANDIDATE_DIR is not None:
        p = CANDIDATE_DIR / f"seed_{seed_no}.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    p = BASELINE_DIR / f"seed_{seed_no}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    raise AssertionError(
        f"seed_{seed_no} 参考缺失：需先运行 lt1（同进程）或存在 "
        "candidate/committed golden")


def _load_summary() -> dict | None:
    if SUMMARY_PATH.exists():
        return json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    if CANDIDATE_DIR is not None and (CANDIDATE_DIR / "summary.json").exists():
        return json.loads((CANDIDATE_DIR / "summary.json").read_text(
            encoding="utf-8"))
    return None


def _fresh_m3(tmp_path, i: int, world_id: str):
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
    db_path = tmp_path / f"m3_long_{i}_{world_id}.db"
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
        row.world_seed_version = "M3-LONG-TEST-SEED-001"
        row.current_blessed_tick = 0
        row.last_committed_real_us = EPOCH0_US
        row.time_rate_remainder = 0
        from tests.conftest import EPOCH0
        rate = TimeRatioRepository(s).add(
            world_id=world_id, real_effective_from=EPOCH0,
            rate_numerator=1_000_000, rate_denominator=86_400_000_000,
            reason="TEST", source="TEST")
        row.current_time_ratio_id = rate.ratio_id
        seed_mini_world(s, with_ecology=True, with_social=True,
                        with_tribulation=True, world_id=world_id)
        s.commit()
    return {"url": url, "factory": factory, "db_path": db_path,
            "world_id": world_id}


def _m3_run(env, years=1000, restart_every_years=None):
    return run_m3a_world(env["factory"], coordinator=_hist_coordinator(),
                         world_id=env["world_id"], years=years,
                         restart_every_years=restart_every_years)


# ---------------------------------------------------------------- 审计
def _invariant_check(env) -> dict:
    issues: list[str] = []
    world_id = env["world_id"]
    with env["factory"]() as s:
        total = sum(g.count for g in s.execute(select(PopulationGroup))
                    .scalars())
        if total <= 0:
            issues.append("population extinct")
        if total > 10_000_000:
            issues.append(f"population explosion {total}")
        for g in s.execute(select(PopulationGroup)).scalars():
            if g.count < 0:
                issues.append("pop negative")
        if len(s.execute(select(Household)).scalars().all()) > 10_000:
            issues.append("household explosion")
        if len(s.execute(select(Lineage)).scalars().all()) > 2_000:
            issues.append("lineage explosion")
        if len(s.execute(select(Institution)).scalars().all()) > 100:
            issues.append("institution explosion")
        for n in s.execute(select(ResourceNode)).scalars():
            if (n.remaining_reserve or 0) < 0:
                issues.append("reserve negative")
        for r in s.execute(select(ResourceStock)).scalars():
            if r.quantity < 0:
                issues.append("stock negative")
        for st in s.execute(select(EcologyState)).scalars():
            if not (0 <= st.habitat_quality <= 1_000_000):
                issues.append("quality range")
        for r in s.execute(select(SettlementSocialState)).scalars():
            if not (0 <= r.social_stress <= 1_000_000):
                issues.append("stress range")
        # 灾劫：阶段合法 + 分类守恒 + Episode 线性（无同窗重复）+ 无 silent stuck
        eps = s.execute(select(TribulationEpisode).order_by(
            TribulationEpisode.entered_tick)).scalars().all()
        seen_ticks = {}
        now_tick = s.execute(text(
            "SELECT current_blessed_tick FROM world_runtime")).scalar() or 0
        for e in eps:
            if e.current_stage not in ("PRECURSOR", "PREPARATION", "IMPACT",
                                       "RESPONSE", "STABILIZATION",
                                       "RESIDUAL_CHANGE", "RECOVERY",
                                       "RESOURCE_SUCCESSION", "NEW_NORMAL"):
                issues.append(f"illegal stage {e.current_stage}")
            key = (e.entered_tick, e.window_tier)
            seen_ticks[key] = seen_ticks.get(key, 0) + 1
            if seen_ticks[key] > 1:
                issues.append(f"duplicate window {key}")
            if e.status == "ACTIVE" \
                    and (now_tick - (e.entered_tick or 0)) > 50_000_000:
                issues.append(f"silent stuck episode {e.episode_id} "
                              f"age={(now_tick - e.entered_tick)//1_000_000}y")
        for r in s.execute(select(TribulationRecoveryState)).scalars():
            if not (0 <= r.progress_num <= r.progress_den * 100):
                issues.append("recovery progress bound")
        for c in s.execute(select(ResourceSuccessionCandidate)).scalars():
            if c.development_status != "NONE":
                issues.append("succession materialized unexpectedly")
        uids = [e.event_uid for e in s.execute(select(WorldEvent)).scalars()]
        if len(set(uids)) != len(uids):
            issues.append("event uid collision")
    # 历史完整性
    audit = HistoryService(env["factory"]).history_integrity_audit(
        world_id=world_id)
    if audit["orphan_links"] or audit["cycle_count"] \
            or audit["tick_paradox_links"] or audit["supersede_loops"]:
        issues.append(f"history integrity {audit['orphan_links']}/"
                      f"{audit['cycle_count']}")
    dup = duplicate_semantic_links_audit(env["factory"], world_id=world_id)
    if dup["duplicate_semantic_links"]:
        issues.append("duplicate semantic links")
    tr = transitive_materialization_audit(env["factory"], world_id=world_id)
    if tr["purely_redundant_transitive_links"]:
        issues.append("redundant transitive links")
    return {"issues": issues, "clean": not issues}


def _sql_counts(env) -> dict:
    """SQL 聚合统计（避免 5000y 全量 ORM 载入）。"""
    with env["factory"]() as s:
        counts = {}
        for t in ("world_events", "population_groups", "households",
                  "lineages", "institutions", "resource_nodes",
                  "resource_stocks", "ecology_state",
                  "settlement_social_state", "simulation_checkpoints",
                  "simulation_run", "tribulation_episodes",
                  "tribulation_recovery_states",
                  "resource_succession_candidates",
                  "causal_history_links", "entity_history_index",
                  "history_state_changes", "history_episode_index"):
            counts[t] = s.execute(text(
                f'SELECT COUNT(*) FROM "{t}"')).scalar()
        counts["distinct_entities_with_history"] = s.execute(text(
            "SELECT COUNT(DISTINCT entity_type || ':' || entity_id) "
            "FROM entity_history_index")).scalar()
        counts["entity_history_index_rows"] = counts["entity_history_index"]
        return counts


def _trib_metrics(env) -> dict:
    """灾劫 + 恢复长周期指标（口径冻结，与 preliminary 一致）。

    - active_recovery：以 Episode 当前阶段为准（stage==RECOVERY 的
      ACTIVE episode 数）。tribulation_recovery_states 行是逐 episode
      账本记录，episode 推进后不再更新，行数随 episode 线性增长。
    - mean/max_recovery_duration：按每 episode RECOVERY_PROGRESS 事件
      时间跨度（首→末 progress tick）统计。
    """
    world_id = env["world_id"]
    ep = episode_state_audit(env["factory"], world_id=world_id)
    s = ep["summary"]
    with env["factory"]() as f:
        active_eps = f.execute(select(TribulationEpisode).where(
            TribulationEpisode.world_id == world_id,
            TribulationEpisode.status == "ACTIVE",
            TribulationEpisode.current_stage == "RECOVERY")).scalars().all()
        stale_rows = f.execute(select(TribulationRecoveryState).where(
            TribulationRecoveryState.world_id == world_id,
            TribulationRecoveryState.status == "IN_PROGRESS")).scalars().all()
        now_tick = f.execute(text(
            "SELECT current_blessed_tick FROM world_runtime")).scalar()
        dur_rows = f.execute(text(
            "SELECT l.episode_id, MIN(e.blessed_tick), MAX(e.blessed_tick) "
            "FROM causal_history_links l JOIN world_events e "
            "ON l.source_kind='EVENT' AND l.source_id=e.event_uid "
            "WHERE l.world_id=:w AND l.relation_type='PART_OF_EPISODE' "
            "AND e.event_type='TRIBULATION_RECOVERY_PROGRESS' "
            "GROUP BY l.episode_id"),
            {"w": world_id}).all()
    ages = [now_tick - (e.entered_tick or 0) for e in active_eps]
    durs = [(mx - mn) // 1_000_000 for (_, mn, mx) in dur_rows]
    return {
        "scheduled_episodes": s["scheduled_episodes"],
        "terminal_completed": s["completed_episodes"],
        "active": s["active_episodes"],
        "recovering": s["recovering_episodes"],
        "new_normal_pending": ep["mutually_exclusive_states"][
            "EPISODE_STATE_NEW_NORMAL_PENDING"],
        "precursor": ep["mutually_exclusive_states"][
            "EPISODE_STATE_PRECURSOR"],
        "mutex_sum": sum(ep["mutually_exclusive_states"].values()),
        "active_recovery_count": len(active_eps),
        "oldest_active_recovery_age_years":
            max(ages) // 1_000_000 if ages else 0,
        "recovery_rows_total": len(stale_rows),
        "recovery_rows_stale_status_semantics":
            "per-episode ledger rows; not updated after episode advances;"
            " linear growth (one row per episode)",
        "mean_recovery_duration_years":
            round(sum(durs) / len(durs), 2) if durs else 0,
        "max_recovery_duration_years": max(durs) if durs else 0,
    }


def _hashes(env) -> dict:
    with env["factory"]() as s:
        world = latest_authoritative_world_checkpoint(s, env["world_id"])
        hist = HistoryService(env["factory"]).causal_history_hash(
            world_id=env["world_id"])
        return {"world_state_hash": world.world_state_hash,
                "event_stream_hash": world.meta["event_stream_hash"],
                "causal_history_hash": hist["hash"]}


def _db_size_mb(env) -> float:
    return env["db_path"].stat().st_size / (1024 * 1024)


def _record(env, rep, wall) -> dict:
    return {
        "world_id": env["world_id"],
        "years": rep.years,
        "wall_seconds": round(wall, 3),
        "db_size_mb": round(_db_size_mb(env), 3),
        "final_blessed_tick": rep.final_blessed_tick,
        "counts": _sql_counts(env),
        "tribulation": _trib_metrics(env),
        "hashes": _hashes(env),
        "invariant_issues": _invariant_check(env)["issues"],
    }


# ---------------------------------------------------------------- adversity
def _m3_crash_schedule(years: int) -> dict[int, str]:
    """确定性崩溃表（≥50 次，覆盖 M2 步骤 + 灾劫全生命周期 + 历史暂存）。

    - 每 20 年一个 REGULAR episode（tier 无关的通用阶段偏移）：
      +1 PRECURSOR、+2 PREPARATION、+3 IMPACT（含 adapters）、
      +8 RECOVERY progress；
    - 通用点：engine:TRIBULATION / before_checkpoint（history 暂存同事务）/
      after_engines / during_apply / engine:ECOLOGY。
    """
    schedule: dict[int, str] = {}
    stage_kinds = ["tribulation:precursor", "tribulation:preparation",
                   "tribulation:impact_plan", "adapter:ECOLOGY",
                   "tribulation:recovery", "engine:TRIBULATION",
                   "before_checkpoint"]
    for k in range(1, 11):
        base = 20 * k
        for offset, kind in zip((1, 2, 3, 3, 8, 1, 2),
                                stage_kinds):
            y = base + offset
            if y < years:
                schedule[y] = kind
    # 通用 M2 点（伪随机年）
    kinds2 = ["after_engines", "during_apply", "engine:ECOLOGY",
              "engine:SOCIAL", "engine:ECONOMY"]
    y = 7
    for i in range(10):
        y = (y * 37 + 101) % (years - 10) + 5
        if y not in schedule:
            schedule[y] = kinds2[i % len(kinds2)]
    return schedule


def _run_m3_adversity(env, years, *, crash_schedule=None, ack_years=(),
                      fence_years=(), monkeypatch=None) -> dict:
    factory = env["factory"]
    world_id = env["world_id"]
    s1 = factory()
    lease = WriterLease(s1, world_id, 100_000)
    lease.acquire()
    writer_id, token = lease.owner, lease.token
    coordinator = _hist_coordinator()

    def step(s, info, _i, _ca=None):
        return coordinator.run_step(
            s, world_id=world_id,
            blessed_start_tick=info["new_blessed_tick"] - info["delta_ticks"],
            blessed_end_tick=info["new_blessed_tick"],
            real_interval_start_us=info["real_interval_start_us"],
            real_interval_end_us=info["real_interval_end_us"],
            step_index=_i, crash_after=_ca,
            simulation_run_id=info.get("simulation_run_id"))

    stats = {"crashes": 0, "ack_losses": 0, "fencing_violations": 0}
    ack_state = {"armed": False, "phase": 0}
    original_commit = fencing_mod.WorldMutationContext.commit

    def patched_commit(self):
        original_commit(self)
        ack_state["phase"] += 1
        if ack_state["armed"] and ack_state["phase"] == 2:
            ack_state["armed"] = False
            raise RuntimeError("simulated COMMIT ACK LOST (m3 endurance)")

    if monkeypatch is not None:
        monkeypatch.setattr(fencing_mod.WorldMutationContext, "commit",
                            patched_commit)

    for year in range(1, years + 1):
        now_us = EPOCH0_US + year * 86_400_000_000
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
            continue  # durable 已提交；本年不重试
        ca = (crash_schedule or {}).get(year)
        if ca:
            try:
                catch_up(factory, world_id=world_id, now_real_us=now_us,
                         writer_id=writer_id, fencing_token=token,
                         simulation_version=SIM_VERSION,
                         simulate_fn=lambda s, info, _y=year, _c=ca:
                         step(s, info, _y, _c))
            except RuntimeError:
                stats["crashes"] += 1
            # 干净重试（幂等：已提交则 skip）
            catch_up(factory, world_id=world_id, now_real_us=now_us,
                     writer_id=writer_id, fencing_token=token,
                     simulation_version=SIM_VERSION,
                     simulate_fn=lambda s, info, _y=year: step(s, info, _y))
            continue
        catch_up(factory, world_id=world_id, now_real_us=now_us,
                 writer_id=writer_id, fencing_token=token,
                 simulation_version=SIM_VERSION,
                 simulate_fn=lambda s, info, _y=year: step(s, info, _y))

    lease.release()
    s1.close()
    return {**_hashes(env), **stats}


# ============================ 测试 ============================
@pytest.mark.parametrize("world_id", M3_LONG_WORLD_IDS)
def test_lt1_1000y_five_seeds(tmp_path, world_id):
    env = _fresh_m3(tmp_path, 1, world_id)
    t0 = time.perf_counter()
    rep = _m3_run(env, years=1000)
    wall = time.perf_counter() - t0
    assert rep.final_blessed_tick == 1_000_000_000
    audit = _invariant_check(env)
    assert audit["clean"], (world_id, audit["issues"])
    record = _record(env, rep, wall)
    seed_no = world_id.split("-")[1]
    _SEED_RECORDS[seed_no] = record
    _dump_candidate(f"seed_{seed_no}.json", record)
    golden = BASELINE_DIR / f"seed_{seed_no}.json"
    if update_mode_enabled():
        # M6D.3 OPT-1（TEST_INFRA_UPDATE_MODE_REPAIR，与 M3a/M3b artifact 测试同一
        # 修复形态）：update mode 写入**当前** artifact 即完成，不先要求等于旧
        # baseline；normal mode 行为逐字不变。
        dump_artifact(record, golden)
        return
    if golden.exists():
        # 已冻结：candidate 必须逐字段复现（telemetry 剥离），否则 FAIL
        assert_deterministic_equal(
            load_artifact(golden), record,
            label=f"m3_integrated_1000y_v1/seed_{seed_no}",
            golden_path=golden)


def test_lt2_seed_001_determinism_double_run(tmp_path):
    world_id = M3_LONG_WORLD_IDS[0]
    a = _fresh_m3(tmp_path, 2, world_id)
    b = _fresh_m3(tmp_path, 3, world_id)
    ra = _m3_run(a, years=1000)
    rb = _m3_run(b, years=1000)
    assert _hashes(a) == _hashes(b)
    assert ra.final_state_hash == rb.final_state_hash
    assert _sql_counts(a) == _sql_counts(b)
    ref = _seed_reference("001")
    assert _hashes(a) == ref["hashes"]


def test_lt3_chunked_replay_1000y(tmp_path):
    world_id = M3_LONG_WORLD_IDS[0]
    one = _fresh_m3(tmp_path, 4, world_id)
    rep1 = _m3_run(one, years=1000)
    for chunk, idx in ((100, 5), (250, 6)):
        env = _fresh_m3(tmp_path, idx, world_id)
        repc = _m3_run(env, years=1000, restart_every_years=chunk)
        assert repc.final_state_hash == rep1.final_state_hash
        assert _hashes(env) == _hashes(one)
    ref = _seed_reference("001")
    assert _hashes(one) == ref["hashes"]


def test_lt4_restart_equivalence(tmp_path):
    world_id = M3_LONG_WORLD_IDS[0]
    one = _fresh_m3(tmp_path, 7, world_id)
    rep1 = _m3_run(one, years=1000)
    # 每 10 年 restart × 100
    env10 = _fresh_m3(tmp_path, 8, world_id)
    rep10 = _m3_run(env10, years=1000, restart_every_years=10)
    assert rep10.final_state_hash == rep1.final_state_hash
    assert _hashes(env10) == _hashes(one)
    # 生命周期边界 restart（7 年切分 → 反复落在灾劫阶段中间）
    env7 = _fresh_m3(tmp_path, 9, world_id)
    rep7 = _m3_run(env7, years=1000, restart_every_years=7)
    assert rep7.final_state_hash == rep1.final_state_hash
    assert _hashes(env7) == _hashes(one)
    ref = _seed_reference("001")
    assert _hashes(one) == ref["hashes"]


def test_lt5_crash_schedule_equivalence(tmp_path, monkeypatch):
    world_id = M3_LONG_WORLD_IDS[0]
    schedule = _m3_crash_schedule(1000)
    assert len(schedule) >= 50
    env = _fresh_m3(tmp_path, 10, world_id)
    ack_years = sorted(schedule.keys())[::10][:5]
    res = _run_m3_adversity(env, 1000, crash_schedule=schedule,
                            ack_years=set(ack_years),
                            monkeypatch=monkeypatch)
    assert res["crashes"] >= 45
    assert res["ack_losses"] == 5
    ref = _seed_reference("001")
    assert res["world_state_hash"] == ref["hashes"]["world_state_hash"]
    assert res["event_stream_hash"] == ref["hashes"]["event_stream_hash"]
    assert res["causal_history_hash"] == ref["hashes"]["causal_history_hash"]


def test_lt6_fencing_takeovers(tmp_path):
    world_id = M3_LONG_WORLD_IDS[0]
    env = _fresh_m3(tmp_path, 11, world_id)
    res = _run_m3_adversity(env, 1000, fence_years={200, 400, 600, 800})
    assert res["fencing_violations"] == 4
    ref = _seed_reference("001")
    assert res["world_state_hash"] == ref["hashes"]["world_state_hash"]
    assert res["event_stream_hash"] == ref["hashes"]["event_stream_hash"]
    assert res["causal_history_hash"] == ref["hashes"]["causal_history_hash"]


def test_lt7_5000y_endurance(tmp_path):
    world_id = M3_LONG_WORLD_IDS[0]
    env = _fresh_m3(tmp_path, 12, world_id)
    t0 = time.perf_counter()
    rep = _m3_run(env, years=5000)
    wall = time.perf_counter() - t0
    assert rep.final_blessed_tick == 5_000_000_000
    audit = _invariant_check(env)
    assert audit["clean"], audit["issues"]
    record = _record(env, rep, wall)
    # 增长形态判定：每 100y 密度（线性参考 300y 基线 ≈ 21914 links/100y）
    counts = record["counts"]
    links_per_100y = counts["causal_history_links"] / 50
    idx_per_100y = counts["entity_history_index"] / 50
    assert links_per_100y < 21914 * 1.6   # 无超线性失控（允许常数放大）
    assert idx_per_100y < 21619 * 1.6
    _dump_candidate("endurance_5000y_seed001.json", record)
    if update_mode_enabled():
        # M6D.3 OPT-1：update mode 写入当前 artifact 即完成（形态同 M3a/M3b）。
        dump_artifact(record, ENDURANCE_PATH)
        return
    if ENDURANCE_PATH.exists():
        assert_deterministic_equal(
            load_artifact(ENDURANCE_PATH), record,
            label="m3_integrated_5000y_seed001_v1",
            golden_path=ENDURANCE_PATH)


def test_lt8_1000y_query_performance_and_why(tmp_path):
    """1000y 库查询性能（p50/p95/max）+ 5 问结构化因果回溯（不断链）。

    结果必须来自结构化 History Graph（state ← change ← event ← cause），
    不允许自然语言推测字段。
    """
    world_id = M3_LONG_WORLD_IDS[0]
    env = _fresh_m3(tmp_path, 13, world_id)
    _m3_run(env, years=1000)
    svc = HistoryService(env["factory"])
    with env["factory"]() as s:
        z = s.execute(select(EcologyState)).scalars().first()
        n = s.execute(select(ResourceNode)).scalars().first()
        st = s.execute(select(SettlementSocialState)).scalars().first()
        inst = s.execute(select(Institution)).scalars().first()
        cands = s.execute(select(ResourceSuccessionCandidate)).scalars().all()
        eps = s.execute(select(TribulationEpisode).order_by(
            TribulationEpisode.entered_tick)).scalars().all()
        major = [e for e in eps if e.window_tier == "MAJOR"][0]
    assert cands, "1000y 应有 succession candidates"
    perf = {}
    for name, fn in (
        ("entity_history", lambda: svc.get_entity_history(
            world_id=world_id, entity_type="ecology_state",
            entity_id=str(z.id))),
        ("episode_history", lambda: svc.get_tribulation_history(
            world_id=world_id, episode_id=major.episode_id)),
        ("explain_state", lambda: svc.explain_state(
            world_id=world_id, entity_type="ecology_state",
            entity_id=str(z.id), field="habitat_quality", max_depth=4,
            max_nodes=40)),
        ("trace_causes", lambda: svc.trace_causes(
            world_id=world_id, kind="EPISODE",
            node_id=major.episode_id, max_depth=4)),
        ("timeline", lambda: svc.get_timeline(
            world_id=world_id, start_tick=999_000_000,
            end_tick=1_000_000_000)),
    ):
        fn()
        ts = []
        for _ in range(10):
            t = time.perf_counter()
            fn()
            ts.append((time.perf_counter() - t) * 1000)
        perf[name] = {"p50_ms": round(statistics.median(ts), 3),
                      "p95_ms": round(sorted(ts)[8], 3),
                      "max_ms": round(max(ts), 3)}
    _dump_candidate("query_performance_1000y.json", perf)

    # 5 问：结构化图回溯不断链（§17）
    def _assert_structured(resp: dict, label: str):
        assert isinstance(resp, dict), label
        assert not (set(resp) & {"text", "explanation", "narrative",
                                 "summary"}), \
            f"{label}: 出现自然语言字段（必须来自结构化 History Graph）"
    q1 = svc.explain_state(world_id=world_id, entity_type="ecology_state",
                           entity_id=str(z.id), field="habitat_quality",
                           max_depth=4)
    _assert_structured(q1, "why-ecology")
    assert q1["last_state_change"] is not None
    q2 = svc.explain_state(world_id=world_id, entity_type="resource_nodes",
                           entity_id=str(n.id),
                           field="remaining_reserve", max_depth=4)
    _assert_structured(q2, "why-resource")
    assert q2["last_state_change"] is not None
    q3 = svc.explain_state(world_id=world_id,
                           entity_type="settlement_social_state",
                           entity_id=str(st.id), field="social_stress",
                           max_depth=4)
    _assert_structured(q3, "why-social-stress")
    assert q3["last_state_change"] is not None
    q4 = svc.explain_state(world_id=world_id, entity_type="institutions",
                           entity_id=str(inst.id), field="state", max_depth=4)
    _assert_structured(q4, "why-institution")
    assert q4["last_state_change"] is not None
    q5 = svc.trace_causes(world_id=world_id, kind="SUCCESSION",
                          node_id=cands[0].candidate_id, max_depth=4)
    _assert_structured(q5, "why-succession")
    assert q5.get("node", {}).get("id") == cands[0].candidate_id


def test_lt9_baseline_artifacts_and_summary(tmp_path):
    ref = _seed_reference("001")
    env = _fresh_m3(tmp_path, 14, M3_LONG_WORLD_IDS[0])
    rep = _m3_run(env, years=1000)
    assert rep.final_state_hash == ref["hashes"]["world_state_hash"]
    assert _hashes(env) == ref["hashes"]
    summary = _load_summary()
    if summary is not None:
        assert set(summary.get("seeds", {})) == set(M3_LONG_WORLD_IDS)
        assert summary["simulation_version"] == SIM_VERSION


def test_lt10_m3b_metric_naming_permanent(tmp_path):
    """M3b 口径永久验证：不得重新引入 entities_with_history 作为指标名。"""
    world_id = M3_LONG_WORLD_IDS[0]
    env = _fresh_m3(tmp_path, 15, world_id)
    rep = _m3_run(env, years=100)
    assert rep.final_blessed_tick == 100_000_000
    record = _record(env, rep, 0.0)
    assert "entity_history_index_rows" in record["counts"] \
        or "entity_history_index" in record["counts"]
    assert "distinct_entities_with_history" in record["counts"]
    for k in ("entities_with_history",):
        assert k not in record["counts"], k
        assert k not in record.get("tribulation", {}), k
    with env["factory"]() as s:
        assert len(s.execute(select(EntityHistoryIndex)).scalars().all()) > 0


def test_lt11_llm_network_zero():
    """M3 Simulation + History 零 LLM / 零网络（§30）。"""
    for rel in ("services/simulation", "services/history"):
        for py in (REPO / rel).rglob("*.py"):
            src = py.read_text(encoding="utf-8")
            for token in ("openai", "anthropic", "import requests",
                          "import httpx", "urllib.request", "socket"):
                assert token not in src, (py, token)


def test_lt12_adaptive_time_resolution_stage_boundaries(tmp_path):
    """Adaptive Time Resolution（§12）：30y/120y/500y 多灾劫窗口推进
    不得跳过 PRECURSOR/PREPARATION/IMPACT/RECOVERY/NEW_NORMAL 阶段边界。"""
    world_id = M3_LONG_WORLD_IDS[0]
    for years, idx in ((30, 30), (120, 31), (500, 32)):
        env = _fresh_m3(tmp_path, idx, world_id)
        rep = _m3_run(env, years=years)
        assert rep.splits > 0, (years, "无区间拆分")
        with env["factory"]() as s:
            eps = s.execute(select(TribulationEpisode).order_by(
                TribulationEpisode.entered_tick)).scalars().all()
            evs = {e.event_uid: e.event_type
                   for e in s.execute(select(WorldEvent)).scalars()}
            links = s.execute(select(CausalHistoryLink).where(
                CausalHistoryLink.world_id == world_id)).scalars().all()
        by_ep: dict[str, set] = {}
        for l in links:
            if l.relation_type == "PART_OF_EPISODE" and l.episode_id \
                    and l.source_kind == "EVENT":
                by_ep.setdefault(l.episode_id, set()).add(
                    evs.get(l.source_id))
        # 阶段边界校验：按 episode 实际到达的阶段（current_stage）要求
        # 对应边界事件存在——已到达的阶段绝不静默跳过；
        # 尚未到达的阶段（如 30y 末仍处于 PRECURSOR 的 episode）不要求。
        stage_order = ("PRECURSOR", "PREPARATION", "IMPACT", "RESPONSE",
                       "STABILIZATION", "RESIDUAL_CHANGE", "RECOVERY",
                       "RESOURCE_SUCCESSION", "NEW_NORMAL")
        required_by_stage = {
            "PRECURSOR": ("TRIBULATION_PRECURSOR_STARTED",),
            "PREPARATION": ("TRIBULATION_PRECURSOR_STARTED",
                            "TRIBULATION_PREPARATION_STARTED"),
            "IMPACT": ("TRIBULATION_PRECURSOR_STARTED",
                       "TRIBULATION_PREPARATION_STARTED",
                       "TRIBULATION_IMPACT_STARTED"),
            "RESPONSE": ("TRIBULATION_PRECURSOR_STARTED",
                         "TRIBULATION_PREPARATION_STARTED",
                         "TRIBULATION_IMPACT_STARTED"),
            "STABILIZATION": ("TRIBULATION_PRECURSOR_STARTED",
                              "TRIBULATION_PREPARATION_STARTED",
                              "TRIBULATION_IMPACT_STARTED"),
            "RESIDUAL_CHANGE": ("TRIBULATION_PRECURSOR_STARTED",
                                "TRIBULATION_PREPARATION_STARTED",
                                "TRIBULATION_IMPACT_STARTED"),
            "RECOVERY": ("TRIBULATION_PRECURSOR_STARTED",
                         "TRIBULATION_PREPARATION_STARTED",
                         "TRIBULATION_IMPACT_STARTED"),
            "RESOURCE_SUCCESSION": ("TRIBULATION_PRECURSOR_STARTED",
                                    "TRIBULATION_PREPARATION_STARTED",
                                    "TRIBULATION_IMPACT_STARTED"),
            "NEW_NORMAL": ("TRIBULATION_PRECURSOR_STARTED",
                           "TRIBULATION_PREPARATION_STARTED",
                           "TRIBULATION_IMPACT_STARTED"),
        }
        # 注：TRIBULATION_NEW_NORMAL_REACHED 仅随 status=COMPLETED 发出
        # （ACTIVE@NEW_NORMAL = NEW_NORMAL_PENDING，合法无该事件）；
        # completed 循环单独断言。
        for e in eps:
            evs_of_ep = by_ep.get(e.episode_id, set())
            required = required_by_stage.get(e.current_stage, ())
            for req in required:
                assert req in evs_of_ep, \
                    (years, e.episode_id, e.current_stage, req)
        completed = [e for e in eps if e.status == "COMPLETED"]
        for e in completed:
            assert "TRIBULATION_NEW_NORMAL_REACHED" \
                in by_ep.get(e.episode_id, set()), (years, e.episode_id)
        if years >= 30:
            assert eps, (years, "无 episode")
        assert _invariant_check(env)["clean"], (years, "invariants")


def test_lt13_summary_artifact():
    """从 5 seed 记录 + endurance + query 性能构建 summary（§23/§25）。

    普通 pytest 只读：committed summary 存在时逐字段比对（telemetry
    剥离），candidate 只写 M3C_CANDIDATE_DIR。
    """
    seeds = {}
    for seed_no in ("001", "002", "003", "004", "005"):
        rec = _seed_reference(seed_no)
        seeds[rec["world_id"]] = {
            "hashes": rec["hashes"],
            "wall_seconds": rec["wall_seconds"],
            "db_size_mb": rec["db_size_mb"],
            "counts": rec["counts"],
            "tribulation": rec["tribulation"],
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
        "tribulation_engine_version": "m3a-tribulation-1",
        "history_schema_version": "history-v1",
        "long_horizon": "M3_INTEGRATED_LONG_HORIZON (TEST_FIXTURE_ONLY)",
        "pipeline_order": ["TIME", "DEMOGRAPHY", "RESOURCE", "ECONOMY",
                           "ECOLOGY", "SOCIAL", "TRIBULATION",
                           "DOMAIN_ADAPTERS", "CAUSAL_HISTORY_INDEXING"],
        "engine_versions": {"DEMOGRAPHY": "m2a-1", "RESOURCE":
                            "m2b-resource-1", "ECONOMY": "m2b-economy-1",
                            "ECOLOGY": "m2c-ecology-1",
                            "SOCIAL": "m2d-social-1",
                            "TRIBULATION": "m3a-tribulation-1"},
        "world_state_hash_schema_version": 6,
        "event_stream_hash_schema_version": 1,
        "causal_history_hash_schema_version": "causal-history-hash-v1",
        "seeds": seeds,
        "db_growth": growth,
    }
    # endurance / query 性能附加（已冻结则必须可复现）
    end = None
    if ENDURANCE_PATH.exists():
        end = load_artifact(ENDURANCE_PATH)
    elif CANDIDATE_DIR is not None \
            and (CANDIDATE_DIR / "endurance_5000y_seed001.json").exists():
        end = json.loads((CANDIDATE_DIR / "endurance_5000y_seed001.json")
                         .read_text(encoding="utf-8"))
    if end:
        summary["endurance_5000y"] = {
            "world_id": end["world_id"],
            "wall_seconds": end["wall_seconds"],
            "db_size_mb": end["db_size_mb"],
            "hashes": end["hashes"],
            "links_per_100y": end["counts"]["causal_history_links"] / 50,
            "history_index_rows_per_100y":
                end["counts"]["entity_history_index"] / 50,
        }
    qp = None
    if CANDIDATE_DIR is not None \
            and (CANDIDATE_DIR / "query_performance_1000y.json").exists():
        qp = json.loads((CANDIDATE_DIR / "query_performance_1000y.json")
                        .read_text(encoding="utf-8"))
    if qp:
        summary["query_performance_1000y"] = qp
    _dump_candidate("summary.json", summary)
    if update_mode_enabled():
        # M6D.3 OPT-1：update mode 写入当前 artifact 即完成（形态同 M3a/M3b）。
        dump_artifact(summary, SUMMARY_PATH)
        return
    if SUMMARY_PATH.exists():
        assert_deterministic_equal(
            load_artifact(SUMMARY_PATH), summary,
            label="m3_integrated_1000y_v1/summary",
            golden_path=SUMMARY_PATH)

# -*- coding: utf-8 -*-
"""M6B-BV —— Bootstrap Viability Audit（owner §6–§9、§11）。

在**完全 synthetic** 环境中：M6 activation 激活世界（tick=0，anchor 显式）→
业务实体表全部为空 → 用**冻结生产管线**
（TIME → DEMOGRAPHY → RESOURCE → ECONOMY → ECOLOGY → SOCIAL → TRIBULATION → HISTORY）
逐年推进，回答：

```
DEMOGRAPHY / RESOURCE / ECONOMY / ECOLOGY / SOCIAL / TRIBULATION
    _EMPTY_BOOTSTRAP = CAN_PROGRESS / CANNOT_PROGRESS
EMPTY_WORLD_CAN_BOOTSTRAP = TRUE / FALSE
```

判定口径（与 owner §8 一致）：引擎不仅要"不报错"，还必须能**自行形成合法后续状态**；
永久空世界（domain 永远无实体）判 CANNOT_PROGRESS。
另附"结构性最小 bootstrap 需求"的**反证探针**：在 mini world 上逐一移除根行，
观察冻结引擎的 fail-closed 行为。
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.conftest import W
from tests.m6_activation_support import (
    M6_EPOCH0_US, build_synthetic_seed, new_synthetic_world,
    synthetic_request, world_counts)
from tests.test_m3b_history import _hist_coordinator

from XiaoguangBlessedLandRuntime.domain.constants import SimulationVersion
from XiaoguangBlessedLandRuntime.services.activation import (
    activate_formal_world)
from XiaoguangBlessedLandRuntime.services.scheduler.adapter import (
    run_blessed_year)
from XiaoguangBlessedLandRuntime.services.simulation.harness import YEAR_US
from XiaoguangBlessedLandRuntime.services.simulation.snapshot import (
    read_snapshot)
from XiaoguangBlessedLandRuntime.services.simulation.state_hash import (
    world_state_hash_v6)
from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease

ANCHOR = M6_EPOCH0_US + 12_345
YEARS = 4

BUSINESS_TABLES = (
    "settlements", "population_groups", "persons", "households", "lineages",
    "institutions", "industries", "resource_nodes", "resource_profiles",
    "resource_stocks", "production_recipes", "production_state",
    "economic_pressure_state", "ecology_zones", "ecology_state",
    "ecology_feedback_state", "settlement_social_state", "social_feedback_state",
    "ecological_regions", "tribulation_profiles", "tribulation_schedules",
    "tribulation_episodes", "tribulation_decisions", "timeline_entries",
    "world_state_changes", "history_state_changes", "causal_history_links",
    "history_episode_index", "entity_history_index", "history_index_state",
)

DOMAIN_EVENT_PREFIXES = {
    "DEMOGRAPHY": ("POPULATION_",),
    "RESOURCE": ("RESOURCE_EXTRACTED", "RESOURCE_DEPLETED",
                 "RESOURCE_SUCCESSION_CANDIDATE_CREATED"),
    "ECONOMY": ("PRODUCTION_COMPLETED", "CONSUMPTION_FULFILLED",
                "RESOURCE_SHORTAGE", "RESOURCE_TRANSFERRED"),
    "ECOLOGY": ("ECOLOGY_THRESHOLD_CROSSED",),
    "SOCIAL": ("HOUSEHOLD_", "LINEAGE_", "INSTITUTION_",
               "SOCIAL_STRESS_THRESHOLD_CROSSED"),
    "TRIBULATION": ("TRIBULATION_", "AUTONOMOUS_RESPONSE_SELECTED",
                    "MITIGATION_COMMITTED", "OWNER_DECISION_COMMITTED"),
}


def _empty_activated_world(work) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    env = new_synthetic_world(work)
    seed_dir = build_synthetic_seed(work)
    out = activate_formal_world(env["factory"], request=synthetic_request(
        seed_dir, world_id=W, activation_anchor_us=ANCHOR))
    assert out.outcome == "COMMITTED"
    return env


def _advance(env, years: int = YEARS) -> None:
    coordinator = _hist_coordinator()
    lease_session = env["factory"]()
    lease = WriterLease(lease_session, W, 300)
    lease.acquire()
    try:
        for year_index in range(years):
            run_blessed_year(env["factory"], world_id=W,
                             year_index=year_index, coordinator=coordinator,
                             lease=lease, epoch0_us=ANCHOR,
                             simulation_version=SimulationVersion.CURRENT)
    finally:
        lease.release()
        lease_session.close()


def _dispose(env) -> None:
    eng = env.get("engine")
    if eng is not None:
        eng.dispose()


def _counts(factory) -> dict:
    out: dict[str, int] = {}
    with factory() as s:
        for t in BUSINESS_TABLES:
            try:
                out[t] = int(s.execute(
                    text(f'SELECT COUNT(*) FROM "{t}"')).scalar())
            except Exception:  # noqa: BLE001
                out[t] = -1
    return out


def _event_types(factory) -> dict[str, int]:
    with factory() as s:
        rows = s.execute(text(
            "SELECT event_type, COUNT(*) FROM world_events "
            "GROUP BY event_type")).all()
    return {str(r[0]): int(r[1]) for r in rows}


def _domain_events(factory, domain: str) -> int:
    prefixes = DOMAIN_EVENT_PREFIXES[domain]
    total = 0
    for etype, n in _event_types(factory).items():
        if any(etype.startswith(p) for p in prefixes):
            total += n
    return total


def _digest(factory) -> str:
    with factory() as s:
        return world_state_hash_v6(
            snapshot=read_snapshot(s, W),
            simulation_version=SimulationVersion.CURRENT,
            pipeline_version="m6b-empty-bootstrap-audit-v1",
            engine_versions={})


# ------------------------------------------------------------------ BV-01
def test_m6bbv01_empty_activated_world_runs_but_forms_nothing(tmp_path):
    """§6/§7：空世界能被冻结管线合法推进，但所有域都**无法**形成状态。"""
    env = _empty_activated_world(tmp_path / "w")
    counts_before = _counts(env["factory"])
    assert all(v == 0 for v in counts_before.values()), counts_before

    _advance(env, YEARS)                       # 不得抛异常

    counts_after = _counts(env["factory"])
    # history_index_state 是 HISTORY 域的**索引簿记行**（非世界实体）：允许存在，
    # 但必须仍是"空索引"（indexed_through_tick = 0，无任何历史被索引）。
    non_zero = {k: v for k, v in counts_after.items()
                if v != 0 and k != "history_index_state"}
    assert non_zero == {}, non_zero             # 业务/历史实体域永久为空
    with env["factory"]() as s:
        idx = s.execute(text(
            "SELECT indexed_through_tick, COUNT(*) FROM history_index_state "
            "GROUP BY indexed_through_tick")).all()
    # HISTORY 索引水位随世界时钟推进，但**没有**任何历史实体/因果链接被建立
    assert [list(map(int, r)) for r in idx] == [[YEARS * 1_000_000, 1]]

    events = _event_types(env["factory"])
    assert events.get("WORLD_SEED_ACTIVATED") == 1
    assert events.get("TIME_ADVANCE") == YEARS   # 只有 M1 基础设施事件
    for domain in DOMAIN_EVENT_PREFIXES:
        assert _domain_events(env["factory"], domain) == 0, domain

    with env["factory"]() as s:
        row = s.execute(text(
            "SELECT current_blessed_tick, last_committed_real_us "
            "FROM world_runtime LIMIT 1")).one()
    assert row[0] == YEARS * 1_000_000           # 时钟正常推进
    assert row[1] == ANCHOR + YEARS * YEAR_US    # 年锚对齐（M6B 接线）
    _dispose(env)


# ------------------------------------------------------------------ BV-02
@pytest.mark.parametrize("domain,minimal_evidence", [
    ("DEMOGRAPHY", "population_groups"),
    ("RESOURCE", "resource_nodes"),
    ("ECONOMY", "resource_stocks"),
    ("ECOLOGY", "ecology_zones"),
    ("SOCIAL", "settlement_social_state"),
    ("TRIBULATION", "tribulation_episodes"),
])
def test_m6bbv02_per_domain_empty_bootstrap_verdict(tmp_path, domain,
                                                    minimal_evidence):
    """§7：逐域判定 —— 无任何域事件、无任何域实体 → CANNOT_PROGRESS。"""
    env = _empty_activated_world(tmp_path / domain)
    _advance(env, 2)
    counts = _counts(env["factory"])
    assert _domain_events(env["factory"], domain) == 0
    assert counts[minimal_evidence] == 0
    _dispose(env)


# ------------------------------------------------------------------ BV-03
def test_m6bbv03_empty_world_progress_is_deterministic(tmp_path):
    """§8：deterministic —— 两次独立运行的初态/终态哈希完全一致。"""
    digests = []
    for tag in ("a", "b"):
        env = _empty_activated_world(tmp_path / tag)
        _advance(env, YEARS)
        digests.append(_digest(env["factory"]))
        _dispose(env)
    assert digests[0] == digests[1]


# ------------------------------------------------------------------ BV-04
def test_m6bbv04_empty_world_has_no_invalid_refs_or_violations(tmp_path):
    """§8：no invalid refs / no divide-by-zero / 无 M2/M3 不变式违反。

    （divide-by-zero 等算术违规会以异常形式出现 → 本测试的前置推进即为证据；
    这里再显式校验引用完整性与历史链一致性。）
    """
    env = _empty_activated_world(tmp_path / "w")
    _advance(env, YEARS)
    with env["factory"]() as s:
        orphan_events = int(s.execute(text(
            "SELECT COUNT(*) FROM world_events e WHERE e.parent_event_ref IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM world_events p "
            "                WHERE p.event_uid = e.parent_event_ref)")).scalar())
        dangling_changes = int(s.execute(text(
            "SELECT COUNT(*) FROM world_state_changes c WHERE c.event_ref IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM world_events e "
            "                WHERE e.event_uid = c.event_ref)")).scalar())
        self_loops = int(s.execute(text(
            "SELECT COUNT(*) FROM world_events WHERE parent_event_ref = event_uid"
        )).scalar())
        links = int(s.execute(text(
            "SELECT COUNT(*) FROM causal_history_links")).scalar())
        # FK 完整性：SQLite PRAGMA foreign_key_check 必须无输出
        fk_rows = s.execute(text("PRAGMA foreign_key_check")).all()
    assert orphan_events == 0
    assert dangling_changes == 0
    assert self_loops == 0
    assert links == 0
    assert fk_rows == []
    _dispose(env)


# ------------------------------------------------------------------ BV-05
def _m3_env(tmp_path, i: int):
    from tests.test_m3_integrated_long import _fresh_m3, M3_LONG_WORLD_IDS
    return _fresh_m3(tmp_path, i, M3_LONG_WORLD_IDS[i % 5])


def _run_one_year_m3(env) -> None:
    """在 mini world（含全量根行）上跑一年冻结管线。"""
    from tests.conftest import EPOCH0_US
    coordinator = _hist_coordinator()
    lease_session = env["factory"]()
    lease = WriterLease(lease_session, env["world_id"], 300)
    lease.acquire()
    try:
        run_blessed_year(env["factory"], world_id=env["world_id"],
                         year_index=0, coordinator=coordinator, lease=lease,
                         epoch0_us=EPOCH0_US,
                         simulation_version=SimulationVersion.CURRENT)
    finally:
        lease.release()
        lease_session.close()


def test_m6bbv05a_populated_mini_world_baseline_progresses(tmp_path):
    """对照：有根行的完整 mini world 能形成域事件（证明探针本身有效）。"""
    env = _m3_env(tmp_path, 1)
    _run_one_year_m3(env)
    events = _event_types(env["factory"])
    domain_total = sum(_domain_events(env["factory"], d)
                       for d in DOMAIN_PREFIXES_FOR_MINI)
    assert domain_total > 0, events
    _dispose(env)


DOMAIN_PREFIXES_FOR_MINI = ("DEMOGRAPHY", "RESOURCE", "ECONOMY", "ECOLOGY",
                            "SOCIAL", "TRIBULATION")


@pytest.mark.parametrize("table,probe", [
    ("settlement_social_state", "social_state_missing"),
    ("resource_stocks", "stock_missing"),
    ("ecology_state", "ecology_state_missing"),
    ("population_groups", "population_root_missing"),
    ("tribulation_schedules", "tribulation_schedule_missing"),
])
def test_m6bbv05_minimum_required_roots_probe(tmp_path, table, probe):
    """§9：结构性最小 bootstrap 需求 —— 逐一移除根行后的冻结引擎行为。"""
    env = _m3_env(tmp_path, 10 + len(probe))
    with env["factory"]() as s:
        s.execute(text(f'DELETE FROM "{table}"'))
        s.commit()
    error: Exception | None = None
    try:
        _run_one_year_m3(env)
    except Exception as exc:  # noqa: BLE001
        error = exc

    if probe in ("social_state_missing", "stock_missing", "ecology_state_missing"):
        # 冻结引擎对"缺根行"是 fail-closed（绝不静默推进）
        assert error is not None, f"{table} 缺失时引擎未 fail-closed"
        assert type(error).__name__ in (
            "IntegrityError", "EconomyStateInconsistent", "EcologyZoneMissing",
            "WorldRuntimeError"), type(error).__name__
    else:
        # 人口根 / 灾劫排期缺失：不报错，但该域**永不产出**
        assert error is None, f"{table} 缺失时不应报错: {error!r}"
        assert _domain_events(
            env["factory"],
            "DEMOGRAPHY" if probe == "population_root_missing" else "TRIBULATION"
        ) == 0
    _dispose(env)

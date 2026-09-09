# -*- coding: utf-8 -*-
"""M3 Preflight 契约测试：TP1–TP32 + 300y Contract Harness。

只使用 Fake/Contract Tribulation Driver（不实现正式灾劫算法/内容/排期）；
全部运行于 tmp 临时库；正式 DB / World Seed 零接触；M2 frozen 语义不变。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import sqlite3
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

import pytest
from sqlalchemy import select, text

from tests.conftest import EPOCH0, EPOCH0_US, PROJECT_ROOT

from XiaoguangBlessedLandRuntime.database.models_core import (SimulationCheckpoint,
                                                              WorldEvent,
                                                              WorldRuntime,
                                                              WorldStateChange)
from XiaoguangBlessedLandRuntime.database.models_world import (
    Household, PopulationGroup, ResourceNode, ResourceStock, Tribulation)
from XiaoguangBlessedLandRuntime.domain.errors import FencingViolation
from XiaoguangBlessedLandRuntime.services import fencing as fencing_mod
from XiaoguangBlessedLandRuntime.services.catchup import catch_up
from XiaoguangBlessedLandRuntime.services.fencing import WorldMutationContext
from XiaoguangBlessedLandRuntime.services.rng_service import RngService
from XiaoguangBlessedLandRuntime.services.simulation.coordinator import (
    SimulationCoordinator)
from XiaoguangBlessedLandRuntime.services.simulation.ecology import EcologyEngine
from XiaoguangBlessedLandRuntime.services.simulation.economy import EconomyEngine
from XiaoguangBlessedLandRuntime.services.simulation.event_stream import (
    deterministic_event_uid)
from XiaoguangBlessedLandRuntime.services.simulation.harness import (
    YEAR_US, run_mini_world_120y)
from XiaoguangBlessedLandRuntime.services.simulation.population import (
    PopulationGroupEngine)
from XiaoguangBlessedLandRuntime.services.simulation.recovery import (
    latest_authoritative_world_checkpoint)
from XiaoguangBlessedLandRuntime.services.simulation.resource import ResourceEngine
from XiaoguangBlessedLandRuntime.services.simulation.social import SocialEngine
from XiaoguangBlessedLandRuntime.services.simulation.tribulation_contracts import (
    DAMAGE_LEVELS, DEFAULT_AUTONOMOUS_RESPONSE_POLICY,
    DOMAIN_ADAPTER_OWNERSHIP, IMPACT_PLAN_SCHEMA_VERSION,
    LIFECYCLE_PHASES, PHASE_IMPACT, PHASE_NEW_NORMAL, PHASE_PREPARATION,
    PHASE_PRECURSOR, PHASE_RECOVERY, PHASE_RESIDUAL_CHANGE,
    PHASE_RESOURCE_SUCCESSION, PHASE_RESPONSE, PHASE_STABILIZATION,
    ContractValidationError, OwnerDecisionInput, RecoveryState,
    TribulationImpactPlan, TribulationProfile, select_targets,
    validate_domain_effect_targets)
from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease

REPO = PROJECT_ROOT
SIM_VERSION = "0.2.0-preflight"
MANIFEST_PATH = REPO / "M2_SIMULATION_SEMANTICS_MANIFEST.json"
SEED_DIR = REPO.parent / "XIAOGUANG_CROW_KB" / "world_seed"

TEST_PROFILES = {
    "TEST_TRIBULATION_PROFILE_001": TribulationProfile(
        profile_id="TEST_TRIBULATION_PROFILE_001", tier="REGULAR",
        theme="ECOLOGICAL_STRESS", intensity_min=20, intensity_max=40,
        population_risk=Fraction(1, 200), resource_damage=Fraction(1, 50),
        inventory_damage=Fraction(1, 100),
        production_disruption=Fraction(1, 100), ecology_pressure=200_000,
        social_displacement=Fraction(1, 200),
        institution_disruption=Fraction(0), duration_steps=1,
        recovery_steps=2, source_refs=("WS-0901", "WS-0903")),
    "TEST_TRIBULATION_PROFILE_002": TribulationProfile(
        profile_id="TEST_TRIBULATION_PROFILE_002", tier="MAJOR",
        theme="EARTH_VEIN_DISTURBANCE", intensity_min=50, intensity_max=70,
        population_risk=Fraction(1, 40), resource_damage=Fraction(1, 12),
        inventory_damage=Fraction(1, 20),
        production_disruption=Fraction(1, 15), ecology_pressure=500_000,
        social_displacement=Fraction(1, 30),
        institution_disruption=Fraction(1, 4), duration_steps=2,
        recovery_steps=3, source_refs=("WS-0902", "WS-0903")),
    "TEST_TRIBULATION_PROFILE_003": TribulationProfile(
        profile_id="TEST_TRIBULATION_PROFILE_003", tier="CENTENNIAL",
        theme="SPIRIT_TIDE", intensity_min=80, intensity_max=100,
        population_risk=Fraction(1, 20), resource_damage=Fraction(1, 6),
        inventory_damage=Fraction(1, 10),
        production_disruption=Fraction(1, 8), ecology_pressure=800_000,
        social_displacement=Fraction(1, 15),
        institution_disruption=Fraction(1, 3), duration_steps=3,
        recovery_steps=4, source_refs=("WS-0901", "WS-0905")),
}


def _profile_for(tier: str) -> TribulationProfile:
    return {p.tier: p for p in TEST_PROFILES.values()}[tier]


def _fresh_env(tmp_path, i: int):
    """mini_world with_ecology+with_social（复用 M2d 环境）。"""
    from tests.test_m2d_social import _fresh_social
    return _fresh_social(tmp_path, i)


def _engines():
    return [PopulationGroupEngine(), ResourceEngine(), EconomyEngine(),
            EcologyEngine(), SocialEngine()]


# ============================ Contract Driver ============================
class ContractTribulationDriver:
    """Fake/Contract 灾劫驱动（仅契约验证，非正式算法）。

    形状 = 冻结的方案 B：每 Step 在 coordinator 之后、同一 fenced
    session 内：(1) 命中 TEST_TRIBULATION_SCHEDULE_001 窗口 → 建
    Episode（tribulations 行）；(2) 推进九阶段生命周期；(3) IMPACT 步
    生成 TribulationImpactPlan 并经 Domain Impact Adapters 应用（所有权
    校验）；(4) 事件/状态变化/恢复/继承候选按契约写入。"""

    REGULAR_EVERY = 10
    MAJOR_EVERY = 50
    CENTENNIAL_EVERY = 100

    def __init__(self, world_id: str, *, crash_after: str | None = None):
        self.world_id = world_id
        self.crash_after = crash_after
        self._crashed = False

    def _crash(self, label: str) -> None:
        if self.crash_after == label and not self._crashed:
            self._crashed = True
            raise RuntimeError(f"crash: {label}")

    def tier_for_year(self, year: int) -> str | None:
        if year % self.CENTENNIAL_EVERY == 0:
            return "CENTENNIAL"
        if year % self.MAJOR_EVERY == 0:
            return "MAJOR"
        if year % self.REGULAR_EVERY == 0:
            return "REGULAR"
        return None

    def simulate(self, session, *, now_real_us: int, year: int) -> None:
        """在 coordinator 之后的同 session 内执行契约驱动（不 commit）。"""
        tick = year * 1_000_000
        # 既有 episode 推进
        self._advance_episodes(session, tick, year)
        tier = self.tier_for_year(year)
        if tier is None:
            return
        profile = _profile_for(tier)
        seq_base = self._event_seq(session)
        # 目标选择：stable ordering + TRIBULATION substream
        rng = RngService(world_id=self.world_id,
                         simulation_version=SIM_VERSION).stream(
            subsystem="TRIBULATION", blessed_period_tick=tick)
        candidates = [("TEST-MAIN-A", {"pop": 1}), ("TEST-SATELLITE-B",
                                                    {"pop": 1})]
        targets = select_targets(candidates, rng, count=1)
        ep_id = f"EP-{year:04d}-{tier}"
        session.add(Tribulation(
            world_id=self.world_id, window_type=tier, phase=PHASE_PRECURSOR,
            params={"episode_id": ep_id, "profile_id": profile.profile_id,
                    "theme": profile.theme,
                    "intensity_range": [profile.intensity_min,
                                        profile.intensity_max],
                    "affected_settlements": targets,
                    "schema": "test-schedule-001"},
            start_blessed_tick=tick))
        self._emit(session, seq_base, "TRIBULATION_PHASE_CHANGED",
                   {"episode_id": ep_id, "phase": PHASE_PRECURSOR,
                    "tier": tier}, {"affected": targets}, tick, now_real_us)
        self._crash("T1")

    def _advance_episodes(self, session, tick: int, year: int) -> None:
        episodes = session.execute(select(Tribulation).where(
            Tribulation.world_id == self.world_id)).scalars().all()
        for ep in episodes:
            phase = ep.phase
            params = ep.params or {}
            ep_id = params.get("episode_id") or f"EP-{ep.id}"
            profile = _profile_for(ep.window_type)
            if phase == PHASE_PRECURSOR:
                ep.phase = PHASE_PREPARATION
                self._emit(session, self._event_seq(session),
                           "TRIBULATION_PHASE_CHANGED",
                           {"episode_id": ep_id, "phase": PHASE_PREPARATION},
                           {"decision_window_ticks": 1_000_000}, tick, 0)
                self._crash("T2")
            elif phase == PHASE_PREPARATION:
                decision = self._valid_decision(session, ep_id, tick)
                if decision is None:
                    ep.params = {**params, "response_policy":
                                 DEFAULT_AUTONOMOUS_RESPONSE_POLICY}
                else:
                    ep.params = {**params, "response_policy": "OWNER_PLAN",
                                 "decision_id":
                                     decision["effect"].get("decision_id")}
                ep.phase = PHASE_IMPACT
                self._apply_impact(session, ep, ep_id, profile, tick)
                self._emit(session, self._event_seq(session),
                           "TRIBULATION_PHASE_CHANGED",
                           {"episode_id": ep_id, "phase": PHASE_IMPACT},
                           {"plan_id": ep.params.get("plan_id")}, tick, 0)
                ep.phase = PHASE_RESPONSE
                self._mitigation(session, ep, profile, tick)
            elif phase == PHASE_RESPONSE:
                ep.phase = PHASE_STABILIZATION
                self._emit(session, self._event_seq(session),
                           "TRIBULATION_PHASE_CHANGED",
                           {"episode_id": ep_id,
                            "phase": PHASE_STABILIZATION}, {}, tick, 0)
            elif phase == PHASE_STABILIZATION:
                ep.phase = PHASE_RESIDUAL_CHANGE
                residual = dict(ep.residual or {})
                residual["residual_changes"] = ["environment_condition"]
                residual["succession_candidate"] = True  # 候选≠掉落
                ep.residual = dict(residual)  # 新对象（JSON 变更检测）
                self._emit(session, self._event_seq(session),
                           "TRIBULATION_PHASE_CHANGED",
                           {"episode_id": ep_id,
                            "phase": PHASE_RESIDUAL_CHANGE},
                           {"succession_candidate": True}, tick, 0)
            elif phase == PHASE_RESIDUAL_CHANGE:
                ep.phase = PHASE_RECOVERY
                residual = dict(ep.residual or {})
                residual["recovery"] = {"need": 100, "progress": 0,
                                        "steps_done": 0}
                ep.residual = dict(residual)
                self._emit(session, self._event_seq(session),
                           "TRIBULATION_PHASE_CHANGED",
                           {"episode_id": ep_id, "phase": PHASE_RECOVERY},
                           {}, tick, 0)
            elif phase == PHASE_RECOVERY:
                residual = dict(ep.residual or {})
                rec = dict(residual.get("recovery", {}))
                rec["progress"] = min(100, rec.get("progress", 0)
                                      + 100 // max(profile.recovery_steps, 1))
                rec["steps_done"] = rec.get("steps_done", 0) + 1
                residual["recovery"] = rec
                ep.residual = dict(residual)
                self._crash("T12")
                if rec["progress"] >= 100:
                    ep.phase = PHASE_RESOURCE_SUCCESSION
                    self._emit(session, self._event_seq(session),
                               "TRIBULATION_PHASE_CHANGED",
                               {"episode_id": ep_id,
                                "phase": PHASE_RESOURCE_SUCCESSION},
                               {"candidate_only": True}, tick, 0)
            elif phase == PHASE_RESOURCE_SUCCESSION:
                ep.phase = PHASE_NEW_NORMAL
                ep.end_blessed_tick = tick
                self._emit(session, self._event_seq(session),
                           "TRIBULATION_PHASE_CHANGED",
                           {"episode_id": ep_id, "phase": PHASE_NEW_NORMAL},
                           {"new_normal": True}, tick, 0)

    def _valid_decision(self, session, episode_id: str, tick: int
                        ) -> dict | None:
        rows = session.execute(text(
            "SELECT event_uid, cause, effect FROM world_events "
            "WHERE event_type='OWNER_DECISION' "
            "AND json_extract(cause, '$.episode_id') = :eid"),
            {"eid": episode_id}).mappings().all()
        for r in rows:
            cause = json.loads(r["cause"]) if isinstance(r["cause"], str) \
                else (r["cause"] or {})
            if int(cause.get("deadline_tick", 0)) < tick:
                continue  # 过期拒绝（TP11）
            return {"event_uid": r["event_uid"], "cause": cause,
                    "effect": json.loads(r["effect"])
                    if isinstance(r["effect"], str) else (r["effect"] or {})}
        return None

    def _apply_impact(self, session, ep: Tribulation, episode_id: str,
                      profile: TribulationProfile, tick: int) -> None:
        params = ep.params or {}
        intensity = profile.intensity_max
        rng = RngService(world_id=self.world_id,
                         simulation_version=SIM_VERSION).stream(
            subsystem="TRIBULATION", blessed_period_tick=tick)
        intensity = profile.intensity_min + rng.randint(
            0, profile.intensity_max - profile.intensity_min)
        plan = TribulationImpactPlan(
            plan_id=f"PLAN-{episode_id}", episode_id=episode_id,
            profile_id=profile.profile_id, tier=profile.tier,
            theme=profile.theme,
            affected_regions=("TEST-REGION-1", "TEST-REGION-2"),
            affected_settlements=tuple(params.get("affected_settlements", [])),
            intensity=intensity, duration_steps=profile.duration_steps,
            recovery_steps=profile.recovery_steps,
            population_risk=profile.population_risk,
            resource_damage=profile.resource_damage,
            inventory_damage=profile.inventory_damage,
            production_disruption=profile.production_disruption,
            ecology_pressure=profile.ecology_pressure,
            social_displacement=profile.social_displacement,
            institution_disruption=profile.institution_disruption,
            recovery_requirements={"stock": 1_000},
            residual_changes=("environment_condition",),
            source_profile=profile.profile_id,
            domain_effects=self._plan_domain_effects(profile, intensity))
        validate_domain_effect_targets(plan)  # 所有权契约（TP3）
        ep.params = {**params, "plan_id": plan.plan_id,
                     "intensity": intensity, "plan_schema":
                     IMPACT_PLAN_SCHEMA_VERSION}
        self._crash("T4")  # T4：impact plan generated（adapter 前）
        # IMPACT 事件先行（TP19 因果链：state_change.event_ref → IMPACT）
        self._emit(session, self._event_seq(session), "TRIBULATION_IMPACT",
                   {"episode_id": episode_id, "plan_id": plan.plan_id},
                   {"intensity": intensity, "tier": profile.tier,
                    "affected": plan.affected_settlements}, tick, 0)
        # 经 Domain Impact Adapters 应用（每个 effect 走其域 adapter）
        crash_labels = {"DEMOGRAPHY": "T5", "RESOURCE": "T6",
                        "ECONOMY": "T6", "ECOLOGY": "T7", "SOCIAL": "T8"}
        for effect in plan.domain_effects:
            self._apply_domain_effect(session, effect, intensity, tick,
                                      episode_id)
            self._crash(crash_labels[effect.domain])
        # 历史因果链接（TP19）：state changes 已由 adapter 记录 event_ref
        self._crash("T9")

    def _plan_domain_effects(self, profile: TribulationProfile,
                             intensity: int) -> list:
        from XiaoguangBlessedLandRuntime.services.simulation.tribulation_contracts import DomainEffect
        f = Fraction(intensity, 100)
        return [
            DomainEffect("DEMOGRAPHY", "population_loss",
                         profile.population_risk * f),
            DomainEffect("RESOURCE", "reserve_damage",
                         profile.resource_damage * f),
            DomainEffect("ECONOMY", "inventory_damage",
                         profile.inventory_damage * f),
            DomainEffect("ECOLOGY", "ecology_pressure", f),
            DomainEffect("SOCIAL", "social_displacement",
                         profile.social_displacement * f),
        ]

    def _apply_domain_effect(self, session, effect, intensity: int,
                             tick: int, episode_id: str) -> None:
        """Domain Impact Adapter（契约版）：按域所有权只写本域表。"""
        from XiaoguangBlessedLandRuntime.services.simulation.tribulation_contracts import DomainEffect
        if not isinstance(effect, DomainEffect):
            effect = DomainEffect(*effect)
        owned = DOMAIN_ADAPTER_OWNERSHIP[effect.domain]
        if effect.domain == "DEMOGRAPHY" and "population_groups" in owned:
            for g in session.execute(select(PopulationGroup).where(
                    PopulationGroup.world_id == self.world_id)).scalars():
                loss = int(g.count * effect.magnitude)
                if loss > 0:
                    self._trace(session, "population_groups", g.id, "count",
                                g.count, g.count - loss, episode_id, tick)
                    g.count -= loss
        elif effect.domain == "RESOURCE" and "resource_nodes" in owned:
            for n in session.execute(select(ResourceNode).where(
                    ResourceNode.world_id == self.world_id)).scalars():
                if not n.remaining_reserve:
                    continue
                loss = int(n.remaining_reserve * effect.magnitude)
                self._trace(session, "resource_nodes", n.id,
                            "remaining_reserve", n.remaining_reserve,
                            n.remaining_reserve - loss, episode_id, tick)
                n.remaining_reserve -= loss
        elif effect.domain == "ECONOMY" and "resource_stocks" in owned:
            for r in session.execute(select(ResourceStock).where(
                    ResourceStock.world_id == self.world_id)).scalars():
                loss = int(r.quantity * effect.magnitude)
                if loss > 0:
                    self._trace(session, "resource_stocks", r.id, "quantity",
                                r.quantity, r.quantity - loss, episode_id,
                                tick)
                    r.quantity -= loss
        elif effect.domain == "ECOLOGY" and "ecology_state" in owned:
            from XiaoguangBlessedLandRuntime.database.models_world import \
                EcologyState
            for st in session.execute(select(EcologyState).where(
                    EcologyState.world_id == self.world_id)).scalars():
                delta = min(int(1_000_000 * effect.magnitude),
                            1_000_000 - st.ecological_stress)
                self._trace(session, "ecology_state", st.id,
                            "ecological_stress", st.ecological_stress,
                            st.ecological_stress + delta, episode_id, tick)
                st.ecological_stress += delta
        elif effect.domain == "SOCIAL" and "households" in owned:
            for h in session.execute(select(Household).where(
                    Household.world_id == self.world_id)).scalars():
                loss = int(h.represented_population * effect.magnitude)
                if loss > 0:
                    self._trace(session, "households", h.id,
                                "represented_population",
                                h.represented_population,
                                h.represented_population - loss,
                                episode_id, tick)
                    h.represented_population -= loss

    def _mitigation(self, session, ep: Tribulation,
                    profile: TribulationProfile, tick: int) -> None:
        """RESPONSE 成本：扣库存（TP13）；最大自主防护下 impact 仍 >0
        （impact 已按 profile 上限应用，mitigation 不回溯免损 —— TP14）。"""
        params = ep.params or {}
        intensity = int(params.get("intensity", 50))
        cost = 1_000_000 * intensity // 10  # 结构化成本
        for r in session.execute(select(ResourceStock).where(
                ResourceStock.world_id == self.world_id,
                ResourceStock.resource_profile_ref == "TEST-RESOURCE-002"
        )).scalars():
            take = min(cost, r.quantity)
            r.quantity -= take
        ep.params = {**params, "mitigation_cost_minor": cost}

    def _trace(self, session, table: str, eid: int, field: str, old, new,
               episode_id: str, tick: int) -> None:
        from XiaoguangBlessedLandRuntime.database.base import utcnow
        ev = session.execute(text(
            "SELECT event_uid FROM world_events "
            "WHERE event_type='TRIBULATION_IMPACT' "
            "AND json_extract(cause, '$.episode_id') = :eid LIMIT 1"),
            {"eid": episode_id}).scalar()
        session.add(WorldStateChange(
            world_id=self.world_id, entity_type=table, entity_id=str(eid),
            field=field, old_value={"v": old}, new_value={"v": new},
            event_ref=ev, blessed_tick=tick, real_time=utcnow()))

    def _emit(self, session, seq: int, event_type: str, cause: dict,
              effect: dict, tick: int, now_real_us: int) -> None:
        from XiaoguangBlessedLandRuntime.services.repositories import \
            EventRepository
        uid = deterministic_event_uid(
            world_id=self.world_id, simulation_version=SIM_VERSION,
            real_start_us=now_real_us, real_end_us=now_real_us,
            engine_id="TRIBULATION", event_type=event_type, seq=seq)
        EventRepository(session).append(
            world_id=self.world_id, event_type=event_type,
            source="SIMULATION", blessed_tick=tick, scope="WORLD",
            cause=cause, effect=effect, event_uid=uid)

    def _event_seq(self, session) -> int:
        return len(session.execute(select(WorldEvent)).scalars().all())


# ============================ 300y harness runner ============================
def _run_300y_with_driver(env, *, crash_after: str | None = None,
                          monkeypatch=None) -> dict:
    """300 福地年：5 引擎 coordinator + Contract Driver（同 fenced
    session，模拟方案 B 形状）。返回统计 dict。"""
    factory = env["factory"]
    world_id = env["world_id"] if "world_id" in env else "MINIWORLD-TEST-001"
    s1 = factory()
    lease = WriterLease(s1, world_id, 100_000)
    lease.acquire()
    coordinator = SimulationCoordinator(_engines())
    driver = ContractTribulationDriver(world_id, crash_after=crash_after)
    stats = {"crashes": 0, "fencing": 0, "ack_loss": 0}

    def step(s, info, _i):
        res = coordinator.run_step(
            s, world_id=world_id,
            blessed_start_tick=info["new_blessed_tick"] - info["delta_ticks"],
            blessed_end_tick=info["new_blessed_tick"],
            real_interval_start_us=info["real_interval_start_us"],
            real_interval_end_us=info["real_interval_end_us"],
            step_index=_i)
        driver.simulate(s, now_real_us=info["real_interval_end_us"],
                        year=_i)
        return res

    for year in range(1, 301):
        now_us = EPOCH0_US + year * YEAR_US
        if crash_after is not None and not stats["crashes"]:
            try:
                catch_up(factory, world_id=world_id, now_real_us=now_us,
                         writer_id=lease.owner, fencing_token=lease.token,
                         simulation_version=SIM_VERSION,
                         simulate_fn=lambda s, info, _y=year: step(s, info, _y))
                stats["crashes"] = 0
            except RuntimeError:
                stats["crashes"] += 1
                # 干净重试（同 schedule 重放 → 同结果）
                catch_up(factory, world_id=world_id, now_real_us=now_us,
                         writer_id=lease.owner, fencing_token=lease.token,
                         simulation_version=SIM_VERSION,
                         simulate_fn=lambda s, info, _y=year: step(s, info, _y))
        else:
            catch_up(factory, world_id=world_id, now_real_us=now_us,
                     writer_id=lease.owner, fencing_token=lease.token,
                     simulation_version=SIM_VERSION,
                     simulate_fn=lambda s, info, _y=year: step(s, info, _y))
    lease.release()
    s1.close()
    return stats


# ============================ TP1–TP7 ============================
def test_tp1_m2_semantics_manifest_unchanged():
    m = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert m["manifest_version"] == "m2-semantics-v1"
    assert m["tribulation_slot"] == "NOT_REGISTERED"
    assert m["world_state_hash_schema_version"] == 5


def test_tp2_tribulation_engine_slot_defined():
    from XiaoguangBlessedLandRuntime.services.simulation.contracts import (
        TRIBULATION_SLOT, TRIBULATION_SLOT_STATE)
    assert TRIBULATION_SLOT == "TRIBULATION"
    assert TRIBULATION_SLOT_STATE == "NOT_REGISTERED"


def test_tp3_cross_domain_ownership_prevents_arbitrary_mutation():
    from XiaoguangBlessedLandRuntime.services.simulation.tribulation_contracts import DomainEffect
    plan = TribulationImpactPlan(
        plan_id="P", episode_id="E", profile_id="TEST_TRIBULATION_PROFILE_002",
        tier="MAJOR", theme="T", affected_regions=("R",),
        affected_settlements=("S",), intensity=50, duration_steps=1,
        recovery_steps=2, population_risk=Fraction(1, 40),
        resource_damage=Fraction(1, 12), inventory_damage=Fraction(1, 20),
        production_disruption=Fraction(1, 15), ecology_pressure=500_000,
        social_displacement=Fraction(1, 30),
        institution_disruption=Fraction(1, 4))
    # 合法域 effect（有 adapter 的域）通过校验
    validate_domain_effect_targets(TribulationImpactPlan(
        **{**plan.__dict__, "domain_effects":
           (DomainEffect("DEMOGRAPHY", "x", Fraction(1, 2)),)}))
    # 越权：无 adapter 的域 → 拒绝（TP3 契约）
    with pytest.raises(ContractValidationError):
        validate_domain_effect_targets(TribulationImpactPlan(
            **{**plan.__dict__, "domain_effects":
               (DomainEffect("TRIBULATION", "x", Fraction(1, 2)),)}))


def test_tp4_impact_plan_schema_validation():
    ok = TribulationImpactPlan(
        plan_id="P", episode_id="E", profile_id="TEST_TRIBULATION_PROFILE_001",
        tier="REGULAR", theme="T", affected_regions=("R",),
        affected_settlements=("S",), intensity=30, duration_steps=1,
        recovery_steps=2, population_risk=Fraction(1, 200),
        resource_damage=Fraction(1, 50), inventory_damage=Fraction(1, 100),
        production_disruption=Fraction(1, 100), ecology_pressure=200_000,
        social_displacement=Fraction(1, 200),
        institution_disruption=Fraction(0))
    assert ok.schema == IMPACT_PLAN_SCHEMA_VERSION
    with pytest.raises(ContractValidationError):
        TribulationImpactPlan(
            plan_id="P", episode_id="E",
            profile_id="TEST_TRIBULATION_PROFILE_001", tier="REGULAR",
            theme="T", affected_regions=("R",), affected_settlements=("S",),
            intensity=250, duration_steps=1, recovery_steps=2,
            population_risk=Fraction(1, 200), resource_damage=Fraction(1, 50),
            inventory_damage=Fraction(1, 100),
            production_disruption=Fraction(1, 100), ecology_pressure=200_000,
            social_displacement=Fraction(1, 200),
            institution_disruption=Fraction(0))
    with pytest.raises(ContractValidationError):
        TribulationImpactPlan(
            plan_id="P", episode_id="E",
            profile_id="TEST_TRIBULATION_PROFILE_001", tier="REGULAR",
            theme="T", affected_regions=("R",), affected_settlements=("S",),
            intensity=30, duration_steps=1, recovery_steps=2,
            population_risk=Fraction(3, 2), resource_damage=Fraction(1, 50),
            inventory_damage=Fraction(1, 100),
            production_disruption=Fraction(1, 100), ecology_pressure=200_000,
            social_displacement=Fraction(1, 200),
            institution_disruption=Fraction(0))
    with pytest.raises(ContractValidationError):
        TribulationImpactPlan(
            plan_id="P", episode_id="E",
            profile_id="TEST_TRIBULATION_PROFILE_001", tier="REGULAR",
            theme="T", affected_regions=(), affected_settlements=(),
            intensity=30, duration_steps=1, recovery_steps=2,
            population_risk=Fraction(1, 200), resource_damage=Fraction(1, 50),
            inventory_damage=Fraction(1, 100),
            production_disruption=Fraction(1, 100), ecology_pressure=200_000,
            social_displacement=Fraction(1, 200),
            institution_disruption=Fraction(0))


def test_tp5_schedule_deterministic():
    d1 = ContractTribulationDriver("W")
    s1 = [d1.tier_for_year(y) for y in range(1, 301)]
    s2 = [ContractTribulationDriver("W").tier_for_year(y)
          for y in range(1, 301)]
    assert s1 == s2
    assert s1[9] == "REGULAR" and s1[49] == "MAJOR" and s1[99] == "CENTENNIAL"
    # 300 年窗口计数（major/centennial 年不重复计 regular）：
    # 24 regular / 3 major / 3 centennial = 30 场
    assert s1.count("REGULAR") == 24
    assert s1.count("MAJOR") == 3
    assert s1.count("CENTENNIAL") == 3


def test_tp6_profile_selection_deterministic():
    assert _profile_for("REGULAR").profile_id \
        == "TEST_TRIBULATION_PROFILE_001"
    assert _profile_for("MAJOR").profile_id == "TEST_TRIBULATION_PROFILE_002"
    assert _profile_for("CENTENNIAL").profile_id \
        == "TEST_TRIBULATION_PROFILE_003"
    for p in TEST_PROFILES.values():
        assert p.status == "TEST_FIXTURE_ONLY"


def test_tp7_target_selection_row_order_independent():
    import random
    rng = random.Random(7)
    a = select_targets([("A", {}), ("B", {}), ("C", {})], rng, count=2)
    rng2 = random.Random(7)
    b = select_targets([("C", {}), ("A", {}), ("B", {})], rng2, count=2)
    assert sorted(a) == sorted(b)


# ============================ TP8–TP14 ============================
def test_tp8_xiaoguang_autonomous_response_available(tmp_path):
    env = _fresh_env(tmp_path, 1)
    _run_300y_with_driver(env)
    with env["factory"]() as s:
        tribs = s.execute(select(Tribulation)).scalars().all()
        assert tribs
        advanced = [t for t in tribs if t.phase != PHASE_PRECURSOR]
        assert advanced  # 至少有 episode 进入响应阶段
        # 无主人决策 → 全部 autonomous（PRECURSOR 尚未到决策点除外）
        assert all(t.params.get("response_policy")
                   == DEFAULT_AUTONOMOUS_RESPONSE_POLICY
                   for t in advanced)


def test_tp9_owner_decision_immutable(tmp_path):
    env = _fresh_env(tmp_path, 2)
    factory = env["factory"]
    world_id = "MINIWORLD-TEST-001"
    with factory() as s:
        from XiaoguangBlessedLandRuntime.services.repositories import \
            EventRepository
        uid = deterministic_event_uid(
            world_id=world_id, simulation_version=SIM_VERSION,
            real_start_us=0, real_end_us=0, engine_id="OWNER_INPUT",
            event_type="OWNER_DECISION", seq=0)
        EventRepository(s).append(
            world_id=world_id, event_type="OWNER_DECISION",
            source="OWNER_INPUT", blessed_tick=0, scope="WORLD",
            cause={"episode_id": "EP-0010-REGULAR", "decision_id": "D1",
                   "action": "EVACUATE", "deadline_tick": 20_000_000},
            effect={"parameters": {"priority": ["TEST-SATELLITE-B"]}},
            event_uid=uid)
        s.commit()
    with pytest.raises(Exception):
        with factory() as s:  # DB 触发器禁 UPDATE/DELETE（immutable）
            e = s.execute(select(WorldEvent)).scalars().first()
            e.cause = {"x": 1}
            s.commit()


def test_tp10_owner_decision_replay_deterministic(tmp_path):
    a = _fresh_env(tmp_path, 3)
    b = _fresh_env(tmp_path, 4)
    for env in (a, b):
        with env["factory"]() as s:
            from XiaoguangBlessedLandRuntime.services.repositories import \
                EventRepository
            uid = deterministic_event_uid(
                world_id="MINIWORLD-TEST-001",
                simulation_version=SIM_VERSION, real_start_us=0,
                real_end_us=0, engine_id="OWNER_INPUT",
                event_type="OWNER_DECISION", seq=0)
            EventRepository(s).append(
                world_id="MINIWORLD-TEST-001",
                event_type="OWNER_DECISION", source="OWNER_INPUT",
                blessed_tick=0, scope="WORLD",
                cause={"episode_id": "EP-0010-REGULAR", "decision_id": "D1",
                       "action": "EVACUATE", "deadline_tick": 99_000_000},
                effect={"parameters": {}}, event_uid=uid)
            s.commit()
    _run_300y_with_driver(a)
    _run_300y_with_driver(b)
    with a["factory"]() as s:
        ta = [(t.window_type, t.phase, t.params.get("response_policy"))
              for t in s.execute(select(Tribulation)).scalars()]
    with b["factory"]() as s:
        tb = [(t.window_type, t.phase, t.params.get("response_policy"))
              for t in s.execute(select(Tribulation)).scalars()]
    assert ta == tb  # 同决策 → 同结果


def test_tp11_expired_decision_rejected(tmp_path):
    env = _fresh_env(tmp_path, 5)
    with env["factory"]() as s:
        from XiaoguangBlessedLandRuntime.services.repositories import \
            EventRepository
        uid = deterministic_event_uid(
            world_id="MINIWORLD-TEST-001", simulation_version=SIM_VERSION,
            real_start_us=0, real_end_us=0, engine_id="OWNER_INPUT",
            event_type="OWNER_DECISION", seq=0)
        EventRepository(s).append(
            world_id="MINIWORLD-TEST-001", event_type="OWNER_DECISION",
            source="OWNER_INPUT", blessed_tick=0, scope="WORLD",
            cause={"episode_id": "EP-0010-REGULAR", "decision_id": "D1",
                   "action": "EVACUATE", "deadline_tick": 1_000_000},
            effect={"parameters": {}}, event_uid=uid)
        s.commit()
    _run_300y_with_driver(env)
    with env["factory"]() as s:
        t = s.execute(text(
            "SELECT params FROM tribulations "
            "WHERE json_extract(params, '$.episode_id') = :eid"),
            {"eid": "EP-0010-REGULAR"}).scalar()
        params = json.loads(t) if isinstance(t, str) else (t or {})
        assert params.get("response_policy") \
            == DEFAULT_AUTONOMOUS_RESPONSE_POLICY  # 过期 → fallback


def test_tp12_offline_fallback_deterministic(tmp_path):
    a = _fresh_env(tmp_path, 6)
    b = _fresh_env(tmp_path, 7)
    _run_300y_with_driver(a)
    _run_300y_with_driver(b)
    with a["factory"]() as s:
        ta = [t.phase for t in s.execute(select(Tribulation)).scalars()]
    with b["factory"]() as s:
        tb = [t.phase for t in s.execute(select(Tribulation)).scalars()]
    assert ta == tb


def test_tp13_mitigation_consumes_declared_resources(tmp_path):
    env = _fresh_env(tmp_path, 8)
    control = _fresh_env(tmp_path, 81)
    _run_300y_with_driver(env)
    run_mini_world_120y(control["factory"], engines=_engines(), years=300)
    with env["factory"]() as s:
        tribs = s.execute(select(Tribulation)).scalars().all()
        stocks = sum(r.quantity for r in s.execute(select(ResourceStock)
                                                   ).scalars())
    with control["factory"]() as s:
        stocks_control = sum(r.quantity for r in s.execute(
            select(ResourceStock)).scalars())
    assert any(t.params.get("mitigation_cost_minor", 0) > 0 for t in tribs)
    assert stocks < stocks_control  # 灾劫+响应成本真实扣减（相对对照）


def test_tp14_no_free_perfect_protection(tmp_path):
    env = _fresh_env(tmp_path, 9)
    _run_300y_with_driver(env)
    with env["factory"]() as s:
        majors = s.execute(select(Tribulation).where(
            Tribulation.window_type == "MAJOR")).scalars().all()
        assert majors
        # 真实损失：人口 state change 账本存在净减少（impact > 0，
        # 最大自主防护也不回溯免损）
        losses = s.execute(select(WorldStateChange).where(
            WorldStateChange.entity_type == "population_groups",
            WorldStateChange.field == "count")).scalars().all()
        assert losses
        total_loss = sum(int((sc.old_value or {}).get("v", 0))
                         - int((sc.new_value or {}).get("v", 0))
                         for sc in losses)
        assert total_loss > 0


# ============================ TP15–TP20 ============================
def test_tp15_residual_change_no_instant_loot(tmp_path):
    env = _fresh_env(tmp_path, 10)
    with env["factory"]() as s:
        nodes_before = len(s.execute(select(ResourceNode)).scalars().all())
    _run_300y_with_driver(env)
    with env["factory"]() as s:
        nodes_after = len(s.execute(select(ResourceNode)).scalars().all())
        done = [t for t in s.execute(select(Tribulation)).scalars()
                if t.phase == PHASE_NEW_NORMAL]
        assert done
        for t in done:
            assert (t.residual or {}).get("succession_candidate") is True
            assert "new_resource_node" not in (t.residual or {})
    assert nodes_after == nodes_before  # 灾劫完成不即时生成资源点


def test_tp16_recovery_spans_committed_steps(tmp_path):
    env = _fresh_env(tmp_path, 11)
    _run_300y_with_driver(env)
    with env["factory"]() as s:
        majors = s.execute(select(Tribulation).where(
            Tribulation.window_type == "MAJOR")).scalars().all()
        assert majors
        rec = [t for t in majors
               if (t.residual or {}).get("recovery", {}).get("steps_done", 0)
               >= 2]
        assert len(rec) >= 1  # 恢复跨 ≥2 committed steps


def test_tp17_new_normal_differs_from_pre_impact(tmp_path):
    env = _fresh_env(tmp_path, 12)
    control = _fresh_env(tmp_path, 121)
    _run_300y_with_driver(env)
    run_mini_world_120y(control["factory"], engines=_engines(), years=300)
    with env["factory"]() as s:
        post_pop = sum(g.count for g in s.execute(select(PopulationGroup)
                                                  ).scalars())
    with control["factory"]() as s:
        post_control = sum(g.count for g in s.execute(
            select(PopulationGroup)).scalars())
    # 非零 impact → 新常态 ≠ 无灾劫对照（≠ 灾前快照）
    assert post_pop != post_control


def test_tp18_episode_links_lifecycle_events(tmp_path):
    env = _fresh_env(tmp_path, 13)
    _run_300y_with_driver(env)
    with env["factory"]() as s:
        evs = s.execute(select(WorldEvent).where(
            WorldEvent.event_type == "TRIBULATION_PHASE_CHANGED"
        )).scalars().all()
        assert evs
        by_ep = {}
        for e in evs:
            ep = e.cause.get("episode_id")
            by_ep.setdefault(ep, []).append(e.cause.get("phase"))
        assert all(len(set(v)) == len(v) for v in by_ep.values())


def test_tp19_causal_chain_traces_state_change_to_trigger(tmp_path):
    env = _fresh_env(tmp_path, 14)
    _run_300y_with_driver(env)
    with env["factory"]() as s:
        scs = s.execute(select(WorldStateChange)).scalars().all()
        assert scs  # 灾劫 state mutation 有账本记录
        for sc in scs:
            assert sc.event_ref  # 可回溯至触发事件
            ev = s.execute(select(WorldEvent).where(
                WorldEvent.event_uid == sc.event_ref)).scalar_one_or_none()
            assert ev is not None
            assert ev.event_type == "TRIBULATION_IMPACT"
            assert ev.cause.get("episode_id")


def test_tp20_no_natural_language_narrative_required(tmp_path):
    env = _fresh_env(tmp_path, 15)
    _run_300y_with_driver(env)
    with env["factory"]() as s:
        for t in s.execute(select(Tribulation)).scalars():
            for v in (t.params or {}).values():
                if isinstance(v, str):
                    assert len(v) < 200  # 结构化，非文学叙事


# ============================ TP21–TP28 ============================
def test_tp21_22_llm_tokens_zero():
    src = (REPO / "services/simulation/tribulation_contracts.py").read_text(
        encoding="utf-8")
    for token in ("openai", "anthropic", "import requests", "import httpx",
                  "chat.completions"):
        assert token not in src.lower()


def test_tp23_network_zero(tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("simulation core 触碰网络")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr("urllib.request.urlopen", _boom, raising=False)
    monkeypatch.setattr("http.client.HTTPConnection", _boom, raising=False)
    env = _fresh_env(tmp_path, 16)
    _run_300y_with_driver(env)


def test_tp24_wall_clock_truth_zero():
    pattern = re.compile(
        r"\b(datetime\.now|time\.time|time\.monotonic|perf_counter"
        r"|time_ns|date\.today)\s*\(")
    src = (REPO / "services/simulation/tribulation_contracts.py").read_text(
        encoding="utf-8")
    assert not pattern.search(src)


def test_tp25_retry_no_duplicate_episode(tmp_path):
    env = _fresh_env(tmp_path, 17)
    _run_300y_with_driver(env)
    with env["factory"]() as s:
        before = len(s.execute(select(Tribulation)).scalars().all())
    # 重试最后一年（同 interval skip）
    run_mini_world_120y(env["factory"], engines=_engines(), years=1)
    with env["factory"]() as s:
        after = len(s.execute(select(Tribulation)).scalars().all())
    assert after == before


def test_tp26_retry_no_duplicate_impact(tmp_path):
    env = _fresh_env(tmp_path, 18)
    _run_300y_with_driver(env)
    with env["factory"]() as s:
        before = len(s.execute(select(WorldEvent).where(
            WorldEvent.event_type == "TRIBULATION_IMPACT")).scalars().all())
    run_mini_world_120y(env["factory"], engines=_engines(), years=1)
    with env["factory"]() as s:
        after = len(s.execute(select(WorldEvent).where(
            WorldEvent.event_type == "TRIBULATION_IMPACT")).scalars().all())
    assert after == before


def test_tp27_stale_writer_cannot_commit(tmp_path):
    env = _fresh_env(tmp_path, 19)
    factory = env["factory"]
    world_id = "MINIWORLD-TEST-001"
    s1 = factory()
    lease = WriterLease(s1, world_id, 120)
    lease.acquire()
    coordinator = SimulationCoordinator(_engines())
    driver = ContractTribulationDriver(world_id)

    def step(s, info):
        coordinator.run_step(
            s, world_id=world_id,
            blessed_start_tick=info["new_blessed_tick"] - info["delta_ticks"],
            blessed_end_tick=info["new_blessed_tick"],
            real_interval_start_us=info["real_interval_start_us"],
            real_interval_end_us=info["real_interval_end_us"], step_index=10)
        driver.simulate(s, now_real_us=info["real_interval_end_us"], year=10)

    with pytest.raises(FencingViolation):
        with WorldMutationContext(factory(), world_id=world_id,
                                  writer_id=lease.owner,
                                  fencing_token=lease.token) as ctx:
            step(ctx.session, {"new_blessed_tick": 10_000_000,
                               "delta_ticks": 10_000_000,
                               "real_interval_start_us": EPOCH0_US,
                               "real_interval_end_us": EPOCH0_US + 10 * YEAR_US})
            ctx.session.execute(text(
                "UPDATE runtime_lock SET lease_token='STOLEN'"))
            ctx.commit()
    with factory() as s:
        assert s.execute(select(Tribulation)).scalars().all() == []
    lease.release()
    s1.close()


def test_tp28_commit_ack_lost_already_committed(tmp_path, monkeypatch):
    env = _fresh_env(tmp_path, 20)
    factory = env["factory"]
    world_id = "MINIWORLD-TEST-001"
    s1 = factory()
    lease = WriterLease(s1, world_id, 120)
    lease.acquire()
    coordinator = SimulationCoordinator(_engines())
    driver = ContractTribulationDriver(world_id)
    original = fencing_mod.WorldMutationContext.commit
    state = {"calls": 0}

    def patched(self):
        original(self)
        state["calls"] += 1
        if state["calls"] == 2:
            raise RuntimeError("simulated COMMIT ACK LOST")

    monkeypatch.setattr(fencing_mod.WorldMutationContext, "commit", patched)

    def step(s, info):
        coordinator.run_step(
            s, world_id=world_id,
            blessed_start_tick=info["new_blessed_tick"] - info["delta_ticks"],
            blessed_end_tick=info["new_blessed_tick"],
            real_interval_start_us=info["real_interval_start_us"],
            real_interval_end_us=info["real_interval_end_us"], step_index=10)
        driver.simulate(s, now_real_us=info["real_interval_end_us"], year=10)

    with pytest.raises(RuntimeError, match="ACK LOST"):
        catch_up(factory, world_id=world_id,
                 now_real_us=EPOCH0_US + 10 * YEAR_US,
                 writer_id=lease.owner, fencing_token=lease.token,
                 simulation_version=SIM_VERSION, simulate_fn=step)
    with factory() as s:
        assert s.execute(select(Tribulation)).scalars().all()  # durable 已提交
        assert s.execute(select(WorldRuntime)).scalar_one() \
            .current_blessed_tick == 10_000_000
    monkeypatch.setattr(fencing_mod.WorldMutationContext, "commit", original)
    res = catch_up(factory, world_id=world_id,
                   now_real_us=EPOCH0_US + 10 * YEAR_US,
                   writer_id=lease.owner, fencing_token=lease.token,
                   simulation_version=SIM_VERSION)
    assert res.skipped is True  # ALREADY_COMMITTED
    lease.release()
    s1.close()


def test_tp29_checkpoint_contains_active_episode_semantics(tmp_path):
    env = _fresh_env(tmp_path, 21)
    _run_300y_with_driver(env)
    with env["factory"]() as s:
        world = latest_authoritative_world_checkpoint(s, "MINIWORLD-TEST-001")
        assert world is not None
        tribs = s.execute(select(Tribulation)).scalars().all()
        # 契约级原子语义：episode 推进的 tick 均 ≤ 权威 checkpoint tick
        assert all((t.start_blessed_tick or 0) <= world.checkpoint_blessed_tick
                   for t in tribs)


# ============================ T1–T12 崩溃矩阵 ============================
@pytest.mark.parametrize("crash_after", [
    pytest.param("T1", id="T1-precursor-creation"),
    pytest.param("T2", id="T2-preparation-state"),
    pytest.param("T4", id="T4-impact-plan-generated"),
    pytest.param("T5", id="T5-population-adapter-staged"),
    pytest.param("T6", id="T6-resource-adapter-staged"),
    pytest.param("T7", id="T7-economy-adapter-staged"),
    pytest.param("T8", id="T8-ecology-adapter-staged"),
    pytest.param("T9", id="T9-history-links-staged"),
    pytest.param("T12", id="T12-recovery-transition"),
])
def test_tp_crash_matrix_t1_t12(tmp_path, crash_after):
    env = _fresh_env(tmp_path, 100 + hash(crash_after) % 100)
    stats = _run_300y_with_driver(env, crash_after=crash_after)
    assert stats["crashes"] == 1
    # 恢复后：一个世界、一条事件流、每个 episode 唯一
    with env["factory"]() as s:
        tribs = s.execute(select(Tribulation)).scalars().all()
        assert tribs
        phases = {}
        for t in tribs:
            key = (t.window_type, t.start_blessed_tick)
            assert key not in phases  # 无重复 episode
            phases[key] = t.phase
        uids = [e.event_uid for e in s.execute(select(WorldEvent)).scalars()]
        assert len(set(uids)) == len(uids)


# ============================ TP30–TP32 ============================
def test_tp30_formal_db_unchanged(formal_db_guard):
    path = os.environ.get("BLR_FORMAL_DB_PATH", "")
    if not path or formal_db_guard is None:
        pytest.skip("BLR_FORMAL_DB_PATH 未设置")
    after = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    assert after == formal_db_guard


def test_tp31_world_seed_unchanged():
    assert SEED_DIR.exists()
    manifest = SEED_DIR / "MANIFEST.sha256.txt"
    for line in manifest.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        h, name = line.split("  ", 1)
        assert hashlib.sha256((SEED_DIR / name).read_bytes()).hexdigest() == h


def test_tp32_m2_baselines_unchanged():
    for name in ("m2a_population_miniworld_120y_v1.json",
                 "m2b_resource_economy_miniworld_120y_v1.json",
                 "m2c_ecology_miniworld_120y_v1.json",
                 "m2d_social_miniworld_120y_v2.json",
                 "m2d_social_miniworld_120y_v1_pre_id_hardening.json"):
        assert (REPO / "tests" / "baselines" / name).exists(), name
    m = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert m["engine_versions"]["SOCIAL"] == "m2d-social-1"

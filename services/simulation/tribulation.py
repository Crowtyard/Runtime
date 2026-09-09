# -*- coding: utf-8 -*-
"""TRIBULATION_ENGINE（M3a）—— World Metabolism 真实实现。

依据 World Bible WS-0901~0910 与 M3 Preflight 冻结契约（方案 B）：
- Tribulation = World Metabolism：压力/破坏/淘汰/重组/恢复/适应/新生；
  不是 Boss Fight / Loot Drop / 随机惩罚箱 / 世界重置。
- 九阶段生命周期：PRECURSOR → PREPARATION → IMPACT → RESPONSE →
  STABILIZATION → RESIDUAL_CHANGE → RECOVERY → RESOURCE_SUCCESSION →
  NEW_NORMAL（WS-0902；每阶段 entered/transition tick + episode_id +
  semantic_version）。
- 引擎只写 tribulation-owned 状态；跨域影响经
  Coordinator 调用的 Domain-owned Impact Adapters（方案 B）。
- 确定性 Episode ID（≥128-bit，tribulation-episode-id-v1）；
  RNG 六子流（SCHEDULE/PROFILE/TARGET/IMPACT/RECOVERY/SUCCESSION）；
  正式 schedule/profile = 0 行（UNCONFIGURED），测试仅
  TEST_TRIBULATION_SCHEDULE_001 + TEST_TRIBULATION_PROFILE_001..003。
- OwnerDecision：显式提交、immutable、supersede、过期/错误 episode
  拒绝、idempotent；离线 fallback = DEFAULT_AUTONOMOUS_RESPONSE_POLICY。
- TRIBULATION_RANK_INFERENCE = 0：不映射转数/修为。
- 零 LLM/网络/wall-clock/commit。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from ...domain.errors import WorldRuntimeError
from ..identity import deterministic_hex_id
from .contracts import (DomainEventDraft, EngineResult, SimulationContext,
                        StateChange)

ENGINE_ID = "TRIBULATION"
ENGINE_VERSION = "m3a-tribulation-1"
TRIBULATION_EPISODE_ID_SCHEMA_VERSION = "tribulation-episode-id-v1"
IMPACT_PLAN_SCHEMA_VERSION = "impact-plan-v2"
M3A_SIMULATION_VERSION = "0.3.0-m3a"
TICKS_PER_BLESSED_YEAR = 1_000_000

TEST_SCHEDULE_ID = "TEST_TRIBULATION_SCHEDULE_001"
DEFAULT_AUTONOMOUS_RESPONSE_POLICY = "DEFAULT_AUTONOMOUS_RESPONSE_POLICY"

STAGE_PRECURSOR = "PRECURSOR"
STAGE_PREPARATION = "PREPARATION"
STAGE_IMPACT = "IMPACT"
STAGE_RESPONSE = "RESPONSE"
STAGE_STABILIZATION = "STABILIZATION"
STAGE_RESIDUAL_CHANGE = "RESIDUAL_CHANGE"
STAGE_RECOVERY = "RECOVERY"
STAGE_RESOURCE_SUCCESSION = "RESOURCE_SUCCESSION"
STAGE_NEW_NORMAL = "NEW_NORMAL"
LIFECYCLE = (STAGE_PRECURSOR, STAGE_PREPARATION, STAGE_IMPACT,
             STAGE_RESPONSE, STAGE_STABILIZATION, STAGE_RESIDUAL_CHANGE,
             STAGE_RECOVERY, STAGE_RESOURCE_SUCCESSION, STAGE_NEW_NORMAL)
_LIFECYCLE_INDEX = {s: i for i, s in enumerate(LIFECYCLE)}

TIER_REGULAR, TIER_MAJOR, TIER_CENTENNIAL = "REGULAR", "MAJOR", "CENTENNIAL"
_TIER_ORDER = {TIER_REGULAR: 1, TIER_MAJOR: 2, TIER_CENTENNIAL: 3}

EV_SCHEDULED = "TRIBULATION_SCHEDULED"
EV_PRECURSOR = "TRIBULATION_PRECURSOR_STARTED"
EV_PREPARATION = "TRIBULATION_PREPARATION_STARTED"
EV_OWNER_DECISION = "OWNER_DECISION_COMMITTED"
EV_AUTONOMOUS = "AUTONOMOUS_RESPONSE_SELECTED"
EV_MITIGATION = "MITIGATION_COMMITTED"
EV_IMPACT_STARTED = "TRIBULATION_IMPACT_STARTED"
EV_IMPACT_APPLIED = "TRIBULATION_IMPACT_APPLIED"
EV_STABILIZED = "TRIBULATION_STABILIZED"
EV_RESIDUAL = "TRIBULATION_RESIDUAL_CHANGE_CREATED"
EV_RECOVERY_PROGRESS = "TRIBULATION_RECOVERY_PROGRESS"
EV_SUCCESSION_CANDIDATE = "RESOURCE_SUCCESSION_CANDIDATE_CREATED"
EV_NEW_NORMAL = "TRIBULATION_NEW_NORMAL_REACHED"
EV_COMPLETED = "TRIBULATION_EPISODE_COMPLETED"

DECISION_ACTIONS = ("STRATEGY", "PRIORITIZE", "EVACUATE", "REBUILD")
DECISION_ACTIVE, DECISION_SUPERSEDED = "ACTIVE", "SUPERSEDED"


class TribulationContractError(WorldRuntimeError):
    code = "TRIBULATION_CONTRACT_VIOLATION"


class OwnerDecisionRejected(WorldRuntimeError):
    code = "OWNER_DECISION_REJECTED"


# ---------------------------------------------------------------- TEST 数据
@dataclass(frozen=True)
class TribulationProfileSpec:
    profile_id: str
    tier: str
    theme: str
    intensity_min: int
    intensity_max: int
    precursor_steps: int = 1
    preparation_steps: int = 1
    impact_steps: int = 1
    population_risk: Fraction = Fraction(0)
    resource_damage: Fraction = Fraction(0)
    inventory_damage: Fraction = Fraction(0)
    production_disruption: Fraction = Fraction(0)
    social_displacement: Fraction = Fraction(0)
    institution_disruption: Fraction = Fraction(0)
    ecology_pressure: int = 0
    recovery_steps: int = 2
    targeting_rules: dict = field(default_factory=dict)
    succession_rules: dict = field(default_factory=dict)
    source_refs: dict = field(default_factory=dict)

    def risk_of(self, kind: str) -> Fraction:
        return {"population": self.population_risk,
                "resource": self.resource_damage,
                "inventory": self.inventory_damage,
                "production": self.production_disruption,
                "social": self.social_displacement,
                "institution": self.institution_disruption}[kind]


# TEST_FIXTURE_ONLY：合成 profile（正式 profile=0，绝不自动创建）
TEST_PROFILES: dict[str, TribulationProfileSpec] = {
    "TEST_TRIBULATION_PROFILE_001": TribulationProfileSpec(
        profile_id="TEST_TRIBULATION_PROFILE_001", tier=TIER_REGULAR,
        theme="ECOLOGICAL_STRESS", intensity_min=20, intensity_max=40,
        population_risk=Fraction(1, 200), resource_damage=Fraction(1, 50),
        inventory_damage=Fraction(1, 100),
        production_disruption=Fraction(1, 100),
        social_displacement=Fraction(1, 200),
        institution_disruption=Fraction(0), ecology_pressure=200_000,
        recovery_steps=2,
        targeting_rules={"mode": "POPULATION_DENSITY"},
        succession_rules={"allow_candidate": True, "maturation_steps": 5},
        source_refs={"bible": ["WS-0901", "WS-0903"]}),
    "TEST_TRIBULATION_PROFILE_002": TribulationProfileSpec(
        profile_id="TEST_TRIBULATION_PROFILE_002", tier=TIER_MAJOR,
        theme="EARTH_VEIN_DISTURBANCE", intensity_min=50, intensity_max=70,
        population_risk=Fraction(1, 40), resource_damage=Fraction(1, 12),
        inventory_damage=Fraction(1, 20),
        production_disruption=Fraction(1, 15),
        social_displacement=Fraction(1, 30),
        institution_disruption=Fraction(1, 4), ecology_pressure=500_000,
        recovery_steps=3,
        targeting_rules={"mode": "POPULATION_DENSITY"},
        succession_rules={"allow_candidate": True, "maturation_steps": 8},
        source_refs={"bible": ["WS-0902", "WS-0903"]}),
    "TEST_TRIBULATION_PROFILE_003": TribulationProfileSpec(
        profile_id="TEST_TRIBULATION_PROFILE_003", tier=TIER_CENTENNIAL,
        theme="SPIRIT_TIDE", intensity_min=80, intensity_max=100,
        population_risk=Fraction(1, 20), resource_damage=Fraction(1, 6),
        inventory_damage=Fraction(1, 10),
        production_disruption=Fraction(1, 8),
        social_displacement=Fraction(1, 15),
        institution_disruption=Fraction(1, 3), ecology_pressure=800_000,
        recovery_steps=4,
        targeting_rules={"mode": "POPULATION_DENSITY"},
        succession_rules={"allow_candidate": True, "maturation_steps": 12},
        source_refs={"bible": ["WS-0901", "WS-0905"]}),
}

TEST_SCHEDULE: list[tuple[str, int]] = [
    (TIER_REGULAR, 10), (TIER_MAJOR, 50), (TIER_CENTENNIAL, 100)]


def episode_identity(*, world_id: str, simulation_version: str,
                     schedule_id: str, tier: str, scheduled_tick: int) -> str:
    return deterministic_hex_id(
        [world_id, simulation_version, schedule_id, tier,
         str(scheduled_tick)],
        bits=128, schema=TRIBULATION_EPISODE_ID_SCHEMA_VERSION)


def _tier_at_tick(schedules: list[dict], tick: int) -> dict | None:
    """窗口判定：高层级替代低层级（不叠加成同年多场）。"""
    hits = [s for s in schedules if s.get("enabled", True)
            and int(s["period_years"]) > 0
            and tick % (int(s["period_years"]) * TICKS_PER_BLESSED_YEAR) == 0]
    if not hits:
        return None
    return max(hits, key=lambda s: _TIER_ORDER[s["tier"]])


def next_tribulation_boundary(session, *, world_id: str, from_tick: int,
                              to_tick: int) -> int | None:
    """Adaptive Time Resolution：返回 (from, to] 内最早的必须拆分边界。

    边界 = 排期窗口命中 tick 或活跃 episode 的阶段转移 tick。
    整数 blessed tick；禁止浮点年份。
    """
    from sqlalchemy import select, text
    from ...database.models_world import (TribulationEpisode,
                                          TribulationSchedule)
    schedules = [{"tier": s.tier, "period_years": s.period_years,
                  "enabled": s.enabled} for s in session.execute(
        select(TribulationSchedule).where(
            TribulationSchedule.world_id == world_id)).scalars()]
    if not schedules:
        return None
    candidates: list[int] = []
    for s in schedules:
        if not s["enabled"] or s["period_years"] <= 0:
            continue
        period = s["period_years"] * TICKS_PER_BLESSED_YEAR
        first = ((from_tick // period) + 1) * period
        if first <= to_tick:
            candidates.append(first)
    for ep in session.execute(select(TribulationEpisode).where(
            TribulationEpisode.world_id == world_id,
            TribulationEpisode.status == "ACTIVE")).scalars():
        tt = ep.transition_tick
        if tt is not None and from_tick < tt <= to_tick:
            candidates.append(int(tt))
    return min(candidates) if candidates else None


def submit_owner_decision(session, *, world_id: str, episode_id: str,
                          action: str, effective_before_tick: int,
                          target_priorities: dict | None = None,
                          resource_allocation: dict | None = None,
                          supersedes_decision_id: str | None = None,
                          decision_id: str | None = None,
                          source: str = "ADMIN_API",
                          submitted_tick: int | None = None,
                          ) -> dict:
    """机器级 OwnerDecisionInput 提交（显式 API；不接聊天/UI/Companion）。

    - action 白名单；episode 必须存在；过期（effective_before_tick <= 当前）
      拒绝；错误 episode 拒绝；supersede 旧决策；重试 idempotent。
    - 提交即写 immutable decision 行 + OWNER_DECISION_COMMITTED 事件
      （确定性 uid）。本服务在调用方事务内运行（不 commit）。
    """
    from sqlalchemy import select, text
    from ...database.models_world import (TribulationDecision,
                                          TribulationEpisode)
    if action not in DECISION_ACTIONS:
        raise OwnerDecisionRejected(f"decision action 非法: {action}",
                                    detail=action)
    ep = session.execute(select(TribulationEpisode).where(
        TribulationEpisode.world_id == world_id,
        TribulationEpisode.episode_id == episode_id)).scalar_one_or_none()
    if ep is None:
        raise OwnerDecisionRejected("decision 作用于不存在的 episode",
                                    detail=episode_id)
    now_tick = submitted_tick if submitted_tick is not None \
        else int(ep.updated_blessed_tick or 0)
    if effective_before_tick <= now_tick:
        raise OwnerDecisionRejected("decision 已过期（deadline 之前未提交）",
                                    detail={"episode": episode_id,
                                            "effective_before":
                                            effective_before_tick})
    if supersedes_decision_id is not None:
        prev = session.execute(select(TribulationDecision).where(
            TribulationDecision.world_id == world_id,
            TribulationDecision.decision_id == supersedes_decision_id
        )).scalar_one_or_none()
        if prev is None:
            raise OwnerDecisionRejected("supersede 目标决策不存在",
                                        detail=supersedes_decision_id)
        prev.status = DECISION_SUPERSEDED
    if decision_id is None:
        seq = len(session.execute(select(TribulationDecision).where(
            TribulationDecision.world_id == world_id)).scalars().all()) + 1
        decision_id = deterministic_hex_id(
            [world_id, episode_id, action, str(effective_before_tick),
             str(seq)], bits=128, schema="owner-decision-v1")
    existing = session.execute(select(TribulationDecision).where(
        TribulationDecision.world_id == world_id,
        TribulationDecision.decision_id == decision_id)).scalar_one_or_none()
    if existing is not None:
        return {"decision_id": decision_id, "idempotent": True}  # retry
    row = TribulationDecision(
        world_id=world_id, decision_id=decision_id, episode_id=episode_id,
        action=action, submitted_tick=now_tick,
        effective_before_tick=effective_before_tick,
        target_priorities=target_priorities or {},
        resource_allocation=resource_allocation or {},
        status=DECISION_ACTIVE,
        supersedes_decision_id=supersedes_decision_id, source=source,
        semantic_version="owner-decision-v1")
    session.add(row)
    from .event_stream import deterministic_event_uid
    from ..repositories import EventRepository
    uid = deterministic_event_uid(
        world_id=world_id, simulation_version=M3A_SIMULATION_VERSION,
        real_start_us=now_tick, real_end_us=now_tick,
        engine_id="OWNER_INPUT", event_type=EV_OWNER_DECISION,
        seq=int(session.execute(text(
            "SELECT COUNT(*) FROM world_events")).scalar() or 0))
    EventRepository(session).append(
        world_id=world_id, event_type=EV_OWNER_DECISION,
        source="OWNER_INPUT", blessed_tick=now_tick, scope="WORLD",
        cause={"episode_id": episode_id, "decision_id": decision_id,
               "action": action},
        effect={"effective_before_tick": effective_before_tick,
                "target_priorities": target_priorities or {},
                "resource_allocation": resource_allocation or {}},
        event_uid=uid)
    return {"decision_id": decision_id, "idempotent": False}


# ============================ TribulationEngine ============================
class TribulationEngine:
    """M3a Tribulation Engine（Engine Protocol 实现；只写 tribulation-owned）。"""

    engine_id: str = ENGINE_ID
    engine_version: str = ENGINE_VERSION

    def __init__(self, *, profiles: dict[str, TribulationProfileSpec]
                 | None = None,
                 extra_draws: int = 0):
        self._profiles = profiles or TEST_PROFILES
        self._extra_draws = extra_draws

    # ---- RNG 六子流（独立 seed；增加任一子流抽样不改其他子流历史）
    def _streams(self, ctx: SimulationContext):
        from ..rng_service import RngService
        svc = RngService(world_id=ctx.world_id,
                         simulation_version=ctx.simulation_version)
        tick = ctx.blessed_start_tick
        return {scope: svc.stream(subsystem=ENGINE_ID, blessed_period_tick=tick,
                                  entity_scope=scope)
                for scope in ("SCHEDULE", "PROFILE", "TARGET", "IMPACT",
                              "RECOVERY", "SUCCESSION")}

    def simulate(self, ctx: SimulationContext) -> EngineResult:
        from sqlalchemy import select
        from ...database.models_world import (TribulationEpisode,
                                              TribulationImpactPlan,
                                              TribulationProfile,
                                              TribulationRecoveryState,
                                              TribulationResidualChange,
                                              TribulationSchedule,
                                              ResourceSuccessionCandidate)
        streams = self._streams(ctx)
        for _ in range(self._extra_draws):
            streams["IMPACT"].randint(0, 1_000_000)

        staged = ctx.staged
        schedules = [dict(r) for r in staged.rows("tribulation_schedules")
                     if r.get("schedule_id")]
        profiles = {r["profile_id"]: r for r in staged.rows(
            "tribulation_profiles")}
        episodes = {r["episode_id"]: dict(r) for r in staged.rows(
            "tribulation_episodes")}
        plans = {r["plan_id"]: dict(r) for r in staged.rows(
            "tribulation_impact_plans")}
        recovery = {r["episode_id"]: dict(r) for r in staged.rows(
            "tribulation_recovery_states")}
        candidates = {r["candidate_id"]: dict(r) for r in staged.rows(
            "resource_succession_candidates")}

        proposed: list[StateChange] = []
        events: list[DomainEventDraft] = []
        metrics = {"episodes_created": 0, "episodes_completed": 0,
                   "impacts_applied": 0, "autonomous": 0, "owner_plans": 0}
        end_tick = ctx.blessed_end_tick

        # ---- 1) 窗口判定（高层级替代低层级）
        hit = _tier_at_tick(schedules, end_tick)
        if hit is not None and hit["tier"] in _TIER_ORDER:
            spec = self._spec_for_tier(hit["tier"])
            if spec is not None:
                ep_id = episode_identity(
                    world_id=ctx.world_id,
                    simulation_version=ctx.simulation_version,
                    schedule_id=hit["schedule_id"], tier=hit["tier"],
                    scheduled_tick=end_tick)
                if ep_id not in episodes:
                    # 目标选择：stable ordering + TARGET 子流
                    candidates_list = sorted(
                        [s["working_name"] for s in staged.rows("settlements")
                         if s.get("working_name")])
                    if candidates_list:
                        idx = streams["TARGET"].randint(
                            0, len(candidates_list) - 1)
                        target = candidates_list[idx]
                    else:
                        target = None
                    proposed.append(StateChange(
                        table="tribulation_episodes", entity_id=None,
                        field=None, old_value=None,
                        new_value={"world_id": ctx.world_id,
                                   "episode_id": ep_id,
                                   "window_tier": hit["tier"],
                                   "schedule_ref": hit["schedule_id"],
                                   "profile_ref": spec.profile_id,
                                   "current_stage": STAGE_PRECURSOR,
                                   "entered_tick": end_tick,
                                   "transition_tick":
                                   end_tick + spec.precursor_steps
                                   * TICKS_PER_BLESSED_YEAR,
                                   "target_settlements":
                                   {"selected": [target]},
                                   "target_regions": {"selected": []},
                                   "status": "ACTIVE",
                                   "decision_policy": None,
                                   "semantic_version": ENGINE_VERSION,
                                   "updated_blessed_tick": end_tick},
                        new_row={"world_id": ctx.world_id,
                                 "episode_id": ep_id,
                                 "window_tier": hit["tier"],
                                 "schedule_ref": hit["schedule_id"],
                                 "profile_ref": spec.profile_id,
                                 "current_stage": STAGE_PRECURSOR,
                                 "entered_tick": end_tick,
                                 "transition_tick":
                                 end_tick + spec.precursor_steps
                                 * TICKS_PER_BLESSED_YEAR,
                                 "target_settlements":
                                 {"selected": [target]},
                                 "target_regions": {"selected": []},
                                 "status": "ACTIVE",
                                 "decision_policy": None,
                                 "semantic_version": ENGINE_VERSION,
                                 "updated_blessed_tick": end_tick}))
                    metrics["episodes_created"] += 1
                    events.append(DomainEventDraft(
                        engine_id=ENGINE_ID, event_type=EV_SCHEDULED,
                        cause={"schedule_id": hit["schedule_id"],
                               "tier": hit["tier"]},
                        effect={"episode_id": ep_id,
                                "scheduled_tick": end_tick}))
                    events.append(DomainEventDraft(
                        engine_id=ENGINE_ID, event_type=EV_PRECURSOR,
                        cause={"episode_id": ep_id, "tier": hit["tier"]},
                        effect={"warning_level": "OBSERVED",
                                "anomaly_signals": [
                                    spec.theme.lower()]}))
                    episodes[ep_id] = {
                        "episode_id": ep_id, "current_stage": STAGE_PRECURSOR,
                        "entered_tick": end_tick,
                        "transition_tick": end_tick + spec.precursor_steps
                        * TICKS_PER_BLESSED_YEAR,
                        "window_tier": hit["tier"], "profile_ref":
                        spec.profile_id, "schedule_ref": hit["schedule_id"],
                        "decision_policy": None}

        # ---- 2) 活跃 episode 阶段推进（每步至多一次转移）
        for ep_id, ep in sorted(episodes.items()):
            if ep.get("status") == "COMPLETED":
                continue
            if ep.get("transition_tick") is not None \
                    and end_tick < ep["transition_tick"]:
                continue  # 阶段未到转移点
            stage = ep["current_stage"]
            spec = self._spec_by_profile_id(ep.get("profile_ref"))
            if spec is None:
                continue
            nxt = LIFECYCLE[_LIFECYCLE_INDEX[stage] + 1] \
                if stage != STAGE_NEW_NORMAL else None
            plan = self._run_stage(ctx, streams, proposed, events, metrics,
                                   ep_id, ep, stage, spec, nxt, end_tick,
                                   profiles, plans, recovery, candidates)
            if plan is not None:
                return EngineResult(
                    engine_id=ENGINE_ID, engine_version=ENGINE_VERSION,
                    proposed_changes=proposed, domain_events=events,
                    metrics=metrics, tribulation_plan=plan)

        return EngineResult(
            engine_id=ENGINE_ID, engine_version=ENGINE_VERSION,
            proposed_changes=proposed, domain_events=events, metrics=metrics)

    # ------------------------------------------------------------ stages
    def _run_stage(self, ctx, streams, proposed, events, metrics, ep_id, ep,
                   stage, spec, nxt, end_tick, profiles, plans, recovery,
                   candidates) -> dict | None:
        from sqlalchemy import select
        from ...database.models_world import (TribulationDecision,
                                              TribulationEpisode,
                                              TribulationImpactPlan,
                                              TribulationRecoveryState,
                                              TribulationResidualChange,
                                              ResourceSuccessionCandidate)
        def p_ep(field_, value_):
            proposed.append(StateChange(
                table="tribulation_episodes", entity_id=ep["id"],
                field=field_, old_value=None, new_value=value_))

        if stage == STAGE_PRECURSOR:
            # → PREPARATION（只发结构异常信号，无正式损失）
            self._advance(p_ep, ep, nxt, spec.preparation_steps, end_tick)
            events.append(DomainEventDraft(
                engine_id=ENGINE_ID, event_type=EV_PREPARATION,
                cause={"episode_id": ep_id},
                effect={"stage": STAGE_PREPARATION}))
            self._crash(ctx, "tribulation:precursor")
        elif stage == STAGE_PREPARATION:
            # 决策检查：ACTIVE 且未过期且 episode 匹配
            decisions = [d for d in ctx.staged.rows("tribulation_decisions")
                         if d.get("episode_id") == ep_id
                         and d.get("status") == DECISION_ACTIVE
                         and int(d.get("effective_before_tick") or 0)
                         > end_tick]
            if decisions:
                policy = "OWNER_PLAN"
                metrics["owner_plans"] += 1
                events.append(DomainEventDraft(
                    engine_id=ENGINE_ID, event_type=EV_OWNER_DECISION,
                    cause={"episode_id": ep_id,
                           "decision_id": decisions[0]["decision_id"]},
                    effect={"action": decisions[0]["action"]}))
            else:
                policy = DEFAULT_AUTONOMOUS_RESPONSE_POLICY
                metrics["autonomous"] += 1
                events.append(DomainEventDraft(
                    engine_id=ENGINE_ID, event_type=EV_AUTONOMOUS,
                    cause={"episode_id": ep_id},
                    effect={"policy": policy}))
            p_ep("decision_policy", policy)
            # Mitigation 成本声明（实际扣减由 Economy Adapter 于 IMPACT 应用）
            intensity_proxy = spec.intensity_min
            events.append(DomainEventDraft(
                engine_id=ENGINE_ID, event_type=EV_MITIGATION,
                cause={"episode_id": ep_id, "policy": policy},
                effect={"cost_basis": intensity_proxy}))
            self._advance(p_ep, ep, nxt, spec.impact_steps, end_tick)
            self._crash(ctx, "tribulation:preparation")
        elif stage == STAGE_IMPACT:
            intensity = spec.intensity_min + streams["IMPACT"].randint(
                0, spec.intensity_max - spec.intensity_min)
            plan = self._build_plan(ctx, ep_id, ep, spec, intensity, end_tick)
            proposed.append(StateChange(
                table="tribulation_impact_plans", entity_id=None, field=None,
                old_value=None, new_value=plan, new_row=plan))
            events.append(DomainEventDraft(
                engine_id=ENGINE_ID, event_type=EV_IMPACT_STARTED,
                cause={"episode_id": ep_id, "plan_id": plan["plan_id"]},
                effect={"intensity": intensity, "tier": ep["window_tier"]}))
            metrics["impacts_applied"] += 1
            p_ep("transition_tick", end_tick + spec.impact_steps
                 * TICKS_PER_BLESSED_YEAR)
            # RESPONSE 在同一 impact 步后由 coordinator（adapters）完成
            p_ep("current_stage", STAGE_RESPONSE)
            ep["current_stage"] = STAGE_RESPONSE
            self._crash(ctx, "tribulation:impact_plan")
            return plan  # coordinator 依此调用 Domain Impact Adapters
        elif stage == STAGE_RESPONSE:
            # 域影响已由 coordinator 经 Domain Impact Adapters 原子应用
            # （EV_IMPACT_APPLIED 由 coordinator 发射）；本阶段仅推进
            self._advance(p_ep, ep, nxt, 1, end_tick)
        elif stage == STAGE_STABILIZATION:
            events.append(DomainEventDraft(
                engine_id=ENGINE_ID, event_type=EV_STABILIZED,
                cause={"episode_id": ep_id},
                effect={"danger_controlled": True}))
            self._advance(p_ep, ep, nxt, 1, end_tick)
        elif stage == STAGE_RESIDUAL_CHANGE:
            residual = {"environment_condition": True,
                        "production_constraint": True}
            proposed.append(StateChange(
                table="tribulation_residual_changes", entity_id=None,
                field=None, old_value=None,
                new_value={"world_id": ctx.world_id, "episode_id": ep_id,
                           "change_kind": "environment_condition",
                           "region_ref": None, "settlement_ref": None,
                           "payload": {"permanent": True,
                                       "theme": spec.theme},
                           "persistent": True,
                           "semantic_version": ENGINE_VERSION},
                new_row={"world_id": ctx.world_id, "episode_id": ep_id,
                         "change_kind": "environment_condition",
                         "region_ref": None, "settlement_ref": None,
                         "payload": {"permanent": True, "theme": spec.theme},
                         "persistent": True,
                         "semantic_version": ENGINE_VERSION}))
            events.append(DomainEventDraft(
                engine_id=ENGINE_ID, event_type=EV_RESIDUAL,
                cause={"episode_id": ep_id},
                effect={"residual": residual}))
            self._advance(p_ep, ep, nxt, 1, end_tick)
        elif stage == STAGE_RECOVERY:
            rec = recovery.get(ep_id)
            if rec is None:
                proposed.append(StateChange(
                    table="tribulation_recovery_states", entity_id=None,
                    field=None, old_value=None,
                    new_value={"world_id": ctx.world_id, "episode_id": ep_id,
                               "recovery_need_num": 100,
                               "recovery_need_den": 100,
                               "progress_num": 0, "progress_den": 100,
                               "resource_requirement": 1,
                               "population_requirement": 1,
                               "ecology_requirement": 1,
                               "social_requirement": 1,
                               "status": "IN_PROGRESS",
                               "started_tick": end_tick,
                               "semantic_version": ENGINE_VERSION,
                               "updated_blessed_tick": end_tick},
                    new_row={"world_id": ctx.world_id, "episode_id": ep_id,
                             "recovery_need_num": 100,
                             "recovery_need_den": 100,
                             "progress_num": 0, "progress_den": 100,
                             "resource_requirement": 1,
                             "population_requirement": 1,
                             "ecology_requirement": 1,
                             "social_requirement": 1,
                             "status": "IN_PROGRESS",
                             "started_tick": end_tick,
                             "semantic_version": ENGINE_VERSION,
                             "updated_blessed_tick": end_tick}))
                recovery[ep_id] = {"progress_num": 0}
            else:
                step = 100 // max(spec.recovery_steps, 1)
                new_progress = min(100, int(rec["progress_num"]) + step)
                rec["progress_num"] = new_progress
                for r in ctx.staged.rows("tribulation_recovery_states"):
                    if r.get("episode_id") == ep_id:
                        proposed.append(StateChange(
                            table="tribulation_recovery_states",
                            entity_id=r["id"], field="progress_num",
                            old_value=None, new_value=new_progress))
                        proposed.append(StateChange(
                            table="tribulation_recovery_states",
                            entity_id=r["id"], field="updated_blessed_tick",
                            old_value=None, new_value=end_tick))
                events.append(DomainEventDraft(
                    engine_id=ENGINE_ID, event_type=EV_RECOVERY_PROGRESS,
                    cause={"episode_id": ep_id},
                    effect={"progress": new_progress}))
                self._crash(ctx, "tribulation:recovery")
                if new_progress < 100:
                    return None
                self._advance(p_ep, ep, nxt, 1, end_tick)
        elif stage == STAGE_RESOURCE_SUCCESSION:
            allow = (spec.succession_rules or {}).get("allow_candidate", False)
            if allow:
                cand_id = deterministic_hex_id(
                    [ctx.world_id, ep_id, "SUCCESSION"], bits=128,
                    schema="succession-candidate-v1")
                if cand_id not in candidates:
                    proposed.append(StateChange(
                        table="resource_succession_candidates", entity_id=None,
                        field=None, old_value=None,
                        new_value={"world_id": ctx.world_id,
                                   "candidate_id": cand_id,
                                   "episode_id": ep_id, "region_ref": None,
                                   "resource_category": "UNKNOWN",
                                   "environment_conditions":
                                   {"theme": spec.theme},
                                   "maturation_requirement":
                                   spec.succession_rules.get(
                                       "maturation_steps", 5),
                                   "observation_progress": 0,
                                   "stability_progress": 0,
                                   "discovery_status": "UNOBSERVED",
                                   "development_status": "NONE",
                                   "semantic_version": ENGINE_VERSION},
                        new_row={"world_id": ctx.world_id,
                                 "candidate_id": cand_id,
                                 "episode_id": ep_id, "region_ref": None,
                                 "resource_category": "UNKNOWN",
                                 "environment_conditions":
                                 {"theme": spec.theme},
                                 "maturation_requirement":
                                 spec.succession_rules.get(
                                     "maturation_steps", 5),
                                 "observation_progress": 0,
                                 "stability_progress": 0,
                                 "discovery_status": "UNOBSERVED",
                                 "development_status": "NONE",
                                 "semantic_version": ENGINE_VERSION}))
                    candidates[cand_id] = {"candidate_id": cand_id}
                    events.append(DomainEventDraft(
                        engine_id=ENGINE_ID,
                        event_type=EV_SUCCESSION_CANDIDATE,
                        cause={"episode_id": ep_id},
                        effect={"candidate_id": cand_id,
                                "resource_node_created": False}))
            self._crash(ctx, "tribulation:succession")
            self._advance(p_ep, ep, nxt, 1, end_tick)
        elif stage == STAGE_NEW_NORMAL:
            p_ep("status", "COMPLETED")
            events.append(DomainEventDraft(
                engine_id=ENGINE_ID, event_type=EV_NEW_NORMAL,
                cause={"episode_id": ep_id},
                effect={"world_not_reset": True}))
            events.append(DomainEventDraft(
                engine_id=ENGINE_ID, event_type=EV_COMPLETED,
                cause={"episode_id": ep_id},
                effect={"stage": STAGE_NEW_NORMAL}))
            metrics["episodes_completed"] += 1
            self._crash(ctx, "tribulation:new_normal")
        return None

    def _crash(self, ctx: SimulationContext, label: str) -> None:
        if ctx.crash_after == label:
            raise RuntimeError(f"crash: {label}")

    def _advance(self, p_ep, ep, nxt, steps, end_tick) -> None:
        p_ep("current_stage", nxt)
        # entered_tick 是创建时刻不变量：只随 episode 创建写入，绝不覆写
        p_ep("transition_tick", end_tick + steps * TICKS_PER_BLESSED_YEAR)
        p_ep("updated_blessed_tick", end_tick)
        ep["current_stage"] = nxt
        ep["transition_tick"] = end_tick + steps * TICKS_PER_BLESSED_YEAR

    def _build_plan(self, ctx, ep_id, ep, spec, intensity, end_tick) -> dict:
        f = Fraction(intensity, 100)
        plan_id = deterministic_hex_id(
            [ctx.world_id, ep_id, "PLAN"], bits=128,
            schema=IMPACT_PLAN_SCHEMA_VERSION)
        targets = (ep.get("target_settlements") or {}).get("selected", [])
        return {
            "world_id": ctx.world_id, "plan_id": plan_id,
            "episode_id": ep_id, "profile_ref": spec.profile_id,
            "tier": ep["window_tier"], "intensity": intensity,
            "affected_regions": {"selected": []},
            "affected_settlements": {"selected": targets},
            "population_risk_num": (spec.population_risk * f).numerator,
            "population_risk_den": (spec.population_risk * f).denominator,
            "resource_damage_num": (spec.resource_damage * f).numerator,
            "resource_damage_den": (spec.resource_damage * f).denominator,
            "inventory_damage_num": (spec.inventory_damage * f).numerator,
            "inventory_damage_den": (spec.inventory_damage * f).denominator,
            "production_disruption_num":
            (spec.production_disruption * f).numerator,
            "production_disruption_den":
            (spec.production_disruption * f).denominator,
            "social_displacement_num":
            (spec.social_displacement * f).numerator,
            "social_displacement_den":
            (spec.social_displacement * f).denominator,
            "institution_disruption_num":
            (spec.institution_disruption * f).numerator,
            "institution_disruption_den":
            (spec.institution_disruption * f).denominator,
            "ecology_pressure": spec.ecology_pressure,
            "mitigation_applied": {},
            "residual_changes": {"environment_condition": True},
            "recovery_requirements": {"stock": 1, "steps":
                                      spec.recovery_steps},
            "succession_candidates": {"allow":
                                      bool((spec.succession_rules or {})
                                           .get("allow_candidate"))},
            "semantic_version": IMPACT_PLAN_SCHEMA_VERSION,
        }

    def _spec_for_tier(self, tier: str) -> TribulationProfileSpec | None:
        for spec in self._profiles.values():
            if spec.tier == tier:
                return spec
        return None

    def _spec_by_profile_id(self, profile_id: str | None
                            ) -> TribulationProfileSpec | None:
        return self._profiles.get(profile_id or "")

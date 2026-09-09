# -*- coding: utf-8 -*-
"""SOCIAL_ENGINE（M2d）—— Aggregate Social Continuity Foundation。

恢复自 runtime_design/07（社会实体：households/lineages/institutions +
population_groups 劳动力池；后台社会事件；CAUSE_BASED）：
- 07 号明确：households（统计级 + 锚点级明细）、lineages（PERSISTENT_
  LINEAGE）、institutions（PERSISTENT_INSTITUTION）、事件分级 scope。
- 07 号的婚姻/职业流动/争执仲裁/文化扩散（MEDIUM_DIFFUSION）> M2d 范围
  → CONFLICT_FOUND 延后（见 M2D 文档）。

M2d 冻结（NEW_PROPOSAL 标注于 M2D_SOCIAL_FOUNDATION.md）：
- 四层：Population Group（M2a）→ Household Aggregate → Persistent
  Lineage → Institution；Persistent Person 晋升接口冻结、默认 0。
- 人口归属契约（m2d-coverage-v1：full）：每 (settlement, species) 的
  ACTIVE household represented_population 之和 == population 总量；
  社会只做 allocation，绝不第二次出生/死亡（SOC_INV_21）。
- 对账顺序（进入 engine_version 语义）：household reconciliation
  （增减分配 + 拆分 + 溶解 + 形成）→ lineage 聚合/涌现/分化/灭绝 →
  institution 生命周期 → settlement social state + feedback →
  threshold events。
- 分配确定性：stable id 排序 round-robin；ID = sha256(social-v1|…|seq)
  前 16 hex（无 UUID4 / rowid / set order）。
- 权威社会状态整数 fixed-point 0..SOCIAL_STATE_SCALE（m2d-scale-1）。
- 事件只在 formation/dissolution/significant transition/threshold
  crossing 发出（事件流不爆炸）；事件是 Domain Event，不是自然语言故事。
- 零 RNG（确定性规则优先）；零 LLM/网络/wall-clock/commit；
  只写 households/lineages/institutions/settlement_social_state/
  social_feedback_state。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from fractions import Fraction

from ...domain.errors import IntegrityError, WorldRuntimeError
from .contracts import (DomainEventDraft, EngineResult, SimulationContext,
                        StateChange)

ENGINE_ID = "SOCIAL"
ENGINE_VERSION = "m2d-social-1"
SOCIAL_STATE_SCALE_VERSION = "m2d-scale-1"
SOCIAL_STATE_SCALE = 1_000_000
FORMATION_VERSION = "m2d-formation-v1"
IDENTITY_SCHEMA_VERSION = "social-v1"

EV_HH_FORMED = "HOUSEHOLD_FORMED"
EV_HH_SPLIT = "HOUSEHOLD_SPLIT"
EV_HH_DISSOLVED = "HOUSEHOLD_DISSOLVED"
EV_LINEAGE_FOUNDED = "LINEAGE_FOUNDED"
EV_LINEAGE_EXTINCT = "LINEAGE_EXTINCT"
EV_INST_FOUNDED = "INSTITUTION_FOUNDED"
EV_INST_STATE = "INSTITUTION_STATE_CHANGED"
EV_INST_DISSOLVED = "INSTITUTION_DISSOLVED"
EV_STRESS_THRESHOLD = "SOCIAL_STRESS_THRESHOLD_CROSSED"

HH_ACTIVE, HH_DISSOLVED = "ACTIVE", "DISSOLVED"
LG_ACTIVE, LG_DORMANT, LG_EXTINCT = "ACTIVE", "DORMANT", "EXTINCT"
IN_ACTIVE, IN_DECLINING = "ACTIVE", "DECLINING"
IN_DORMANT, IN_DISSOLVED = "DORMANT", "DISSOLVED"

STRESS_LOW, STRESS_ELEVATED, STRESS_HIGH = "LOW", "ELEVATED", "HIGH"


class SocialProfileUnconfigured(WorldRuntimeError):
    code = "SOCIAL_UNCONFIGURED"


@dataclass(frozen=True)
class SocialProfile:
    """社会 profile（M2d 仅 synthetic TEST；正式种族/机构 SOCIAAL_UNCONFIGURED）。

    机制可配置 —— 不把任何现实家庭/婚姻/政治结构写成默认。"""
    profile_id: str
    formation_size: int = 5            # 新 household 目标规模
    split_threshold: int = 6           # 超过即拆分
    lineage_found_generation: int = 3  # 涌现为 lineage 的最低代数
    lineage_found_size: int = 6        # 涌现最低规模
    lineage_split_households: int = 12  # lineage 分化阈值（household 数）
    institution_found_pop: int = 80    # 成立门槛（人口）
    institution_dissolve_pop: int = 50  # 解散门槛（人口）
    institution_decline_cohesion: int = 500_000
    institution_dormant_cohesion: int = 300_000
    institution_active_cohesion: int = 600_000
    pressure_weights: dict[str, Fraction] = field(default_factory=lambda: {
        "economy": Fraction(4, 8), "ecology": Fraction(3, 8),
        "mobility": Fraction(1, 8)})
    stress_thresholds: tuple[int, int] = (300_000, 600_000)
    migration_modifier_k: Fraction = Fraction(1, 2)
    fertility_context_k: Fraction = Fraction(1, 4)
    social_support_k: Fraction = Fraction(1, 2)
    semantic_version: str = "test-social-1"

    def __post_init__(self) -> None:
        if sum(self.pressure_weights.values()) != 1:
            raise ValueError("pressure_weights 必须和为 1")
        if not (0 < self.stress_thresholds[0] < self.stress_thresholds[1]
                < SOCIAL_STATE_SCALE):
            raise ValueError("stress_thresholds 非法")


# TEST_FIXTURE_ONLY：synthetic social profile（不得作为正式社会 Canon）
TEST_SOCIAL_PROFILE = SocialProfile(profile_id="TEST-SOCIAL-PROFILE-001")

SOCIAL_PROFILES: dict[str, SocialProfile] = {
    "TEST-SOCIAL-PROFILE-001": TEST_SOCIAL_PROFILE,
}


def social_identity(*, world_id: str, kind: str, settlement: str,
                    species: str, tick: int, seq: int) -> str:
    """确定性实体 ID（IDENTITY_SCHEMA_VERSION=social-v1；无 UUID4）。"""
    payload = "|".join([IDENTITY_SCHEMA_VERSION, world_id, kind, settlement,
                        species, str(tick), str(seq)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(value, hi))


def _level_of(stress: int, thresholds: tuple[int, int]) -> str:
    if stress >= thresholds[1]:
        return STRESS_HIGH
    if stress >= thresholds[0]:
        return STRESS_ELEVATED
    return STRESS_LOW


class SocialEngine:
    """Aggregate Social Foundation Engine（Engine Protocol 实现）。"""

    engine_id: str = ENGINE_ID
    engine_version: str = ENGINE_VERSION

    def __init__(self, *, profile: SocialProfile | None = None,
                 extra_draws: int = 0):
        """extra_draws：测试专用 —— 额外消耗 RNG 证明 substream 独立性
        （SD32）；引擎算法本身零 RNG。"""
        self._profile = profile or TEST_SOCIAL_PROFILE
        self._extra_draws = extra_draws

    # ------------------------------------------------------------ simulate
    def simulate(self, ctx: SimulationContext) -> EngineResult:
        staged = ctx.staged
        profile = self._profile
        if ctx.crash_after == "mid:SOCIAL":
            raise RuntimeError("crash: mid:SOCIAL")
        for _ in range(self._extra_draws):
            ctx.rng.randint(0, 1_000_000)

        settlements = sorted(
            [s["working_name"] for s in staged.rows("settlements")
             if s.get("working_name")])
        species_set = sorted({g["species"] for g in staged.rows(
            "population_groups")})

        # ---- 声明输入（staged 视图；不查其他引擎私有 DB）
        pop_now = {(g["settlement_ref"], g["species"]): 0
                   for g in staged.rows("population_groups")}
        for g in staged.rows("population_groups"):
            key = (g.get("settlement_ref"), g["species"])
            pop_now[key] = pop_now.get(key, 0) + int(g["count"])
        pop_snapshot = {}
        for g in ctx.snapshot.rows("population_groups"):
            key = (g.get("settlement_ref"), g["species"])
            pop_snapshot[key] = pop_snapshot.get(key, 0) + int(g["count"])

        econ_stress = {}
        for p in staged.rows("economic_pressure_state"):
            sref = p.get("settlement_ref")
            demand = int(p.get("demand_minor") or 0)
            unmet = int(p.get("unmet_minor") or 0)
            ratio = Fraction(unmet, demand) if demand > 0 else Fraction(0)
            cur = _clamp(ratio.numerator * SOCIAL_STATE_SCALE
                         // ratio.denominator, 0, SOCIAL_STATE_SCALE)
            econ_stress[sref] = max(econ_stress.get(sref, 0), cur)

        zone_settlement = {z.get("zone_id"): z.get("settlement_relation")
                           for z in staged.rows("ecology_zones")}
        ecol_stress = {}
        for fb in staged.rows("ecology_feedback_state"):
            sref = zone_settlement.get(fb.get("zone_ref"))
            if not sref:
                continue
            f = Fraction(int(fb.get("environmental_stress_num") or 0),
                         int(fb.get("environmental_stress_den") or 1))
            cur = _clamp(f.numerator * SOCIAL_STATE_SCALE // f.denominator,
                         0, SOCIAL_STATE_SCALE)
            ecol_stress[sref] = max(ecol_stress.get(sref, 0), cur)

        households = {r["id"]: dict(r) for r in staged.rows("households")}
        lineages = {r["id"]: dict(r) for r in staged.rows("lineages")}
        institutions = {r["id"]: dict(r) for r in staged.rows("institutions")}
        social_states = {r["settlement_ref"]: r for r in staged.rows(
            "settlement_social_state")}
        feedback_rows = {r["settlement_ref"]: r for r in staged.rows(
            "social_feedback_state")}

        proposed: list[StateChange] = []
        events: list[DomainEventDraft] = []
        metrics = {"households_formed": 0, "households_split": 0,
                   "households_dissolved": 0, "lineages_founded": 0,
                   "lineages_extinct": 0, "institutions_founded": 0,
                   "institutions_dissolved": 0,
                   "institution_state_transitions": 0,
                   "stress_threshold_crossings": 0,
                   "feedback_applications": 0}

        def hh_order(r: dict) -> tuple:
            return (r["settlement_ref"], r["species"], r["household_id"])

        def active_hh(settlement: str, species: str) -> list[dict]:
            return sorted([r for r in households.values()
                           if r["settlement_ref"] == settlement
                           and r["species"] == species
                           and r["state"] == HH_ACTIVE], key=hh_order)

        # 步内 INSERT 序号（确定性 ID；含本步已插入的实体）
        _ins_seq: dict[tuple, int] = {}

        def next_seq(kind: str, settlement: str, species: str) -> int:
            key = (kind, settlement, species)
            _ins_seq[key] = _ins_seq.get(key, 0) + 1
            if kind == "HH":
                staged_n = sum(1 for r in households.values()
                               if r["settlement_ref"] == settlement
                               and r["species"] == species)
            elif kind == "LG":
                staged_n = sum(1 for _ in lineages.values())
            else:
                staged_n = sum(1 for _ in institutions.values())
            return staged_n + _ins_seq[key]

        # ============ Phase H：Household 对账（每 settlement × species）
        for settlement in settlements:
            for species in species_set:
                key = (settlement, species)
                total_pop = pop_now.get(key, 0)
                hhs = active_hh(settlement, species)
                represented = sum(int(r["represented_population"]) for r in hhs)
                delta = total_pop - represented
                if ctx.crash_after == "mid:SOCIAL_HOUSEHOLD":
                    raise RuntimeError("crash: mid:SOCIAL_HOUSEHOLD")
                if delta > 0:
                    # 增长分配：stable id 序 round-robin（确定性）
                    for i in range(delta):
                        r = hhs[i % len(hhs)] if hhs else None
                        if r is None:
                            break
                        r["represented_population"] = \
                            int(r["represented_population"]) + 1
                elif delta < 0:
                    # 衰减扣减：规模最大者先扣（规模 desc、id asc）
                    need = -delta
                    order = sorted(hhs, key=lambda r: (
                        -int(r["represented_population"]), r["household_id"]))
                    for r in order:
                        if need <= 0:
                            break
                        size = int(r["represented_population"])
                        take = min(size, need)
                        r["represented_population"] = size - take
                        need -= take
                # 无 ACTIVE household 且有人口 → 形成（formation policy）
                hhs = active_hh(settlement, species)
                if not hhs and total_pop > 0:
                    n = (total_pop + profile.formation_size - 1) \
                        // profile.formation_size
                    for i in range(n):
                        size = total_pop // n + (1 if i < total_pop % n else 0)
                        hh_id = social_identity(
                            world_id=ctx.world_id, kind="HH",
                            settlement=settlement, species=species,
                            tick=ctx.blessed_end_tick,
                            seq=next_seq("HH", settlement, species))
                        row = {
                            "world_id": ctx.world_id, "household_id": hh_id,
                            "settlement_ref": settlement, "species": species,
                            "represented_population": size, "generation": 1,
                            "lineage_ref": None, "anchor_group_ref": None,
                            "state": HH_ACTIVE,
                            "formation_version": FORMATION_VERSION,
                            "updated_blessed_tick": ctx.blessed_end_tick,
                        }
                        proposed.append(StateChange(
                            table="households", entity_id=None, field=None,
                            old_value=None, new_value=dict(row),
                            new_row=dict(row)))
                        metrics["households_formed"] += 1
                        events.append(DomainEventDraft(
                            engine_id=ENGINE_ID, event_type=EV_HH_FORMED,
                            cause={"settlement": settlement,
                                   "species": species},
                            effect={"household_id": hh_id,
                                    "size": size, "generation": 1}))
                    hhs = []
                # 拆分（split_threshold）
                hhs = active_hh(settlement, species)
                for r in sorted(hhs, key=hh_order):
                    size = int(r["represented_population"])
                    if size <= profile.split_threshold:
                        continue
                    half_a = size // 2
                    half_b = size - half_a
                    r["represented_population"] = half_a
                    new_hh_id = social_identity(
                        world_id=ctx.world_id, kind="HH",
                        settlement=settlement, species=species,
                        tick=ctx.blessed_end_tick,
                        seq=next_seq("HH", settlement, species))
                    parent_lineage = r.get("lineage_ref")
                    lineage_ok = False
                    if parent_lineage:
                        for lg in lineages.values():
                            if lg.get("lineage_id") == parent_lineage \
                                    and lg.get("status") != LG_EXTINCT:
                                lineage_ok = True
                                break
                    row = {
                        "world_id": ctx.world_id, "household_id": new_hh_id,
                        "settlement_ref": settlement, "species": species,
                        "represented_population": half_b,
                        "generation": int(r["generation"]) + 1,
                        "lineage_ref": parent_lineage if lineage_ok else None,
                        "anchor_group_ref": r.get("anchor_group_ref"),
                        "state": HH_ACTIVE,
                        "formation_version": FORMATION_VERSION,
                        "updated_blessed_tick": ctx.blessed_end_tick,
                    }
                    proposed.append(StateChange(
                        table="households", entity_id=None, field=None,
                        old_value=None, new_value=dict(row),
                        new_row=dict(row)))
                    metrics["households_split"] += 1
                    events.append(DomainEventDraft(
                        engine_id=ENGINE_ID, event_type=EV_HH_SPLIT,
                        cause={"settlement": settlement, "species": species},
                        effect={"parent_household_id": r["household_id"],
                                "new_household_id": new_hh_id,
                                "parent_size": half_a,
                                "new_size": half_b,
                                "generation": int(r["generation"]) + 1}))
                # 溶解（size == 0 的 ACTIVE household）
                for r in sorted(active_hh(settlement, species), key=hh_order):
                    if int(r["represented_population"]) > 0:
                        continue
                    r["state"] = HH_DISSOLVED
                    r["_dissolved_this_step"] = 1
                    metrics["households_dissolved"] += 1
                    events.append(DomainEventDraft(
                        engine_id=ENGINE_ID, event_type=EV_HH_DISSOLVED,
                        cause={"settlement": settlement, "species": species},
                        effect={"household_id": r["household_id"],
                                "generation": int(r["generation"])}))
        if ctx.crash_after == "after:SOCIAL_HOUSEHOLD":
            raise RuntimeError("crash: after:SOCIAL_HOUSEHOLD")

        # ============ Phase L：Lineage 聚合/涌现/分化/灭绝
        if ctx.crash_after == "mid:SOCIAL_LINEAGE":
            raise RuntimeError("crash: mid:SOCIAL_LINEAGE")
        lineage_by_id = {lg.get("lineage_id"): lg for lg in lineages.values()
                         if lg.get("lineage_id")}
        # 聚合（recompute from ACTIVE households）
        for lg in lineage_by_id.values():
            members = [h for h in households.values()
                       if h.get("lineage_ref") == lg.get("lineage_id")
                       and h["state"] == HH_ACTIVE]
            lg["_represented"] = sum(int(h["represented_population"])
                                     for h in members)
            lg["_count"] = len(members)
            lg["_generation"] = max((int(h["generation"]) for h in members),
                                    default=int(lg.get("generation") or 1))
            if lg["_represented"] == 0 and lg["_count"] == 0 \
                    and lg.get("status") != LG_EXTINCT:
                lg["_to_extinct"] = True
            else:
                lg["_to_extinct"] = False
        # 涌现：generation ≥ 阈值且规模 ≥ 阈值且无 lineage 的 household
        founded_this_step = 0
        for settlement in settlements:
            for species in species_set:
                for r in sorted(active_hh(settlement, species), key=hh_order):
                    if founded_this_step >= 1:
                        break
                    if r.get("lineage_ref"):
                        continue
                    if int(r["generation"]) < profile.lineage_found_generation:
                        continue
                    if int(r["represented_population"]) \
                            < profile.lineage_found_size:
                        continue
                    seq = next_seq("LG", settlement, species)
                    lg_id = social_identity(
                        world_id=ctx.world_id, kind="LG",
                        settlement=settlement, species=species,
                        tick=ctx.blessed_end_tick, seq=seq)
                    row = {
                        "world_id": ctx.world_id, "lineage_type": "FAMILY",
                        "lineage_id": lg_id, "origin_settlement": settlement,
                        "represented_population":
                            int(r["represented_population"]),
                        "household_count": 1, "generation": int(r["generation"]),
                        "status": LG_ACTIVE,
                        "founded_tick": ctx.blessed_end_tick,
                        "parent_lineage_ref": None,
                        "semantic_version": profile.semantic_version,
                        "updated_blessed_tick": ctx.blessed_end_tick,
                    }
                    proposed.append(StateChange(
                        table="lineages", entity_id=None, field=None,
                        old_value=None, new_value=dict(row),
                        new_row=dict(row)))
                    r["lineage_ref"] = lg_id
                    lineage_by_id[lg_id] = {"lineage_id": lg_id,
                                            "status": LG_ACTIVE}
                    metrics["lineages_founded"] += 1
                    founded_this_step += 1
                    events.append(DomainEventDraft(
                        engine_id=ENGINE_ID, event_type=EV_LINEAGE_FOUNDED,
                        cause={"settlement": settlement, "species": species},
                        effect={"lineage_id": lg_id,
                                "founder_household": r["household_id"],
                                "generation": int(r["generation"]),
                                "parent_lineage": None}))
        # 分化：household_count ≥ 阈值 → 最大成员 household 立子 lineage
        for lg in sorted(lineage_by_id.values(),
                         key=lambda x: x.get("lineage_id") or ""):
            if founded_this_step >= 1:
                break
            if lg.get("status") == LG_EXTINCT:
                continue
            members = sorted(
                [h for h in households.values()
                 if h.get("lineage_ref") == lg.get("lineage_id")
                 and h["state"] == HH_ACTIVE],
                key=lambda h: (-int(h["represented_population"]),
                               h["household_id"]))
            if len(members) < profile.lineage_split_households:
                continue
            branch = members[0]
            if int(branch["generation"]) < 2 \
                    or int(branch["represented_population"]) \
                    < profile.lineage_found_size:
                continue
            seq = next_seq("LG", branch["settlement_ref"],
                           branch["species"])
            child_id = social_identity(
                world_id=ctx.world_id, kind="LG",
                settlement=branch["settlement_ref"],
                species=branch["species"],
                tick=ctx.blessed_end_tick, seq=seq)
            row = {
                "world_id": ctx.world_id, "lineage_type": "FAMILY",
                "lineage_id": child_id,
                "origin_settlement": branch["settlement_ref"],
                "represented_population":
                    int(branch["represented_population"]),
                "household_count": 1,
                "generation": int(branch["generation"]),
                "status": LG_ACTIVE, "founded_tick": ctx.blessed_end_tick,
                "parent_lineage_ref": lg.get("lineage_id"),
                "semantic_version": profile.semantic_version,
                "updated_blessed_tick": ctx.blessed_end_tick,
            }
            proposed.append(StateChange(
                table="lineages", entity_id=None, field=None,
                old_value=None, new_value=dict(row), new_row=dict(row)))
            branch["lineage_ref"] = child_id
            lineage_by_id[child_id] = {"lineage_id": child_id,
                                       "status": LG_ACTIVE}
            metrics["lineages_founded"] += 1
            founded_this_step += 1
            events.append(DomainEventDraft(
                engine_id=ENGINE_ID, event_type=EV_LINEAGE_FOUNDED,
                cause={"settlement": branch["settlement_ref"],
                       "species": branch["species"]},
                effect={"lineage_id": child_id,
                        "founder_household": branch["household_id"],
                        "generation": int(branch["generation"]),
                        "parent_lineage": lg.get("lineage_id")}))
        if ctx.crash_after == "after:SOCIAL_LINEAGE":
            raise RuntimeError("crash: after:SOCIAL_LINEAGE")

        # ============ Phase I：Institution 生命周期
        if ctx.crash_after == "mid:SOCIAL_INSTITUTION":
            raise RuntimeError("crash: mid:SOCIAL_INSTITUTION")
        for settlement in settlements:
            pop = sum(pop_now.get((settlement, sp), 0) for sp in species_set)
            cohesion = int(social_states.get(settlement, {}).get(
                "social_cohesion", SOCIAL_STATE_SCALE))
            insts = sorted(
                [i for i in institutions.values()
                 if i.get("settlement_ref") == settlement],
                key=lambda i: i.get("institution_id") or i.get("kind") or "")
            for inst in insts:
                st = inst.get("state") or IN_ACTIVE
                new_st = st
                if st == IN_ACTIVE:
                    if pop < profile.institution_dissolve_pop:
                        new_st = IN_DISSOLVED
                    elif cohesion < profile.institution_decline_cohesion:
                        new_st = IN_DECLINING
                elif st == IN_DECLINING:
                    if pop < profile.institution_dissolve_pop:
                        new_st = IN_DISSOLVED
                    elif cohesion < profile.institution_dormant_cohesion:
                        new_st = IN_DORMANT
                    elif cohesion >= profile.institution_active_cohesion:
                        new_st = IN_ACTIVE
                elif st == IN_DORMANT:
                    if pop < profile.institution_dissolve_pop:
                        new_st = IN_DISSOLVED
                    elif cohesion >= profile.institution_active_cohesion:
                        new_st = IN_ACTIVE
                # DISSOLVED 终态（不复活）
                if new_st != st:
                    inst["state"] = new_st
                    if new_st == IN_DISSOLVED:
                        metrics["institutions_dissolved"] += 1
                        events.append(DomainEventDraft(
                            engine_id=ENGINE_ID, event_type=EV_INST_DISSOLVED,
                            cause={"settlement": settlement},
                            effect={"institution_id":
                                    inst.get("institution_id")
                                    or inst.get("kind")}))
                    else:
                        metrics["institution_state_transitions"] += 1
                        events.append(DomainEventDraft(
                            engine_id=ENGINE_ID, event_type=EV_INST_STATE,
                            cause={"settlement": settlement},
                            effect={"institution_id":
                                    inst.get("institution_id")
                                    or inst.get("kind"),
                                    "from_state": st, "to_state": new_st}))
            # 成立：人口达标且无存续机构（每聚落每步 ≤ 1）
            if pop >= profile.institution_found_pop \
                    and not any(i.get("state") != IN_DISSOLVED
                                for i in insts):
                seq = next_seq("INST", settlement, "")
                inst_id = social_identity(
                    world_id=ctx.world_id, kind="INST",
                    settlement=settlement, species="",
                    tick=ctx.blessed_end_tick, seq=seq)
                row = {
                    "world_id": ctx.world_id, "kind": "COMMUNITY_BODY",
                    "settlement_ref": settlement,
                    "state": IN_ACTIVE,
                    "institution_id": inst_id,
                    "founded_tick": ctx.blessed_end_tick,
                    "profile_ref": profile.profile_id,
                    "updated_blessed_tick": ctx.blessed_end_tick,
                }
                proposed.append(StateChange(
                    table="institutions", entity_id=None, field=None,
                    old_value=None, new_value=dict(row), new_row=dict(row)))
                metrics["institutions_founded"] += 1
                events.append(DomainEventDraft(
                    engine_id=ENGINE_ID, event_type=EV_INST_FOUNDED,
                    cause={"settlement": settlement},
                    effect={"institution_id": inst_id,
                            "kind": "COMMUNITY_BODY"}))

        # ============ Phase S：Settlement Social State + Feedback
        for settlement in settlements:
            srow = social_states.get(settlement)
            if srow is None:
                raise IntegrityError(f"聚落 {settlement} 缺 social state 行",
                                     detail=settlement)
            frow = feedback_rows.get(settlement)
            if frow is None:
                raise IntegrityError(f"聚落 {settlement} 缺 feedback 行",
                                     detail=settlement)
            w = profile.pressure_weights
            econ = econ_stress.get(settlement, 0)
            ecol = ecol_stress.get(settlement, 0)
            mob = 0
            for sp in species_set:
                before = pop_snapshot.get((settlement, sp), 0)
                after = pop_now.get((settlement, sp), 0)
                mob = max(mob, _clamp(
                    abs(after - before) * SOCIAL_STATE_SCALE
                    // max(after, 1), 0, SOCIAL_STATE_SCALE))
            stress_f = w["economy"] * econ + w["ecology"] * ecol \
                + w["mobility"] * mob
            stress = _clamp(stress_f.numerator // stress_f.denominator,
                            0, SOCIAL_STATE_SCALE)
            cohesion = SOCIAL_STATE_SCALE - stress
            active_before = sum(1 for h in households.values()
                                if h.get("settlement_ref") == settlement
                                and h.get("state") == HH_ACTIVE)
            dissolved_now = sum(1 for h in households.values()
                                if h.get("settlement_ref") == settlement
                                and h.get("state") == HH_DISSOLVED
                                and int(h.get("_dissolved_this_step") or 0)
                                == 1)
            stability = SOCIAL_STATE_SCALE - (
                dissolved_now * SOCIAL_STATE_SCALE
                // max(active_before + dissolved_now, 1))
            unallocated = 0
            for sp in species_set:
                reps = sum(int(h["represented_population"])
                           for h in households.values()
                           if h.get("settlement_ref") == settlement
                           and h["species"] == sp
                           and h["state"] == HH_ACTIVE)
                unallocated += max(pop_now.get((settlement, sp), 0) - reps, 0)

            mig_f = Fraction(1) + stress_f * profile.migration_modifier_k \
                / SOCIAL_STATE_SCALE
            fert_f = Fraction(1) - stress_f * profile.fertility_context_k \
                / SOCIAL_STATE_SCALE
            sup_f = Fraction(1) - stress_f * profile.social_support_k \
                / SOCIAL_STATE_SCALE
            stress_ratio = Fraction(stress, SOCIAL_STATE_SCALE)

            for fname, value in (
                    ("social_stress", stress),
                    ("social_cohesion", cohesion),
                    ("household_stability", stability),
                    ("mobility_pressure", mob),
                    ("unallocated_population", unallocated),
                    ("stress_min_seen", min(int(srow["stress_min_seen"]),
                                            stress)),
                    ("stress_max_seen", max(int(srow["stress_max_seen"]),
                                            stress)),
                    ("engine_version", ENGINE_VERSION),
                    ("updated_blessed_tick", ctx.blessed_end_tick)):
                proposed.append(StateChange(
                    table="settlement_social_state", entity_id=srow["id"],
                    field=fname, old_value=None, new_value=value))
            for fname, value in (
                    ("migration_modifier_num", mig_f.numerator),
                    ("migration_modifier_den", mig_f.denominator),
                    ("fertility_context_num", fert_f.numerator),
                    ("fertility_context_den", fert_f.denominator),
                    ("social_support_num", sup_f.numerator),
                    ("social_support_den", sup_f.denominator),
                    ("social_stress_num", stress_ratio.numerator),
                    ("social_stress_den", stress_ratio.denominator),
                    ("engine_version", ENGINE_VERSION),
                    ("updated_blessed_tick", ctx.blessed_end_tick)):
                proposed.append(StateChange(
                    table="social_feedback_state", entity_id=frow["id"],
                    field=fname, old_value=None, new_value=value))
            metrics["feedback_applications"] += 1

            prev_stress = int(srow["social_stress"])
            prev_level = _level_of(prev_stress, profile.stress_thresholds)
            new_level = _level_of(stress, profile.stress_thresholds)
            if prev_level != new_level:
                metrics["stress_threshold_crossings"] += 1
                events.append(DomainEventDraft(
                    engine_id=ENGINE_ID, event_type=EV_STRESS_THRESHOLD,
                    cause={"settlement": settlement},
                    effect={"from_level": prev_level, "to_level": new_level,
                            "stress_before_minor": prev_stress,
                            "stress_after_minor": stress}))

        # ============ 持久化 household/lineage 变更
        for r in households.values():
            for fname in ("represented_population", "generation",
                          "lineage_ref", "state", "updated_blessed_tick"):
                value = r[fname] if fname != "updated_blessed_tick" \
                    else ctx.blessed_end_tick
                proposed.append(StateChange(
                    table="households", entity_id=r["id"], field=fname,
                    old_value=None, new_value=value))
        for lg in lineages.values():
            if "id" not in lg or lg.get("lineage_id") is None:
                continue  # 本步 INSERT 的新行（聚合值已随行写入）或 M0 行
            proposed.append(StateChange(
                table="lineages", entity_id=lg["id"],
                field="represented_population", old_value=None,
                new_value=lg.get("_represented",
                                 int(lg.get("represented_population") or 0))))
            proposed.append(StateChange(
                table="lineages", entity_id=lg["id"],
                field="household_count", old_value=None,
                new_value=lg.get("_count",
                                 int(lg.get("household_count") or 0))))
            proposed.append(StateChange(
                table="lineages", entity_id=lg["id"],
                field="generation", old_value=None,
                new_value=lg.get("_generation",
                                 int(lg.get("generation") or 1))))
            new_status = LG_EXTINCT if lg.get("_to_extinct") \
                else lg.get("status")
            if new_status != lg.get("status"):
                metrics["lineages_extinct"] += 1
                events.append(DomainEventDraft(
                    engine_id=ENGINE_ID, event_type=EV_LINEAGE_EXTINCT,
                    cause={"lineage_id": lg.get("lineage_id")},
                    effect={"origin_settlement": lg.get("origin_settlement"),
                            "final_generation": lg.get("_generation", 1)}))
            proposed.append(StateChange(
                table="lineages", entity_id=lg["id"],
                field="status", old_value=None, new_value=new_status))
            proposed.append(StateChange(
                table="lineages", entity_id=lg["id"],
                field="updated_blessed_tick", old_value=None,
                new_value=ctx.blessed_end_tick))
        for inst in institutions.values():
            proposed.append(StateChange(
                table="institutions", entity_id=inst["id"],
                field="state", old_value=None,
                new_value=inst.get("state")))
            proposed.append(StateChange(
                table="institutions", entity_id=inst["id"],
                field="updated_blessed_tick", old_value=None,
                new_value=ctx.blessed_end_tick))

        return EngineResult(
            engine_id=ENGINE_ID, engine_version=ENGINE_VERSION,
            proposed_changes=proposed, domain_events=events,
            draw_count=self._extra_draws, metrics=metrics)
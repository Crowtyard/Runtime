# -*- coding: utf-8 -*-
"""Domain-owned Tribulation Impact Adapters（M3a 方案 B）。

Coordinator 在 IMPACT 步调用本模块适配器，把 TribulationImpactPlan 的
各域影响原子应用到各 Domain 所有权状态（同一 WorldMutationContext）。
每个适配器只修改本域所有权表；返回 AdapterResult：
- domain_events：进入 event_stream_hash；
- state_changes：(entity_type, entity_id, field, old, new) 元组 ——
  由 coordinator 统一写 world_state_changes（event_ref 回填为
  TRIBULATION_IMPACT_APPLIED 事件 uid）；
- affected_entity_ids：最小因果关联。
适配器零 commit / 零 LLM / 零网络 / 零 wall-clock。

M6D.3 MINIMAL TRIBULATION EFFECT APPLICATION FIX（只改"效果如何进入权威状态"）：
- 冻结语义（runtime_design/M3A_TRIBULATION_ENGINE.md §14-§20）：各域影响是
  **相对 delta**（比例损失/扣减），且 pipeline 中 TRIBULATION 位于 domain
  engines **之后** → 权威结果必须是
  `post_engine_value + delta`，且**恰好应用一次**。
- 因此适配器**不再直接 mutate ORM 行**（旧实现直接 setattr，随后被
  coordinator 对同一步 staged 变更的 `setattr` 覆盖 —— last-write-wins，
  effect 静默丢失；M6D.3 §2 最小复现：population 11→engine 10→effect −2→
  persisted 10，应为 8）。
- 适配器只**计算并返回** state_changes；应用由 coordinator 在本步
  `_apply_changes` 之后统一执行（见 coordinator._apply_adapter_effects），
  以 `ADAPTER_FIELD_BOUNDS` 做有界裁剪。
- 不改概率、不改 T-B profile / period、不改任何域方程。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from sqlalchemy import select

from .contracts import DomainEventDraft
from .tribulation import ENGINE_ID

#: M6D.3：适配器效果的权威裁剪边界 (table, field) -> (min, max|None)
ADAPTER_FIELD_BOUNDS: dict[tuple[str, str], tuple[int, int | None]] = {
    ("population_groups", "count"): (0, None),
    ("resource_nodes", "remaining_reserve"): (0, None),
    ("resource_stocks", "quantity"): (0, None),
    ("ecology_state", "habitat_quality"): (0, 1_000_000),
    ("households", "represented_population"): (0, None),
    ("settlement_social_state", "social_stress"): (0, 1_000_000),
}


@dataclass(frozen=True)
class AdapterResult:
    domain: str
    domain_events: list[DomainEventDraft] = field(default_factory=list)
    state_changes: tuple = ()
    affected_entity_ids: tuple = ()


def _plan_risk(plan: dict, prefix: str) -> Fraction:
    num = int(plan.get(f"{prefix}_num") or 0)
    den = int(plan.get(f"{prefix}_den") or 1)
    return Fraction(num, den) if den > 0 else Fraction(0)


def _intensity_fraction(plan: dict) -> Fraction:
    return Fraction(int(plan.get("intensity", 0)), 100)


def _targets(plan: dict) -> list:
    return (plan.get("affected_settlements") or {}).get("selected", []) or []


class DemographyTribulationAdapter:
    """聚合人口影响（无个体 NPC/死亡名单；M2a 守恒与 cohort 对账保持）。"""
    domain = "DEMOGRAPHY"

    def apply(self, session, plan: dict) -> AdapterResult:
        from ...database.models_world import PopulationGroup
        risk = _plan_risk(plan, "population_risk")
        changes: list[tuple] = []
        affected: list[str] = []
        total_loss = 0
        for sref in _targets(plan):
            for g in session.execute(select(PopulationGroup).where(
                    PopulationGroup.world_id == plan["world_id"],
                    PopulationGroup.settlement_ref == sref)).scalars():
                loss = int(g.count * risk)
                if loss <= 0:
                    continue
                changes.append(("population_groups", g.id, "count", g.count,
                                max(g.count - loss, 0)))
                affected.append(f"population_groups:{g.id}")
                total_loss += loss
        events = []
        if total_loss > 0:
            events.append(DomainEventDraft(
                engine_id=ENGINE_ID, event_type="DEMOGRAPHY_IMPACT_APPLIED",
                cause={"episode_id": plan["episode_id"]},
                effect={"population_loss": total_loss,
                        "settlements": _targets(plan)}))
        return AdapterResult(domain=self.domain, domain_events=events,
                             state_changes=tuple(changes),
                             affected_entity_ids=tuple(affected))


class ResourceTribulationAdapter:
    """资源节点损毁（储量扣减；绝不免费生成新节点）。"""
    domain = "RESOURCE"

    def apply(self, session, plan: dict) -> AdapterResult:
        from ...database.models_world import ResourceNode
        risk = _plan_risk(plan, "resource_damage")
        changes: list[tuple] = []
        affected: list[str] = []
        total = 0
        for n in session.execute(select(ResourceNode).where(
                ResourceNode.world_id == plan["world_id"])).scalars():
            if not n.remaining_reserve:
                continue
            loss = int(n.remaining_reserve * risk)
            if loss <= 0:
                continue
            changes.append(("resource_nodes", n.id, "remaining_reserve",
                            n.remaining_reserve,
                            max(n.remaining_reserve - loss, 0)))
            affected.append(f"resource_nodes:{n.id}")
            total += loss
        events = []
        if total > 0:
            events.append(DomainEventDraft(
                engine_id=ENGINE_ID, event_type="RESOURCE_IMPACT_APPLIED",
                cause={"episode_id": plan["episode_id"]},
                effect={"reserve_damage": total}))
        return AdapterResult(domain=self.domain, domain_events=events,
                             state_changes=tuple(changes),
                             affected_entity_ids=tuple(affected))


class EconomyTribulationAdapter:
    """库存损失 + mitigation 成本扣减（stock-flow ledger 闭合，inventory ≥0）。"""
    domain = "ECONOMY"

    def apply(self, session, plan: dict) -> AdapterResult:
        from ...database.models_world import ResourceStock
        risk = _plan_risk(plan, "inventory_damage")
        mitigation = plan.get("mitigation_applied") or {}
        changes: list[tuple] = []
        affected: list[str] = []
        total = 0
        targets = _targets(plan)
        for r in session.execute(select(ResourceStock).where(
                ResourceStock.world_id == plan["world_id"])).scalars():
            loss = int(r.quantity * risk)
            if r.settlement_ref in targets:
                loss += int(mitigation.get("cost_minor", 0)
                            // max(len(targets), 1))
            loss = min(loss, r.quantity)
            if loss <= 0:
                continue
            changes.append(("resource_stocks", r.id, "quantity", r.quantity,
                            max(r.quantity - loss, 0)))
            affected.append(f"resource_stocks:{r.id}")
            total += loss
        events = []
        if total > 0:
            events.append(DomainEventDraft(
                engine_id=ENGINE_ID, event_type="ECONOMY_IMPACT_APPLIED",
                cause={"episode_id": plan["episode_id"]},
                effect={"inventory_loss": total}))
        return AdapterResult(domain=self.domain, domain_events=events,
                             state_changes=tuple(changes),
                             affected_entity_ids=tuple(affected))


class EcologyTribulationAdapter:
    """生态质量损失（fixed-point 有界；不直接写 Resource）。"""
    domain = "ECOLOGY"

    def apply(self, session, plan: dict) -> AdapterResult:
        from ...database.models_world import EcologyState
        pressure = int(plan.get("ecology_pressure") or 0)
        changes: list[tuple] = []
        affected: list[str] = []
        for st in session.execute(select(EcologyState).where(
                EcologyState.world_id == plan["world_id"])).scalars():
            share = _intensity_fraction(plan) * Fraction(pressure, 1_000_000)
            delta_quality = min(int(1_000_000 * share), st.habitat_quality)
            if delta_quality <= 0:
                continue
            changes.append(("ecology_state", st.id, "habitat_quality",
                            st.habitat_quality,
                            max(st.habitat_quality - delta_quality, 0)))
            affected.append(f"ecology_state:{st.id}")
        events = []
        if changes:
            events.append(DomainEventDraft(
                engine_id=ENGINE_ID, event_type="ECOLOGY_IMPACT_APPLIED",
                cause={"episode_id": plan["episode_id"]},
                effect={"quality_loss": sum(c[3] - c[4] for c in changes)}))
        return AdapterResult(domain=self.domain, domain_events=events,
                             state_changes=tuple(changes),
                             affected_entity_ids=tuple(affected))


class SocialTribulationAdapter:
    """家庭疏散 + 社会压力（有界；不改人口总数）。"""
    domain = "SOCIAL"

    def apply(self, session, plan: dict) -> AdapterResult:
        from ...database.models_world import (Household,
                                              SettlementSocialState)
        disp = _plan_risk(plan, "social_displacement")
        changes: list[tuple] = []
        affected: list[str] = []
        displaced_total = 0
        for sref in _targets(plan):
            for h in session.execute(select(Household).where(
                    Household.world_id == plan["world_id"],
                    Household.settlement_ref == sref,
                    Household.state == "ACTIVE")).scalars():
                loss = int(h.represented_population * disp)
                if loss <= 0:
                    continue
                changes.append(("households", h.id, "represented_population",
                                h.represented_population,
                                max(h.represented_population - loss, 0)))
                affected.append(f"households:{h.id}")
                displaced_total += loss
        for sref in _targets(plan):
            for st in session.execute(select(SettlementSocialState).where(
                    SettlementSocialState.world_id == plan["world_id"],
                    SettlementSocialState.settlement_ref == sref)).scalars():
                bump = min(int(300_000 * _intensity_fraction(plan)),
                           1_000_000 - st.social_stress)
                if bump <= 0:
                    continue
                changes.append(("settlement_social_state", st.id,
                                "social_stress", st.social_stress,
                                min(st.social_stress + bump, 1_000_000)))
                affected.append(f"settlement_social_state:{st.id}")
        events = []
        if displaced_total > 0:
            events.append(DomainEventDraft(
                engine_id=ENGINE_ID, event_type="SOCIAL_IMPACT_APPLIED",
                cause={"episode_id": plan["episode_id"]},
                effect={"displaced": displaced_total}))
        return AdapterResult(domain=self.domain, domain_events=events,
                             state_changes=tuple(changes),
                             affected_entity_ids=tuple(affected))


DOMAIN_ADAPTERS = {
    "DEMOGRAPHY": DemographyTribulationAdapter(),
    "RESOURCE": ResourceTribulationAdapter(),
    "ECONOMY": EconomyTribulationAdapter(),
    "ECOLOGY": EcologyTribulationAdapter(),
    "SOCIAL": SocialTribulationAdapter(),
}

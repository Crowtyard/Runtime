# -*- coding: utf-8 -*-
"""RESOURCE_ENGINE（M2b）—— Aggregate Resource Extraction。

恢复自 runtime_design/08（生产链第 1 环节 RESOURCE_NODE → EXTRACTION）：
- 只负责 Resource Node 可用性 / 储量 / 开采容量 / 开采量 / 资源侧约束。
- 不做库存/生产/消费/转移/价格（08 号市场简化模型推迟 —— M2b 只建
  PHYSICAL STOCK-FLOW ECONOMY，见 M2B 文档 NEW_PROPOSAL）。
- 不修改人口/生态/社会；跨系统只经 modifier / domain event。

M2b 冻结（NEW_PROPOSAL 已标注于 M2B_RESOURCE_ECONOMY_ENGINE.md）：
- 权威数量 = 整数 minor units（1 canonical unit = profile.quantity_scale
  minor units）；无 float 权威量（RE_INV_08/09）。
- extraction_capacity = minor units / 福地年；亚年区间经
  extraction_carry 整数进位（零浮点累计；chunk/restart 不丢）。
- 开采效率（08 号 risk 的 aggregate 化）：每 step 每节点一次离散抽样
  idx = rng.randint(0,3) → 效率 ∈ {100%, 95%, 90%, 85%}（RESOURCE
  substream；不影响其它引擎）。
- finite reserve：extracted <= remaining_reserve；结束
  reserve_end = reserve_start − extracted + explicit_external_regeneration
  （当前 regeneration = 0；生态再生属 M2c）。
- 储量耗尽 → state=EXHAUSTED（CAUSE_BASED，08 号 WS-0703）+ 事件
  RESOURCE_DEPLETED。完整八态状态机属后续里程碑。
- 引擎零 commit / 零 LLM / 零网络 / 零 wall-clock。
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from ...domain.errors import WorldRuntimeError
from .contracts import (DomainEventDraft, EngineResult, SimulationContext,
                        StateChange)

ENGINE_ID = "RESOURCE"
ENGINE_VERSION = "m2b-resource-1"
TICKS_PER_BLESSED_YEAR = 1_000_000

EV_EXTRACTED = "RESOURCE_EXTRACTED"
EV_DEPLETED = "RESOURCE_DEPLETED"

# TEST_FIXTURE_ONLY：离散开采效率表（08 号 risk 的 aggregate 化；非 Canon）
EFFICIENCY_TABLE = ((100, 100), (95, 100), (90, 100), (85, 100))


class ResourceProfileUnconfigured(WorldRuntimeError):
    code = "RESOURCE_UNCONFIGURED"


@dataclass(frozen=True)
class ResourceProfile:
    """资源 profile（M2b 仅 synthetic TEST 参数；正式资源 UNCONFIGURED）。"""
    resource_id: str
    unit: str = "unit"
    quantity_scale: int = 1_000_000
    renewability: str = "FINITE"
    extractability: str | None = "EXTRACTABLE"
    consumption_category: str | None = None
    production_usability: str | None = None
    semantic_version: str = "test-profile-1"

    def __post_init__(self) -> None:
        if self.quantity_scale <= 0:
            raise ValueError("quantity_scale 必须为正")


# TEST_FIXTURE_ONLY：synthetic resource profile（不得作为正式资源 Canon）
TEST_RESOURCE_PROFILE_ORE = ResourceProfile(
    resource_id="TEST-RESOURCE-001", unit="unit", quantity_scale=1_000_000,
    renewability="FINITE", extractability="EXTRACTABLE",
    consumption_category=None, production_usability="PRODUCTION_INPUT",
    semantic_version="test-profile-1")
TEST_RESOURCE_PROFILE_FOOD = ResourceProfile(
    resource_id="TEST-RESOURCE-002", unit="unit", quantity_scale=1_000_000,
    renewability="FINITE", extractability=None,
    consumption_category="CONSUMPTION",
    production_usability="PRODUCTION_OUTPUT",
    semantic_version="test-profile-1")

RESOURCE_PROFILES: dict[str, ResourceProfile] = {
    "TEST-RESOURCE-001": TEST_RESOURCE_PROFILE_ORE,
    "TEST-RESOURCE-002": TEST_RESOURCE_PROFILE_FOOD,
}


@dataclass(frozen=True)
class ResourceModifiers:
    """跨引擎只读输入 DTO（M2b neutral；M2c Ecology 起供给真实值）。

    - regeneration_delta：显式外部再生（minor units/福地年；M2b = 0）。
    - yield_modifier / degradation_modifier / external_disruption_modifier：
      未来生态/灾劫信号（Fraction；当前 0）。
    """
    regeneration_delta: int = 0
    yield_modifier: Fraction = Fraction(0)
    degradation_modifier: Fraction = Fraction(0)
    external_disruption_modifier: Fraction = Fraction(0)


class ResourceEngine:
    """Aggregate Resource Engine（Engine Protocol 实现；只写 resource_nodes）。"""

    engine_id: str = ENGINE_ID
    engine_version: str = ENGINE_VERSION

    def __init__(self, *, profiles: dict[str, ResourceProfile] | None = None,
                 modifiers: ResourceModifiers | None = None,
                 extra_draws: int = 0):
        """extra_draws：测试专用 —— 额外消耗 RNG 以证明 substream 独立性
        （RB34）；生产路径恒为 0。"""
        self._profiles = profiles if profiles is not None else RESOURCE_PROFILES
        self._modifiers = modifiers if modifiers is not None \
            else ResourceModifiers()
        self._extra_draws = extra_draws

    def _profile_of(self, ref: str | None) -> ResourceProfile:
        profile = self._profiles.get(ref or "")
        if profile is None:
            raise ResourceProfileUnconfigured(
                f"资源 profile {ref!r} 未配置（正式资源保持 UNCONFIGURED）",
                detail=ref)
        return profile

    def simulate(self, ctx: SimulationContext) -> EngineResult:
        staged = ctx.staged
        nodes = sorted(staged.rows("resource_nodes"),
                       key=lambda r: (r["kind"], r["region_ref"], r["id"]))
        if ctx.crash_after == "mid:RESOURCE":
            raise RuntimeError("crash: mid:RESOURCE")
        # 测试专用：额外 RNG 消耗（RB34 substream 独立性证明；生产路径恒 0）
        for _ in range(self._extra_draws):
            ctx.rng.randint(0, 1_000_000)
        if not nodes:
            return EngineResult(
                engine_id=ENGINE_ID, engine_version=ENGINE_VERSION,
                metrics={"extracted_minor": 0, "depleted": 0, "nodes": 0})

        delta_ticks = ctx.blessed_end_tick - ctx.blessed_start_tick
        proposed: list[StateChange] = []
        events: list[DomainEventDraft] = []
        extracted_total = 0
        depleted = 0

        for node in nodes:
            ref = node.get("resource_profile_ref")
            if not ref:
                raise ResourceProfileUnconfigured(
                    f"资源节点 {node['kind']!r} 无 resource_profile_ref",
                    detail=node["kind"])
            self._profile_of(ref)

            capacity = node.get("extraction_capacity") or 0
            reserve = node.get("remaining_reserve")
            if reserve is None:
                # 未定级储量 = 不可开采（正式安全；不做静默推断）
                extracted = 0
                new_carry = int(node.get("extraction_carry", 0))
                reserve_after = None
            else:
                # 离散效率抽样（RESOURCE substream）
                idx = ctx.rng.randint(0, len(EFFICIENCY_TABLE) - 1)
                eff_num, eff_den = EFFICIENCY_TABLE[idx]
                eff_capacity = capacity * eff_num // eff_den
                carry = int(node.get("extraction_carry", 0)) \
                    + eff_capacity * delta_ticks
                attempt = carry // TICKS_PER_BLESSED_YEAR
                new_carry = carry % TICKS_PER_BLESSED_YEAR
                extracted = min(attempt, reserve)
                reserve_after = reserve - extracted \
                    + self._modifiers.regeneration_delta
                if reserve_after < 0:
                    reserve_after = 0
                    extracted = reserve

            new_state = node.get("state")
            state_version = int(node.get("state_version", 0))
            if reserve_after == 0 and reserve is not None and reserve > 0:
                new_state = "EXHAUSTED"
                state_version += 1
                depleted += 1
                events.append(DomainEventDraft(
                    engine_id=ENGINE_ID, event_type=EV_DEPLETED,
                    cause={"node_kind": node["kind"],
                           "profile_ref": node.get("resource_profile_ref")},
                    effect={"reserve_minor": 0}))

            extracted_total += extracted
            proposed.append(StateChange(
                table="resource_nodes", entity_id=node["id"],
                field="remaining_reserve", old_value=None,
                new_value=reserve_after))
            proposed.append(StateChange(
                table="resource_nodes", entity_id=node["id"],
                field="extraction_carry", old_value=None,
                new_value=new_carry))
            proposed.append(StateChange(
                table="resource_nodes", entity_id=node["id"],
                field="last_extracted_minor", old_value=None,
                new_value=extracted))
            proposed.append(StateChange(
                table="resource_nodes", entity_id=node["id"],
                field="engine_version", old_value=None,
                new_value=ENGINE_VERSION))
            proposed.append(StateChange(
                table="resource_nodes", entity_id=node["id"],
                field="state_version", old_value=None,
                new_value=state_version))
            proposed.append(StateChange(
                table="resource_nodes", entity_id=node["id"],
                field="updated_blessed_tick", old_value=None,
                new_value=ctx.blessed_end_tick))
            if new_state != node.get("state"):
                proposed.append(StateChange(
                    table="resource_nodes", entity_id=node["id"],
                    field="state", old_value=None, new_value=new_state))

            if extracted > 0:
                events.append(DomainEventDraft(
                    engine_id=ENGINE_ID, event_type=EV_EXTRACTED,
                    cause={"node_kind": node["kind"],
                           "settlement_relation":
                               node.get("settlement_relation"),
                           "profile_ref": ref},
                    effect={"quantity_minor": extracted,
                            "efficiency_num": eff_num if reserve is not None
                            else 100,
                            "efficiency_den": eff_den if reserve is not None
                            else 100,
                            "reserve_after_minor": reserve_after}))

        return EngineResult(
            engine_id=ENGINE_ID, engine_version=ENGINE_VERSION,
            proposed_changes=proposed, domain_events=events,
            draw_count=len(nodes) + self._extra_draws,
            metrics={"extracted_minor": extracted_total,
                     "depleted": depleted, "nodes": len(nodes)})

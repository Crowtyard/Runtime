# -*- coding: utf-8 -*-
"""M3 PREFLIGHT —— Tribulation & Causal History 契约（非引擎实现）。

本模块只定义结构化契约（dataclass + 校验 + 纯函数），不包含：
- 正式灾劫算法 / 影响公式 / 灾劫内容库 / 正式排期；
- 任何 DB 写入 / 引擎注册。
M3a 正式实现时必须遵守这些契约（并在需要时升级语义版本）。

冻结决策（M3_PREFLIGHT）：
- Tribulation = World Metabolism（WS-0901）；九阶段生命周期（WS-0902）。
- Cross-Domain Ownership = 方案 B：TribulationEngine 生成
  TribulationImpactPlan（只写 tribulation-owned 状态）→ Coordinator 经
  Domain Impact Adapters（按域所有权声明）在同一 WorldMutationContext
  原子应用 → 事件/双层 checkpoint/哈希沿用 M2 冻结机制。
- TRIBULATION 在 M2 语义中保持 NOT_REGISTERED；M3a 才注册。
- 正式 schedule/profile = NOT_ACTIVATED / UNKNOWN；测试仅
  TEST_TRIBULATION_SCHEDULE_001 + TEST_TRIBULATION_PROFILE_001..003。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

# ---------------------------------------------------------------- 常量
TRIBULATION_CONTRACT_VERSION = "m3-preflight-contract-v1"
IMPACT_PLAN_SCHEMA_VERSION = "impact-plan-v1"
EPISODE_SCHEMA_VERSION = "episode-v1"
DECISION_SCHEMA_VERSION = "owner-decision-v1"
SCHEDULE_SCHEMA_VERSION = "test-schedule-001"

PHASE_PRECURSOR = "PRECURSOR"
PHASE_PREPARATION = "PREPARATION"
PHASE_IMPACT = "IMPACT"
PHASE_RESPONSE = "RESPONSE"
PHASE_STABILIZATION = "STABILIZATION"
PHASE_RESIDUAL_CHANGE = "RESIDUAL_CHANGE"
PHASE_RECOVERY = "RECOVERY"
PHASE_RESOURCE_SUCCESSION = "RESOURCE_SUCCESSION"
PHASE_NEW_NORMAL = "NEW_NORMAL"
LIFECYCLE_PHASES = (PHASE_PRECURSOR, PHASE_PREPARATION, PHASE_IMPACT,
                    PHASE_RESPONSE, PHASE_STABILIZATION,
                    PHASE_RESIDUAL_CHANGE, PHASE_RECOVERY,
                    PHASE_RESOURCE_SUCCESSION, PHASE_NEW_NORMAL)

TIER_REGULAR, TIER_MAJOR, TIER_CENTENNIAL = ("REGULAR", "MAJOR",
                                              "CENTENNIAL")
TIERS = (TIER_REGULAR, TIER_MAJOR, TIER_CENTENNIAL)

DAMAGE_NONE, DAMAGE_MINOR = "NONE", "MINOR"
DAMAGE_MODERATE, DAMAGE_SEVERE = "MODERATE", "SEVERE"
DAMAGE_CATASTROPHIC = "CATASTROPHIC"
DAMAGE_LEVELS = (DAMAGE_NONE, DAMAGE_MINOR, DAMAGE_MODERATE,
                 DAMAGE_SEVERE, DAMAGE_CATASTROPHIC)

DEFAULT_AUTONOMOUS_RESPONSE_POLICY = "DEFAULT_AUTONOMOUS_RESPONSE_POLICY"
RESPONSE_AUTONOMOUS = "AUTONOMOUS"
RESPONSE_OWNER_PLAN = "OWNER_PLAN"

# 小光管理协调型策略（XiaoguangResponsePolicy 白名单；无超凡手段）
XIAOGUANG_RESPONSE_ACTIONS = frozenset({
    "PERCEIVE_PRECURSOR", "ISSUE_WARNING", "SCHEDULE_RESOURCES",
    "EVACUATE_SETTLEMENTS", "PROTECT_CRITICAL_REGIONS",
    "COORDINATE_RECOVERY", "ALLOCATE_STOCKPILE",
})


class ContractValidationError(ValueError):
    """契约校验失败（结构化 plan/decision 不合法）。"""


# ---------------------------------------------------------------- 结构
@dataclass(frozen=True)
class TribulationProfile:
    """灾劫 profile（TEST_FIXTURE_ONLY；正式 profile 未创建）。"""
    profile_id: str
    tier: str
    theme: str
    intensity_min: int = 0
    intensity_max: int = 100
    population_risk: Fraction = Fraction(0)
    resource_damage: Fraction = Fraction(0)
    inventory_damage: Fraction = Fraction(0)
    production_disruption: Fraction = Fraction(0)
    ecology_pressure: int = 0
    social_displacement: Fraction = Fraction(0)
    institution_disruption: Fraction = Fraction(0)
    duration_steps: int = 1
    recovery_steps: int = 1
    source_refs: tuple[str, ...] = ()
    status: str = "TEST_FIXTURE_ONLY"
    semantic_version: str = "test-trib-profile-1"

    def __post_init__(self) -> None:
        if self.tier not in TIERS:
            raise ContractValidationError(f"tier 非法: {self.tier}")
        if not (0 <= self.intensity_min <= self.intensity_max <= 100):
            raise ContractValidationError("intensity 范围非法")
        if self.duration_steps < 1 or self.recovery_steps < 1:
            raise ContractValidationError("duration/recovery 必须 ≥1 step")
        for f in (self.population_risk, self.resource_damage,
                  self.inventory_damage, self.production_disruption,
                  self.social_displacement, self.institution_disruption):
            if not (Fraction(0) <= f <= Fraction(1)):
                raise ContractValidationError(f"risk 比例越界: {f}")


@dataclass(frozen=True)
class OwnerDecisionInput:
    """主人决策（External Approved Input；immutable once committed）。"""
    decision_id: str
    episode_id: str
    action: str            # 白名单：STRATEGY / PRIORITIZE / EVACUATE / REBUILD
    parameters: dict = field(default_factory=dict)
    deadline_tick: int = 0
    schema: str = DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.decision_id or not self.episode_id:
            raise ContractValidationError("decision 必须含 id/episode")
        if self.action not in ("STRATEGY", "PRIORITIZE", "EVACUATE",
                               "REBUILD"):
            raise ContractValidationError(f"decision action 非法: "
                                          f"{self.action}")


@dataclass(frozen=True)
class DomainEffect:
    """单域影响声明（经 Domain Impact Adapter 应用）。

    - domain：DEMOGRAPHY/RESOURCE/ECONOMY/ECOLOGY/SOCIAL；
    - kind / magnitude / target_ref：结构化有界参数（由 adapter 解释）。
    """
    domain: str
    kind: str
    magnitude: Fraction
    target_ref: str | None = None

    def __post_init__(self) -> None:
        if self.domain not in ("DEMOGRAPHY", "RESOURCE", "ECONOMY",
                               "ECOLOGY", "SOCIAL"):
            raise ContractValidationError(f"effect domain 非法: "
                                          f"{self.domain}")
        if not (Fraction(0) <= self.magnitude <= Fraction(1)):
            raise ContractValidationError(f"effect magnitude 越界: "
                                          f"{self.magnitude}")


@dataclass(frozen=True)
class TribulationImpactPlan:
    """灾劫影响计划（结构化、有界、确定性、可验证；LLM 不可篡改）。"""
    plan_id: str
    episode_id: str
    profile_id: str
    tier: str
    theme: str
    affected_regions: tuple[str, ...]
    affected_settlements: tuple[str, ...]
    intensity: int
    duration_steps: int
    recovery_steps: int
    population_risk: Fraction
    resource_damage: Fraction
    inventory_damage: Fraction
    production_disruption: Fraction
    ecology_pressure: int
    social_displacement: Fraction
    institution_disruption: Fraction
    recovery_requirements: dict = field(default_factory=dict)
    residual_changes: tuple[str, ...] = ()
    source_profile: str = ""
    domain_effects: tuple[DomainEffect, ...] = ()
    schema: str = IMPACT_PLAN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.plan_id or not self.episode_id or not self.profile_id:
            raise ContractValidationError("plan 必须含 id/episode/profile")
        if self.tier not in TIERS:
            raise ContractValidationError(f"plan tier 非法: {self.tier}")
        if not (0 <= self.intensity <= 100):
            raise ContractValidationError("plan intensity 越界")
        if self.ecology_pressure < 0:
            raise ContractValidationError("ecology_pressure 为负")
        if self.duration_steps < 1 or self.recovery_steps < 1:
            raise ContractValidationError("plan duration/recovery 非法")
        if not self.affected_regions and not self.affected_settlements:
            raise ContractValidationError("plan 缺少受影响目标")
        for f in (self.population_risk, self.resource_damage,
                  self.inventory_damage, self.production_disruption,
                  self.social_displacement, self.institution_disruption):
            if not (Fraction(0) <= f <= Fraction(1)):
                raise ContractValidationError(f"plan risk 比例越界: {f}")


@dataclass(frozen=True)
class RecoveryState:
    """灾后恢复（跨 committed step；下一个 tick 不清零）。"""
    episode_id: str
    recovery_need: Fraction
    recovery_progress: Fraction = Fraction(0)
    resource_requirement: int = 0
    population_requirement: int = 0
    ecology_requirement: int = 0
    social_requirement: int = 0
    recovery_state: str = PHASE_RECOVERY

    def __post_init__(self) -> None:
        if not (Fraction(0) <= self.recovery_progress
                <= self.recovery_need <= Fraction(1)):
            raise ContractValidationError("recovery 进度/需求越界")


# ---------------------------------------------------------------- 目标选择
def stable_target_order(entries: list[tuple[str, dict]]) -> list[str]:
    """stable ordering：语义键排序（row 物理顺序无关）。"""
    return [k for k, _ in sorted(entries, key=lambda kv: kv[0])]


def select_targets(entries: list[tuple[str, dict]], rng,
                   *, count: int = 1) -> list[str]:
    """确定性目标选择：stable ordering + seeded RNG 抽样（无放回）。"""
    ordered = stable_target_order(entries)
    if count >= len(ordered):
        return ordered
    chosen: list[str] = []
    pool = list(ordered)
    for _ in range(count):
        idx = rng.randint(0, len(pool) - 1)
        chosen.append(pool.pop(idx))
    return chosen


# ---------------------------------------------------------------- 所有权
DOMAIN_ADAPTER_OWNERSHIP = {
    "DEMOGRAPHY": frozenset({"population_groups"}),
    "RESOURCE": frozenset({"resource_nodes"}),
    "ECONOMY": frozenset({"resource_stocks", "production_state",
                          "economic_pressure_state"}),
    "ECOLOGY": frozenset({"ecology_state", "ecology_feedback_state"}),
    "SOCIAL": frozenset({"households", "lineages", "institutions",
                         "settlement_social_state",
                         "social_feedback_state"}),
}


def validate_domain_effect_targets(plan: TribulationImpactPlan) -> None:
    """契约校验：plan 的每个 domain effect 必须落在该域所有权表内
    （跨域任意表直写被拒绝 —— 方案 B 所有权约束）。"""
    for e in plan.domain_effects:
        owned = DOMAIN_ADAPTER_OWNERSHIP.get(e.domain)
        if owned is None:
            raise ContractValidationError(f"effect domain 无 adapter: "
                                          f"{e.domain}")

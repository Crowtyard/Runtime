# -*- coding: utf-8 -*-
"""ECOLOGY_ENGINE（M2c）—— Deterministic Ecological State Evolution。

恢复自 runtime_design/09（生态区域状态 + 超载→退化 + 区域退化/新生）：
- 09 号明确：ecological_regions 每区记录状态；承载力约束使用强度；
  超载 → 退化事件（CAUSE_BASED）；区域退化/新生（演替）为既有概念。
- 09 号的 food web / 异兽 / 季节波动 / 物种关系 → 不在 M2c（M2c 只做
  聚合环境质量/压力/恢复/再生反馈；CONFLICT_FOUND 见 M2C 文档）。
- 生态参数（恢复率/阈值/敏感性）旧设计未定量 → NEW_PROPOSAL 公式，
  TEST_FIXTURE_ONLY；正式生态 profile 保持 ECOLOGY_UNCONFIGURED。

M2c 冻结（NEW_PROPOSAL 标注于 M2C_ECOLOGY_ENGINE.md）：
- 权威生态状态 = 整数 fixed-point 0..ECOLOGY_STATE_SCALE(=1_000_000)；
  无 float/NaN/Inf（EC_INV_01/03/04/05）。
- 每 step 唯一顺序（进入 engine_version 语义）：
  read staged pressure → degradation → recovery → update quality →
  derive feedback → emit threshold events。
- 压力输入只经 staged 视图声明读取（人口 / 开采 / 生产 / 消耗 / 短缺）；
  不查询其他引擎私有 DB。external_pressure = neutral 占位。
- 退化 = 压力 × 敏感性 × 脆弱度（低质量更脆弱）；恢复 = 恢复率 ×
  (1−压力) × 距 ceiling 比例（恢复有 ceiling，无无限恢复）。
- 亚年区间经 degradation_carry / recovery_carry 整数进位（零浮点累计；
  chunk/restart 不丢）。
- 反馈输出 → ecology_feedback_state（committed authoritative）：
  regeneration_capacity_minor_per_year / yield_modifier /
  extraction_modifier / habitat_stress_level / environmental_stress。
  只影响 NEXT_COMMITTED_STEP（ECOLOGY_FEEDBACK_LATENCY）。
- 阈值：HEALTHY/STRESSED/DEGRADED/CRITICAL 由 profile fixed thresholds
  判定（版本化），仅跨级时发事件（事件流不爆炸）。
- 零 RNG（无随机灾害 —— 确定性模型优先，§42）；零 LLM/网络/wall-clock；
  零 commit；只写 ecology_state / ecology_feedback_state。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction

from ...domain.errors import WorldRuntimeError
from .contracts import (DomainEventDraft, EngineResult, SimulationContext,
                        StateChange)

ENGINE_ID = "ECOLOGY"
ENGINE_VERSION = "m2c-ecology-1"
TICKS_PER_BLESSED_YEAR = 1_000_000

ECOLOGY_STATE_SCALE_VERSION = "m2c-scale-1"
ECOLOGY_STATE_SCALE = 1_000_000
THRESHOLD_SCHEMA_VERSION = "m2c-threshold-v1"

EV_THRESHOLD = "ECOLOGY_THRESHOLD_CROSSED"

LEVEL_HEALTHY, LEVEL_STRESSED = "HEALTHY", "STRESSED"
LEVEL_DEGRADED, LEVEL_CRITICAL = "DEGRADED", "CRITICAL"
LEVELS = (LEVEL_HEALTHY, LEVEL_STRESSED, LEVEL_DEGRADED, LEVEL_CRITICAL)


class EcologyProfileUnconfigured(WorldRuntimeError):
    code = "ECOLOGY_UNCONFIGURED"


class EcologyZoneMissing(WorldRuntimeError):
    code = "ECOLOGY_ZONE_MISSING"


@dataclass(frozen=True)
class EcologyProfile:
    """生态 profile（M2c 仅 synthetic TEST；正式生态 UNCONFIGURED）。

    - recovery_rate：每福地年恢复比例（Fraction）。
    - recovery_ceiling：恢复上限（0..SCALE；质量不得超越）。
    - sensitivity：退化敏感性（Fraction）。
    - pressure_weights：population/extraction/production/depletion 权重
      （Fraction，和=1）。
    - pop_pressure_per_person：每 1 人的聚合人口压力（minor units/人）。
    - renewable_regen_minor_per_full_quality：满质量下可再生资源年再生量
      （minor units/福地年）。
    - thresholds：(stressed_min, degraded_min, critical_min) 固定阈值
      （quality >= stressed_min → HEALTHY，依此类推）。
    """
    profile_id: str
    recovery_rate: Fraction = Fraction(1, 25)
    recovery_ceiling: int = 900_000
    sensitivity: Fraction = Fraction(1, 100)
    pressure_weights: dict[str, Fraction] = field(default_factory=lambda: {
        "population": Fraction(2, 8), "extraction": Fraction(3, 8),
        "production": Fraction(2, 8), "depletion": Fraction(1, 8)})
    pop_pressure_per_person: int = 1_000
    renewable_regen_minor_per_full_quality: int = 220_000_000
    thresholds: tuple[int, int, int] = (800_000, 500_000, 200_000)
    semantic_version: str = "test-ecology-1"

    def __post_init__(self) -> None:
        if not (0 < self.recovery_ceiling <= ECOLOGY_STATE_SCALE):
            raise ValueError("recovery_ceiling 必须 ∈ (0, SCALE]")
        if self.sensitivity <= 0:
            raise ValueError("sensitivity 必须为正")
        if sum(self.pressure_weights.values()) != 1:
            raise ValueError("pressure_weights 必须和为 1")
        if len(self.thresholds) != 3 or \
                not (0 < self.thresholds[2] < self.thresholds[1]
                     < self.thresholds[0] < ECOLOGY_STATE_SCALE):
            raise ValueError("thresholds 必须严格递减且合法")

    def level_of(self, quality: int) -> str:
        if quality >= self.thresholds[0]:
            return LEVEL_HEALTHY
        if quality >= self.thresholds[1]:
            return LEVEL_STRESSED
        if quality >= self.thresholds[2]:
            return LEVEL_DEGRADED
        return LEVEL_CRITICAL


# TEST_FIXTURE_ONLY：synthetic ecology profile（不得作为正式生态 Canon）
TEST_ECOLOGY_PROFILE = EcologyProfile(profile_id="TEST-ECOLOGY-PROFILE-001")

ECOLOGY_PROFILES: dict[str, EcologyProfile] = {
    "TEST-ECOLOGY-PROFILE-001": TEST_ECOLOGY_PROFILE,
}


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(value, hi))


class EcologyEngine:
    """Aggregate Ecology Engine（Engine Protocol 实现）。"""

    engine_id: str = ENGINE_ID
    engine_version: str = ENGINE_VERSION

    def __init__(self, *, profiles: dict[str, EcologyProfile] | None = None,
                 extra_draws: int = 0):
        """extra_draws：测试专用 —— 额外消耗 RNG 证明 substream 独立性
        （EC26）；引擎算法本身零 RNG。"""
        self._profiles = profiles if profiles is not None else ECOLOGY_PROFILES
        self._extra_draws = extra_draws

    def _profile_of(self, ref: str | None) -> EcologyProfile:
        profile = self._profiles.get(ref or "")
        if profile is None:
            raise EcologyProfileUnconfigured(
                f"生态 profile {ref!r} 未配置（正式生态保持 UNCONFIGURED）",
                detail=ref)
        return profile

    def simulate(self, ctx: SimulationContext) -> EngineResult:
        staged = ctx.staged
        if ctx.crash_after == "mid:ECOLOGY":
            raise RuntimeError("crash: mid:ECOLOGY")
        for _ in range(self._extra_draws):
            ctx.rng.randint(0, 1_000_000)

        zones = sorted([z for z in staged.rows("ecology_zones")
                        if z.get("zone_id")],
                       key=lambda z: z["zone_id"])
        if not zones:
            return EngineResult(
                engine_id=ENGINE_ID, engine_version=ENGINE_VERSION,
                metrics={"zones": 0, "degradation_minor": 0,
                         "recovery_minor": 0, "threshold_crossings": 0,
                         "feedback_applications": 0})

        # ---- 声明输入：staged 视图（不查其他引擎私有 DB）
        population = {s["working_name"]: sum(
            int(g["count"]) for g in staged.rows("population_groups")
            if g.get("settlement_ref") == s["working_name"])
            for s in staged.rows("settlements") if s.get("working_name")}
        nodes = staged.rows("resource_nodes")
        stocks = staged.rows("resource_stocks")
        snapshot_stocks = {r["id"]: r for r in ctx.snapshot.rows(
            "resource_stocks")}
        delta_ticks = ctx.blessed_end_tick - ctx.blessed_start_tick
        years_den = TICKS_PER_BLESSED_YEAR

        state_rows = {r["zone_ref"]: r for r in staged.rows("ecology_state")}
        feedback_rows = {r["zone_ref"]: r for r in staged.rows(
            "ecology_feedback_state")}

        proposed: list[StateChange] = []
        events: list[DomainEventDraft] = []
        metrics = {"zones": len(zones), "degradation_minor": 0,
                   "recovery_minor": 0, "threshold_crossings": 0,
                   "feedback_applications": 0}

        for zone in zones:
            profile = self._profile_of(zone.get("profile_ref"))
            sref = zone.get("settlement_relation")
            zref = zone["zone_id"]
            srow = state_rows.get(zref)
            if srow is None:
                raise EcologyZoneMissing(
                    f"生态区 {zref!r} 缺 ecology_state 行", detail=zref)
            frow = feedback_rows.get(zref)
            if frow is None:
                raise EcologyZoneMissing(
                    f"生态区 {zref!r} 缺 ecology_feedback_state 行",
                    detail=zref)

            quality = int(srow["habitat_quality"])

            # ---- 1) 压力输入（每个有明确量纲，加权组合，禁止无说明相加）
            pop = population.get(sref, 0)
            p_pop = _clamp(pop * profile.pop_pressure_per_person, 0,
                           ECOLOGY_STATE_SCALE)
            p_ext = 0
            p_dep = 0
            for node in nodes:
                if node.get("region_ref") != zone.get("region_ref"):
                    continue
                extracted = int(node.get("last_extracted_minor", 0))
                capacity = int(node.get("extraction_capacity") or 0)
                reserve_after = int(node.get("remaining_reserve") or 0)
                # 开采压力 = 本步开采量 / 本步名义容量（容量 × 年数）
                denom = capacity * delta_ticks // TICKS_PER_BLESSED_YEAR
                ratio = Fraction(extracted, denom) if denom > 0 else Fraction(0)
                p_ext = max(p_ext, _clamp(
                    ratio.numerator * ECOLOGY_STATE_SCALE // ratio.denominator,
                    0, ECOLOGY_STATE_SCALE))
                depletion = Fraction(extracted,
                                     reserve_after + extracted) \
                    if reserve_after + extracted > 0 else Fraction(1)
                p_dep = max(p_dep, _clamp(
                    depletion.numerator * ECOLOGY_STATE_SCALE
                    // depletion.denominator, 0, ECOLOGY_STATE_SCALE))
            p_prod = 0
            # 生产压力 = 本步实际产出 / 该聚落登记配方的本步理论产能
            recipes = {r["recipe_id"]: r for r in staged.rows(
                "production_recipes")}
            prod_denom = 0
            for ps in staged.rows("production_state"):
                if ps.get("settlement_ref") != sref:
                    continue
                rec = recipes.get(ps.get("recipe_ref")) or {}
                cap = int(rec.get("capacity_batches_per_year") or 0)
                out_q = int(rec.get("output_qty_minor") or 0)
                prod_denom += cap * out_q * delta_ticks \
                    // TICKS_PER_BLESSED_YEAR
            produced_delta = 0
            for stock in stocks:
                if stock.get("settlement_ref") != sref:
                    continue
                before = snapshot_stocks.get(stock["id"], {})
                produced_delta += int(stock.get("cum_produced_minor", 0)) \
                    - int(before.get("cum_produced_minor", 0))
            if prod_denom > 0:
                ratio = Fraction(max(produced_delta, 0), prod_denom)
                p_prod = _clamp(
                    ratio.numerator * ECOLOGY_STATE_SCALE
                    // ratio.denominator, 0, ECOLOGY_STATE_SCALE)
            p_ext_out = 0  # external_pressure = neutral 占位（M3 才接）

            w = profile.pressure_weights
            total_f = (w["population"] * p_pop + w["extraction"] * p_ext
                       + w["production"] * p_prod
                       + w["depletion"] * p_dep)
            total_pressure = _clamp(
                total_f.numerator // total_f.denominator, 0,
                ECOLOGY_STATE_SCALE)

            # ---- 2) 退化（压力 × 敏感性 × 脆弱度；低质量更脆弱）
            # 量纲：quality units / 福地年（pressure 已为 0..SCALE 质量单位）
            vulnerability = Fraction(2 * ECOLOGY_STATE_SCALE - quality,
                                     2 * ECOLOGY_STATE_SCALE)
            deg_amount = Fraction(total_pressure, 1) \
                * profile.sensitivity * vulnerability
            carry = int(srow["degradation_carry"]) \
                + deg_amount.numerator * delta_ticks
            deg_applied = carry // (deg_amount.denominator * years_den)
            deg_carry_new = carry % (deg_amount.denominator * years_den)
            quality = max(0, quality - deg_applied)

            # ---- 3) 恢复（恢复率 × (1−压力) × 距 ceiling 距离；有上限）
            pressure_share = Fraction(total_pressure, ECOLOGY_STATE_SCALE)
            rec_amount = profile.recovery_rate \
                * (Fraction(1) - pressure_share) \
                * Fraction(max(profile.recovery_ceiling - quality, 0), 1)
            rcarry = int(srow["recovery_carry"]) \
                + rec_amount.numerator * delta_ticks
            rec_applied = rcarry // (rec_amount.denominator * years_den)
            rec_carry_new = rcarry % (rec_amount.denominator * years_den)
            quality = min(profile.recovery_ceiling, quality + rec_applied)

            # ---- 4) 派生状态与反馈
            regen_capacity = quality  # 再生能力随质量变化（派生，0..SCALE）
            stress = total_pressure
            # 可再生资源年再生量（feedback；RESOURCE 下一 step 应用）
            regen_minor_per_year = quality \
                * profile.renewable_regen_minor_per_full_quality \
                // ECOLOGY_STATE_SCALE
            # yield/extraction modifier（m2c-yield-v1）：
            #   3/4 + quality/(4×SCALE) → quality=SCALE 时 1，=0 时 3/4
            yield_f = Fraction(3, 4) + Fraction(quality, 4 * ECOLOGY_STATE_SCALE)
            env_stress = Fraction(total_pressure, ECOLOGY_STATE_SCALE)
            level = profile.level_of(quality)

            for fname, value in (
                    ("habitat_quality", quality),
                    ("regeneration_capacity", regen_capacity),
                    ("ecological_stress", stress),
                    ("population_pressure", p_pop),
                    ("extraction_pressure", p_ext),
                    ("production_pressure", p_prod),
                    ("depletion_pressure", p_dep),
                    ("external_pressure", p_ext_out),
                    ("degradation_carry", deg_carry_new),
                    ("recovery_carry", rec_carry_new),
                    ("quality_min_seen", min(
                        int(srow["quality_min_seen"]) or quality, quality)),
                    ("quality_max_seen", max(int(srow["quality_max_seen"]),
                                             quality)),
                    ("engine_version", ENGINE_VERSION),
                    ("updated_blessed_tick", ctx.blessed_end_tick)):
                proposed.append(StateChange(
                    table="ecology_state", entity_id=srow["id"],
                    field=fname, old_value=None, new_value=value))

            for fname, value in (
                    ("regeneration_capacity_minor_per_year",
                     regen_minor_per_year),
                    ("yield_modifier_num", yield_f.numerator),
                    ("yield_modifier_den", yield_f.denominator),
                    ("extraction_modifier_num", yield_f.numerator),
                    ("extraction_modifier_den", yield_f.denominator),
                    ("habitat_stress_level", level),
                    ("environmental_stress_num", env_stress.numerator),
                    ("environmental_stress_den", env_stress.denominator),
                    ("engine_version", ENGINE_VERSION),
                    ("updated_blessed_tick", ctx.blessed_end_tick)):
                proposed.append(StateChange(
                    table="ecology_feedback_state", entity_id=frow["id"],
                    field=fname, old_value=None, new_value=value))

            # ---- 5) 阈值事件（仅跨级；direction 进入 payload）
            prev_level = profile.level_of(int(srow["habitat_quality"]))
            if prev_level != level:
                metrics["threshold_crossings"] += 1
                events.append(DomainEventDraft(
                    engine_id=ENGINE_ID, event_type=EV_THRESHOLD,
                    cause={"zone_id": zref,
                           "threshold_schema": THRESHOLD_SCHEMA_VERSION},
                    effect={"from_level": prev_level, "to_level": level,
                            "quality_before_minor": int(srow[
                                "habitat_quality"]),
                            "quality_after_minor": quality,
                            "pressure_minor": stress}))

            metrics["degradation_minor"] += deg_applied
            metrics["recovery_minor"] += rec_applied
            metrics["feedback_applications"] += 1

        return EngineResult(
            engine_id=ENGINE_ID, engine_version=ENGINE_VERSION,
            proposed_changes=proposed, domain_events=events,
            draw_count=self._extra_draws, metrics=metrics)

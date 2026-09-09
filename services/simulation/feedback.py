# -*- coding: utf-8 -*-
"""ECONOMY → DEMOGRAPHY modifier adapter（M2b，NEW_PROPOSAL）。

CROSS_ENGINE_FEEDBACK_LATENCY = NEXT_COMMITTED_STEP（Preflight 冻结）：
- ECONOMY 于 step N 把经济压力写入 committed authoritative state
  （economic_pressure_state 表，随双层 checkpoint 同事务提交）。
- DEMOGRAPHY 于 step N+1 经 start-of-step snapshot 读取该 committed 状态。
- 禁止同 tick 回写重算 DEMOGRAPHY；本模块不写任何状态。

TEST_FIXTURE_ONLY：shortage → mortality 映射只对 synthetic
TEST-SPECIES-001 生效；正式种族（Human/Hairy Men/Rockmen/Mermen/
Mushroommen）保持 UNKNOWN/UNCONFIGURED —— 任何压力映射一律 0，
绝不擅自配置正式参数。
"""
from __future__ import annotations

from fractions import Fraction

from .snapshot import WorldSnapshot

# TEST_FIXTURE_ONLY 映射（synthetic；非 Canon；正式种族不适用）
PRESSURE_TO_MORTALITY = {
    "NONE": Fraction(0),
    "LOW": Fraction(1, 1000),
    "HIGH": Fraction(1, 100),
}
SYNTHETIC_SPECIES = "TEST-SPECIES-001"
STRESS_ORDER = {"NONE": 0, "LOW": 1, "HIGH": 2}

# M2c：生态压力 → 人口外部死亡率敏感性（TEST_FIXTURE_ONLY；正式种族=0）
ECOLOGY_MORTALITY_SENSITIVITY = Fraction(1, 500)
ECOLOGY_STRESS_LEVEL_ORDER = {
    "NONE": 0, "HEALTHY": 0, "STRESSED": 1, "DEGRADED": 2, "CRITICAL": 3}


def settlement_pressure_stress(snapshot: WorldSnapshot,
                               settlement_ref: str | None) -> str:
    """聚落压力等级 = 该聚落所有资源压力行的最高 stress（无行为 NONE）。"""
    worst = "NONE"
    for row in snapshot.rows("economic_pressure_state"):
        if row.get("settlement_ref") != settlement_ref:
            continue
        level = row.get("stress_level") or "NONE"
        if STRESS_ORDER.get(level, 0) > STRESS_ORDER[worst]:
            worst = level
    return worst


def demography_mortality_pressure_modifier(snapshot: WorldSnapshot, *,
                                           species: str,
                                           settlement_ref: str | None,
                                           ) -> Fraction:
    """把上一 committed step 的经济压力映射为外部死亡率修正（Fraction）。

    - species != TEST-SPECIES-001 → Fraction(0)（正式种族 UNCONFIGURED）。
    - 无压力行（M2a 世界/纯 DEMOGRAPHY 管线）→ Fraction(0)。
    """
    if species != SYNTHETIC_SPECIES:
        return Fraction(0)
    stress = settlement_pressure_stress(snapshot, settlement_ref)
    return PRESSURE_TO_MORTALITY.get(stress, Fraction(0))


def demography_ecology_pressure_modifier(snapshot: WorldSnapshot, *,
                                         species: str,
                                         settlement_ref: str | None,
                                         ) -> Fraction:
    """把上一 committed step 的生态压力（ecology_feedback_state.
    environmental_stress）映射为外部死亡率修正（M2c）。

    - species != TEST-SPECIES-001 → Fraction(0)（正式种族 UNCONFIGURED）。
    - 无生态反馈行（M2a/M2b 世界）→ Fraction(0)。
    - 映射 = environmental_stress × ECOLOGY_MORTALITY_SENSITIVITY
      （TEST_FIXTURE_ONLY）。
    """
    if species != SYNTHETIC_SPECIES:
        return Fraction(0)
    zone_ids = {z.get("zone_id") for z in snapshot.rows("ecology_zones")
                if z.get("settlement_relation") == settlement_ref}
    worst = Fraction(0)
    for fb in snapshot.rows("ecology_feedback_state"):
        if fb.get("zone_ref") not in zone_ids:
            continue
        stress = Fraction(int(fb.get("environmental_stress_num") or 0),
                          int(fb.get("environmental_stress_den") or 1))
        if stress > worst:
            worst = stress
    return worst * ECOLOGY_MORTALITY_SENSITIVITY


def demography_ecology_stress_level(snapshot: WorldSnapshot, *,
                                    settlement_ref: str | None) -> int:
    """聚落关联生态区的最高 habitat_stress_level（int 0..3；metrics 用）。"""
    zone_ids = {z.get("zone_id") for z in snapshot.rows("ecology_zones")
                if z.get("settlement_relation") == settlement_ref}
    worst = 0
    for fb in snapshot.rows("ecology_feedback_state"):
        if fb.get("zone_ref") not in zone_ids:
            continue
        level = fb.get("habitat_stress_level") or "NONE"
        worst = max(worst, ECOLOGY_STRESS_LEVEL_ORDER.get(level, 0))
    return worst


# M2d：社会反馈 → 人口学修正（TEST_FIXTURE_ONLY；无反馈行=中性 1/1）
_SOCIAL_MODIFIER_CLAMP = (Fraction(1, 2), Fraction(2, 1))


def _social_feedback_of(snapshot: WorldSnapshot,
                        settlement_ref: str | None) -> dict:
    for row in snapshot.rows("social_feedback_state"):
        if row.get("settlement_ref") == settlement_ref:
            return row
    return {}


def demography_social_migration_modifier(snapshot: WorldSnapshot, *,
                                         settlement_ref: str | None) -> Fraction:
    """社会迁移修正（migration_modifier，clamp [1/2, 2]）；无反馈行=1。"""
    row = _social_feedback_of(snapshot, settlement_ref)
    if not row:
        return Fraction(1)
    f = Fraction(int(row.get("migration_modifier_num") or 1),
                 int(row.get("migration_modifier_den") or 1))
    return max(_SOCIAL_MODIFIER_CLAMP[0], min(f, _SOCIAL_MODIFIER_CLAMP[1]))


def demography_social_fertility_modifier(snapshot: WorldSnapshot, *,
                                         settlement_ref: str | None) -> Fraction:
    """社会生育情境修正（fertility_context，clamp [1/2, 2]）；无反馈行=1。"""
    row = _social_feedback_of(snapshot, settlement_ref)
    if not row:
        return Fraction(1)
    f = Fraction(int(row.get("fertility_context_num") or 1),
                 int(row.get("fertility_context_den") or 1))
    return max(_SOCIAL_MODIFIER_CLAMP[0], min(f, _SOCIAL_MODIFIER_CLAMP[1]))

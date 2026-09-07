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

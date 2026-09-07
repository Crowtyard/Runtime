# -*- coding: utf-8 -*-
"""mini_world_v1 —— 合成确定性测试夹具（M2 Preflight）。

TEST_FIXTURE_ONLY：全部数值只具测试意义，不读取/不复制正式 Seed Package，
不冒充 Local Canon，绝不写入正式 DB。

定义（恢复自 18_testing_strategy + roadmap M2 验收）：
  2 settlements（1 MAIN + 1 SATELLITE）/ 1 species / 1 resource node。
M2a：population_groups = cohort 行（06 号设计；TEST_SPECIES_001 的 40 个
1 福地年 bucket，15..39 均匀分布；A=300、B=100）。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ...database.models_world import (EcologicalRegion, PopulationGroup,
                                     ResourceNode, Settlement)
from .population import (DEMOGRAPHY_PROFILE_REF, ENGINE_VERSION,
                         TEST_INITIAL_BUCKETS, TEST_INITIAL_COUNT_A_PER_BUCKET,
                         TEST_INITIAL_COUNT_B_PER_BUCKET,
                         TEST_SPECIES_PROFILE)

MINI_WORLD_ID = "MINIWORLD-TEST-001"
MINI_SPECIES = "TEST-SPECIES-001"
TEST_COHORT_BUCKETS = TEST_SPECIES_PROFILE.cohort_buckets

MINI_SETTLEMENTS = [
    {"working_name": "TEST-MAIN-A", "settlement_type": "MAIN",
     "region_ref": "TEST-REGION-1", "state": "STABLE",
     "population_capacity": 500},
    {"working_name": "TEST-SATELLITE-B", "settlement_type": "SATELLITE",
     "region_ref": "TEST-REGION-2", "state": "STABLE",
     "population_capacity": 200},
]

MINI_RESOURCE_NODE = {
    "kind": "TEST-ORE-001", "region_ref": "TEST-REGION-1",
    "state": "STABLE"}

MINI_ECOLOGY = {
    "terrain": "TEST-PLAINS", "climate": "TEST-TEMPERATE",
    "water": "TEST-RIVER", "danger_level": "LOW",
    "carrying_capacity": 1000, "state": "STABLE"}


def seed_mini_world(session: Session) -> None:
    """向当前（测试）库播种 mini_world 实体（幂等）。"""
    from sqlalchemy import select

    existing = session.execute(
        select(Settlement).where(Settlement.world_id == MINI_WORLD_ID)
    ).scalars().first()
    if existing is not None:
        return

    for s in MINI_SETTLEMENTS:
        session.add(Settlement(world_id=MINI_WORLD_ID, **s))
    # cohort 行 = population_groups（06 号设计）；必须覆盖全部 bucket 0..N-1
    # （空 bucket 也占行 —— 出生落入 bucket 0，缺行会丢失人口，违反 P_INV_12）
    for b in range(TEST_COHORT_BUCKETS):
        session.add(PopulationGroup(
            world_id=MINI_WORLD_ID, species=MINI_SPECIES,
            settlement_ref="TEST-MAIN-A", age_cohort=str(b),
            occupation_group="MIXED",
            count=TEST_INITIAL_COUNT_A_PER_BUCKET if b in TEST_INITIAL_BUCKETS
            else 0,
            age_advance_carry_ticks=0,
            species_profile_ref=DEMOGRAPHY_PROFILE_REF,
            demography_version=ENGINE_VERSION))
        session.add(PopulationGroup(
            world_id=MINI_WORLD_ID, species=MINI_SPECIES,
            settlement_ref="TEST-SATELLITE-B", age_cohort=str(b),
            occupation_group="MIXED",
            count=TEST_INITIAL_COUNT_B_PER_BUCKET if b in TEST_INITIAL_BUCKETS
            else 0,
            age_advance_carry_ticks=0,
            species_profile_ref=DEMOGRAPHY_PROFILE_REF,
            demography_version=ENGINE_VERSION))
    session.add(ResourceNode(world_id=MINI_WORLD_ID, **MINI_RESOURCE_NODE))
    session.add(EcologicalRegion(world_id=MINI_WORLD_ID, **MINI_ECOLOGY))
    session.flush()

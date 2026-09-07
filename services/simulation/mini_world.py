# -*- coding: utf-8 -*-
"""mini_world_v1 —— 合成确定性测试夹具（M2 Preflight）。

TEST_FIXTURE_ONLY：全部数值只具测试意义，不读取/不复制正式 Seed Package，
不冒充 Local Canon，绝不写入正式 DB。

定义（恢复自 18_testing_strategy + roadmap M2 验收）：
  2 settlements（1 MAIN + 1 SATELLITE）/ 1 species / 1 resource node。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ...database.models_world import (EcologicalRegion, PopulationGroup,
                                     ResourceNode, Settlement)

MINI_WORLD_ID = "MINIWORLD-TEST-001"
MINI_SPECIES = "TEST-SPECIES-001"

MINI_SETTLEMENTS = [
    {"working_name": "TEST-MAIN-A", "settlement_type": "MAIN",
     "region_ref": "TEST-REGION-1", "state": "STABLE",
     "population_capacity": 500},
    {"working_name": "TEST-SATELLITE-B", "settlement_type": "SATELLITE",
     "region_ref": "TEST-REGION-2", "state": "STABLE",
     "population_capacity": 200},
]

MINI_GROUPS = [
    {"settlement_ref": "TEST-MAIN-A", "age_cohort": "ALL",
     "occupation_group": "MIXED", "count": 300},
    {"settlement_ref": "TEST-SATELLITE-B", "age_cohort": "ALL",
     "occupation_group": "MIXED", "count": 100},
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
    for g in MINI_GROUPS:
        session.add(PopulationGroup(world_id=MINI_WORLD_ID,
                                    species=MINI_SPECIES, **g))
    session.add(ResourceNode(world_id=MINI_WORLD_ID, **MINI_RESOURCE_NODE))
    session.add(EcologicalRegion(world_id=MINI_WORLD_ID, **MINI_ECOLOGY))
    session.flush()

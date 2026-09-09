# -*- coding: utf-8 -*-
"""mini_world_v1 —— 合成确定性测试夹具（M2 Preflight；M2b integrated）。

TEST_FIXTURE_ONLY：全部数值只具测试意义，不读取/不复制正式 Seed Package，
不冒充 Local Canon，绝不写入正式 DB。

定义（恢复自 18_testing_strategy + roadmap M2 验收）：
  2 settlements（1 MAIN + 1 SATELLITE）/ 1 species / 1 resource node。
M2a：population_groups = cohort 行（06 号设计；TEST_SPECIES_001 的 40 个
1 福地年 bucket，15..39 均匀分布；A=300、B=100）。
M2b integrated：1 个 TEST-ORE 节点（finite reserve，归属 A 开采）+
2 个 TEST resource profile（ORE/FOOD）+ 库存行 + 1 条合成配方
（2 ORE → 1 FOOD，容量 450 batch/年，loss 1/100）+ 生产进位行 +
经济压力行（2 聚落 × 2 资源）。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ...database.models_world import (EcologicalRegion, EcologyFeedbackState,
                                     EcologyState, EcologyZone,
                                     EconomicPressureState, Household,
                                     Institution, Lineage, PopulationGroup,
                                     ProductionRecipe, ProductionState,
                                     ResourceNode, ResourceProfile,
                                     ResourceStock, Settlement,
                                     SettlementSocialState,
                                     SocialFeedbackState)
from .ecology import (ECOLOGY_STATE_SCALE, ENGINE_VERSION
                      as ECOLOGY_ENGINE_VERSION)
from .ecology import TEST_ECOLOGY_PROFILE
from .economy import ENGINE_VERSION as ECONOMY_ENGINE_VERSION
from .population import (DEMOGRAPHY_PROFILE_REF, ENGINE_VERSION,
                         TEST_INITIAL_BUCKETS, TEST_INITIAL_COUNT_A_PER_BUCKET,
                         TEST_INITIAL_COUNT_B_PER_BUCKET,
                         TEST_SPECIES_PROFILE)
from .resource import ENGINE_VERSION as RESOURCE_ENGINE_VERSION
from .resource import RESOURCE_PROFILES
from .social import (ENGINE_VERSION as SOCIAL_ENGINE_VERSION)
from .social import (FORMATION_VERSION, SOCIAL_STATE_SCALE,
                     TEST_SOCIAL_PROFILE)

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

# ---- M2b integrated fixture（TEST_FIXTURE_ONLY；整数 minor units）----
# 储量：400,000 canonical units（120 年开采 ~1000/年 绰绰有余，finite）
MINI_ORE_RESERVE_UNITS = 400_000
# 开采容量：1,200 canonical units / 福地年
MINI_ORE_CAPACITY_UNITS = 1_200
# 初始库存（canonical units）：A ore=1000、food=100；B ore=0、food=0
# （A 产能 360 > A 需求 ~350 但有 100 缓冲 → A 每年少量盈余转给 B；
#   B 零库存零生产 → 持续短缺 → 基线覆盖 transfer + shortage + feedback）
MINI_STOCK_UNITS = {
    ("TEST-MAIN-A", "TEST-RESOURCE-001"): 1_000,
    ("TEST-MAIN-A", "TEST-RESOURCE-002"): 100,
    ("TEST-SATELLITE-B", "TEST-RESOURCE-001"): 0,
    ("TEST-SATELLITE-B", "TEST-RESOURCE-002"): 0,
}
# 合成配方：2 ORE → 1 FOOD；容量 360 batch/年；loss 1/100；无劳动力约束
MINI_RECIPE = {
    "recipe_id": "TEST-RECIPE-ORE-FOOD-001",
    "input_resource_ref": "TEST-RESOURCE-001", "input_qty_minor": 2_000_000,
    "output_resource_ref": "TEST-RESOURCE-002", "output_qty_minor": 1_000_000,
    "capacity_batches_per_year": 360, "labor_per_batch": 0,
    "loss_num": 1, "loss_den": 100, "semantic_version": "test-recipe-1",
}

MINI_SCALE = RESOURCE_PROFILES["TEST-RESOURCE-001"].quantity_scale

# ---- M2c integrated fixture（TEST_FIXTURE_ONLY；with_ecology=True 时追加）----
# 生态区：每聚落 1 个；初始质量 900,000/1,000,000（=profile ceiling）
MINI_ECOLOGY_ZONES = [
    {"zone_id": "TEST-ZONE-A", "region_ref": "TEST-REGION-1",
     "settlement_relation": "TEST-MAIN-A",
     "profile_ref": TEST_ECOLOGY_PROFILE.profile_id},
    {"zone_id": "TEST-ZONE-B", "region_ref": "TEST-REGION-2",
     "settlement_relation": "TEST-SATELLITE-B",
     "profile_ref": TEST_ECOLOGY_PROFILE.profile_id},
]
MINI_ECOLOGY_INITIAL_QUALITY = TEST_ECOLOGY_PROFILE.recovery_ceiling
# 可再生节点：TEST-TIMBER（区域 2，B 开采）；储量 5,000 units，容量 200/年，
# ceiling = 5,000 units（再生上限，禁止无限增长）
MINI_TIMBER_NODE = {
    "kind": "TEST-TIMBER-001", "region_ref": "TEST-REGION-2",
    "state": "STABLE",
    "resource_profile_ref": "TEST-RESOURCE-003",
    "settlement_relation": "TEST-SATELLITE-B",
    "remaining_reserve": 5_000 * MINI_SCALE,
    "extraction_capacity": 200 * MINI_SCALE,
    "extraction_carry": 0, "last_extracted_minor": 0,
    "engine_version": RESOURCE_ENGINE_VERSION, "state_version": 0,
    "reserve_ceiling_minor": 5_000 * MINI_SCALE, "regeneration_carry": 0,
}
MINI_TIMBER_STOCK_UNITS = {("TEST-MAIN-A", "TEST-RESOURCE-003"): 0,
                           ("TEST-SATELLITE-B", "TEST-RESOURCE-003"): 100}

# ---- M2d integrated fixture（TEST_FIXTURE_ONLY；with_social=True 时追加）----
# 初始聚合家庭：A 60 × 5 = 300；B 20 × 5 = 100（generation 1）
MINI_HOUSEHOLD_SIZE = TEST_SOCIAL_PROFILE.formation_size
MINI_LINEAGE_B = "TEST-LINEAGE-B-001"  # B 的 synthetic lineage（3 户，测灭绝）
MINI_INSTITUTIONS = [
    {"kind": "COMMUNITY_BODY", "settlement_ref": "TEST-MAIN-A",
     "state": "ACTIVE", "institution_id": "TEST-INST-A-001"},
    {"kind": "COMMUNITY_BODY", "settlement_ref": "TEST-SATELLITE-B",
     "state": "ACTIVE", "institution_id": "TEST-INST-B-001"},
]


def seed_mini_world(session: Session, *, with_ecology: bool = False,
                    with_social: bool = False,
                    world_id: str = MINI_WORLD_ID) -> None:
    """向当前（测试）库播种 mini_world 实体（幂等）。

    with_ecology=False：M2a/M2b 精确夹具（不新增任何行 —— 基线复现依赖）。
    with_ecology=True：M2c integrated 夹具（追加生态区/生态状态/生态反馈 +
    可再生 TEST-TIMBER 节点与库存）。
    with_social=True：M2d integrated 夹具（追加聚合家庭/lineage/institution/
    聚落社会状态/社会反馈；要求 with_ecology=True）。
    world_id：默认 MINI_WORLD_ID；long-horizon 压力测试用独立合成世界 ID。"""
    from sqlalchemy import select

    wid = world_id
    existing = session.execute(
        select(Settlement).where(Settlement.world_id == wid)
    ).scalars().first()
    if existing is not None:
        return

    for s in MINI_SETTLEMENTS:
        session.add(Settlement(world_id=wid, **s))
    # cohort 行 = population_groups（06 号设计）；必须覆盖全部 bucket 0..N-1
    # （空 bucket 也占行 —— 出生落入 bucket 0，缺行会丢失人口，违反 P_INV_12）
    for b in range(TEST_COHORT_BUCKETS):
        session.add(PopulationGroup(
            world_id=wid, species=MINI_SPECIES,
            settlement_ref="TEST-MAIN-A", age_cohort=str(b),
            occupation_group="MIXED",
            count=TEST_INITIAL_COUNT_A_PER_BUCKET if b in TEST_INITIAL_BUCKETS
            else 0,
            age_advance_carry_ticks=0,
            species_profile_ref=DEMOGRAPHY_PROFILE_REF,
            demography_version=ENGINE_VERSION))
        session.add(PopulationGroup(
            world_id=wid, species=MINI_SPECIES,
            settlement_ref="TEST-SATELLITE-B", age_cohort=str(b),
            occupation_group="MIXED",
            count=TEST_INITIAL_COUNT_B_PER_BUCKET if b in TEST_INITIAL_BUCKETS
            else 0,
            age_advance_carry_ticks=0,
            species_profile_ref=DEMOGRAPHY_PROFILE_REF,
            demography_version=ENGINE_VERSION))
    session.add(ResourceNode(
        world_id=wid, **MINI_RESOURCE_NODE,
        resource_profile_ref="TEST-RESOURCE-001",
        settlement_relation="TEST-MAIN-A",
        remaining_reserve=MINI_ORE_RESERVE_UNITS * MINI_SCALE,
        extraction_capacity=MINI_ORE_CAPACITY_UNITS * MINI_SCALE,
        extraction_carry=0, last_extracted_minor=0,
        engine_version=RESOURCE_ENGINE_VERSION, state_version=0))
    session.add(EcologicalRegion(world_id=wid, **MINI_ECOLOGY))

    # M2b：resource profiles / stocks / recipe / production state / pressure
    # （with_ecology=False 时只注册 M2b 的两个资源 —— 保持 M2b 夹具逐字节）
    profile_refs = (sorted(RESOURCE_PROFILES) if with_ecology
                    else ["TEST-RESOURCE-001", "TEST-RESOURCE-002"])
    for rid in profile_refs:
        profile = RESOURCE_PROFILES[rid]
        session.add(ResourceProfile(
            world_id=wid, resource_id=profile.resource_id,
            unit=profile.unit, quantity_scale=profile.quantity_scale,
            renewability=profile.renewability,
            extractability=profile.extractability,
            consumption_category=profile.consumption_category,
            production_usability=profile.production_usability,
            semantic_version=profile.semantic_version))
    for (sref, ref), units in sorted(MINI_STOCK_UNITS.items()):
        session.add(ResourceStock(
            world_id=wid, settlement_ref=sref,
            resource_profile_ref=ref, quantity=units * MINI_SCALE,
            consumption_carry=0, engine_version=ECONOMY_ENGINE_VERSION))
    session.add(ProductionRecipe(world_id=wid, **MINI_RECIPE))
    for sref in ("TEST-MAIN-A", "TEST-SATELLITE-B"):
        session.add(ProductionState(
            world_id=wid, settlement_ref=sref,
            recipe_ref=MINI_RECIPE["recipe_id"], production_carry=0,
            engine_version=ECONOMY_ENGINE_VERSION))
        for ref in profile_refs:
            session.add(EconomicPressureState(
                world_id=wid, settlement_ref=sref,
                resource_profile_ref=ref, demand_minor=0, fulfilled_minor=0,
                unmet_minor=0, shortage_ratio_num=0, shortage_ratio_den=1,
                sustained_shortage_steps=0, stress_level="NONE",
                engine_version=ECONOMY_ENGINE_VERSION))

    # M2c：生态区 + 生态状态 + 生态反馈 + 可再生 TEST-TIMBER 节点与库存
    if with_ecology:
        for z in MINI_ECOLOGY_ZONES:
            session.add(EcologyZone(
                world_id=wid, zone_id=z["zone_id"],
                region_ref=z["region_ref"],
                settlement_relation=z["settlement_relation"],
                profile_ref=z["profile_ref"],
                semantic_version=TEST_ECOLOGY_PROFILE.semantic_version))
            session.add(EcologyState(
                world_id=wid, zone_ref=z["zone_id"],
                habitat_quality=MINI_ECOLOGY_INITIAL_QUALITY,
                regeneration_capacity=MINI_ECOLOGY_INITIAL_QUALITY,
                ecological_stress=0, population_pressure=0,
                extraction_pressure=0, production_pressure=0,
                depletion_pressure=0, external_pressure=0,
                degradation_carry=0, recovery_carry=0,
                quality_min_seen=MINI_ECOLOGY_INITIAL_QUALITY,
                quality_max_seen=MINI_ECOLOGY_INITIAL_QUALITY,
                engine_version=ECOLOGY_ENGINE_VERSION))
            session.add(EcologyFeedbackState(
                world_id=wid, zone_ref=z["zone_id"],
                regeneration_capacity_minor_per_year=0,
                yield_modifier_num=1, yield_modifier_den=1,
                extraction_modifier_num=1, extraction_modifier_den=1,
                habitat_stress_level="HEALTHY",
                environmental_stress_num=0, environmental_stress_den=1,
                engine_version=ECOLOGY_ENGINE_VERSION))
        session.add(ResourceNode(
            world_id=wid, **MINI_TIMBER_NODE))
        for (sref, ref), units in sorted(MINI_TIMBER_STOCK_UNITS.items()):
            session.add(ResourceStock(
                world_id=wid, settlement_ref=sref,
                resource_profile_ref=ref, quantity=units * MINI_SCALE,
                consumption_carry=0, engine_version=ECONOMY_ENGINE_VERSION))

    # M2d：聚合家庭 + synthetic lineage + institution + 社会状态/反馈
    if with_social:
        hh_seq = {"TEST-MAIN-A": 0, "TEST-SATELLITE-B": 0}
        for sref, count in (("TEST-MAIN-A", 300), ("TEST-SATELLITE-B", 100)):
            n = count // MINI_HOUSEHOLD_SIZE
            for i in range(n):
                hh_seq[sref] += 1
                lineage_ref = None
                if sref == "TEST-SATELLITE-B" and i < 3:
                    lineage_ref = MINI_LINEAGE_B
                session.add(Household(
                    world_id=wid,
                    household_id=f"TEST-HH-{sref[-1]}-{hh_seq[sref]:03d}",
                    settlement_ref=sref, species=MINI_SPECIES,
                    represented_population=MINI_HOUSEHOLD_SIZE,
                    generation=1, lineage_ref=lineage_ref,
                    anchor_group_ref="20", state="ACTIVE",
                    formation_version=FORMATION_VERSION,
                    updated_blessed_tick=0))
        session.add(Lineage(
            world_id=wid, lineage_type="FAMILY",
            lineage_id=MINI_LINEAGE_B, origin_settlement="TEST-SATELLITE-B",
            represented_population=3 * MINI_HOUSEHOLD_SIZE,
            household_count=3, generation=1, status="ACTIVE",
            founded_tick=0, semantic_version=TEST_SOCIAL_PROFILE.semantic_version,
            updated_blessed_tick=0))
        for spec in MINI_INSTITUTIONS:
            session.add(Institution(
                world_id=wid, kind=spec["kind"],
                settlement_ref=spec["settlement_ref"],
                state=spec["state"],
                institution_id=spec["institution_id"], founded_tick=0,
                profile_ref=TEST_SOCIAL_PROFILE.profile_id,
                updated_blessed_tick=0))
        for sref in ("TEST-MAIN-A", "TEST-SATELLITE-B"):
            session.add(SettlementSocialState(
                world_id=wid, settlement_ref=sref,
                social_stress=0, social_cohesion=SOCIAL_STATE_SCALE,
                household_stability=SOCIAL_STATE_SCALE,
                mobility_pressure=0, unallocated_population=0,
                stress_min_seen=0, stress_max_seen=0,
                engine_version=SOCIAL_ENGINE_VERSION, updated_blessed_tick=0))
            session.add(SocialFeedbackState(
                world_id=wid, settlement_ref=sref,
                migration_modifier_num=1, migration_modifier_den=1,
                fertility_context_num=1, fertility_context_den=1,
                social_support_num=1, social_support_den=1,
                social_stress_num=0, social_stress_den=1,
                engine_version=SOCIAL_ENGINE_VERSION, updated_blessed_tick=0))
    session.flush()

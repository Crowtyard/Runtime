"""业务实体表模型（M0 建表；实体字段按 PHASE_1_9 03 号核心列，扩展随 M1 引擎）。
当前库必须保持 EMPTY_WORLD：本文件只定义结构，不产生任何行。

时间列约定：blessed 时间坐标 = CANONICAL_BLESSED_TICK（整数 µy，*_tick 列，BigInteger）；
现实时间 = aware UTC（UtcDateTime）。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (JSON, BigInteger, Boolean, Float, ForeignKey, Integer,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, UtcDateTime, utcnow


class Settlement(Base):
    """聚落（WS-0406：4 主 + 6~10 卫星 为 SEED 设计，未激活）。"""
    __tablename__ = "settlements"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    settlement_type: Mapped[str] = mapped_column(String(16), nullable=False)  # MAIN/SATELLITE/NODE
    region_ref: Mapped[str | None] = mapped_column(String(64))
    working_name: Mapped[str | None] = mapped_column(String(128))  # 无批准地名=WORKING_NAME
    state: Mapped[str | None] = mapped_column(String(16))
    population_capacity: Mapped[int | None] = mapped_column(Integer)
    meta: Mapped[dict | None] = mapped_column(JSON)


class PopulationGroup(Base):
    """宏观人口群体（12,000 人按群体聚合，不做个体 Agent）。"""
    __tablename__ = "population_groups"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    species: Mapped[str] = mapped_column(String(32), nullable=False)
    settlement_ref: Mapped[str | None] = mapped_column(String(64))
    age_cohort: Mapped[str | None] = mapped_column(String(16))
    occupation_group: Mapped[str | None] = mapped_column(String(64))
    household_stats: Mapped[dict | None] = mapped_column(JSON)
    count: Mapped[int] = mapped_column(Integer, default=0)
    updated_blessed_tick: Mapped[int | None] = mapped_column(BigInteger)
    # M2a Population Group Engine（cohort 即 population_groups 行，06 号设计）：
    age_advance_carry_ticks: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0")  # 亚年区间进位（整数）
    species_profile_ref: Mapped[str | None] = mapped_column(String(64))  # 人口学 profile 引用（NULL=UNCONFIGURED）
    demography_version: Mapped[str | None] = mapped_column(String(32))  # 人口引擎语义版本


class Person(Base):
    """Persistent Person（仅锚点；llm_eligible 标记）。"""
    __tablename__ = "persons"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(128))
    species: Mapped[str | None] = mapped_column(String(32))
    birth_blessed_tick: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(12), default="alive")
    residence_ref: Mapped[str | None] = mapped_column(String(64))
    occupation_ref: Mapped[str | None] = mapped_column(String(64))
    lineage_ref: Mapped[str | None] = mapped_column(String(64))
    traits: Mapped[dict | None] = mapped_column(JSON)
    relation_tags: Mapped[dict | None] = mapped_column(JSON)
    llm_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    demise: Mapped[dict | None] = mapped_column(JSON)


class Lineage(Base):
    """家庭/血缘/师徒等长期关系（PERSISTENT_LINEAGE）。"""
    __tablename__ = "lineages"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    lineage_type: Mapped[str] = mapped_column(String(16), nullable=False)  # FAMILY/APPRENTICE/CLAN
    head_person_ref: Mapped[str | None] = mapped_column(String(64))
    member_ids: Mapped[list | None] = mapped_column(JSON)
    history_ref: Mapped[str | None] = mapped_column(String(64))


class Institution(Base):
    """工坊/市场/药园/运输组织等长期机构（PERSISTENT_INSTITUTION）。"""
    __tablename__ = "institutions"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    settlement_ref: Mapped[str | None] = mapped_column(String(64))
    owner_ref: Mapped[str | None] = mapped_column(String(64))
    state: Mapped[str | None] = mapped_column(String(16))
    capacity: Mapped[int | None] = mapped_column(Integer)
    members: Mapped[list | None] = mapped_column(JSON)


class Industry(Base):
    __tablename__ = "industries"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    node_ref: Mapped[str | None] = mapped_column(String(64))
    input_output: Mapped[dict | None] = mapped_column(JSON)
    labor: Mapped[int | None] = mapped_column(Integer)
    capacity: Mapped[dict | None] = mapped_column(JSON)
    seasonality: Mapped[dict | None] = mapped_column(JSON)
    risk: Mapped[float | None] = mapped_column(Float)
    state: Mapped[str | None] = mapped_column(String(16))


class ResourceNode(Base):
    """资源节点（WS-0703 八态；M2b 只关心可用性/储量/开采）。"""
    __tablename__ = "resource_nodes"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    region_ref: Mapped[str | None] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16), default="STABLE")
    yield_model: Mapped[dict | None] = mapped_column(JSON)
    history_ref: Mapped[str | None] = mapped_column(String(64))
    # ---- M2b Resource Engine（整数 minor units；无 float 权威量） ----
    resource_profile_ref: Mapped[str | None] = mapped_column(String(64))  # 资源 profile 引用（NULL=UNCONFIGURED）
    settlement_relation: Mapped[str | None] = mapped_column(String(64))  # 开采归属聚落
    remaining_reserve: Mapped[int | None] = mapped_column(BigInteger)  # 剩余储量（minor units；NULL=未定级）
    extraction_capacity: Mapped[int | None] = mapped_column(BigInteger)  # 名义开采容量（minor units/福地年）
    extraction_carry: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0")  # 亚年开采进位（整数）
    last_extracted_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0")  # 本步开采量（staged feed-forward 给 ECONOMY）
    engine_version: Mapped[str | None] = mapped_column(String(32))
    state_version: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                               default=0, server_default="0")
    updated_blessed_tick: Mapped[int | None] = mapped_column(BigInteger)
    # ---- M2c Ecology 反馈（Resource 侧持久化状态）----
    reserve_ceiling_minor: Mapped[int | None] = mapped_column(
        BigInteger)  # 可再生资源储量上限（NULL=非可再生/无上限）
    regeneration_carry: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0")  # 亚年再生进位（整数）


class ResourceProfile(Base):
    """资源 profile（M2b：TEST_FIXTURE_ONLY 参数；正式资源保持 UNCONFIGURED）。

    权威数量 = 整数 minor units；1 canonical unit = quantity_scale minor units。
    """
    __tablename__ = "resource_profiles"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    resource_id: Mapped[str] = mapped_column(String(32), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default="unit")
    quantity_scale: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                                default=1_000_000)
    renewability: Mapped[str] = mapped_column(String(16), nullable=False,
                                              default="FINITE")
    extractability: Mapped[str | None] = mapped_column(String(16))
    consumption_category: Mapped[str | None] = mapped_column(String(32))  # CONSUMPTION/NULL
    production_usability: Mapped[str | None] = mapped_column(String(32))  # INPUT/OUTPUT/NULL
    semantic_version: Mapped[str | None] = mapped_column(String(32))

    __table_args__ = (UniqueConstraint("world_id", "resource_id",
                                       name="uq_resource_profiles_world_resource"),)


class ResourceStock(Base):
    """聚落库存（integer minor units；含 stock-flow ledger 累计计数器）。

    RE_INV_14：end = start + extracted + produced + imported
                     − input − consumed − exported − lost（全整数可对账）。
    """
    __tablename__ = "resource_stocks"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    settlement_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_profile_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                          default=0, server_default="0")
    consumption_carry: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0")  # 亚年需求进位
    cum_extracted_minor: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                                     default=0, server_default="0")
    cum_produced_minor: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                                    default=0, server_default="0")
    cum_input_minor: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                                 default=0, server_default="0")
    cum_imported_minor: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                                    default=0, server_default="0")
    cum_exported_minor: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                                    default=0, server_default="0")
    cum_consumed_minor: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                                    default=0, server_default="0")
    cum_lost_minor: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                                default=0, server_default="0")
    engine_version: Mapped[str | None] = mapped_column(String(32))
    updated_blessed_tick: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (UniqueConstraint("world_id", "settlement_ref",
                                       "resource_profile_ref",
                                       name="uq_resource_stocks_world_settlement_resource"),)


class ProductionRecipe(Base):
    """Aggregate Production Recipe（input → output 显式守恒；loss 显式声明）。"""
    __tablename__ = "production_recipes"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    recipe_id: Mapped[str] = mapped_column(String(32), nullable=False)
    input_resource_ref: Mapped[str | None] = mapped_column(String(64))
    input_qty_minor: Mapped[int | None] = mapped_column(BigInteger)  # 每 batch 输入
    output_resource_ref: Mapped[str | None] = mapped_column(String(64))
    output_qty_minor: Mapped[int | None] = mapped_column(BigInteger)  # 每 batch 产出
    capacity_batches_per_year: Mapped[int | None] = mapped_column(BigInteger)  # NULL=不设上限
    labor_per_batch: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                                 default=0, server_default="0")  # 0=无劳动力约束
    loss_num: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                          default=0, server_default="0")
    loss_den: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                          default=1, server_default="1")
    semantic_version: Mapped[str | None] = mapped_column(String(32))

    __table_args__ = (UniqueConstraint("world_id", "recipe_id",
                                       name="uq_production_recipes_world_recipe"),)


class ProductionState(Base):
    """聚落 × recipe 的生产进位状态（整数 carry；重启/切块不丢失）。"""
    __tablename__ = "production_state"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    settlement_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    recipe_ref: Mapped[str] = mapped_column(String(32), nullable=False)
    production_carry: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                                  default=0, server_default="0")
    engine_version: Mapped[str | None] = mapped_column(String(32))
    updated_blessed_tick: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (UniqueConstraint("world_id", "settlement_ref", "recipe_ref",
                                       name="uq_production_state_world_settlement_recipe"),)


class EconomicPressureState(Base):
    """经济压力状态（committed authoritative state；restart 可完整恢复）。

    反馈延迟冻结：ECONOMY 于 step N 写本表 → DEMOGRAPHY 于 step N+1 经
    snapshot 读取（CROSS_ENGINE_FEEDBACK_LATENCY = NEXT_COMMITTED_STEP）。
    shortage_ratio = unmet/demand 的 fixed-point（num/den 已约分）。
    """
    __tablename__ = "economic_pressure_state"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    settlement_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_profile_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    demand_minor: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                              default=0, server_default="0")
    fulfilled_minor: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                                 default=0, server_default="0")
    unmet_minor: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                             default=0, server_default="0")
    shortage_ratio_num: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                                    default=0, server_default="0")
    shortage_ratio_den: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                                    default=1, server_default="1")
    sustained_shortage_steps: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0")
    stress_level: Mapped[str] = mapped_column(String(16), nullable=False,
                                              default="NONE", server_default="NONE")
    engine_version: Mapped[str | None] = mapped_column(String(32))
    updated_blessed_tick: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (UniqueConstraint(
        "world_id", "settlement_ref", "resource_profile_ref",
        name="uq_economic_pressure_state_world_settlement_resource"),)


class EcologyZone(Base):
    """生态区（M2c）：聚合环境单元。独立领域概念 —— 不等于 Settlement，
    也不等于 Resource Node；经 region_ref / settlement_relation 关联。"""
    __tablename__ = "ecology_zones"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    zone_id: Mapped[str] = mapped_column(String(32), nullable=False)
    region_ref: Mapped[str | None] = mapped_column(String(64))
    settlement_relation: Mapped[str | None] = mapped_column(String(64))
    profile_ref: Mapped[str | None] = mapped_column(String(64))  # NULL=UNCONFIGURED
    semantic_version: Mapped[str | None] = mapped_column(String(32))

    __table_args__ = (UniqueConstraint("world_id", "zone_id",
                                       name="uq_ecology_zones_world_zone"),)


class EcologyState(Base):
    """生态区状态（M2c）：整数 fixed-point 0..ECOLOGY_STATE_SCALE。

    质量/压力/再生容量全整数；退化/恢复亚年进位持久化；min/max 见证值
    持久化（restart 不丢失）。"""
    __tablename__ = "ecology_state"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    zone_ref: Mapped[str] = mapped_column(String(32), nullable=False)
    habitat_quality: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                                 default=0, server_default="0")
    regeneration_capacity: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0")
    ecological_stress: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0")
    population_pressure: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0")
    extraction_pressure: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0")
    production_pressure: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0")
    depletion_pressure: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0")
    external_pressure: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0")
    degradation_carry: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0")
    recovery_carry: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0")
    quality_min_seen: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                                  default=0, server_default="0")
    quality_max_seen: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                                  default=0, server_default="0")
    engine_version: Mapped[str | None] = mapped_column(String(32))
    updated_blessed_tick: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (UniqueConstraint("world_id", "zone_ref",
                                       name="uq_ecology_state_world_zone"),)


class EcologyFeedbackState(Base):
    """生态反馈状态（M2c）：committed authoritative feedback。

    RESOURCE / DEMOGRAPHY 于下一 committed step 经 snapshot 读取
    （ECOLOGY_FEEDBACK_LATENCY = NEXT_COMMITTED_STEP）。
    """
    __tablename__ = "ecology_feedback_state"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    zone_ref: Mapped[str] = mapped_column(String(32), nullable=False)
    regeneration_capacity_minor_per_year: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0")
    yield_modifier_num: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                                    default=1, server_default="1")
    yield_modifier_den: Mapped[int] = mapped_column(BigInteger, nullable=False,
                                                    default=1, server_default="1")
    extraction_modifier_num: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1, server_default="1")
    extraction_modifier_den: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1, server_default="1")
    habitat_stress_level: Mapped[str] = mapped_column(String(16), nullable=False,
                                                      default="NONE",
                                                      server_default="NONE")
    environmental_stress_num: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0")
    environmental_stress_den: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1, server_default="1")
    engine_version: Mapped[str | None] = mapped_column(String(32))
    updated_blessed_tick: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (UniqueConstraint(
        "world_id", "zone_ref",
        name="uq_ecology_feedback_state_world_zone"),)


class EcologicalRegion(Base):
    __tablename__ = "ecological_regions"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    terrain: Mapped[str | None] = mapped_column(String(32))
    climate: Mapped[str | None] = mapped_column(String(32))
    water: Mapped[str | None] = mapped_column(String(32))
    flora_classes: Mapped[list | None] = mapped_column(JSON)
    fauna_classes: Mapped[list | None] = mapped_column(JSON)
    spiritual_resources: Mapped[list | None] = mapped_column(JSON)
    danger_level: Mapped[str | None] = mapped_column(String(12))
    carrying_capacity: Mapped[int | None] = mapped_column(Integer)
    state: Mapped[str | None] = mapped_column(String(16))


class Tribulation(Base):
    """灾劫实例（T-3M 九阶段；WS-0905 禁止转数推断）。"""
    __tablename__ = "tribulations"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    window_type: Mapped[str] = mapped_column(String(16), nullable=False)  # REGULAR/MAJOR/CENTENNIAL
    phase: Mapped[str] = mapped_column(String(24), nullable=False)
    params: Mapped[dict | None] = mapped_column(JSON)
    start_blessed_tick: Mapped[int | None] = mapped_column(BigInteger)
    end_blessed_tick: Mapped[int | None] = mapped_column(BigInteger)
    residual: Mapped[dict | None] = mapped_column(JSON)


class TimelineEntry(Base):
    __tablename__ = "timeline_entries"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    blessed_tick: Mapped[int | None] = mapped_column(BigInteger)
    real_time: Mapped[datetime | None] = mapped_column(UtcDateTime())
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    spotlight: Mapped[bool] = mapped_column(Boolean, default=False)
    digest_text: Mapped[str | None] = mapped_column(Text)
    event_ref: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)


class CulturalElement(Base):
    __tablename__ = "cultural_elements"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    origin: Mapped[str] = mapped_column(String(8), nullable=False)  # REAL/BLESSED
    element: Mapped[str] = mapped_column(String(128), nullable=False)
    phase: Mapped[str] = mapped_column(String(24), default="CONTACT")
    adoption_stats: Mapped[dict | None] = mapped_column(JSON)

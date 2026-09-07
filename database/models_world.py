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
    """资源节点（WS-0703 八态）。"""
    __tablename__ = "resource_nodes"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    world_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    region_ref: Mapped[str | None] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16), default="STABLE")
    yield_model: Mapped[dict | None] = mapped_column(JSON)
    history_ref: Mapped[str | None] = mapped_column(String(64))


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

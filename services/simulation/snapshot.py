# -*- coding: utf-8 -*-
"""WorldSnapshot / StagedWorld（M2 Preflight 冻结）。

- WorldSnapshot：step 开始时从权威 DB 一次性读取（不可变）。
- StagedWorld：start snapshot 的内存拷贝；引擎读暂存视图（Feed-Forward），
  经 propose() 声明变更；中间状态只在内存，绝不提前成为 authoritative DB。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...database.models_core import WorldRuntime
from ...database.models_world import (EcologicalRegion, Industry, Institution,
                                     Lineage, PopulationGroup, ResourceNode,
                                     Settlement)
from ...domain.errors import IntegrityError
from .contracts import ENGINE_OWNERSHIP, StateChange

SNAPSHOT_TABLES = (
    "settlements", "population_groups", "resource_nodes", "industries",
    "ecological_regions", "lineages", "institutions")

_MODEL_BY_TABLE = {
    "settlements": Settlement,
    "population_groups": PopulationGroup,
    "resource_nodes": ResourceNode,
    "industries": Industry,
    "ecological_regions": EcologicalRegion,
    "lineages": Lineage,
    "institutions": Institution,
}

_FIELDS = {
    "settlements": ("id", "world_id", "settlement_type", "region_ref",
                    "working_name", "state", "population_capacity", "meta"),
    "population_groups": ("id", "world_id", "species", "settlement_ref",
                          "age_cohort", "occupation_group", "count"),
    "resource_nodes": ("id", "world_id", "kind", "region_ref", "state"),
    "industries": ("id", "world_id", "kind", "node_ref", "labor",
                   "capacity", "state"),
    "ecological_regions": ("id", "world_id", "terrain", "climate", "water",
                           "danger_level", "carrying_capacity", "state"),
    "lineages": ("id", "world_id", "lineage_type", "head_person_ref",
                 "member_ids"),
    "institutions": ("id", "world_id", "kind", "settlement_ref",
                     "owner_ref", "state", "capacity"),
}


def _row_dict(model, fields) -> dict:
    return {f: getattr(model, f) for f in fields}


def _canonical(row: dict, table: str) -> Any:
    """语义键元组（哈希规范化排序用；见契约 §9）。"""
    key_specs = {
        "settlements": ("settlement_type", "working_name"),
        "population_groups": ("species", "settlement_ref", "age_cohort",
                              "occupation_group"),
        "resource_nodes": ("kind", "region_ref"),
        "industries": ("kind", "node_ref"),
        "ecological_regions": ("terrain", "climate", "water"),
        "lineages": ("lineage_type", "head_person_ref"),
        "institutions": ("kind", "settlement_ref", "owner_ref"),
    }
    return tuple(_norm(row[k]) for k in key_specs[table])


def _norm(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(sorted((k, _norm(v)) for k, v in value.items()))
    if isinstance(value, list):
        return tuple(_norm(v) for v in value)
    return value


@dataclass(frozen=True)
class WorldSnapshot:
    """start-of-step 权威快照（不可变）。"""
    world_id: str
    blessed_tick: int
    last_committed_real_us: int
    time_rate_remainder: int
    current_time_ratio_id: int | None
    tables: dict[str, tuple[dict, ...]] = field(default_factory=dict)

    def rows(self, table: str) -> tuple[dict, ...]:
        return self.tables.get(table, ())


def read_snapshot(session: Session, world_id: str) -> WorldSnapshot:
    runtime = session.execute(
        select(WorldRuntime).where(WorldRuntime.world_id == world_id)
    ).scalar_one_or_none()
    if runtime is None:
        raise IntegrityError("world_runtime 行缺失", detail=world_id)
    tables: dict[str, tuple[dict, ...]] = {}
    for table, model in _MODEL_BY_TABLE.items():
        rows = [_row_dict(m, _FIELDS[table]) for m in session.execute(
            select(model).where(model.world_id == world_id)).scalars()]
        tables[table] = tuple(sorted(rows, key=lambda r: (_canonical(r, table),
                                                          r["id"])))
    return WorldSnapshot(
        world_id=world_id,
        blessed_tick=runtime.current_blessed_tick,
        last_committed_real_us=runtime.last_committed_real_us,
        time_rate_remainder=runtime.time_rate_remainder,
        current_time_ratio_id=runtime.current_time_ratio_id,
        tables=tables)


class StagedWorld:
    """内存暂存世界（Feed-Forward）：引擎读 staged 视图、经 propose 声明变更。"""

    def __init__(self, snapshot: WorldSnapshot):
        self.snapshot = snapshot
        self._rows: dict[str, dict[int, dict]] = {
            table: {r["id"]: dict(r) for r in rows}
            for table, rows in snapshot.tables.items()}
        self.changes: list[StateChange] = []

    def rows(self, table: str) -> tuple[dict, ...]:
        return tuple(self._rows.get(table, {}).values())

    def get(self, table: str, entity_id: int) -> dict | None:
        return self._rows.get(table, {}).get(entity_id)

    def propose(self, *, engine_id: str, table: str, entity_id: int,
                field: str, new_value: Any) -> None:
        if table not in SNAPSHOT_TABLES:
            raise IntegrityError("propose 目标表不在快照契约内", detail=table)
        if table not in ENGINE_OWNERSHIP.get(engine_id, frozenset()):
            raise IntegrityError(
                f"引擎 {engine_id} 无权写表 {table}（所有权契约）",
                detail={"engine": engine_id, "table": table})
        row = self._rows[table][entity_id]
        old = row.get(field)
        if old == new_value:
            return
        row[field] = new_value
        self.changes.append(StateChange(table=table, entity_id=entity_id,
                                        field=field, old_value=old,
                                        new_value=new_value))

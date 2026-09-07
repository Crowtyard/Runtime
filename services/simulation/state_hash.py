# -*- coding: utf-8 -*-
"""world_state_hash（WORLD_STATE_HASH_SCHEMA_VERSION=2 / =3）。

- v2（M2a 冻结）：只覆盖 M2a 状态域（7 张表 + M2a 字段集）。字段集与表集
  显式冻结于此 —— 后续 snapshot 扩展不得静默改变 v2 输出（M2a 120y 基线
  逐字节复现依赖此冻结）。
- v3（M2b）：覆盖 Population + Resource Node/Profile + Inventory +
  Production State + Economy Pressure State（快照全状态域）。
- canonical serialization：UTF-8 JSON（sort_keys + 紧凑分隔符）+ 实体按语义
  键排序（snapshot._canonical）；禁止行物理顺序/autoincrement 顺序/now()
  时间戳/日志元数据/事件日志作为输入。
"""
from __future__ import annotations

import hashlib
import json

from .snapshot import WorldSnapshot

WORLD_STATE_HASH_SCHEMA_VERSION = 3  # 当前（M2b）
WORLD_STATE_HASH_SCHEMA_VERSION_V2 = 2  # M2a 冻结（回归基线）

# M2a 冻结表集（v2 只哈希这 7 张表，绝不因 snapshot 扩展而漂移）
_V2_TABLES = frozenset({
    "settlements", "population_groups", "resource_nodes", "industries",
    "ecological_regions", "lineages", "institutions"})

# M2a 冻结字段集（v2 每表只取这些字段；resource_nodes 不含 M2b 扩展列）
_V2_FIELDS = {
    "settlements": ("id", "world_id", "settlement_type", "region_ref",
                    "working_name", "state", "population_capacity", "meta"),
    "population_groups": ("id", "world_id", "species", "settlement_ref",
                          "age_cohort", "occupation_group", "count",
                          "age_advance_carry_ticks", "species_profile_ref",
                          "demography_version", "updated_blessed_tick"),
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


def _build_doc(*, snapshot: WorldSnapshot, simulation_version: str,
               pipeline_version: str, engine_versions: dict[str, str],
               schema_version: int, table_fields: dict[str, tuple[str, ...]]
               ) -> dict:
    doc = {
        "schema_version": schema_version,
        "world_id": snapshot.world_id,
        "clock": {
            "blessed_tick": snapshot.blessed_tick,
            "last_committed_real_us": snapshot.last_committed_real_us,
            "time_rate_remainder": snapshot.time_rate_remainder,
            "current_time_ratio_id": snapshot.current_time_ratio_id,
        },
        "simulation_version": simulation_version,
        "pipeline_version": pipeline_version,
        "engine_versions": dict(sorted(engine_versions.items())),
        "tables": {
            t: [_strip(row, table_fields[t]) for row in snapshot.rows(t)]
            for t in sorted(table_fields)
        },
    }
    return doc


def _strip(row: dict, fields: tuple[str, ...]) -> dict:
    """只保留版本冻结字段，并排除 autoincrement id（插入顺序依赖）。"""
    return {k: row[k] for k in fields if k != "id" and k in row}


def world_state_hash_v2(*, snapshot: WorldSnapshot, simulation_version: str,
                        pipeline_version: str,
                        engine_versions: dict[str, str]) -> str:
    """M2a 冻结 v2（回归基线专用；语义永不变化）。"""
    doc = _build_doc(
        snapshot=snapshot, simulation_version=simulation_version,
        pipeline_version=pipeline_version, engine_versions=engine_versions,
        schema_version=WORLD_STATE_HASH_SCHEMA_VERSION_V2,
        table_fields={t: _V2_FIELDS[t] for t in sorted(_V2_TABLES)})
    return _digest(doc)


def world_state_hash_v3(*, snapshot: WorldSnapshot, simulation_version: str,
                        pipeline_version: str,
                        engine_versions: dict[str, str]) -> str:
    """M2b v3：覆盖快照全状态域（含 Resource/Economy）。"""
    from .snapshot import _FIELDS  # 延迟导入避免循环
    doc = _build_doc(
        snapshot=snapshot, simulation_version=simulation_version,
        pipeline_version=pipeline_version, engine_versions=engine_versions,
        schema_version=WORLD_STATE_HASH_SCHEMA_VERSION,
        table_fields=dict(_FIELDS))
    return _digest(doc)


def _digest(doc: dict) -> str:
    canonical = json.dumps(doc, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"), default=_json_default)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _json_default(value):
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, dict):
        return dict(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)

# -*- coding: utf-8 -*-
"""world_state_hash v2（WORLD_STATE_HASH_SCHEMA_VERSION=2）。

canonical serialization：UTF-8 JSON（sort_keys + 紧凑分隔符）+ 实体按语义键
排序（snapshot._canonical）；禁止把行物理顺序/autoincrement 顺序/now() 时间戳/
日志元数据/事件日志作为输入。哈希 schema 版本字段可升级。
"""
from __future__ import annotations

import hashlib
import json

from .snapshot import WorldSnapshot

WORLD_STATE_HASH_SCHEMA_VERSION = 2


def world_state_hash_v2(
    *,
    snapshot: WorldSnapshot,
    simulation_version: str,
    pipeline_version: str,
    engine_versions: dict[str, str],
) -> str:
    """稳定排序 + 版本化 schema 的确定性状态哈希。"""
    doc = {
        "schema_version": WORLD_STATE_HASH_SCHEMA_VERSION,
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
        "tables": {t: [_strip_unstable(r) for r in snapshot.rows(t)]
                   for t in sorted(snapshot.tables)},
    }
    canonical = json.dumps(doc, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"), default=_json_default)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _strip_unstable(row: dict) -> dict:
    """排除 autoincrement id（插入顺序依赖）等不稳定字段。"""
    return {k: v for k, v in row.items() if k != "id"}


def _json_default(value):
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, dict):
        return dict(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)

# -*- coding: utf-8 -*-
"""DOMAIN_ENTITY_ID / OPERATION ID —— 确定性持久化身份（M2 Integrated Review）。

规则（冻结）：
- 任何 M2 persistent domain identity >= 128-bit（hex 至少 32 字符）。
- 确定性：hash(带版本前缀的 canonical parts)；禁止 UUID4 / wall clock /
  DB autoincrement / 随机熵进入世界语义身份。
- retry / restart 稳定（对世界语义身份；operational id 允许含 writer 维度，
  见 run_id 文档）。
"""
from __future__ import annotations

import hashlib

DOMAIN_ENTITY_ID_SCHEMA_VERSION = "domain-entity-id-v1"


def deterministic_hex_id(parts: list[str], *, bits: int = 128,
                         schema: str = DOMAIN_ENTITY_ID_SCHEMA_VERSION,
                         ) -> str:
    """确定性 hex 身份：sha256(schema|p1|p2|…)[:bits/4]。

    bits ∈ {128, 256}；默认 128-bit（32 hex）。
    """
    if bits not in (128, 256):
        raise ValueError("bits 必须为 128 或 256")
    payload = "|".join([schema, *[str(p) for p in parts]]).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[: bits // 4]

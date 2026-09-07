# -*- coding: utf-8 -*-
"""Event UID 与 Event Stream Hash（M2 Preflight Hardening）。

Event UID（EVENT_UID_SCHEMA_VERSION=1）：
  sha256("v1|world_id|simulation_version|interval_start|interval_end|
         engine_id|event_type|stable_local_sequence") 的 hex 前 32 字符（128-bit）。
  禁止 UUID4 / wall clock / DB autoincrement / 随机值。

Event Stream Hash（EVENT_STREAM_HASH_SCHEMA_VERSION=1）：
  增量链：h_0 = H(seed)；h_i = H(schema|world|simver|h_{i-1}|step_i 的 domain
  events（发射顺序）)。证明截至某 simulation run 的机器级 Domain Event Stream
  的确定内容与顺序；Diagnostic Log 永不进入；与 world_state_hash 语义分离
  （状态哈希不变 ≠ 事件流哈希不变，反之亦然）。
"""
from __future__ import annotations

import hashlib
import json

EVENT_UID_SCHEMA_VERSION = 1
EVENT_UID_HEX_LEN = 32  # 128-bit collision resistance
EVENT_STREAM_HASH_SCHEMA_VERSION = 1


def deterministic_event_uid(*, world_id: str, simulation_version: str,
                            real_start_us: int, real_end_us: int,
                            engine_id: str, event_type: str,
                            seq: int) -> str:
    """确定性事件 identity（≥128-bit；event_type 参与语义身份）。"""
    payload = "v%d|%s" % (EVENT_UID_SCHEMA_VERSION, "|".join([
        world_id, simulation_version, str(real_start_us),
        str(real_end_us), engine_id, event_type, str(seq)]))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:EVENT_UID_HEX_LEN]


def _seed_doc(world_id: str, simulation_version: str) -> str:
    return "event-stream-v%d|%s|%s" % (EVENT_STREAM_HASH_SCHEMA_VERSION,
                                       world_id, simulation_version)


def empty_event_stream_hash(world_id: str, simulation_version: str) -> str:
    return hashlib.sha256(
        _seed_doc(world_id, simulation_version).encode("utf-8")).hexdigest()


def step_event_stream_hash(prev_hash: str | None, *, world_id: str,
                           simulation_version: str,
                           events: list[dict]) -> str:
    """把一步发射的 domain events（发射顺序）链接进事件流哈希。

    events 每项：{event_uid, blessed_tick, event_type, source, cause,
    effect, severity, scope}（canonical、无 wall-clock/行 id）。
    """
    doc = {
        "schema_version": EVENT_STREAM_HASH_SCHEMA_VERSION,
        "world_id": world_id,
        "simulation_version": simulation_version,
        "prev_hash": prev_hash,
        "events": [
            {k: v for k, v in sorted(e.items())} for e in events
        ],
    }
    canonical = json.dumps(doc, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

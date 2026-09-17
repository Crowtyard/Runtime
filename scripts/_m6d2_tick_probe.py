"""M6D.2 — inspect the per-entity population count changes at a casualty tick."""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict

PATH = sys.argv[1]
TICK = int(sys.argv[2])
con = sqlite3.connect("file:" + PATH.replace("\\", "/") + "?mode=ro", uri=True)
rows = con.execute(
    "SELECT entity_id, old_value, new_value, engine_id, episode_id, "
    "trigger_event_id, event_ref FROM history_state_changes "
    "WHERE entity_type='population_groups' AND field='count' AND blessed_tick=?",
    (TICK,)).fetchall()
per_entity: dict[str, list] = defaultdict(list)
for eid, old_raw, new_raw, engine, ep, trig, evref in rows:
    old = json.loads(old_raw)["v"] if old_raw else None
    new = json.loads(new_raw)["v"] if new_raw else None
    per_entity[str(eid)].append((old, new, engine, ep, trig, evref))
print("rows", len(rows), "distinct_entities", len(per_entity))
dup = {k: v for k, v in per_entity.items() if len(v) > 1}
print("entities_with_multiple_change_rows", len(dup))
total = 0
for k, v in list(per_entity.items())[:400]:
    delta = sum((n - o) for o, n, *_ in v if o is not None and n is not None)
    total += delta
print("sum_delta_all_entities", total)
for k, v in list(dup.items())[:6]:
    print("DUP", k, v)
events = con.execute(
    "SELECT event_type, event_uid, effect FROM world_events WHERE blessed_tick=?",
    (TICK,)).fetchall()
for et, uid, eff in events:
    if "IMPACT" in et or "POPULATION" in et:
        print("EVENT", et, uid[:12], (eff or "")[:160])
con.close()

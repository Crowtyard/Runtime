"""M6D.2 — find adapter state changes that overlap engine changes in the same step.

For every tick where a tribulation adapter wrote a HistoryStateChange (episode_id
set), count how many (entity_type, entity_id, field) keys ALSO have an engine row in
the same tick (=> last-write-wins overwrite risk), and how many are adapter-only
(=> the adapter's value is the one that persists).

READ-ONLY.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict

PATH = sys.argv[1]
con = sqlite3.connect("file:" + PATH.replace("\\", "/") + "?mode=ro", uri=True)
rows = con.execute(
    "SELECT blessed_tick, entity_type, entity_id, field, old_value, new_value, "
    "episode_id, engine_id FROM history_state_changes WHERE episode_id IS NOT NULL"
).fetchall()
print("adapter_change_rows", len(rows))
by_tick_key: dict[tuple, list] = defaultdict(list)
for t, et, eid, f, o, n, ep, eng in rows:
    by_tick_key[(int(t), et, str(eid), f)].append(
        (json.loads(o)["v"] if o else None, json.loads(n)["v"] if n else None,
         eng))
engine_rows = con.execute(
    "SELECT blessed_tick, entity_type, entity_id, field, old_value, new_value "
    "FROM history_state_changes WHERE episode_id IS NULL").fetchall()
engine_index = set((int(t), et, str(eid), f) for t, et, eid, f, _o, _n in engine_rows)
overlap = 0
adapter_only = 0
by_table: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
for key, entries in by_tick_key.items():
    t, et, eid, f = key
    adapter_delta = sum((n - o) for o, n, _e in entries
                        if o is not None and n is not None)
    if key in engine_index:
        overlap += 1
        by_table[et][0] += 1
        by_table[et][2] += adapter_delta
    else:
        adapter_only += 1
        by_table[et][1] += 1
        by_table[et][3] += adapter_delta
print("adapter_keys_total", len(by_tick_key))
print("ADAPTER_OVERLAPS_ENGINE_SAME_STEP", overlap)
print("ADAPTER_ONLY", adapter_only)
for et, (ov, ao, ovd, aod) in sorted(by_table.items()):
    print("  %-24s overlap_keys=%-4d adapter_only_keys=%-4d "
          "overlap_adapter_delta=%-5d adapter_only_delta=%d"
          % (et, ov, ao, ovd, aod))
con.close()

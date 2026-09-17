"""M6D.2 — follow the persisted population count chain for specific entities."""
from __future__ import annotations

import json
import sqlite3
import sys

PATH = sys.argv[1]
IDS = [int(x) for x in sys.argv[2].split(",")]
con = sqlite3.connect("file:" + PATH.replace("\\", "/") + "?mode=ro", uri=True)
for eid in IDS:
    rows = con.execute(
        "SELECT blessed_tick, old_value, new_value, episode_id, trigger_event_id "
        "FROM history_state_changes WHERE entity_type='population_groups' "
        "AND field='count' AND entity_id=? ORDER BY blessed_tick, id",
        (str(eid),)).fetchall()
    print("=== entity", eid, "changes:", len(rows))
    for tick, o, n, ep, tr in rows:
        ov = json.loads(o)["v"] if o else None
        nv = json.loads(n)["v"] if n else None
        flag = "ADAPTER" if ep else "engine "
        marker = ""
        if ov is not None and nv is not None and abs(nv - ov) == 0:
            marker = " (no-op)"
        print("   y%-4s %-7s %s -> %s%s" % (tick // 1_000_000, flag, ov, nv,
                                            marker))
    cur = con.execute("SELECT count FROM population_groups WHERE id=?", (eid,)).fetchone()
    print("   FINAL_DB_COUNT", cur[0] if cur else None)
con.close()

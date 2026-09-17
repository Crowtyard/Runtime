"""M6D.2 — cumulative human ledger at each checkpoint (READ-ONLY)."""
from __future__ import annotations

import json
import sqlite3
import sys

PATH = sys.argv[1]
con = sqlite3.connect("file:" + PATH.replace("\\", "/") + "?mode=ro", uri=True)
SQL = ("SELECT blessed_tick, event_type, effect FROM world_events "
       "WHERE event_type IN ('POPULATION_BIRTHS','POPULATION_DEATHS',"
       "'DEMOGRAPHY_IMPACT_APPLIED') AND blessed_tick <= ?")
for limit in (0, 10_000_000, 50_000_000, 100_000_000, 300_000_000):
    b = d = i = 0
    for _tick, etype, eff in con.execute(SQL, (limit,)):
        e = json.loads(eff) if eff else {}
        if etype == "POPULATION_BIRTHS":
            b += int(e.get("count", 0) or 0)
        elif etype == "POPULATION_DEATHS":
            d += int(e.get("count", 0) or 0)
        else:
            i += int(e.get("population_loss", 0) or 0)
    print("tick<=%4dy births=%6d deaths=%6d losses=%3d net=%7d implied_pop=%7d"
          % (limit // 1_000_000, b, d, i, b - d - i, 12000 + b - d - i))
con.close()

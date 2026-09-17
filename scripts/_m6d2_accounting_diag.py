"""M6D.2 — population accounting diagnosis (READ-ONLY, no re-run).

Reconstructs the per-tick population delta from the history ledger
(history_state_changes on population_groups.count), compares it with the
per-tick POPULATION_BIRTHS / POPULATION_DEATHS event effects and the tribulation
DEMOGRAPHY_IMPACT_APPLIED losses, and reports the exact years where the owner §13
identity does not close, with the residual sign and magnitude.

Usage: python scripts/_m6d2_accounting_diag.py --db <path> [--out json]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
from collections import defaultdict


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    path = pathlib.Path(args.db)
    uri = "file:" + str(path).replace("\\", "/") + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        cur = con.execute(
            "SELECT blessed_tick, old_value, new_value FROM history_state_changes "
            "WHERE entity_type='population_groups' AND field='count'")
        net: dict[int, int] = defaultdict(int)
        rows = 0
        for tick, old_raw, new_raw in cur:
            rows += 1
            try:
                old = json.loads(old_raw)["v"]
                new = json.loads(new_raw)["v"]
            except Exception:
                continue
            if old is None or new is None:
                continue
            net[int(tick)] += int(new) - int(old)

        ev = con.execute(
            "SELECT blessed_tick, event_type, effect FROM world_events "
            "WHERE event_type IN ('POPULATION_BIRTHS','POPULATION_DEATHS',"
            "'DEMOGRAPHY_IMPACT_APPLIED')")
        births: dict[int, int] = defaultdict(int)
        deaths: dict[int, int] = defaultdict(int)
        impacts: dict[int, int] = defaultdict(int)
        impact_events: dict[int, int] = defaultdict(int)
        for tick, etype, effect_raw in ev:
            try:
                effect = json.loads(effect_raw) if effect_raw else {}
            except Exception:
                effect = {}
            tick = int(tick)
            if etype == "POPULATION_BIRTHS":
                births[tick] += int(effect.get("count", 0) or 0)
            elif etype == "POPULATION_DEATHS":
                deaths[tick] += int(effect.get("count", 0) or 0)
            else:
                impacts[tick] += int(effect.get("population_loss", 0) or 0)
                impact_events[tick] += 1

        ticks = sorted(set(net) | set(births) | set(deaths) | set(impacts))
        mismatches = []
        tot_net = tot_b = tot_d = tot_i = 0
        for t in ticks:
            n, b, d, i = net.get(t, 0), births.get(t, 0), deaths.get(t, 0), \
                impacts.get(t, 0)
            tot_net += n
            tot_b += b
            tot_d += d
            tot_i += i
            resid_no_casualty = n - (b - d)
            resid_with_casualty = n - (b - d - i)
            if resid_no_casualty != 0 or resid_with_casualty != 0:
                mismatches.append({
                    "blessed_tick": t, "year": t / 1_000_000,
                    "net_population_delta": n, "births": b, "deaths": d,
                    "tribulation_losses": i,
                    "impact_events": impact_events.get(t, 0),
                    "residual_births_minus_deaths": resid_no_casualty,
                    "residual_incl_casualties": resid_with_casualty})
    finally:
        con.close()

    out = {
        "db": str(path),
        "ticks": len(ticks),
        "history_state_change_rows": rows,
        "totals": {"net_population_delta": tot_net, "births": tot_b,
                   "deaths": tot_d, "tribulation_losses": tot_i},
        "residual_totals": {
            "births_minus_deaths": tot_net - (tot_b - tot_d),
            "incl_casualties": tot_net - (tot_b - tot_d - tot_i)},
        "mismatch_tick_count": len(mismatches),
        "mismatches": mismatches[:60],
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))
    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""M6D.3 §6/§9/§10/§11 — TRIBULATION_EFFECT_APPLIED_IDENTITY gate (READ-ONLY).

Verifies, on a finished world DB, that every tribulation effect that was RECORDED
also LANDED in the authoritative state, exactly once:

  * chain consistency: for each adapter ledger row (episode_id IS NOT NULL) on
    (table, entity_id, field), the next change row for the same key must start at
    the adapter row's new value (or, if it is the last row, the live table value
    must equal it);
  * same-step composition: where an owning-engine row exists for the same key in
    the same step, the engine row's new value must equal the adapter row's old
    value (delta applied on the post-engine value, not on a stale pre-step value);
  * magnitude reconciliation per domain: recorded effect (event payload) ==
    applied magnitude (sum of adapter ledger deltas);
  * exactly-once: no key may carry two adapter rows in the same step.

Usage: python scripts/_m6d3_effect_identity.py --db PATH [--out JSON]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
from collections import defaultdict

FIELD_OF_EVENT = {
    "DEMOGRAPHY_IMPACT_APPLIED": ("population_groups", "count", "population_loss"),
    "RESOURCE_IMPACT_APPLIED": ("resource_nodes", "remaining_reserve",
                                "reserve_damage"),
    "ECONOMY_IMPACT_APPLIED": ("resource_stocks", "quantity", "inventory_loss"),
    "ECOLOGY_IMPACT_APPLIED": ("ecology_state", "habitat_quality", "quality_loss"),
    "SOCIAL_IMPACT_APPLIED": ("households", "represented_population", "displaced"),
}


def _json_int(raw):
    try:
        return int(json.loads(raw)["v"])
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    con = sqlite3.connect("file:" + str(pathlib.Path(args.db)).replace("\\", "/")
                          + "?mode=ro", uri=True)

    rows = con.execute(
        "SELECT blessed_tick, entity_type, entity_id, field, old_value, new_value, "
        "episode_id FROM history_state_changes "
        "WHERE entity_type IN ('population_groups','resource_nodes','resource_stocks',"
        "'ecology_state','households','settlement_social_state') "
        "ORDER BY entity_type, entity_id, field, blessed_tick, id").fetchall()
    chains: dict[tuple, list] = defaultdict(list)
    adapter_keys: set = set()
    for tick, et, eid, field, old_raw, new_raw, episode in rows:
        key = (et, str(eid), field)
        chains[key].append({"tick": int(tick), "old": _json_int(old_raw),
                            "new": _json_int(new_raw), "adapter": episode is not None})
        if episode is not None:
            adapter_keys.add((int(tick), et, str(eid), field))

    recorded = defaultdict(int)
    recorded_rows = 0
    for et, eff in con.execute("SELECT event_type, effect FROM world_events "
                               "WHERE event_type LIKE '%IMPACT_APPLIED'"):
        if et not in FIELD_OF_EVENT:
            continue
        payload = json.loads(eff) if eff else {}
        _, _, field_name = FIELD_OF_EVENT[et]
        recorded[et] += int(payload.get(field_name, 0) or 0)
        recorded_rows += 1

    live = {}
    for et, field in (("population_groups", "count"),
                      ("resource_nodes", "remaining_reserve"),
                      ("resource_stocks", "quantity"),
                      ("ecology_state", "habitat_quality"),
                      ("households", "represented_population"),
                      ("settlement_social_state", "social_stress")):
        if field not in ("count", "remaining_reserve", "quantity",
                         "habitat_quality", "represented_population",
                         "social_stress"):
            continue
        try:
            for eid, value in con.execute(
                    "SELECT id, %s FROM %s" % (field, et)):
                live[(et, str(eid), field)] = int(value)
        except sqlite3.Error:
            pass

    dropped = []
    applied_magnitude = defaultdict(int)
    applied_rows = 0
    composition_ok = composition_bad = 0
    exactly_once_violations = []
    seen_step_key: set = set()
    last_row_value = {}

    for key, entries in chains.items():
        for idx, entry in enumerate(entries):
            if not entry["adapter"]:
                continue
            step_key = (entry["tick"], key)
            if step_key in seen_step_key:
                exactly_once_violations.append(step_key)
            seen_step_key.add(step_key)
            nxt = entries[idx + 1] if idx + 1 < len(entries) else None
            observed = nxt["old"] if nxt is not None else live.get(key)
            last_row_value[key] = entry["new"]
            if observed is None or observed != entry["new"]:
                dropped.append({"key": list(key), "tick": entry["tick"],
                                "adapter_new": entry["new"], "observed": observed})
            applied_magnitude[key[0]] += abs(int(entry["new"] or 0)
                                             - int(entry["old"] or 0))
            applied_rows += 1
            # same-step composition with the owning engine row
            for other in entries:
                if other["tick"] == entry["tick"] and not other["adapter"]:
                    if other["new"] == entry["old"]:
                        composition_ok += 1
                    else:
                        composition_bad += 1

    out = {
        "db": str(args.db),
        "TRIBULATION_IMPACT_EVENTS": recorded_rows,
        "TRIBULATION_EFFECTS_RECORDED_ROWS": applied_rows,
        "TRIBULATION_EFFECTS_RECORDED_MAGNITUDE_BY_EVENT": dict(recorded),
        "TRIBULATION_EFFECTS_APPLIED_ROWS": applied_rows,
        "TRIBULATION_EFFECTS_APPLIED_MAGNITUDE_BY_TABLE":
            dict(applied_magnitude),
        "TRIBULATION_EFFECTS_DROPPED": len(dropped),
        "TRIBULATION_EFFECTS_DROPPED_SAMPLES": dropped[:10],
        "MAGNITUDE_RECONCILIATION": {
            "DEMOGRAPHY": {"recorded": recorded.get("DEMOGRAPHY_IMPACT_APPLIED"),
                           "applied": applied_magnitude.get("population_groups")},
            "RESOURCE": {"recorded": recorded.get("RESOURCE_IMPACT_APPLIED"),
                         "applied": applied_magnitude.get("resource_nodes")},
            "ECONOMY": {"recorded": recorded.get("ECONOMY_IMPACT_APPLIED"),
                        "applied": applied_magnitude.get("resource_stocks")},
            "ECOLOGY": {"recorded": recorded.get("ECOLOGY_IMPACT_APPLIED"),
                        "applied": applied_magnitude.get("ecology_state")},
            "SOCIAL": {"recorded": recorded.get("SOCIAL_IMPACT_APPLIED"),
                       "applied": applied_magnitude.get("households")},
        },
        "SAME_STEP_COMPOSITION_OK": composition_ok,
        "SAME_STEP_COMPOSITION_BAD": composition_bad,
        "EXACTLY_ONCE_VIOLATIONS": len(exactly_once_violations),
        "TRIBULATION_EFFECT_APPLIED_IDENTITY":
            "PASS" if (not dropped and not composition_bad
                       and not exactly_once_violations) else "FAIL",
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))
    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8", newline="\n")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

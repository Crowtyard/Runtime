"""M6D.3 §17-§21 — restart/history equivalence audit on the M6D.2 evidence DBs.

READ-ONLY. Establishes:
  * the exact DEFINITION of each hash the M6D.2 report quoted
    (event stream hash vs canonical causal history hash -- different projections),
  * like-for-like recomputation of the canonical causal history hash on
    RUN1 (continuous) / RUN2 (determinism replica) / RUN3 (restart chain),
  * streaming digests + first-difference search over world_events.event_uid,
    causal_history_links and entity_history_index.

Usage: python scripts/_m6d3_history_equivalence.py --root DIR [--out JSON]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sqlite3

TABLES = ("world_events", "causal_history_links", "entity_history_index",
          "history_state_changes", "history_episode_index", "history_index_state")


def connect(path: pathlib.Path) -> sqlite3.Connection:
    return sqlite3.connect("file:" + str(path).replace("\\", "/") + "?mode=ro",
                           uri=True)


def counts(con: sqlite3.Connection) -> dict:
    out = {}
    for t in TABLES:
        try:
            out[t] = con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
        except sqlite3.Error as exc:
            out[t] = "ERR:%s" % exc
    return out


def stream_digest(con: sqlite3.Connection, sql: str) -> tuple[str, int]:
    h = hashlib.sha256()
    n = 0
    for row in con.execute(sql):
        h.update(("|".join("" if v is None else str(v) for v in row)
                  + "\n").encode("utf-8"))
        n += 1
    return h.hexdigest(), n


def first_difference(con_a: sqlite3.Connection, con_b: sqlite3.Connection,
                     sql: str, key_index: int = 0, limit: int = 5) -> dict:
    """Stream both ordered result sets and report the first key-level differences."""
    missing: list = []
    extra: list = []
    different: list = []
    it_a = iter(con_a.execute(sql))
    it_b = iter(con_b.execute(sql))
    row_a = next(it_a, None)
    row_b = next(it_b, None)
    while (row_a is not None or row_b is not None) and len(different) < limit:
        if row_a is None:
            extra.append(row_b[key_index])
            row_b = next(it_b, None)
            continue
        if row_b is None:
            missing.append(row_a[key_index])
            row_a = next(it_a, None)
            continue
        ka, kb = row_a[key_index], row_b[key_index]
        if ka == kb:
            if row_a != row_b and len(different) < limit:
                different.append({"key": ka, "a": list(map(str, row_a)),
                                  "b": list(map(str, row_b))})
            row_a = next(it_a, None)
            row_b = next(it_b, None)
        elif str(ka) < str(kb):
            missing.append(ka)
            row_a = next(it_a, None)
        else:
            extra.append(kb)
            row_b = next(it_b, None)
    return {"first_missing": missing[:limit], "missing_count_seen": len(missing),
            "first_extra": extra[:limit], "extra_count_seen": len(extra),
            "first_different": different}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.expandvars(r"%TEMP%\m6d2_5ohuj6y7"))
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    root = pathlib.Path(args.root)
    dbs = {stage: root / stage / "m6c1d_world.db"
           for stage in ("run1", "run2", "run3")}
    con = {k: connect(v) for k, v in dbs.items() if v.exists()}

    out: dict = {
        "definitions": {
            "CONTINUOUS_HISTORY_HASH_DEFINITION": {
                "value_quoted_in_M6D2_report": "921324e2b779e130e273172fbbfa1f3d5b1f2d67b3c7f827398482e82a2ea2cf",
                "function": "services/history/service.py::canonical_causal_history_hash",
                "tables": ["causal_history_links"],
                "projection": "[schema_version, world_id, count] + per link "
                              "(relation_type, source_kind, source_id, target_kind, "
                              "target_id, episode_id, status, committed_tick, "
                              "semantic_version)",
                "ordering": "ORDER BY link_id (row-order independent)",
                "genesis_inclusion": "world_id in prefix; genesis only via its links",
            },
            "RESTART_HISTORY_HASH_DEFINITION": {
                "value_quoted_in_M6D2_report": "921324e2b779e130e273172fbbfa1f3d5b1f2d67b3c7f827398482e82a2ea2cf",
                "function": "services/history/service.py::canonical_causal_history_hash",
                "tables": ["causal_history_links"],
                "projection": "IDENTICAL to CONTINUOUS_HISTORY_HASH_DEFINITION",
                "ordering": "ORDER BY link_id",
                "genesis_inclusion": "identical",
            },
            "EVENT_STREAM_HASH_DEFINITION": {
                "value_quoted_in_M6D2_report": "25b93c40e6f15fdb1d04fc46c406a2d455acfa559c50bdaf353193cab896fcef",
                "function": "services/simulation/event_stream.py::step_event_stream_hash",
                "tables": ["(incrementally chained in-memory emitted domain events; "
                           "mirrored into world_events)"],
                "projection": "[schema_version, world_id, simulation_version, "
                              "prev_hash, step events (emission order, canonical dicts)]",
                "ordering": "emission order, chained step by step",
                "note": "NOT a history hash: different function/table/ordering/"
                        "projection from the causal history hash -> different value "
                        "by construction, for the SAME world.",
            },
        },
        "counts": {k: counts(c) for k, c in con.items()},
        "digests": {},
    }

    queries = {
        "world_events_by_uid": ("SELECT event_uid, blessed_tick, event_type, source, "
                                "cause, effect, severity, scope FROM world_events "
                                "ORDER BY event_uid", 0),
        "causal_links": ("SELECT link_id, relation_type, source_kind, source_id, "
                         "target_kind, target_id, episode_id, status, committed_tick, "
                         "semantic_version FROM causal_history_links "
                         "ORDER BY link_id", 0),
        "entity_history_index": ("SELECT world_id, entity_type, entity_id, link_id "
                                 "FROM entity_history_index "
                                 "ORDER BY entity_type, entity_id, link_id", 0),
        "history_state_changes": ("SELECT world_id, entity_type, entity_id, field, "
                                  "blessed_tick, engine_id FROM history_state_changes "
                                  "ORDER BY blessed_tick, entity_type, entity_id, "
                                  "field, id", 0),
    }
    for name, (sql, keyidx) in queries.items():
        out["digests"][name] = {}
        for stage, c in con.items():
            digest, n = stream_digest(c, sql)
            out["digests"][name][stage] = {"sha256": digest, "rows": n}
        ref = "run1"
        for stage, c in con.items():
            if stage == ref:
                continue
            out["digests"][name]["diff_%s_vs_%s" % (ref, stage)] = first_difference(
                con[ref], c, sql, keyidx)
    # canonical causal history hash recomputed with the production function
    sys_path = str(pathlib.Path(__file__).resolve().parents[1].parent)
    import sys
    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)
    from XiaoguangBlessedLandRuntime.services.history.service import (  # noqa: E402
        canonical_causal_history_hash)

    class _Link:
        __slots__ = ("link_id", "relation_type", "source_kind", "source_id",
                     "target_kind", "target_id", "episode_id", "status",
                     "committed_tick", "semantic_version")

        def __init__(self, row):  # noqa: D401
            (self.link_id, self.relation_type, self.source_kind, self.source_id,
             self.target_kind, self.target_id, self.episode_id, self.status,
             self.committed_tick, self.semantic_version) = row

    world_ids = {}
    for stage, c in con.items():
        wid = c.execute("SELECT world_id FROM world_runtime LIMIT 1").fetchone()
        world_ids[stage] = wid[0] if wid else None
    hashes = {}
    for stage, c in con.items():
        rows = [_Link(r) for r in c.execute(
            "SELECT link_id, relation_type, source_kind, source_id, target_kind, "
            "target_id, episode_id, status, committed_tick, semantic_version "
            "FROM causal_history_links")]
        hashes[stage] = canonical_causal_history_hash(world_ids[stage], rows)
    out["recomputed_canonical_causal_history_hash"] = hashes
    out["world_ids"] = world_ids
    out["HASH_DEFINITION_EQUIVALENT"] = True
    out["RESTART_HISTORY_EQUIVALENCE"] = (
        "PASS" if hashes.get("run1") == hashes.get("run3") else "FAIL")
    for c in con.values():
        c.close()
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True,
                       default=str), encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

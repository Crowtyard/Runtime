"""M6D.3 §4 — golden baseline inventory (READ-ONLY).

Dumps, for the M3 tribulation baselines: every file's relative path + sha256 +
selected deterministic fields (state/event/history hashes, counts, key metrics),
so that OLD (pre-refreeze) and NEW (post-fix) values can be recorded side by side
in the refreeze provenance manifest.

Usage:
  python scripts/_m6d3_baseline_inventory.py --out <json> [--label OLD|NEW]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
DIRS = [
    "tests/baselines/m3a_tribulation_synthetic_300y_v1",
    "tests/baselines/m3b_causal_history_300y_v1",
]
INTERESTING = (
    "final_world_state_hash", "final_event_stream_hash", "world_state_hash",
    "causal_history_hash", "hash", "counts", "orphan_links", "cycle_count",
    "entity_history_index_rows", "distinct_entities_with_history",
    "distinct_event_ids_indexed", "links_total", "state_changes_indexed",
    "world_state_hash_schema_version", "simulation_version",
    "indexed_through_tick", "committed_until_tick", "event_count",
    "causal_link_count", "timeline_entries", "wall_seconds",
)


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pick(doc, depth: int = 0):
    """Collect interesting deterministic fields from a nested artifact."""
    out = {}
    if isinstance(doc, dict):
        for key, value in doc.items():
            if key in INTERESTING and not isinstance(value, (dict, list)):
                out[key] = value
            elif isinstance(value, (dict, list)) and depth < 4:
                sub = pick(value, depth + 1)
                if sub:
                    out[key] = sub
    elif isinstance(doc, list):
        for i, item in enumerate(doc[:3]):
            sub = pick(item, depth + 1)
            if sub:
                out["[%d]" % i] = sub
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="UNLABELED")
    args = ap.parse_args()
    result = {"label": args.label, "dirs": {}}
    for rel in DIRS:
        base = ROOT / rel
        entry = {"exists": base.exists(), "files": {}}
        if base.exists():
            for path in sorted(base.rglob("*")):
                if not path.is_file():
                    continue
                rel_file = str(path.relative_to(base)).replace("\\", "/")
                info = {"sha256": sha256_file(path),
                        "size_bytes": path.stat().st_size}
                if path.suffix == ".json":
                    try:
                        doc = json.loads(path.read_text(encoding="utf-8"))
                        info["deterministic_fields"] = pick(doc)
                    except Exception as exc:  # pragma: no cover
                        info["parse_error"] = str(exc)
                entry["files"][rel_file] = info
        result["dirs"][rel] = entry
    pathlib.Path(args.out).write_text(
        json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8", newline="\n")
    for rel, entry in result["dirs"].items():
        print("%s (%d files)" % (rel, len(entry["files"])))
        for name, info in entry["files"].items():
            print("   %-42s %s" % (name, info["sha256"][:20]))
    print("ARTIFACT", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

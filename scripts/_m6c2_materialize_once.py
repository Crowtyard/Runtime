"""M6C.2 — single tick-0 materialization worker (TEST ONLY; used by the determinism driver).

One process = one fresh temp SQLite + one production Materializer call (no simulation).
Prints JSON: BOOTSTRAP_CANONICAL_HASH + per-table digests + counts + PYTHONHASHSEED.

Usage: python scripts/_m6c2_materialize_once.py --label A --out result.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT.parent), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _m6c2_support import build_empty_world  # noqa: E402
from XiaoguangBlessedLandRuntime.services.activation import (  # noqa: E402
    materializer as M)
from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease  # noqa: E402

WORLD_ID = "M6C2-DETERMINISM-001"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="A")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    work = pathlib.Path(tempfile.mkdtemp(prefix="m6c2_det_%s_" % args.label))
    env = build_empty_world(work, WORLD_ID)
    session = env["factory"]()
    try:
        lease = WriterLease(session, WORLD_ID, 300)
        lease.acquire(commit=False)
        result = M.materialize_snapshot_v1(
            session, world_id=WORLD_ID, writer_id=lease.owner,
            fencing_token=lease.token, blessed_tick=0)
        session.commit()
    finally:
        session.close()
    with env["factory"]() as session:
        projection = M.bootstrap_projection(session, WORLD_ID)
    tables = projection["projection"]["tables"]
    per_table = {t: hashlib.sha256(json.dumps(rows, sort_keys=True,
                                              ensure_ascii=False,
                                              separators=(",", ":")).encode("utf-8")
                                   ).hexdigest()
                 for t, rows in tables.items()}
    doc = {
        "label": args.label,
        "python_hashseed": os.environ.get("PYTHONHASHSEED", "<unset>"),
        "pid": os.getpid(),
        "world_id": WORLD_ID,
        "snapshot_sha256": M.SNAPSHOT_V1_SHA256,
        "projection_version": M.BOOTSTRAP_PROJECTION_VERSION,
        "BOOTSTRAP_CANONICAL_HASH": projection["BOOTSTRAP_CANONICAL_HASH"],
        "row_counts": projection["row_counts"],
        "per_table_digest": per_table,
        "materializer_counts": result["counts"],
        "cohort_rule": result["cohort_rule"],
    }
    pathlib.Path(args.out).write_text(
        json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8", newline="\n")
    print("WORKER " + json.dumps({k: doc[k] for k in (
        "label", "python_hashseed", "pid", "BOOTSTRAP_CANONICAL_HASH")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

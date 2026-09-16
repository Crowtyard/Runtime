"""M6A.1F §8/§9/§10 — PostgreSQL zero-row activation concurrency (two OS PROCESSES).

Runs only with BLR_TEST_PG_DSN + BLR_TEST_PG_ALLOW=1 (same gated contract as the other
PG suites); the DB name must contain "test" (fail-closed).  Fresh synthetic PG database,
canonical zero-row, then two independent OS processes call the production
activate_formal_world() concurrently.  Only real DB behaviour is recorded.

PG_ZERO_ROW_CONCURRENCY is required because services/activation/service.py and
services/writer_lock.py contain no dialect guard (SQLAlchemy-level code, dialect-agnostic),
i.e. M6_FORMAL_ACTIVATION_POSTGRES_SUPPORTED = TRUE.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile

import pytest
from sqlalchemy import text

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB_NAME = "blr_pg_zero_row_test"
WORLD_ID = "M6A1F-PG-CLAIM"
ANCHOR_A = 1_767_225_600_000_000
ANCHOR_B = 1_767_225_600_000_000 + 3_600_000_000
ZERO_TABLES = ("world_runtime", "runtime_lock", "time_ratio_history", "world_events")

CHILD = r'''
import json, pathlib, sys
root, url, seed_dir, anchor, out_path = sys.argv[1:6]
sys.path.insert(0, root)
sys.path.insert(0, str(pathlib.Path(root).parent))
from XiaoguangBlessedLandRuntime.database.db import create_db_engine, make_session_factory
from XiaoguangBlessedLandRuntime.services import repositories as repos
from XiaoguangBlessedLandRuntime.services import writer_lock as wl
counters = {"claim": 0, "fence": 0}
_c, _a = repos.RuntimeRepository.create_not_activated, wl.WriterLease.acquire
def claim(self, **kw):
    row = _c(self, **kw); counters["claim"] += 1; return row
def fence(self, *a, **kw):
    out = _a(self, *a, **kw); counters["fence"] += 1; return out
repos.RuntimeRepository.create_not_activated = claim
wl.WriterLease.acquire = fence
from XiaoguangBlessedLandRuntime.services.activation import activate_formal_world
from tests.m6_activation_support import synthetic_request
result = {}
try:
    outcome = activate_formal_world(make_session_factory(create_db_engine(url)),
        request=synthetic_request(pathlib.Path(seed_dir), world_id=sys.argv[6],
                                  activation_anchor_us=int(anchor)))
    result["outcome"] = getattr(outcome, "outcome", str(outcome))
except Exception as exc:
    result["outcome"] = type(exc).__name__
    result["detail"] = str(exc)[:200]
result.update(counters)          # 无论成功/失败都记录真实 claim/fence 计数
pathlib.Path(out_path).write_text(json.dumps(result), encoding="utf-8")
'''


def _require_pg():
    dsn = os.environ.get("BLR_TEST_PG_DSN")
    if not dsn or os.environ.get("BLR_TEST_PG_ALLOW") != "1":
        pytest.skip("PG gate requires BLR_TEST_PG_DSN + BLR_TEST_PG_ALLOW=1")
    if "test" not in dsn.lower():
        pytest.fail("refusing a non-test PG database (fail-closed)")
    return dsn


def _fresh_pg_db(dsn: str):
    """DROP+CREATE the dedicated test DB, migrate, assert canonical zero-row."""
    import psycopg
    from sqlalchemy.engine import make_url
    from XiaoguangBlessedLandRuntime.services.db_lifecycle import migrate_database
    url = make_url(dsn)
    # psycopg 需要 libpq conninfo（不是 SQLAlchemy 的 +psycopg URL）
    admin = url.set(database="blr_pre_m6").set(drivername="postgresql")
    with psycopg.connect(admin.render_as_string(hide_password=False),
                         autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{DB_NAME}"')
    target = str(url.set(database=DB_NAME).render_as_string(hide_password=False))
    migrate_database(target, project_root=ROOT)
    return target


def _counts(url: str) -> dict:
    from XiaoguangBlessedLandRuntime.database.db import (
        create_db_engine, make_session_factory)
    engine = create_db_engine(url)
    try:
        with make_session_factory(engine)() as s:
            return {t: int(s.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() or 0)
                    for t in ZERO_TABLES}
    finally:
        engine.dispose()


def test_m6a1pg_zero_row_concurrency_two_processes(tmp_path):
    dsn = _require_pg()
    url = _fresh_pg_db(dsn)
    assert _counts(url) == {t: 0 for t in ZERO_TABLES}

    from tests.m6_activation_support import build_synthetic_seed
    seed_dir = build_synthetic_seed(tmp_path, name="seed_pg")
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("BLR_TEST_PLUGIN_DATA_DIR", None)
    procs = []
    outs = []
    for anchor in (ANCHOR_A, ANCHOR_B):
        out_path = tmp_path / f"child_{anchor}.json"
        outs.append(out_path)
        procs.append(subprocess.Popen(
            [sys.executable, "-c", CHILD, str(ROOT), url, str(seed_dir),
             str(anchor), str(out_path), WORLD_ID],
            cwd=str(ROOT), env=env))
    for proc in procs:
        assert proc.wait(timeout=900) is not None
    results = [json.loads(p.read_text(encoding="utf-8")) for p in outs]
    outcomes = [r.get("outcome") for r in results]
    claims = sum(r.get("claim", 0) for r in results)
    fences = sum(r.get("fence", 0) for r in results)
    final = _counts(url)

    winner_claims = sum(r.get("claim", 0) for r in results
                        if r.get("outcome") == "COMMITTED")
    loser_fences = sum(r.get("fence", 0) for r in results
                       if r.get("outcome") != "COMMITTED")
    loser_outcome = [o for o in outcomes if o != "COMMITTED"]

    assert outcomes.count("COMMITTED") == 1, (outcomes, results, final)
    # §4/§11：只有 claim winner 能取得有效 activation fence
    assert winner_claims == 1, (winner_claims, results)
    assert fences == 1, (fences, results)
    assert loser_fences == 0, (loser_fences, results)
    assert final["world_runtime"] == 1 and final["time_ratio_history"] == 1
    assert final["world_events"] == 1, final
    assert final["runtime_lock"] <= 1
    # PG loser 的真实仲裁结果（§10：只记录真实 DB 行为）
    print("PG_CLAIM_WINNERS", winner_claims, "PG_FENCE_WINNERS", fences,
          "PG_COMMIT_WINNERS", outcomes.count("COMMITTED"),
          "PG_LOSER_OUTCOME", loser_outcome, "PG_LOSER_FENCES", loser_fences)

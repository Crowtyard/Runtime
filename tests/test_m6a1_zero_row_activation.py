"""M6A.1 — canonical ZERO-ROW activation entry contract (RED until the repair lands).

Owner §8: this test file was written BEFORE the production repair and currently
proves RED.  It uses a fresh file-backed migrated DB and calls the production
activation entrypoint directly — it must NOT pre-create a runtime row, seed
time_ratio_history, or use the legacy preseeded fixtures.

When the M6A.1 repair lands, remove the strict xfail marker: the contract test
must then pass as an ordinary test (a suite must never be kept green by expected
failures).
"""
from __future__ import annotations

import pathlib

import pytest
from sqlalchemy import text

from tests.m6_activation_support import build_synthetic_seed, synthetic_request

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORLD_ID = "M6A1-ZERO-ROW"
ANCHOR_US = 1_767_225_600_000_000
ZERO_TABLES = ("world_runtime", "runtime_lock", "time_ratio_history", "world_events")

#: §18 legacy preseeded fixtures — tokens assembled from parts so that this
#: scanner never matches its own literals (the previous version was a false
#: positive against itself).
_LEGACY_TOKENS = ("seed_" + "m6_world", "create_not_" + "activated",
                  "m6_" + "world(")


def _fresh_zero_row_env(tmp_path, tag: str = "zr"):
    """Fresh migrated FILE-BACKED DB in canonical zero-row state (nothing else)."""
    from XiaoguangBlessedLandRuntime.database.db import (
        create_db_engine, make_session_factory)
    from XiaoguangBlessedLandRuntime.services.db_lifecycle import migrate_database
    db_path = tmp_path / f"m6a1_{tag}.sqlite"
    url = "sqlite:///" + db_path.resolve().as_posix()
    migrate_database(url, project_root=ROOT)
    engine = create_db_engine(url)
    return {"url": url, "db_path": db_path, "engine": engine,
            "factory": make_session_factory(engine)}


def _counts(factory) -> dict:
    out = {}
    with factory() as s:
        for table in ZERO_TABLES:
            out[table] = int(s.execute(text(
                f"SELECT COUNT(*) FROM {table}")).scalar() or 0)
    return out


def test_m6a1_precondition_is_true_canonical_zero_row(tmp_path):
    """Precondition (PASSES today): canonical pre-activation state is 0 rows."""
    env = _fresh_zero_row_env(tmp_path, "pre")
    counts = _counts(env["factory"])
    assert counts == {t: 0 for t in ZERO_TABLES}, counts


def test_m6_activation_from_canonical_zero_row_state(tmp_path):
    """§11 contract: zero-row -> single atomic activation -> COMPLETE ACTIVE."""
    from XiaoguangBlessedLandRuntime.services.activation import (
        activate_formal_world)
    env = _fresh_zero_row_env(tmp_path, "activate")
    seed_dir = build_synthetic_seed(tmp_path, name="seed_zero_row")
    request = synthetic_request(seed_dir, world_id=WORLD_ID,
                                activation_anchor_us=ANCHOR_US)
    outcome = activate_formal_world(env["factory"], request=request)
    counts = _counts(env["factory"])
    assert counts["world_runtime"] == 1
    assert counts["world_events"] == 1
    with env["factory"]() as s:
        row = s.execute(text(
            "SELECT runtime_status, current_blessed_tick FROM world_runtime "
            "LIMIT 1")).one()
        assert row.runtime_status == "ACTIVE"
        assert row.current_blessed_tick == 0
        assert s.execute(text(
            "SELECT COUNT(*) FROM time_ratio_history")).scalar() == 1
    assert getattr(outcome, "outcome", None) in ("COMMITTED", "ALREADY_COMMITTED")


def test_m6a1_failed_activation_leaves_canonical_zero_row_state(tmp_path):
    """§12 rollback contract: a pre-commit failure must leave zero durable state
    (no placeholder runtime row, no orphan lock/rate/genesis)."""
    from XiaoguangBlessedLandRuntime.services.activation import (
        activate_formal_world)
    env = _fresh_zero_row_env(tmp_path, "rollback")
    seed_dir = build_synthetic_seed(tmp_path, name="seed_rollback")
    # 真正的 pre-commit 拒绝：非 canon initial tick（M6A ac06 同源语义）
    request = synthetic_request(seed_dir, world_id=WORLD_ID,
                                activation_anchor_us=ANCHOR_US,
                                initial_blessed_tick=1)
    with pytest.raises(Exception):
        activate_formal_world(env["factory"], request=request)
    counts = _counts(env["factory"])
    assert counts == {t: 0 for t in ZERO_TABLES}, counts
    # 拒绝后仍可从 canonical zero-row 正常激活（证明没有残留半状态阻塞）
    ok = activate_formal_world(
        env["factory"],
        request=synthetic_request(seed_dir, world_id=WORLD_ID,
                                  activation_anchor_us=ANCHOR_US))
    assert getattr(ok, "outcome", None) in ("COMMITTED", "ALREADY_COMMITTED")
    after = _counts(env["factory"])
    assert after["world_runtime"] == 1 and after["world_events"] == 1
    assert after["time_ratio_history"] >= 1


def test_m6a1_no_legacy_preseeded_fixture_is_used(tmp_path):
    """§18: this file must not depend on the legacy preseeded fixtures.

    Scans only CODE lines (comments/docstrings excluded) for the preseeded-helper
    call tokens, assembled from parts so the scanner cannot match itself.
    """
    source_lines = pathlib.Path(__file__).read_text(encoding="utf-8").splitlines()
    hits: list[tuple[int, str]] = []
    in_docstring = False
    for number, line in enumerate(source_lines, 1):
        stripped = line.strip()
        if stripped.count('"""') == 1:
            in_docstring = not in_docstring
            continue
        if in_docstring or stripped.startswith("#"):
            continue
        for token in _LEGACY_TOKENS:
            if token in line and "token" not in line:
                hits.append((number, token))
    assert hits == [], hits
    env = _fresh_zero_row_env(tmp_path, "nolegacy")
    assert _counts(env["factory"]) == {t: 0 for t in ZERO_TABLES}

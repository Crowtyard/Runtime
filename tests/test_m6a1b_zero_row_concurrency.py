"""M6A.1 §13/§14 — concurrent zero-row activation + fencing correctness.

Two INDEPENDENT engines/connections on the SAME file-backed database start from
world_runtime = 0 and call the production entrypoint at the same time.  Exactly one
may become ACTIVE; the durable state must show exactly one world, one initial rate
binding, one seed consumption and one genesis, with no loser residue.

(Threads with separate engine instances = separate DBAPI connections.  Two OS
processes would be stronger; that is recorded as a residual limitation.)
"""
from __future__ import annotations

import pathlib
import threading

import pytest
from sqlalchemy import text

from tests.m6_activation_support import build_synthetic_seed, synthetic_request
from tests.test_m6a1_zero_row_activation import _fresh_zero_row_env

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORLD_ID = "M6A1-CONCURRENT"
ANCHOR_A = 1_767_225_600_000_000
ANCHOR_B = 1_767_225_600_000_000 + 86_400_000_000


def _activate_in_thread(url: str, seed_dir, anchor: int, out: dict, key: str) -> None:
    from XiaoguangBlessedLandRuntime.database.db import (
        create_db_engine, make_session_factory)
    from XiaoguangBlessedLandRuntime.services.activation import (
        activate_formal_world)
    engine = create_db_engine(url)          # its own pool + connections
    factory = make_session_factory(engine)
    try:
        outcome = activate_formal_world(factory, request=synthetic_request(
            seed_dir, world_id=WORLD_ID, activation_anchor_us=anchor))
        out[key] = getattr(outcome, "outcome", str(outcome))
    except Exception as exc:  # noqa: BLE001
        out[key] = f"{type(exc).__name__}: {exc}"
    finally:
        engine.dispose()


def test_m6a1b_concurrent_zero_row_activation_single_winner(tmp_path):
    env = _fresh_zero_row_env(tmp_path, "concurrent")
    seed_dir = build_synthetic_seed(tmp_path, name="seed_concurrent")
    results: dict = {}
    threads = [
        threading.Thread(target=_activate_in_thread,
                         args=(env["url"], seed_dir, ANCHOR_A, results, "A")),
        threading.Thread(target=_activate_in_thread,
                         args=(env["url"], seed_dir, ANCHOR_B, results, "B")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert set(results) == {"A", "B"}, results
    committed = [k for k, v in results.items() if v == "COMMITTED"]
    assert len(committed) == 1, results
    assert results["A"] == "COMMITTED" or results["B"] == "COMMITTED"

    with env["factory"]() as s:
        assert int(s.execute(text("SELECT COUNT(*) FROM world_runtime")).scalar()) == 1
        assert int(s.execute(text(
            "SELECT COUNT(*) FROM world_events WHERE event_type="
            "'WORLD_SEED_ACTIVATED'")).scalar()) == 1
        assert int(s.execute(text(
            "SELECT COUNT(*) FROM time_ratio_history")).scalar()) == 1
        assert int(s.execute(text("SELECT COUNT(*) FROM runtime_lock")).scalar()) <= 1
        row = s.execute(text("SELECT runtime_status, current_blessed_tick "
                             "FROM world_runtime LIMIT 1")).one()
        assert row.runtime_status == "ACTIVE" and row.current_blessed_tick == 0
    ACT_RESULTS = results
    assert "COMMITTED" in ACT_RESULTS.values()


def test_m6a1b_loser_leaves_no_residue_and_second_activation_is_idempotent(tmp_path):
    """胜利者只有一个 anchor；第二次 activation 零写入。"""
    from XiaoguangBlessedLandRuntime.services.activation import (
        activate_formal_world)
    env = _fresh_zero_row_env(tmp_path, "idem")
    seed_dir = build_synthetic_seed(tmp_path, name="seed_idem")
    first = activate_formal_world(env["factory"], request=synthetic_request(
        seed_dir, world_id=WORLD_ID, activation_anchor_us=ANCHOR_A))
    assert getattr(first, "outcome", None) == "COMMITTED"

    def state() -> dict:
        with env["factory"]() as s:
            return {
                "worlds": int(s.execute(text("SELECT COUNT(*) FROM world_runtime")).scalar()),
                "events": int(s.execute(text("SELECT COUNT(*) FROM world_events")).scalar()),
                "genesis": int(s.execute(text(
                    "SELECT COUNT(*) FROM world_events WHERE event_type="
                    "'WORLD_SEED_ACTIVATED'")).scalar()),
                "rates": int(s.execute(text(
                    "SELECT COUNT(*) FROM time_ratio_history")).scalar()),
                "tick": s.execute(text("SELECT current_blessed_tick FROM "
                                       "world_runtime LIMIT 1")).scalar(),
            }

    before = state()
    # (a) 同一 anchor 重试 → canonical ALREADY_COMMITTED（零写入）
    same = activate_formal_world(env["factory"], request=synthetic_request(
        seed_dir, world_id=WORLD_ID, activation_anchor_us=ANCHOR_A))
    assert getattr(same, "outcome", None) in ("ALREADY_COMMITTED",)
    # (b) 不同 anchor → canonical idempotent rejection（禁止改写 anchor）
    from XiaoguangBlessedLandRuntime.domain.errors import ActivationRefused
    with pytest.raises(ActivationRefused):
        activate_formal_world(env["factory"], request=synthetic_request(
            seed_dir, world_id=WORLD_ID, activation_anchor_us=ANCHOR_B))
    after = state()
    assert before == after, (before, after)
    assert after["worlds"] == 1 and after["genesis"] == 1 and after["rates"] == 1
    assert after["tick"] == 0

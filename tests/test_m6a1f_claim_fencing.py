"""M6A.1F — two-stage zero-row activation ownership: CLAIM then FENCE.

Owner-approved protocol C:
  Stage 1 TRANSACTIONAL ACTIVATION CLAIM = the unique, still-uncommitted insertion of
          world_runtime(world_id) inside the activation transaction.
  Stage 2 WRITER LEASE / FENCING        = only the claim holder may call
          WriterLease.acquire(commit=False); then rate binding / seed truth /
          ACTIVE+tick0+anchor / genesis / commit.

This module PROVES (or falsifies) the two invariants:
  CAN_TWO_ACTIVATORS_BOTH_PASS_ACTIVATION_CLAIM          == FALSE
  CAN_TWO_ACTIVATORS_BOTH_ACQUIRE_VALID_ACTIVATION_FENCE == FALSE

Production is instrumented only through test-side monkeypatch wrappers (§5); no
production logging, no seed exposure, no Runtime API pollution.
"""
from __future__ import annotations

import pathlib
import threading
from collections import defaultdict

import pytest
from sqlalchemy import text

from tests.m6_activation_support import build_synthetic_seed, synthetic_request
from tests.test_m6a1_zero_row_activation import _fresh_zero_row_env

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORLD_ID = "M6A1F-CLAIM"
ANCHOR_A = 1_767_225_600_000_000
ANCHOR_B = 1_767_225_600_000_000 + 3_600_000_000
ITERATIONS = 20

_EVENTS: dict[str, dict] = defaultdict(lambda: defaultdict(int))
_LOCK = threading.Lock()


def _bump(key: str) -> None:
    with _LOCK:
        _EVENTS[threading.current_thread().name][key] += 1


def _reset() -> None:
    with _LOCK:
        _EVENTS.clear()


def _install_instrumentation(monkeypatch) -> None:
    """Claim = world_runtime insertion; Fence = WriterLease.acquire."""
    from XiaoguangBlessedLandRuntime.services import repositories as repos
    from XiaoguangBlessedLandRuntime.services import writer_lock as wl

    original_create = repos.RuntimeRepository.create_not_activated
    original_acquire = wl.WriterLease.acquire

    def create(self, **kwargs):  # noqa: ANN001
        _bump("CLAIM_ATTEMPTED")
        try:
            row = original_create(self, **kwargs)
        except Exception:
            _bump("CLAIM_REJECTED")
            raise
        _bump("CLAIM_ACQUIRED")
        return row

    def acquire(self, *args, **kwargs):  # noqa: ANN001
        _bump("FENCE_ATTEMPTED")
        try:
            out = original_acquire(self, *args, **kwargs)
        except Exception:
            _bump("FENCE_REJECTED")
            raise
        _bump("FENCE_ACQUIRED")
        return out

    monkeypatch.setattr(repos.RuntimeRepository, "create_not_activated", create)
    monkeypatch.setattr(wl.WriterLease, "acquire", acquire)


def _activate_once(url: str, seed_dir, anchor: int, activator: str,
                   results: dict) -> None:
    from XiaoguangBlessedLandRuntime.database.db import (
        create_db_engine, make_session_factory)
    from XiaoguangBlessedLandRuntime.services.activation import (
        activate_formal_world)
    old = threading.current_thread().name
    threading.current_thread().name = activator      # ACTIVATOR_ID for instrumentation
    engine = create_db_engine(url)                   # own pool + own connection
    factory = make_session_factory(engine)
    try:
        outcome = activate_formal_world(factory, request=synthetic_request(
            seed_dir, world_id=WORLD_ID, activation_anchor_us=anchor))
        results[activator] = getattr(outcome, "outcome", str(outcome))
    except Exception as exc:  # noqa: BLE001
        results[activator] = f"{type(exc).__name__}"
    finally:
        engine.dispose()
        threading.current_thread().name = old


def _run_pair(env, seed_dir, anchor_a=ANCHOR_A, anchor_b=ANCHOR_B) -> dict:
    results: dict = {}
    threads = [
        threading.Thread(target=_activate_once,
                         args=(env["url"], seed_dir, anchor_a, "A", results)),
        threading.Thread(target=_activate_once,
                         args=(env["url"], seed_dir, anchor_b, "B", results)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=180)
    return results


def _durable_state(env) -> dict:
    with env["factory"]() as s:
        return {
            "worlds": int(s.execute(text("SELECT COUNT(*) FROM world_runtime")).scalar()),
            "rates": int(s.execute(text("SELECT COUNT(*) FROM time_ratio_history")).scalar()),
            "genesis": int(s.execute(text(
                "SELECT COUNT(*) FROM world_events WHERE event_type="
                "'WORLD_SEED_ACTIVATED'")).scalar()),
            "locks": int(s.execute(text("SELECT COUNT(*) FROM runtime_lock")).scalar()),
            "tick": s.execute(text("SELECT current_blessed_tick FROM world_runtime "
                                   "LIMIT 1")).scalar(),
        }


@pytest.mark.parametrize("iteration", range(ITERATIONS))
def test_m6a1f_two_activators_claim_then_fence(tmp_path, monkeypatch, iteration):
    """§6: 20 real concurrent zero-row activations on file-backed SQLite."""
    _reset()
    _install_instrumentation(monkeypatch)
    env = _fresh_zero_row_env(tmp_path, f"claim{iteration}")
    seed_dir = build_synthetic_seed(tmp_path, name=f"seed{iteration}")
    results = _run_pair(env, seed_dir)

    claims = sum(v.get("CLAIM_ACQUIRED", 0) for v in _EVENTS.values())
    fences = sum(v.get("FENCE_ACQUIRED", 0) for v in _EVENTS.values())
    commits = [k for k, v in results.items() if v == "COMMITTED"]
    state = _durable_state(env)

    assert claims == 1, (iteration, dict(_EVENTS), results)
    assert fences == 1, (iteration, dict(_EVENTS), results)
    assert len(commits) == 1, (iteration, results, dict(_EVENTS))
    assert state["worlds"] == 1 and state["rates"] == 1 and state["genesis"] == 1
    assert state["tick"] == 0
    assert state["locks"] <= 1
    # 落败方不得留下任何残留（无第二世界/第二 rate/第二 genesis）
    assert state["genesis"] == 1


def test_m6a1f_claim_rollback_takeover(tmp_path, monkeypatch):
    """§8: a rolled-back claim leaves no zombie ownership; the survivor activates."""
    from XiaoguangBlessedLandRuntime.services import repositories as repos

    _reset()
    _install_instrumentation(monkeypatch)
    env = _fresh_zero_row_env(tmp_path, "takeover")
    seed_dir = build_synthetic_seed(tmp_path, name="seed_takeover")

    # Activator A claims (transient world_runtime insert) then faults before the fence
    original_create = repos.RuntimeRepository.create_not_activated
    state = {"armed": True}

    def create_then_fault(self, **kwargs):  # noqa: ANN001
        row = original_create(self, **kwargs)
        self.session.flush()
        if state["armed"]:
            state["armed"] = False
            _bump("CLAIM_ACQUIRED")
            # 模拟真实 fault 处理器的 rollback+close（若不清理会一直持有 SQLite
            # 写锁，进程内第二个 activator 会拿到 OperationalError 而不是 clean
            # 的 canonical 结果 —— 该运维事实记录在 M6A.1F 报告中）。
            self.session.rollback()
            self.session.close()
            raise RuntimeError("injected fault after claim, before fence")
        _bump("CLAIM_ACQUIRED")
        return row

    monkeypatch.setattr(repos.RuntimeRepository, "create_not_activated",
                        create_then_fault)
    results: dict = {}
    _activate_once(env["url"], seed_dir, ANCHOR_A, "A", results)
    assert results["A"].startswith("RuntimeError"), results
    after_fault = _durable_state(env)
    assert after_fault["worlds"] == 0, after_fault        # claim rolled back fully
    assert after_fault["rates"] == 0 and after_fault["genesis"] == 0

    # Survivor B can claim, fence and complete on the same DB
    monkeypatch.setattr(repos.RuntimeRepository, "create_not_activated",
                        original_create)
    _activate_once(env["url"], seed_dir, ANCHOR_B, "B", results)
    assert results["B"] == "COMMITTED", results
    final = _durable_state(env)
    assert final["worlds"] == 1 and final["rates"] == 1 and final["genesis"] == 1
    assert final["tick"] == 0


def test_m6a1f_fence_is_required_after_claim(tmp_path, monkeypatch):
    """§3 CLAIM_OWNER_ACQUIRES_FENCE: a claim without a fence must not activate."""
    from XiaoguangBlessedLandRuntime.services import writer_lock as wl

    _reset()
    _install_instrumentation(monkeypatch)

    def failing_acquire(self, *args, **kwargs):  # noqa: ANN001
        _bump("FENCE_ATTEMPTED")
        _bump("FENCE_REJECTED")
        raise wl.WriterLockConflict("injected fence failure",
                                    detail={"world_id": self.world_id})

    monkeypatch.setattr(wl.WriterLease, "acquire", failing_acquire)
    env = _fresh_zero_row_env(tmp_path, "nofence")
    seed_dir = build_synthetic_seed(tmp_path, name="seed_nofence")
    results: dict = {}
    _activate_once(env["url"], seed_dir, ANCHOR_A, "A", results)
    assert not results["A"] == "COMMITTED", results
    state = _durable_state(env)
    assert state == {"worlds": 0, "rates": 0, "genesis": 0, "locks": 0, "tick": None}, state
    assert sum(v.get("CLAIM_ACQUIRED", 0) for v in _EVENTS.values()) == 1
    assert sum(v.get("FENCE_REJECTED", 0) for v in _EVENTS.values()) == 1

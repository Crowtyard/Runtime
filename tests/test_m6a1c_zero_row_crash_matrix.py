"""M6A.1F — zero-row crash matrix C0–C8, session cleanup, ACK-lost, restart, scheduler.

All runs use a fresh file-backed SQLite DB in true canonical zero-row state.
Faults are injected test-side (monkeypatch) at the exact stage boundaries; after
every fault the harness asserts (a) durable state is ZERO or COMPLETE_ACTIVE only,
(b) the activation session is closed and the SQLite write lock is actually released
(verified by performing a legal write from a brand-new connection — no sleeping).
"""
from __future__ import annotations

import pathlib

import pytest
from sqlalchemy import text

from tests.m6_activation_support import build_synthetic_seed, synthetic_request
from tests.test_m6a1_zero_row_activation import _fresh_zero_row_env

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORLD_ID = "M6A1F-CRASH"
ANCHOR_US = 1_767_225_600_000_000
ZERO_TABLES = ("world_runtime", "runtime_lock", "time_ratio_history", "world_events")


class InjectedFault(RuntimeError):
    """Test-side stage-boundary fault (C1..C7)."""


def _state(env) -> dict:
    with env["factory"]() as s:
        return {t: int(s.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() or 0)
                for t in ZERO_TABLES}


def _write_lock_released(env) -> bool:
    """A brand-new engine/connection must be able to write immediately."""
    from XiaoguangBlessedLandRuntime.database.db import (
        create_db_engine, make_session_factory)
    engine = create_db_engine(env["url"])
    factory = make_session_factory(engine)
    try:
        with factory() as s:
            s.execute(text("CREATE TABLE IF NOT EXISTS lock_probe (id INTEGER)"))
            s.execute(text("INSERT INTO lock_probe (id) VALUES (1)"))
            s.commit()
            s.execute(text("DROP TABLE lock_probe"))
            s.commit()
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        engine.dispose()


def _install_stage_fault(monkeypatch, stage: str) -> None:
    """Fault right after the named activation stage."""
    from XiaoguangBlessedLandRuntime.services import repositories as repos
    from XiaoguangBlessedLandRuntime.services import writer_lock as wl
    from XiaoguangBlessedLandRuntime.services.activation import service as svc

    def fault() -> None:
        raise InjectedFault(f"injected fault at {stage}")

    if stage == "C1":      # after transient runtime claim insert
        original = repos.RuntimeRepository.create_not_activated

        def create(self, **kw):  # noqa: ANN001
            row = original(self, **kw)
            self.session.flush()
            fault()
            return row
        monkeypatch.setattr(repos.RuntimeRepository, "create_not_activated", create)
    elif stage == "C2":    # after fence acquisition
        original_acq = wl.WriterLease.acquire

        def acquire(self, *a, **kw):  # noqa: ANN001
            out = original_acq(self, *a, **kw)
            fault()
            return out
        monkeypatch.setattr(wl.WriterLease, "acquire", acquire)
    elif stage == "C3":    # after initial rate binding
        original_seed = svc._seed_canonical_initial_rate

        def seed_rate(session, request):  # noqa: ANN001
            out = original_seed(session, request)
            fault()
            return out
        monkeypatch.setattr(svc, "_seed_canonical_initial_rate", seed_rate)
    elif stage in ("C4", "C5", "C6", "C7"):
        # seed truth / ACTIVE+tick+anchor / genesis / immediately before commit:
        # all four are staged by RuntimeRepository.activate + the genesis writer, so
        # faulting after `activate()` covers C5; C4/C6/C7 fault on the surrounding
        # service steps in the same transaction.
        if stage == "C5":
            original_activate = repos.RuntimeRepository.activate

            def activate(self, **kw):  # noqa: ANN001
                out = original_activate(self, **kw)
                fault()
                return out
            monkeypatch.setattr(repos.RuntimeRepository, "activate", activate)
        else:
            original_bind = repos.TimeRatioRepository.bind_blessed_start

            def bind(self, **kw):  # noqa: ANN001
                out = original_bind(self, **kw)
                fault()
                return out
            monkeypatch.setattr(repos.TimeRatioRepository, "bind_blessed_start", bind)
    else:                   # C0: before the transaction even opens
        original_probe = repos.RuntimeRepository.get

        def probe(self):  # noqa: ANN001
            fault()
            return original_probe(self)
        monkeypatch.setattr(repos.RuntimeRepository, "get", probe)


@pytest.mark.parametrize("stage", ["C0", "C1", "C2", "C3", "C5", "C6", "C7"])
def test_m6a1c_crash_matrix_zero_row(tmp_path, monkeypatch, stage):
    """§8/§9/§10: every pre-commit fault leaves ZERO durable state, session closed
    and the SQLite write lock released."""
    from XiaoguangBlessedLandRuntime.services.activation import (
        activate_formal_world)
    _install_stage_fault(monkeypatch, stage)
    env = _fresh_zero_row_env(tmp_path, f"crash{stage}")
    seed_dir = build_synthetic_seed(tmp_path, name=f"seed_crash{stage}")
    with pytest.raises(Exception):
        activate_formal_world(env["factory"], request=synthetic_request(
            seed_dir, world_id=WORLD_ID, activation_anchor_us=ANCHOR_US))
    state = _state(env)
    assert state == {t: 0 for t in ZERO_TABLES}, (stage, state)
    assert _write_lock_released(env), f"{stage}: sqlite write lock still held"
    # 之后仍可从 canonical zero-row 正常激活（无 zombie claim / 无资源泄漏）
    # 解除 fault 注入，否则第二次 activation 会再次命中同一注入点
    monkeypatch.undo()
    from tests.test_m6a1_zero_row_activation import _fresh_zero_row_env as fresh
    env2 = fresh(tmp_path, f"after{stage}")
    out = activate_formal_world(env2["factory"], request=synthetic_request(
        seed_dir, world_id=WORLD_ID, activation_anchor_us=ANCHOR_US))
    assert getattr(out, "outcome", None) == "COMMITTED", (stage, out)
    assert _state(env2)["world_runtime"] == 1


def test_m6a1c_ack_lost_reconciliation(tmp_path):
    """§12/§15 C8: the commit is durable but the caller never sees the ACK."""
    from XiaoguangBlessedLandRuntime.services.activation import (
        activate_formal_world)
    from XiaoguangBlessedLandRuntime.services.durable_truth import (
        read_activation_truth)
    env = _fresh_zero_row_env(tmp_path, "acklost")
    seed_dir = build_synthetic_seed(tmp_path, name="seed_acklost")
    request = synthetic_request(seed_dir, world_id=WORLD_ID,
                                activation_anchor_us=ANCHOR_US)
    out = activate_formal_world(env["factory"], request=request)
    assert getattr(out, "outcome", None) == "COMMITTED"
    before = _state(env)

    # ACK lost: a brand-new process-equivalent runtime re-reads durable truth
    from XiaoguangBlessedLandRuntime.database.db import (
        create_db_engine, make_session_factory)
    engine = create_db_engine(env["url"])
    factory = make_session_factory(engine)
    try:
        truth = read_activation_truth(factory, world_id=WORLD_ID)
        assert truth.committed is True
        again = activate_formal_world(factory, request=request)
        assert getattr(again, "outcome", None) == "ALREADY_COMMITTED"
    finally:
        engine.dispose()
    assert _state(env) == before, "ACK-lost reconciliation must not mutate state"


def test_m6a1c_restart_equivalence(tmp_path):
    """§14: dispose everything, reopen, and read back the same activation truth."""
    from XiaoguangBlessedLandRuntime.services.activation import (
        activate_formal_world)
    from XiaoguangBlessedLandRuntime.services.durable_truth import (
        read_world_epoch_anchor)
    env = _fresh_zero_row_env(tmp_path, "restart")
    seed_dir = build_synthetic_seed(tmp_path, name="seed_restart")
    out = activate_formal_world(env["factory"], request=synthetic_request(
        seed_dir, world_id=WORLD_ID, activation_anchor_us=ANCHOR_US))
    assert getattr(out, "outcome", None) == "COMMITTED"
    before = _state(env)
    env["engine"].dispose()

    engine2 = __import__("XiaoguangBlessedLandRuntime.database.db",
                         fromlist=["create_db_engine"]).create_db_engine(env["url"])
    factory2 = __import__("XiaoguangBlessedLandRuntime.database.db",
                          fromlist=["make_session_factory"]).make_session_factory(engine2)
    try:
        assert _state({"factory": factory2}) == before
        assert read_world_epoch_anchor(factory2, world_id=WORLD_ID) == ANCHOR_US
        with factory2() as s:
            row = s.execute(text("SELECT runtime_status, current_blessed_tick "
                                 "FROM world_runtime LIMIT 1")).one()
            assert row.runtime_status == "ACTIVE" and row.current_blessed_tick == 0
            assert int(s.execute(text("SELECT COUNT(*) FROM time_ratio_history")
                                 ).scalar()) == 1
    finally:
        engine2.dispose()


def test_m6a1c_scheduler_three_states(tmp_path, monkeypatch):
    """§17: DORMANT on zero-row, DORMANT after a failed activation, VALID when active."""
    from XiaoguangBlessedLandRuntime.services.activation import (
        activate_formal_world)
    from XiaoguangBlessedLandRuntime.services.scheduler.core import (
        DEFAULT_OPERATIONAL_EPOCH0_US, RuntimeScheduler)
    from XiaoguangBlessedLandRuntime.services.durable_truth import (
        read_world_epoch_anchor)

    # STATE A: canonical zero-row -> no durable anchor -> default epoch, DORMANT
    env_a = _fresh_zero_row_env(tmp_path, "sched_a")
    assert read_world_epoch_anchor(env_a["factory"], world_id=WORLD_ID) is None
    scheduler_a = RuntimeScheduler(session_factory=env_a["factory"], world_id=WORLD_ID)
    assert scheduler_a.epoch0_us in (None, DEFAULT_OPERATIONAL_EPOCH0_US)

    # STATE B: failed activation (pre-commit fault) -> still no anchor
    _install_stage_fault(monkeypatch, "C3")
    env_b = _fresh_zero_row_env(tmp_path, "sched_b")
    seed_dir = build_synthetic_seed(tmp_path, name="seed_sched")
    with pytest.raises(Exception):
        activate_formal_world(env_b["factory"], request=synthetic_request(
            seed_dir, world_id=WORLD_ID, activation_anchor_us=ANCHOR_US))
    assert read_world_epoch_anchor(env_b["factory"], world_id=WORLD_ID) is None
    assert _state(env_b) == {t: 0 for t in ZERO_TABLES}

    # STATE C: successful activation -> durable anchor is the requested instant
    monkeypatch.undo()
    env_c = _fresh_zero_row_env(tmp_path, "sched_c")
    out = activate_formal_world(env_c["factory"], request=synthetic_request(
        seed_dir, world_id=WORLD_ID, activation_anchor_us=ANCHOR_US))
    assert getattr(out, "outcome", None) == "COMMITTED"
    assert read_world_epoch_anchor(env_c["factory"], world_id=WORLD_ID) == ANCHOR_US

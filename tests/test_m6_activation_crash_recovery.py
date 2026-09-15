# -*- coding: utf-8 -*-
"""M6A-CR —— 激活崩溃矩阵（owner §22）。

在每个注入点崩溃后，durable truth 必须满足：

```
0 worlds  or  exactly 1 committed world
```

绝不允许：half world / second world / double seed consumption。
崩溃后重试必须收敛到**恰好一个**已提交世界（且 seed 消费次数 ≤ 1）。
"""
from __future__ import annotations

import pytest
from sqlalchemy import exc as sa_exc, select

from tests.m6_activation_support import (
    build_synthetic_seed, synthetic_request, world_counts)

from XiaoguangBlessedLandRuntime.database.models_core import WorldRuntime
from XiaoguangBlessedLandRuntime.domain.errors import ActivationOutcomeUnknown
from XiaoguangBlessedLandRuntime.services.activation import (
    OUTCOME_ALREADY_COMMITTED, OUTCOME_COMMITTED, activate_formal_world)


def _injected_dbapi_error() -> sa_exc.DBAPIError:
    """真实 DBAPIError 实例（COMMIT 期间连接故障的等价物）。"""
    return sa_exc.OperationalError("COMMIT", {}, RuntimeError("injected"))


def _activate(seed_dir, factory):
    return activate_formal_world(factory,
                                 request=synthetic_request(seed_dir))


def _invariant(counts: dict) -> None:
    """§22 不变量：0 个世界，或恰好 1 个已提交世界。"""
    assert counts["world_runtime_rows"] in (0, 1), counts
    assert counts["active_worlds"] in (0, 1), counts
    assert counts["genesis_events"] in (0, 1), counts
    assert counts["active_worlds"] == counts["genesis_events"], counts
    # 速率行"已开始计"必须与激活严格同步（绝不半绑定）
    assert (counts["rate_blessed_starts"] == [None]) == \
        (counts["active_worlds"] == 0), counts


# ------------------------------------------------------------------ crash points
def _install(monkeypatch, point: str, tmp_path):  # noqa: ANN001
    """在指定协议阶段注入崩溃；返回会被抛出的异常类型。"""
    from XiaoguangBlessedLandRuntime.services.activation import service as svc
    from XiaoguangBlessedLandRuntime.services.fencing import (
        WorldMutationContext)
    from XiaoguangBlessedLandRuntime.services.repositories import (
        RuntimeRepository)

    if point == "before_seed_read":
        def boom(*a, **k):
            raise RuntimeError("crash: before seed read")
        monkeypatch.setattr(svc, "load_seed_package", boom)
        return RuntimeError

    if point == "after_seed_read":
        real = svc.load_seed_package

        def after(*a, **k):
            pkg = real(*a, **k)
            assert pkg.manifest_entries > 0
            raise RuntimeError("crash: after synthetic seed read")
        monkeypatch.setattr(svc, "load_seed_package", after)
        return RuntimeError

    if point == "during_bootstrap_preparation":
        def boom(*a, **k):
            raise RuntimeError("crash: during bootstrap preparation")
        monkeypatch.setattr(svc, "_effective_ratio", boom)
        return RuntimeError

    if point == "before_db_transaction":
        def boom(*a, **k):
            raise RuntimeError("crash: before db transaction")
        monkeypatch.setattr(svc, "WorldMutationContext", boom)
        return RuntimeError

    if point == "inside_transaction":
        real_activate = RuntimeRepository.activate

        def partial(self, **kw):
            real_activate(self, **kw)          # 已写入，但事务尚未提交
            raise RuntimeError("crash: inside transaction")
        monkeypatch.setattr(RuntimeRepository, "activate", partial)
        return RuntimeError

    if point == "before_commit":
        def boom(self):
            raise RuntimeError("crash: before commit")
        monkeypatch.setattr(WorldMutationContext, "commit", boom)
        return RuntimeError

    if point == "after_commit_before_ack":
        real_commit = WorldMutationContext.commit

        def commit_then_die(self):
            real_commit(self)                  # durable commit 已发生
            raise _injected_dbapi_error()      # ACK 丢失
        monkeypatch.setattr(WorldMutationContext, "commit", commit_then_die)
        return None                        # 服务自行 reconcile，不抛出

    if point == "after_ack_before_state_update":
        real_commit = WorldMutationContext.commit

        def commit_then_die(self):
            real_commit(self)
            raise _injected_dbapi_error()
        monkeypatch.setattr(WorldMutationContext, "commit", commit_then_die)
        # durable truth 也读不到 → fail-closed（ActivationOutcomeUnknown）
        monkeypatch.setattr(svc, "_reconcile_after_unknown_commit",
                            lambda *a, **k: None)
        return ActivationOutcomeUnknown

    raise AssertionError(f"unknown crash point {point}")


CRASH_POINTS = (
    "before_seed_read",
    "after_seed_read",
    "during_bootstrap_preparation",
    "before_db_transaction",
    "inside_transaction",
    "before_commit",
    "after_commit_before_ack",
    "after_ack_before_state_update",
)


@pytest.mark.parametrize("point", CRASH_POINTS)
def test_m6cr01_crash_matrix_zero_or_exactly_one_world(
        tmp_path, m6_world, monkeypatch, point):
    seed_dir = build_synthetic_seed(tmp_path)
    expected_exc = _install(monkeypatch, point, tmp_path)

    if expected_exc is not None:
        with pytest.raises(expected_exc):
            _activate(seed_dir, m6_world)
    else:
        out = _activate(seed_dir, m6_world)
        assert out.outcome == OUTCOME_COMMITTED
        assert out.commit_outcome_was_ambiguous is True   # 走了 ambiguity 路径 verify
        assert out.written is False                       # 本次调用未再写入

    counts = world_counts(m6_world)
    _invariant(counts)

    # 重试（新的一次调用 = 模拟重启后的恢复）必须收敛到恰好 1 个已提交世界
    monkeypatch.undo()
    retry = _activate(seed_dir, m6_world)
    assert retry.outcome in (OUTCOME_COMMITTED, OUTCOME_ALREADY_COMMITTED)
    after = world_counts(m6_world)
    _invariant(after)
    assert after["active_worlds"] == 1
    assert after["genesis_events"] == 1
    assert after["world_runtime_rows"] == 1
    with m6_world() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        assert row.runtime_status == "ACTIVE"
        assert row.world_seed_version == "1.0"


@pytest.mark.parametrize("point", ["before_commit", "inside_transaction",
                                   "before_db_transaction"])
def test_m6cr02_precommit_crashes_leave_absolutely_no_partial_state(
        tmp_path, m6_world, monkeypatch, point):
    """提交前崩溃：速率行必须仍为"未开始计"，时钟仍为 NULL（A5）。"""
    seed_dir = build_synthetic_seed(tmp_path)
    _install(monkeypatch, point, tmp_path)
    with pytest.raises(RuntimeError):
        _activate(seed_dir, m6_world)
    counts = world_counts(m6_world)
    assert counts["active_worlds"] == 0
    assert counts["genesis_events"] == 0
    assert counts["world_events"] == 0
    assert counts["rate_blessed_starts"] == [None]
    assert counts["runtime_lock_rows"] == 0
    with m6_world() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        assert row.runtime_status == "NOT_ACTIVATED"
        assert row.world_seed_version is None
        assert row.current_blessed_tick is None
        assert row.last_committed_real_us is None


def test_m6cr03_unknown_outcome_never_blind_retries(tmp_path, m6_world,
                                                    monkeypatch):
    """§16：commit 结果未知且 truth 不可读 → fail-closed，且**不得**自动重试。"""
    seed_dir = build_synthetic_seed(tmp_path)
    calls = {"n": 0}
    real_commit = None

    from XiaoguangBlessedLandRuntime.services.activation import service as svc
    from XiaoguangBlessedLandRuntime.services.fencing import (
        WorldMutationContext)

    real_commit = WorldMutationContext.commit

    def commit_then_die(self):
        calls["n"] += 1
        real_commit(self)
        raise _injected_dbapi_error()

    monkeypatch.setattr(WorldMutationContext, "commit", commit_then_die)
    monkeypatch.setattr(svc, "_reconcile_after_unknown_commit",
                        lambda *a, **k: None)

    with pytest.raises(ActivationOutcomeUnknown):
        _activate(seed_dir, m6_world)
    assert calls["n"] == 1                     # 只尝试过一次 commit（无盲重试）
    counts = world_counts(m6_world)
    _invariant(counts)
    assert counts["active_worlds"] == 1        # 事实上已提交（ACK 丢失）

# -*- coding: utf-8 -*-
"""M6A-SW —— 激活的单写者 / fencing（owner §15）。

要求（两个 Activator 竞争时）：

```
ACTIVATION_WINNERS    = 1
FORMAL_WORLD_COUNT    = 1
SEED_CONSUMPTION_COUNT = 1
```

并且：被接管的旧 writer（stale fencing token）**永远不能提交**激活事务。
"""
from __future__ import annotations

import threading
import time

import pytest
from sqlalchemy import select

from tests.conftest import W
from tests.m6_activation_support import (
    build_synthetic_seed, synthetic_request, world_counts)

from XiaoguangBlessedLandRuntime.database.models_core import (
    RuntimeLock, WorldRuntime)
from XiaoguangBlessedLandRuntime.domain.errors import (
    ActivationRefused, FencingViolation)
from XiaoguangBlessedLandRuntime.services.activation import (
    OUTCOME_COMMITTED, activate_formal_world)
from XiaoguangBlessedLandRuntime.services.fencing import WorldMutationContext
from XiaoguangBlessedLandRuntime.services.repositories import RuntimeRepository
from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease


def _activate(seed_dir, factory):
    return activate_formal_world(factory,
                                 request=synthetic_request(seed_dir))


# ------------------------------------------------------------------ SW-01
def test_m6sw01_foreign_lease_blocks_activation(tmp_path, m6_world):
    """另一 Runtime 持有 writer 租约时，激活必须被拒绝（零写入）。"""
    seed_dir = build_synthetic_seed(tmp_path)
    holder = m6_world()
    lease = WriterLease(holder, W, 120)
    lease.acquire()                       # 另一实例持有世界写权限
    try:
        with pytest.raises(ActivationRefused):
            _activate(seed_dir, m6_world)
        counts = world_counts(m6_world)
        assert counts["active_worlds"] == 0
        assert counts["world_events"] == 0
        assert counts["rate_blessed_starts"] == [None]
    finally:
        lease.release()
        holder.close()

    out = _activate(seed_dir, m6_world)   # 租约释放后可激活
    assert out.outcome == OUTCOME_COMMITTED
    counts = world_counts(m6_world)
    assert counts["active_worlds"] == 1
    assert counts["genesis_events"] == 1
    assert counts["runtime_lock_rows"] == 0     # 租约已释放，无残留


# ------------------------------------------------------------------ SW-02
def test_m6sw02_stale_fencing_token_cannot_commit_activation(
        tmp_path, m6_world):
    """被接管的旧 writer 不得提交激活事务（强 fencing）。"""
    seed_dir = build_synthetic_seed(tmp_path)
    stale = m6_world()
    lease_a = WriterLease(stale, W, 1)      # 短租约，稍后过期
    lease_a.acquire()
    stale_token = lease_a.token
    stale_owner = lease_a.owner

    # 让 A 的租约过期，B 接管（真实 CAS 接管路径）
    time.sleep(1.2)
    b_session = m6_world()
    lease_b = WriterLease(b_session, W, 120)
    lease_b.acquire()
    assert lease_b.token != stale_token

    with m6_world() as s:
        with pytest.raises(FencingViolation):
            with WorldMutationContext(s, world_id=W, writer_id=stale_owner,
                                      fencing_token=stale_token) as ctx:
                RuntimeRepository(ctx.session).activate(
                    world_id=W, world_seed_version="1.0",
                    initial_blessed_tick=0, activation_real_us=1,
                    current_time_ratio_id=None)
        s.rollback()

    counts = world_counts(m6_world)
    assert counts["active_worlds"] == 0
    assert counts["world_events"] == 0
    with m6_world() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        assert row.runtime_status == "NOT_ACTIVATED"

    lease_a.release()          # 旧 token：不得误删 B 的租约
    with m6_world() as s:
        lock = s.execute(select(RuntimeLock)).scalar_one()
        assert lock.lease_token == lease_b.token
    lease_b.release()
    stale.close()
    b_session.close()


# ------------------------------------------------------------------ SW-03
def test_m6sw03_two_concurrent_activators_exactly_one_winner(tmp_path,
                                                            m6_world):
    """§15：两个 Activator 竞争 → 恰好一个赢家、一个世界、一次 seed 消费。"""
    seed_dir = build_synthetic_seed(tmp_path)
    results: list[dict] = []
    barrier = threading.Barrier(2)

    def worker(tag: str) -> None:
        barrier.wait()
        try:
            out = _activate(seed_dir, m6_world)
            results.append({"tag": tag, "outcome": out.outcome,
                            "written": out.written, "error": None})
        except Exception as exc:  # noqa: BLE001
            results.append({"tag": tag, "outcome": None, "written": False,
                            "error": type(exc).__name__})

    threads = [threading.Thread(target=worker, args=(t,)) for t in ("A", "B")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert len(results) == 2
    winners = [r for r in results if r["written"]]
    assert len(winners) == 1, results                 # ACTIVATION_WINNERS = 1
    for r in results:
        assert r["error"] in (None, "ActivationRefused",
                              "ActivationOutcomeUnknown"), results
    counts = world_counts(m6_world)
    assert counts["world_runtime_rows"] == 1          # FORMAL_WORLD_COUNT = 1
    assert counts["active_worlds"] == 1
    assert counts["genesis_events"] == 1              # SEED_CONSUMPTION_COUNT = 1
    assert counts["world_events"] == 1
    assert counts["rate_blessed_starts"] != [None]
    assert counts["runtime_lock_rows"] == 0


# ------------------------------------------------------------------ SW-04
def test_m6sw04_activation_does_not_leave_lock_behind(tmp_path, m6_world):
    """激活成功后不得留下租约（否则会永久阻塞 scheduler 的 writer 获取）。"""
    seed_dir = build_synthetic_seed(tmp_path)
    for _ in range(3):
        try:
            _activate(seed_dir, m6_world)
        except Exception:  # noqa: BLE001
            pass
        with m6_world() as s:
            assert s.execute(select(RuntimeLock)).scalars().all() == []
    assert world_counts(m6_world)["genesis_events"] == 1
    assert world_counts(m6_world)["active_worlds"] == 1
    assert world_counts(m6_world)["seed_consumption_count"] == 1

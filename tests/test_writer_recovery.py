"""SINGLE_WRITER + STALE_WRITER_RECOVERY 深度测试。

覆盖：跨会话即时可见 / 第二个 writer 拒绝 / 过期接管（崩溃、重启、僵尸进程）/
owner identity / token fencing / renew / 释放失败兜底（世界不会永久锁死）。
"""
from __future__ import annotations

import pytest
from sqlalchemy import select, text

from XiaoguangBlessedLandRuntime.database.models_core import RuntimeLock
from XiaoguangBlessedLandRuntime.domain.errors import WriterLockConflict
from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease, world_writer

W = "W"


def _expire_lock(session_factory):
    with session_factory() as s:
        s.execute(text(
            "UPDATE runtime_lock SET expires_at = '2000-01-01 00:00:00+00:00'"))
        s.commit()


def test_lease_visible_cross_session_immediately(seeded_session_factory):
    """关键修正：acquire 立即提交（前序实现直到 with 退出才提交 → 跨进程空洞）。"""
    s1 = seeded_session_factory()
    lease = WriterLease(s1, W, 120)
    lease.acquire()  # 调用方不再显式 commit
    try:
        with seeded_session_factory() as s2:
            row = s2.execute(select(RuntimeLock)).scalar_one()
            assert row.lease_token == lease.token
            with pytest.raises(WriterLockConflict):
                WriterLease(s2, W, 120).acquire()
    finally:
        lease.release()
        s1.close()


def test_crashed_writer_blocked_then_recovered(seeded_session_factory):
    """进程异常退出（未 release）：未过期 → 拒绝；过期 → STALE_WRITER_RECOVERY 接管。"""
    s1 = seeded_session_factory()
    l1 = WriterLease(s1, W, 120)
    l1.acquire()
    s1.close()  # 模拟崩溃：租约残留
    with seeded_session_factory() as s2:
        with pytest.raises(WriterLockConflict):
            WriterLease(s2, W, 120).acquire()
    _expire_lock(seeded_session_factory)  # 模拟租约到期（机器重启/时间流逝）
    s3 = seeded_session_factory()
    l3 = WriterLease(s3, W, 120, owner="recovered-process")
    l3.acquire()
    try:
        with seeded_session_factory() as s:
            row = s.execute(select(RuntimeLock)).scalar_one()
            assert row.lease_token == l3.token
            assert row.owner == "recovered-process"
    finally:
        l3.release()
        s3.close()


def test_owner_identity_recorded(seeded_session_factory):
    s = seeded_session_factory()
    lease = WriterLease(s, W, 120, owner="host-a:1234:abcd")
    lease.acquire()
    try:
        with seeded_session_factory() as s2:
            row = s2.execute(select(RuntimeLock)).scalar_one()
            assert row.owner == "host-a:1234:abcd"
    finally:
        lease.release()
        s.close()


def test_release_token_fencing(seeded_session_factory):
    """旧持有者的 release 不得删除新持有者的租约（token fencing）。"""
    s1 = seeded_session_factory()
    l1 = WriterLease(s1, W, 120)
    l1.acquire()
    _expire_lock(seeded_session_factory)
    s2 = seeded_session_factory()
    l2 = WriterLease(s2, W, 120)
    l2.acquire()
    try:
        l1.release()  # 旧 token：静默 no-op
        with seeded_session_factory() as s:
            row = s.execute(select(RuntimeLock)).scalar_one()
            assert row.lease_token == l2.token
    finally:
        l2.release()
        s1.close()
        s2.close()


def test_renew_extends_lease(seeded_session_factory):
    s = seeded_session_factory()
    lease = WriterLease(s, W, 120)
    lease.acquire()
    try:
        with seeded_session_factory() as s2:
            before = s2.execute(select(RuntimeLock)).scalar_one().expires_at
        lease.renew()
        with seeded_session_factory() as s2:
            after = s2.execute(select(RuntimeLock)).scalar_one().expires_at
        assert after > before
    finally:
        lease.release()
        s.close()


def test_renew_after_takeover_fails(seeded_session_factory):
    s1 = seeded_session_factory()
    l1 = WriterLease(s1, W, 120)
    l1.acquire()
    _expire_lock(seeded_session_factory)
    s2 = seeded_session_factory()
    l2 = WriterLease(s2, W, 120)
    l2.acquire()
    try:
        with pytest.raises(WriterLockConflict):
            l1.renew()
    finally:
        l2.release()
        s1.close()
        s2.close()


def test_release_failure_falls_back_to_expiry(seeded_session_factory, monkeypatch):
    """释放失败：不吞业务、租约保留、过期后仍可接管 → 世界不会永久锁死。"""
    s = seeded_session_factory()
    token_held = {}
    with world_writer(s, W) as lease:
        token_held["token"] = lease.token
        def _boom():  # noqa: ANN202
            raise RuntimeError("release boom")
        monkeypatch.setattr(lease, "release", _boom)
    with seeded_session_factory() as s2:
        row = s2.execute(select(RuntimeLock)).scalar_one_or_none()
        assert row is not None and row.lease_token == token_held["token"]
    _expire_lock(seeded_session_factory)
    s3 = seeded_session_factory()
    l3 = WriterLease(s3, W, 120)
    l3.acquire()  # 过期后接管成功
    l3.release()
    s3.close()

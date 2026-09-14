# -*- coding: utf-8 -*-
"""PRE-M6 POSTGRESQL FUNCTIONAL GATE（A–G）。

只验证功能性等价（**不含** commit ambiguity —— 那是下一独立阶段）：

A. Single Writer（真实 PG、独立连接；含两连接并发竞态与两**真实 OS 进程**竞态）
B. Fencing / stale writer（旧 token 的 world / history / checkpoint mutation 全部被拒）
C. Lease expiry / takeover（走 production coordination path，禁止手工改 DB 造 takeover）
D. Restart equivalence（含**真实进程重启**：两个 OS 进程接力）
E. Chunk equivalence（direct vs 100/250/10 年预算分块）
F. Deterministic world result on PostgreSQL（含与 SQLite 参考的跨方言语义一致）
G. History integrity on PostgreSQL（orphan / cycles / invalid refs = 0）+ 事件不可变性

运行方式（缺任一变量即按设计 skip；库名不含 ``test`` 则 fail-closed）：

    BLR_TEST_PG_DSN=postgresql+psycopg://.../<db_with_test_in_name>
    BLR_TEST_PG_ALLOW=1
    <pg-venv>\\Scripts\\python.exe -m pytest tests/test_pg_functional_gate.py -q

规模可由环境变量调整（默认见下）。所有世界均为合成（世界 id 复用
``M3LONG-00X`` 约定与 SQLite 参照一致），绝不触碰正式库 / live / World Seed。
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.pg_functional_support import (base_dsn_or_skip, counts,
                                        fresh_env, hashes, live_lease_rows,
                                        m3_run, scheduler_to, spawn_worker,
                                        wait_worker)

SEEDS = int(os.environ.get("BLR_PG_GATE_SEEDS", "5"))
YEARS = int(os.environ.get("BLR_PG_GATE_YEARS", "100"))
CHUNK_YEARS = int(os.environ.get("BLR_PG_GATE_CHUNK_YEARS", "250"))
CHUNK_BUDGETS = tuple(int(x) for x in os.environ.get(
    "BLR_PG_GATE_CHUNK_BUDGETS", "250,100,10").split(","))
RESTART_YEARS = int(os.environ.get("BLR_PG_GATE_RESTART_YEARS", "120"))
RESTART_EVERY = int(os.environ.get("BLR_PG_GATE_RESTART_EVERY", "25"))
PROC_SPLIT = int(os.environ.get("BLR_PG_GATE_PROC_SPLIT", "60"))
CROSS_SEEDS = int(os.environ.get("BLR_PG_GATE_CROSS_SEEDS", "3"))

SEED_WORLD_IDS = [f"M3LONG-{n:03d}" for n in range(1, SEEDS + 1)]
CROSS_WORLD_IDS = SEED_WORLD_IDS[:CROSS_SEEDS]
GATE_DB_BASE = 20            # fresh_env 索引起点（避免与其它测试库重名）

_CACHE: dict = {}


def _pg() -> str:
    """守卫：无 DSN/ALLOW → skip；库名不含 test → fail-closed。"""
    return base_dsn_or_skip()


@pytest.fixture(autouse=True)
def _require_pg_env():
    """每个 gate 测试前先走同一条守卫（非 PG 环境整体 skip）。"""
    return _pg()


def _lease_attempt(dsn: str, world_id: str, *, lease_seconds: int = 120,
                   hold_seconds: float = 0.0):
    """独立 engine / 独立连接上的一次租约获取尝试。"""
    from XiaoguangBlessedLandRuntime.database.db import (
        create_db_engine, make_session_factory)
    from XiaoguangBlessedLandRuntime.domain.errors import WriterLockConflict
    from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease
    engine = create_db_engine(dsn)
    factory = make_session_factory(engine)
    session = factory()
    lease = WriterLease(session, world_id, lease_seconds)
    try:
        lease.acquire()
    except WriterLockConflict as exc:
        session.close()
        engine.dispose()
        return None, str(exc)
    if hold_seconds:
        time.sleep(hold_seconds)
    return (lease, engine), "ACQUIRED"


# ------------------------------------------------------------- A. Single Writer
def test_pg_single_writer_exclusive_and_renew():
    dsn = _pg()
    env = fresh_env(GATE_DB_BASE, "PGGATE-WRITER-001", seed=False)
    try:
        a, msg = _lease_attempt(env["dsn"], env["world_id"])
        assert a is not None, msg
        lease_a, engine_a = a
        try:
            assert live_lease_rows(env) == 1          # MAX_AUTHORITATIVE_WRITERS = 1

            # B 在 A 租约有效期内并发申请 → 必须被拒
            b, msg_b = _lease_attempt(env["dsn"], env["world_id"])
            assert b is None and "另一 Runtime" in msg_b, msg_b

            # A 续约成功；B 仍被拒
            lease_a.renew()
            b2, msg_b2 = _lease_attempt(env["dsn"], env["world_id"])
            assert b2 is None and "另一 Runtime" in msg_b2, msg_b2

            # 释放后可再次获取（同一 world 不会永久锁死）
            lease_a.release()
            assert live_lease_rows(env) == 0
            c, msg_c = _lease_attempt(env["dsn"], env["world_id"])
            assert c is not None, msg_c
            c[0].release()
            c[1].dispose()
        finally:
            engine_a.dispose()
    finally:
        env["engine"].dispose()


def test_pg_single_writer_concurrent_two_connections():
    """两连接真并发抢锁：恰好一个胜出（DB 侧无第二把活租约）。"""
    dsn = _pg()
    env = fresh_env(GATE_DB_BASE + 1, "PGGATE-WRITER-002", seed=False)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_lease_attempt, env["dsn"], env["world_id"])
                       for _ in range(2)]
            results = [f.result() for f in futures]
        winners = [r for r in results if r[0] is not None]
        losers = [r for r in results if r[0] is None]
        assert len(winners) == 1, results
        assert len(losers) == 1, results
        assert live_lease_rows(env) == 1
        for winner, _ in winners:
            winner[0].release()
            winner[1].dispose()
    finally:
        env["engine"].dispose()


# ------------------------------------------------- C. lease expiry / takeover
def test_pg_lease_expiry_takeover_production_path():
    """租约到期 → 新 writer 经 **production CAS 接管**（不手工改 DB）。"""
    dsn = _pg()
    env = fresh_env(GATE_DB_BASE + 2, "PGGATE-TAKEOVER-001", seed=False)
    try:
        a, msg = _lease_attempt(env["dsn"], env["world_id"], lease_seconds=2)
        assert a is not None, msg
        lease_a, engine_a = a
        token_a = lease_a.token
        owner_a = lease_a.owner
        try:
            # A 停止心跳 → 租约自然过期（不手动 UPDATE runtime_lock）
            time.sleep(3.5)
            assert live_lease_rows(env) == 0
            b, msg_b = _lease_attempt(env["dsn"], env["world_id"],
                                      lease_seconds=120)
            assert b is not None, f"接管失败: {msg_b}"
            lease_b, engine_b = b
            try:
                assert lease_b.token != token_a          # 新一代 lease token
                # DB 侧租约身份确实已更替（同进程内 owner 字符串相同，故验 token）
                from XiaoguangBlessedLandRuntime.database.base import utcnow
                with env["factory"]() as s:
                    row = s.execute(text(
                        "SELECT lease_token, owner, expires_at FROM runtime_lock "
                        "WHERE world_id = :w"), {"w": env["world_id"]}).one()
                assert row[0] == lease_b.token and row[0] != token_a
                assert row[1] == owner_a          # 同一 OS 进程 → owner 身份相同
                assert row[2] > utcnow()          # 新租约在原租约过期后生效
                # A 持旧 token 续约 → 必须失败
                from XiaoguangBlessedLandRuntime.domain.errors import (
                    WriterLockConflict)
                with pytest.raises(WriterLockConflict):
                    lease_a.renew()
            finally:
                lease_b.release()
                engine_b.dispose()
        finally:
            engine_a.dispose()
    finally:
        env["engine"].dispose()


# ------------------------------------------------------------ B. stale writer
def test_pg_stale_writer_all_mutations_rejected():
    """被接管后的旧 writer：world / history / checkpoint 三类 mutation 全部被拒。"""
    dsn = _pg()
    env = fresh_env(GATE_DB_BASE + 3, "PGGATE-STALE-001", seed=False)
    try:
        from XiaoguangBlessedLandRuntime.database.db import (
            create_db_engine, make_session_factory)
        from XiaoguangBlessedLandRuntime.domain.errors import FencingViolation
        from XiaoguangBlessedLandRuntime.services.fencing import (
            WorldMutationContext)
        from XiaoguangBlessedLandRuntime.services.repositories import (
            EventRepository)

        a, msg = _lease_attempt(env["dsn"], env["world_id"], lease_seconds=2)
        assert a is not None, msg
        lease_a, engine_a = a
        stale_token, stale_owner = lease_a.token, lease_a.owner
        engine_a.dispose()
        lease_a.session.close()

        time.sleep(3.5)
        b, msg_b = _lease_attempt(env["dsn"], env["world_id"],
                                  lease_seconds=120)
        assert b is not None, msg_b
        lease_b, engine_b = b
        before = counts(env)

        engine_stale = create_db_engine(env["dsn"])
        factory_stale = make_session_factory(engine_stale)
        attempts: dict = {}

        with factory_stale() as s:
            with pytest.raises(FencingViolation):
                with WorldMutationContext(s, world_id=env["world_id"],
                                          writer_id=stale_owner,
                                          fencing_token=stale_token):
                    EventRepository(s).append(world_id=env["world_id"],
                                              event_type="STALE",
                                              source="STALE-WRITER",
                                              blessed_tick=1)
            attempts["world_mutation"] = "REJECTED"

        with factory_stale() as s:
            with pytest.raises(FencingViolation):
                with WorldMutationContext(s, world_id=env["world_id"],
                                          writer_id=stale_owner,
                                          fencing_token=stale_token) as ctx:
                    s.execute(text(
                        "INSERT INTO simulation_checkpoints (world_id, "
                        "checkpoint_blessed_tick, world_state_hash, complete, "
                        "meta, created_at, rate_remainder) VALUES (:w, 1, "
                        "'stale', true, '{}'::json, now(), 0)"),
                        {"w": env["world_id"]})
                    ctx.commit()
            attempts["checkpoint_commit"] = "REJECTED"

        with factory_stale() as s:
            with pytest.raises(FencingViolation):
                with WorldMutationContext(s, world_id=env["world_id"],
                                          writer_id=stale_owner,
                                          fencing_token=stale_token) as ctx:
                    s.execute(text(
                        "INSERT INTO causal_history_links (world_id, link_id, "
                        "relation_type, source_kind, source_id, target_kind, "
                        "target_id, committed_tick, status) VALUES "
                        "(:w, 'STALE-LINK', 'CAUSES', 'EVENT', 'x', 'EVENT', "
                        "'y', 1, 'ACTIVE')"), {"w": env["world_id"]})
                    ctx.commit()
            attempts["history_mutation"] = "REJECTED"

        after = counts(env)
        engine_stale.dispose()
        lease_b.release()
        engine_b.dispose()

        assert attempts == {"world_mutation": "REJECTED",
                            "checkpoint_commit": "REJECTED",
                            "history_mutation": "REJECTED"}, attempts
        assert after == before, (before, after)   # STALE_WRITER_MUTATIONS = 0
        assert after["world_events"] == 0
        assert after["simulation_checkpoints"] == 0
    finally:
        env["engine"].dispose()


# ------------------------------------------------------ 真实 OS 进程竞态（§10）
def test_pg_process_level_writer_race(tmp_path):
    """两个**真实 OS 进程**同一毫秒窗口抢锁 → 恰好一个胜出。"""
    dsn = _pg()
    env = fresh_env(GATE_DB_BASE + 4, "PGGATE-PROC-001", seed=False)
    try:
        start_at_ms = int((time.time() + 8) * 1000)
        procs, outs = [], []
        for i in range(2):
            out = tmp_path / f"race_{i}.json"
            outs.append(out)
            procs.append(spawn_worker(
                {"action": "acquire", "dsn": env["dsn"],
                 "world_id": env["world_id"], "lease_seconds": 60,
                 "hold_seconds": 0, "release_on_exit": False,
                 "start_at_ms": start_at_ms, "owner": f"proc-racer-{i}"},
                out))
        results = [wait_worker(p, o, timeout=180) for p, o in zip(procs, outs)]
        for r in results:
            assert r["ok"], r
        outcomes = [r["result"]["result"] for r in results]
        assert sorted(outcomes) == ["ACQUIRED", "REJECTED"], outcomes
        assert len({r["result"]["pid"] for r in results}) == 2   # 确为两个进程
        assert live_lease_rows(env) == 1                         # 活租约唯一
    finally:
        env["engine"].dispose()


def test_pg_process_level_stale_worker_mutations_rejected(tmp_path):
    """进程 A 死亡留过期租约 → 进程 B 接管 → 进程 A 的旧 token 写入被拒。"""
    dsn = _pg()
    env = fresh_env(GATE_DB_BASE + 5, "PGGATE-PROC-002", seed=False)
    try:
        out_a = tmp_path / "proc_a.json"
        proc_a = spawn_worker(
            {"action": "acquire", "dsn": env["dsn"],
             "world_id": env["world_id"], "lease_seconds": 3,
             "hold_seconds": 0, "release_on_exit": False,
             "owner": "proc-dead-writer"}, out_a)
        res_a = wait_worker(proc_a, out_a, timeout=180)
        assert res_a["ok"] and res_a["result"]["result"] == "ACQUIRED", res_a
        token_a = res_a["result"]["token"]
        proc_a.wait(timeout=60)                    # 进程正常退出（不释放租约）

        time.sleep(3.5)                            # 租约自然过期
        b, msg_b = _lease_attempt(env["dsn"], env["world_id"], lease_seconds=120)
        assert b is not None, msg_b
        lease_b, engine_b = b
        try:
            out_c = tmp_path / "proc_c.json"
            proc_c = spawn_worker(
                {"action": "stale_mutation", "dsn": env["dsn"],
                 "world_id": env["world_id"], "token": token_a,
                 "owner": "proc-dead-writer"}, out_c)
            res_c = wait_worker(proc_c, out_c, timeout=300)
            assert res_c["ok"], res_c
            assert res_c["result"]["mutations_applied"] == 0, res_c
            for kind, verdict in res_c["result"]["attempts"].items():
                assert verdict.startswith("REJECTED"), (kind, verdict)
            assert counts(env) == res_c["result"]["before"]
        finally:
            lease_b.release()
            engine_b.dispose()
    finally:
        env["engine"].dispose()


# ------------------------------------------------------- F. determinism on PG
@pytest.mark.parametrize("world_id", SEED_WORLD_IDS)
def test_pg_determinism_repeat_and_cross_dialect(world_id, tmp_path):
    """同一 seed：PG 两次独立运行结果一致；并在抽样 seed 上与 SQLite 参照一致。"""
    dsn = _pg()
    index = SEED_WORLD_IDS.index(world_id)
    env1 = fresh_env(GATE_DB_BASE + 10 + index * 2, world_id)
    env2 = fresh_env(GATE_DB_BASE + 11 + index * 2, world_id)
    try:
        m3_run(env1, years=YEARS)
        h1 = hashes(env1)
        m3_run(env2, years=YEARS)
        h2 = hashes(env2)
        assert h1 == h2, ("PG repeat mismatch", h1, h2)
        _CACHE.setdefault("pg_determinism", {})[world_id] = h1

        if world_id in CROSS_WORLD_IDS:
            from tests.test_m3_integrated_long import _fresh_m3, _hashes
            ref = _fresh_m3(tmp_path, 900 + index, world_id)
            m3_run(ref, years=YEARS)
            h_sqlite = _hashes(ref)
            assert h1 == h_sqlite, ("cross-dialect mismatch", h1, h_sqlite)
    finally:
        env1["engine"].dispose()
        env2["engine"].dispose()


# --------------------------------------------------- E. chunk equivalence on PG
def test_pg_chunk_equivalence_direct_reference(tmp_path):
    """direct 参照（供各 budget 分块比对）。"""
    dsn = _pg()
    env = fresh_env(GATE_DB_BASE + 30, "M3LONG-001")
    try:
        m3_run(env, years=CHUNK_YEARS)
        _CACHE["direct_chunk_ref"] = hashes(env)
        assert _CACHE["direct_chunk_ref"]["world_state_hash"]
    finally:
        env["engine"].dispose()


@pytest.mark.parametrize("budget_years", CHUNK_BUDGETS)
def test_pg_chunk_equivalence(budget_years, tmp_path):
    """budget 只影响节奏：任意分块最终三哈希 == direct。"""
    dsn = _pg()
    ref = _CACHE.get("direct_chunk_ref")
    assert ref is not None, "direct 参照缺失（须先运行参照测试）"
    env = fresh_env(GATE_DB_BASE + 40 + budget_years, "M3LONG-001")
    try:
        sched = scheduler_to(env, budget_years=budget_years,
                             target_years=CHUNK_YEARS,
                             state_dir=tmp_path / f"state_{budget_years}")
        sched.stop()
        got = hashes(env)
        assert got == ref, (budget_years, got, ref)
        with env["factory"]() as s:
            assert s.execute(text(
                "SELECT COUNT(*) FROM world_events")).scalar() > 0
    finally:
        env["engine"].dispose()


# ------------------------------------------------- D. restart equivalence on PG
def test_pg_restart_equivalence_same_process(tmp_path):
    """分段落盘后继续（restart_every_years）== direct。"""
    dsn = _pg()
    ref = fresh_env(GATE_DB_BASE + 50, "M3LONG-001")
    env = fresh_env(GATE_DB_BASE + 51, "M3LONG-001")
    try:
        m3_run(ref, years=RESTART_YEARS)
        m3_run(env, years=RESTART_YEARS, restart_every_years=RESTART_EVERY)
        assert hashes(env) == hashes(ref)
    finally:
        ref["engine"].dispose()
        env["engine"].dispose()


def test_pg_process_restart_equivalence(tmp_path):
    """**真实进程重启**：进程1 跑前半程退出 → 进程2（新 engine）续跑 == direct。"""
    dsn = _pg()
    env = fresh_env(GATE_DB_BASE + 60, "M3LONG-001")
    ref = fresh_env(GATE_DB_BASE + 61, "M3LONG-001")
    try:
        m3_run(ref, years=PROC_SPLIT * 2)          # direct 参照
        out1 = tmp_path / "restart_1.json"
        p1 = spawn_worker({"action": "run_years", "dsn": env["dsn"],
                           "world_id": env["world_id"], "years": PROC_SPLIT,
                           "start_year": 0}, out1)
        r1 = wait_worker(p1, out1, timeout=1800)
        assert r1["ok"], r1
        out2 = tmp_path / "restart_2.json"
        p2 = spawn_worker({"action": "run_years", "dsn": env["dsn"],
                           "world_id": env["world_id"], "years": PROC_SPLIT,
                           "start_year": PROC_SPLIT}, out2)
        r2 = wait_worker(p2, out2, timeout=1800)
        assert r2["ok"], r2
        assert r2["result"]["final_blessed_tick"] == PROC_SPLIT * 2 * 1_000_000
        assert r2["result"]["hashes"] == hashes(ref), (
            r2["result"]["hashes"], hashes(ref))
    finally:
        env["engine"].dispose()
        ref["engine"].dispose()


# ------------------------------------------------ G. history integrity + 不可变
def test_pg_history_integrity_and_event_immutability(tmp_path):
    """完成仿真后：history audit 全 0；world_events UPDATE/DELETE/TRUNCATE 全被拒。"""
    dsn = _pg()
    env = fresh_env(GATE_DB_BASE + 70, "M3LONG-001")
    try:
        years = int(os.environ.get("BLR_PG_GATE_HISTORY_YEARS", "60"))
        m3_run(env, years=years)

        from XiaoguangBlessedLandRuntime.services.history.service import (
            HistoryService)
        audit = HistoryService(env["factory"]).history_integrity_audit(
            world_id=env["world_id"])
        assert audit["orphan_links"] == 0, audit["orphan_samples"]
        assert audit["cycle_count"] == 0, audit["cycle_samples"]
        assert audit["invalid_relations"] == [], audit["invalid_relations"]
        assert audit["tick_paradox_links"] == 0, audit["tick_paradox_samples"]
        assert audit["duplicate_links"] == 0, audit["duplicate_samples"]
        assert audit["clean"] is True

        with env["factory"]() as s:
            events_before = s.execute(text(
                "SELECT COUNT(*) FROM world_events WHERE world_id = :w"),
                {"w": env["world_id"]}).scalar()
        assert events_before > 0

        from sqlalchemy import exc as sa_exc

        from XiaoguangBlessedLandRuntime.database.invariants import (
            verify_event_immutability)
        verify_event_immutability(env["engine"])

        for sql, op in (("UPDATE world_events SET event_type = 'MUT'", "UPDATE"),
                        (f"DELETE FROM world_events WHERE world_id = "
                         f"'{env['world_id']}'", "DELETE"),
                        ("TRUNCATE TABLE world_events", "TRUNCATE")):
            with env["engine"].connect() as c:
                with pytest.raises(sa_exc.DatabaseError) as exc:
                    c.execute(text(sql))
            assert "append-only" in str(exc.value), (op, str(exc.value))
            assert op in str(exc.value), (op, str(exc.value))

        with env["factory"]() as s:
            assert s.execute(text(
                "SELECT COUNT(*) FROM world_events WHERE world_id = :w"),
                {"w": env["world_id"]}).scalar() == events_before
        verify_event_immutability(env["engine"])
    finally:
        env["engine"].dispose()

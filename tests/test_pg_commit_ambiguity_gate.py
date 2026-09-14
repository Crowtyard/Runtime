# -*- coding: utf-8 -*-
"""PRE-M6 POSTGRESQL COMMIT AMBIGUITY GATE（CA-01..CA-07）。

真实 PostgreSQL + **真实 OS 进程** + **真实连接/服务器故障**；
不使用 monkeypatch / Python 异常注入作为最终证据（那属 unit regression）。

结构（owner §4）：Controller（本测试进程）
  ├── Writer Process A（独立 engine/连接/进程）
  ├── Recovery Process B（独立 engine/连接/进程）
  └── PostgreSQL 16 TEST 容器（仅 blr-pre-m6-postgres；绝不碰 stayops-postgres / live）

durable truth 只来自 PostgreSQL（§15）；BLIND_RETRY_COUNT 由恢复驱动断言（§16）。
租约按生产语义**自然过期**后才接管（绝不手工 UPDATE runtime_lock）；被杀 writer
留下的租约最坏阻塞 `Settings().writer_lease_seconds`（120s）——测试显式等待该时间。

运行：需 BLR_TEST_PG_DSN + BLR_TEST_PG_ALLOW=1（缺任一 → 整体 skip；库名不含 test → fail-closed）。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from tests.pg_ambiguity_support import (ALREADY_COMMITTED, NOT_COMMITTED,
                                       RUNNING_STALE, RecoveryDriver, kill_worker,
                                       authoritative_hashes, container_restart,
                                       durable_tick, history_audit, invariants,
                                       lease_live, reset_ambiguity_db,
                                       reset_reference_db, seed_world,
                                       sentinel_paths, spawn, terminate_backend,
                                       wait_lease_expiry, wait_pg_healthy,
                                       wait_result, wait_sentinel)
from tests.pg_functional_support import base_dsn_or_skip

CA03_ITERATIONS = int(os.environ.get("BLR_PG_AMBIG_CA03_ITERATIONS", "20"))
CA07_ITERATIONS = int(os.environ.get("BLR_PG_AMBIG_CA07_ITERATIONS", "5"))
LEASE_SHORT = 2          # 短租约（生产 mutation 会刷新为 settings TTL，接管需等其过期）


@pytest.fixture(autouse=True)
def _require_pg_env():
    return base_dsn_or_skip()


# --------------------------------------------------------------------- helpers
def _amb(world_id: str) -> dict:
    dsn = reset_ambiguity_db()
    return seed_world(dsn, world_id)


def _factory(env):
    from XiaoguangBlessedLandRuntime.database.db import (
        create_db_engine, make_session_factory)
    engine = create_db_engine(env["dsn"])
    return engine, make_session_factory(engine)


def _driver(factory, world_id: str) -> RecoveryDriver:
    from XiaoguangBlessedLandRuntime.services.simulation.tribulation import (
        M3A_SIMULATION_VERSION)
    from tests.conftest import EPOCH0_US
    return RecoveryDriver(factory=factory, world_id=world_id,
                          epoch0_us=EPOCH0_US,
                          simulation_version=M3A_SIMULATION_VERSION)


def _hist_coordinator():
    from tests.test_m3b_history import _hist_coordinator as hc
    return hc()


def _submit_after_expiry(factory, world_id: str, driver: RecoveryDriver,
                         year: int, *, timeout: float = 400.0) -> dict:
    """等租约自然过期 → 生产 acquire → 生产提交 → 释放（每步都是生产 API）。"""
    from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease
    if lease_live(factory, world_id):
        wait_lease_expiry(factory, world_id, timeout=timeout)
    session = factory()
    lease = WriterLease(session, world_id, 300)
    lease.acquire()
    try:
        return driver.submit_year(year, owner=lease.owner, token=lease.token,
                                  coordinator=_hist_coordinator())
    finally:
        lease.release()
        session.close()


def _reference(world_id: str, years: int) -> dict:
    """无故障 direct 参照（独立库、同 world_id、同 synthetic seed）。"""
    dsn = reset_reference_db()
    env = seed_world(dsn, world_id)
    engine, factory = _factory(env)
    driver = _driver(factory, world_id)
    from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease
    session = factory()
    lease = WriterLease(session, world_id, 600)
    lease.acquire()
    for year in range(years):
        driver.classify(year)          # 参照同样先核对 durable truth（非盲重试）
        res = driver.submit_year(year, owner=lease.owner, token=lease.token,
                                 coordinator=_hist_coordinator())
        assert res["client_outcome"] == "SUCCESS", res
    lease.release()
    session.close()
    hashes = authoritative_hashes(factory, world_id)
    inv = invariants(factory, world_id, expected_years=years)
    _assert_clean(inv, years=years)
    engine.dispose()
    return {"hashes": hashes, "invariants": inv}


def _recover(dsn: str, world_id: str, years: list[int], tmp_path: Path,
             *, name: str) -> dict:
    """在**独立进程**中走生产 recovery 路径（先查 durable truth 再决定提交）。"""
    out = tmp_path / f"{name}.json"
    proc = spawn({"action": "recover_continue", "dsn": dsn,
                  "world_id": world_id, "years": years}, out)
    res = wait_result(out, timeout=1800)
    proc.wait(timeout=120)
    assert res["ok"], res
    return res["result"]


def _assert_clean(inv: dict, *, years: int, stale_token: str | None = None):
    assert inv["duplicate_ticks"] == 0, inv
    assert inv["duplicate_history_events"] == 0, inv
    assert inv["lost_ticks"] == 0, inv
    assert inv["forked_history"] == 0, inv
    assert inv["history_orphan_links"] == 0, inv
    assert inv["history_causal_cycles"] == 0, inv
    assert inv["history_invalid_refs"] == 0, inv
    assert inv["history_clean"] is True, inv
    assert inv["final_tick"] == years * 1_000_000, inv
    if stale_token is not None:
        assert inv["stale_writer_mutations"] == 0, inv


def _json_load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


# ---------------------------------------------------------------- CA-01
def test_ca01_definite_rollback(tmp_path):
    """事务已开始、COMMIT 之前真实终止 writer 进程 → PG 回滚 → 未提交 → 允许重做。"""
    world_id = "PGAMB-CA01"
    env = _amb(world_id)
    ref = _reference(world_id, 1)

    out = tmp_path / "ca01_writer.json"
    proc = spawn({"action": "advance_year", "dsn": env["dsn"],
                  "world_id": world_id, "year_index": 0, "slow_ms": 5000,
                  "lease_seconds": LEASE_SHORT}, out)
    inside = wait_sentinel(sentinel_paths(out)["inside_tx"], timeout=180)
    # Windows venv 启动器：Popen.pid 只是 stub，真实 worker 是其子进程
    # （sentinel 由真实 worker 写出 → 以该 PID 为终止目标）
    assert int(inside["pid"]) > 0
    kill_worker(proc, pid=int(inside["pid"]))   # 真实 OS 级终止（显式真实 PID）
    assert not out.exists(), "应用确认不得存在（进程在事务中被杀）"

    engine, factory = _factory(env)
    driver = _driver(factory, world_id)
    info = driver.classify(0)
    assert info["outcome"] in (NOT_COMMITTED, RUNNING_STALE), info
    assert info["durable_tick"] == 0, info                    # 世界未推进
    expiry_wait = wait_lease_expiry(factory, world_id, timeout=400)

    rec = _recover(env["dsn"], world_id, [0], tmp_path, name="ca01_recovery")
    assert rec["classifications"][0]["outcome"] in (NOT_COMMITTED, RUNNING_STALE)
    assert rec["blind_retry_count"] == 0
    assert rec["submissions"][0]["result"]["client_outcome"] == "SUCCESS"

    inv = invariants(factory, world_id, expected_years=1)
    _assert_clean(inv, years=1)
    assert authoritative_hashes(factory, world_id) == ref["hashes"]
    engine.dispose()
    print(f"CA01_DURABLE_OUTCOME=NOT_COMMITTED lease_expiry_wait={expiry_wait:.1f}s")


# ---------------------------------------------------------------- CA-02
def test_ca02_committed_worker_dies_before_app_ack(tmp_path):
    """COMMIT 已 durable、应用确认前进程被杀 → 恢复必须判定 ALREADY_COMMITTED 且不重试。"""
    world_id = "PGAMB-CA02"
    env = _amb(world_id)
    ref = _reference(world_id, 2)

    out = tmp_path / "ca02_writer.json"
    proc = spawn({"action": "advance_year", "dsn": env["dsn"],
                  "world_id": world_id, "year_index": 0,
                  "block_after_commit_seconds": 600,
                  "lease_seconds": LEASE_SHORT}, out)
    committed = wait_sentinel(sentinel_paths(out)["committed"], timeout=600)
    assert committed["phase"] == "COMMITTED_UNACKED", committed
    kill_worker(proc, pid=int(committed["pid"]))
    assert not out.exists(), "应用确认不得存在（进程在确认前被杀）"

    engine, factory = _factory(env)
    driver = _driver(factory, world_id)
    info = driver.classify(0)
    assert info["outcome"] == ALREADY_COMMITTED, info       # CA02_DURABLE_OUTCOME = COMMITTED
    assert info["durable_tick"] == 1_000_000, info
    assert info["committed_run_id"] is not None, info

    wait_lease_expiry(factory, world_id, timeout=400)
    rec = _recover(env["dsn"], world_id, [0, 1], tmp_path, name="ca02_recovery")
    assert rec["classifications"][0]["outcome"] == ALREADY_COMMITTED
    assert rec["blind_retry_count"] == 0                    # CA02_BLIND_RETRY = 0
    assert [s["year_index"] for s in rec["submissions"]] == [1]

    inv = invariants(factory, world_id, expected_years=2)
    _assert_clean(inv, years=2)
    assert authoritative_hashes(factory, world_id) == ref["hashes"]
    engine.dispose()


# ---------------------------------------------------------------- CA-03
def test_ca03_connection_lost_during_commit(tmp_path):
    """真实 `pg_terminate_backend` 在 COMMIT 窗口扫掠；每轮 reconcile，world 只推进一次。"""
    world_id = "PGAMB-CA03"
    env = _amb(world_id)
    ref = _reference(world_id, CA03_ITERATIONS)
    engine, factory = _factory(env)
    driver = _driver(factory, world_id)
    dsn = env["dsn"]

    committed_ambiguous = not_committed_ambiguous = kill_missed_ok = 0
    client_error = client_ok = 0
    rows = []
    for year in range(CA03_ITERATIONS):
        slow_ms = 60 if year % 2 == 0 else 150
        out = tmp_path / f"ca03_{year}.json"
        sentinels = sentinel_paths(out)
        for attempt in range(3):
            proc = spawn({"action": "advance_year", "dsn": dsn,
                          "world_id": world_id, "year_index": year,
                          "slow_ms": slow_ms, "lease_seconds": LEASE_SHORT}, out)
            started = wait_sentinel(sentinels["started"], timeout=300)
            if started.get("phase") != "LEASE_REJECTED":
                break
            # 上一轮的租约仍存活（生产语义：等待自然过期后接管）
            wait_lease_expiry(factory, world_id, timeout=400)
            for p in sentinels.values():
                p.unlink(missing_ok=True)
        else:
            raise AssertionError(f"year {year} 连续 3 次无法获取租约")
        if year % 2 == 0:
            # 事务内 kill → PG 回滚在途事务 → durable 必为未提交
            sig = wait_sentinel(sentinels["inside_tx"], timeout=300)
            delay_ms = [0, 20, 60][(year // 2) % 3]
            signal_name = "INSIDE_TX"
        else:
            # COMMIT 窗口竞速：~1ms 探测精度，kill 与 COMMIT 真竞速
            sig = wait_sentinel(sentinels["pre_commit"], timeout=300, poll=0.001)
            delay_ms = [0, 1, 2, 3, 5, 8][(year // 2) % 6]
            signal_name = "PRE_COMMIT"
        time.sleep(delay_ms / 1000.0)
        killed = terminate_backend(int(sig["backend_pid"]))   # False = 未命中（已正常完成）
        res = wait_result(out, timeout=300)
        client = res["result"].get("client_outcome")
        if client == "ERROR":
            client_error += 1
        else:
            client_ok += 1
        proc.wait(timeout=60)

        info = driver.classify(year)
        if client == "ERROR" and info["outcome"] == ALREADY_COMMITTED:
            committed_ambiguous += 1
        elif client == "ERROR":
            not_committed_ambiguous += 1
        elif not killed:
            kill_missed_ok += 1
        else:
            kill_missed_ok += 1        # 客户端已确认（kill 落在 ack 之后）
        if info["outcome"] != ALREADY_COMMITTED:
            submit = _submit_after_expiry(factory, world_id, driver, year)
            assert submit["client_outcome"] == "SUCCESS", submit
        rows.append({"year": year, "signal": signal_name,
                     "kill_delay_ms": delay_ms, "slow_ms": slow_ms,
                     "kill_landed": killed, "client": client,
                     "durable": info["outcome"]})

    assert driver.blind_retry_count == 0, "严禁盲重试"
    inv = invariants(factory, world_id, expected_years=CA03_ITERATIONS)
    _assert_clean(inv, years=CA03_ITERATIONS)
    assert authoritative_hashes(factory, world_id) == ref["hashes"]
    engine.dispose()
    print(f"CA03_ITERATIONS={CA03_ITERATIONS} "
          f"AMBIGUOUS_COMMITTED={committed_ambiguous} "
          f"AMBIGUOUS_NOT_COMMITTED={not_committed_ambiguous} "
          f"CLIENT_ERROR={client_error} CLIENT_OK={client_ok} "
          f"KILL_MISSED_OR_POST_ACK={kill_missed_ok}")
    assert client_error >= 1, "至少一轮必须观察到客户端 outcome 未知"
    assert committed_ambiguous + not_committed_ambiguous + kill_missed_ok \
        == CA03_ITERATIONS
    assert not_committed_ambiguous >= 1, rows


# ---------------------------------------------------------------- CA-04
def test_ca04_server_restart_around_commit(tmp_path):
    """COMMIT 窗口内真实重启 PG 服务器（仅测试容器）→ 客户端 UNKNOWN → 恢复 reconcile。"""
    world_id = "PGAMB-CA04"
    env = _amb(world_id)
    ref = _reference(world_id, 2)
    dsn = env["dsn"]

    out = tmp_path / "ca04_writer.json"
    proc = spawn({"action": "advance_year", "dsn": dsn, "world_id": world_id,
                  "year_index": 0, "slow_ms": 10000,
                  "lease_seconds": LEASE_SHORT}, out)
    wait_sentinel(sentinel_paths(out)["inside_tx"], timeout=300)
    container_restart()                      # 仅 blr-pre-m6-postgres
    res = wait_result(out, timeout=300)
    assert res["result"]["client_outcome"] == "ERROR", res
    proc.wait(timeout=60)
    assert wait_pg_healthy(timeout=240) == "healthy"       # PG_HEALTH

    engine, factory = _factory(env)
    driver = _driver(factory, world_id)
    info = driver.classify(0)
    assert info["outcome"] in (NOT_COMMITTED, RUNNING_STALE, ALREADY_COMMITTED), info

    rec = _recover(dsn, world_id, [0, 1], tmp_path, name="ca04_recovery")
    assert rec["blind_retry_count"] == 0
    inv = invariants(factory, world_id, expected_years=2)
    _assert_clean(inv, years=2)
    assert authoritative_hashes(factory, world_id) == ref["hashes"]
    engine.dispose()


# ---------------------------------------------------------------- CA-05 / CA-06
def test_ca05_takeover_after_ambiguity_and_ca06_stale_retry(tmp_path):
    """歧义提交后接管：B 必须先 reconcile A 的最后一笔；A 的旧 token 重提必须被拒。"""
    world_id = "PGAMB-CA05"
    env = _amb(world_id)
    ref = _reference(world_id, 2)
    dsn = env["dsn"]

    out = tmp_path / "ca05_writer_a.json"
    proc = spawn({"action": "advance_year", "dsn": dsn, "world_id": world_id,
                  "year_index": 0, "slow_ms": 5000,
                  "lease_seconds": LEASE_SHORT}, out)
    inside = wait_sentinel(sentinel_paths(out)["inside_tx"], timeout=300)
    assert terminate_backend(int(inside["backend_pid"]))
    res = wait_result(out, timeout=300)
    assert res["result"]["client_outcome"] == "ERROR"
    token_a, owner_a = res["result"]["token"], res["result"]["owner"]
    kill_worker(proc, pid=int(res["result"]["pid"]))   # A 消失（进程级，显式 PID）

    engine, factory = _factory(env)
    expiry_wait = wait_lease_expiry(factory, world_id, timeout=400)

    # Writer B：生产 CAS 接管（过期租约）→ epoch N+1
    from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease
    lease_session = factory()
    lease_b = WriterLease(lease_session, world_id, 300)
    lease_b.acquire()
    assert lease_b.token != token_a, "接管必须产生新 lease token（epoch N+1）"
    from sqlalchemy import text as _text
    with factory() as s:
        takeover_at = s.execute(_text(
            "SELECT acquired_at FROM runtime_lock WHERE world_id = :w"),
            {"w": world_id}).scalar()          # durable 接管时刻（epoch N+1 起点）

    driver = _driver(factory, world_id)
    info = driver.classify(0)
    assert info["outcome"] in (ALREADY_COMMITTED, NOT_COMMITTED, RUNNING_STALE)
    if info["outcome"] != ALREADY_COMMITTED:
        submit0 = driver.submit_year(0, owner=lease_b.owner, token=lease_b.token,
                                     coordinator=_hist_coordinator())
        assert submit0["client_outcome"] == "SUCCESS", submit0
    assert driver.blind_retry_count == 0

    # CA-06：A 的旧 token 重提**尚未提交**的 year1 → fenced 事务 → 必须被 fencing 拒绝
    out_retry = tmp_path / "ca06_stale_retry.json"
    p_retry = spawn({"action": "stale_retry", "dsn": dsn, "world_id": world_id,
                     "year_index": 1, "owner": owner_a, "token": token_a},
                    out_retry)
    retry = wait_result(out_retry, timeout=300)
    p_retry.wait(timeout=60)
    assert retry["ok"], retry
    assert retry["result"]["outcome"]["client_outcome"] == "ERROR", retry
    assert "FencingViolation" in retry["result"]["outcome"]["error_type"], retry
    assert retry["result"]["mutated"] is False, retry

    # 受控盲重试探针（§16）：即使不查真值直接重提**已提交**年份，
    # 生产幂等也必须使其成为 no-op（DB 层安全网），不得产生重复
    probe = driver.blind_probe(0, owner=lease_b.owner, token=lease_b.token,
                               coordinator=_hist_coordinator())
    assert probe["client_outcome"] == "SUCCESS", probe
    assert driver.blind_retry_probes == 1

    driver.classify(1)          # 推进新年份前同样先核对 durable truth（非盲推进）
    submit1 = driver.submit_year(1, owner=lease_b.owner, token=lease_b.token,
                                 coordinator=_hist_coordinator())
    assert submit1["client_outcome"] == "SUCCESS", submit1
    assert driver.blind_retry_count == 0
    lease_b.release()
    lease_session.close()

    inv = invariants(factory, world_id, expected_years=2, stale_token=token_a,
                     takeover_at=takeover_at)
    _assert_clean(inv, years=2, stale_token=token_a)
    assert authoritative_hashes(factory, world_id) == ref["hashes"]
    engine.dispose()
    print(f"CA05_TAKEOVER epoch_new!=epoch_old=True lease_expiry_wait="
          f"{expiry_wait:.1f}s BLIND_RETRY_PROBES={driver.blind_retry_probes} "
          f"BLIND_RETRY_COUNT={driver.blind_retry_count}")


# ---------------------------------------------------------------- CA-07
def test_ca07_ack_lost_equivalent_cases(tmp_path):
    """≥5 次「durable commit 成功 + 应用级确认未保留」（真实进程被杀）。

    每个用例使用**独立合成 world**（同一专用库）以避免租约相互阻塞：
    writer 完成真实 COMMIT 后阻塞、由 controller 在应用完成记录写出前杀死进程，
    于是 durable = COMMITTED 而应用确认不存在；恢复必须 ALREADY_COMMITTED 且不重试。
    """
    ack_lost_cases = 0
    for i in range(CA07_ITERATIONS):
        # 每轮独立库 + 单 world（生产管线按单世界假设设计；隔离更干净）
        dsn = reset_ambiguity_db()
        world_id = "PGAMB-CA07"
        seed_world(dsn, world_id)
        ref = _reference(world_id, 1)
        ref_hashes = ref["hashes"]
        engine, factory = _factory({"dsn": dsn})
        driver = _driver(factory, world_id)

        out = tmp_path / f"ca07_{i}.json"
        proc = spawn({"action": "advance_year", "dsn": dsn,
                      "world_id": world_id, "year_index": 0,
                      "block_after_commit_seconds": 600,
                      "lease_seconds": LEASE_SHORT}, out)
        committed = wait_sentinel(sentinel_paths(out)["committed"], timeout=600)
        assert committed["phase"] == "COMMITTED_UNACKED", committed
        kill_worker(proc, pid=int(committed["pid"]))
        assert not out.exists(), "应用级完成记录不得存在（进程在确认前被杀）"

        info = driver.classify(0)
        assert info["outcome"] == ALREADY_COMMITTED, info
        assert info["durable_tick"] == 1_000_000, info
        assert driver.blind_retry_count == 0            # 恢复路径未盲重试
        ack_lost_cases += 1

        inv = invariants(factory, world_id, expected_years=1)
        _assert_clean(inv, years=1)
        assert authoritative_hashes(factory, world_id) == ref_hashes, i
        engine.dispose()
    print(f"CA07_ACK_LOST_EQUIVALENT_CASES={ack_lost_cases}")
    assert ack_lost_cases >= 5, f"ACK lost 等价用例不足: {ack_lost_cases}"


def test_ca07b_scheduler_path_recovery(tmp_path):
    """生产**调度器**路径的 ACK-lost：进程在 world commit 后被真实终止。

    如实记录该轮是否观测到「应用确认未保留」（状态文件未写出）；无论哪种，
    恢复都必须由 durable truth 判定且不产生重复。
    """
    world_id = "PGAMB-CA07B"
    env = _amb(world_id)
    dsn = env["dsn"]
    engine, factory = _factory(env)
    driver = _driver(factory, world_id)
    # 参照：同 world_id、同 seed、**2 年**无故障推进（与最终 committed 边界对齐）
    ref = _reference(world_id, 2)
    ref_hashes = ref["hashes"]
    from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease
    session = factory()
    lease = WriterLease(session, world_id, 600)
    lease.acquire()
    driver.classify(0)
    res = driver.submit_year(0, owner=lease.owner, token=lease.token,
                             coordinator=_hist_coordinator())
    assert res["client_outcome"] == "SUCCESS", res
    lease.release()
    session.close()

    state_dir = tmp_path / "ca07b_state"
    out = tmp_path / "ca07b.json"
    proc = spawn({"action": "scheduler_cycle", "dsn": dsn, "world_id": world_id,
                  "target_years": 2, "state_dir": str(state_dir)}, out)
    started = wait_sentinel(sentinel_paths(out)["started"], timeout=300)
    deadline = time.time() + 900
    advanced = False
    while time.time() < deadline:
        if durable_tick(factory, world_id) == 2_000_000:
            advanced = True
            break
        if out.exists():
            break
        time.sleep(0.005)
    if advanced:
        kill_worker(proc, pid=int(started["pid"]))
    else:
        proc.wait(timeout=900)
    ack_retained = bool((_json_load(out).get("result") or {}).get(
        "state_file_exists"))
    info = driver.classify(1)
    assert info["outcome"] in (ALREADY_COMMITTED, NOT_COMMITTED,
                               RUNNING_STALE), info
    assert driver.blind_retry_count == 0
    if info["outcome"] != ALREADY_COMMITTED:
        submit = _submit_after_expiry(factory, world_id, driver, 1)
        assert submit["client_outcome"] == "SUCCESS", submit
    inv = invariants(factory, world_id, expected_years=2)
    _assert_clean(inv, years=2)
    assert authoritative_hashes(factory, world_id) == ref_hashes
    engine.dispose()
    print(f"CA07B_ADVANCED={advanced} ACK_RETAINED={ack_retained}")


# ---------------------------------------------------------------- CA-08
def test_ca08_scheduler_connection_loss_must_fail_closed(tmp_path):
    """生产**调度器**在 COMMIT 期遭遇真实连接故障：必须 durable-truth 核对或 fail-closed。

    审计 AMB-AUDIT-01 的实证用例：`RuntimeScheduler._execute_batch` 的歧义分支
    只 `except RuntimeError`，而真实连接故障是 `sqlalchemy.exc.OperationalError`
    （MRO 不含 RuntimeError）。要求行为（owner §1）：
    UNKNOWN outcome → 绝不盲重试 → 查 durable truth → 只有在 truth 明确后继续；
    无法判定则 fail-closed（RECOVERING/FAILED），不得静默停在 CATCHING_UP。
    """
    world_id = "PGAMB-CA08"
    env = _amb(world_id)
    dsn = env["dsn"]
    out = tmp_path / "ca08_sched.json"
    proc = spawn({"action": "scheduler_cycle", "dsn": dsn,
                  "world_id": world_id, "target_years": 1, "slow_ms": 8000,
                  "state_dir": str(tmp_path / "ca08_state")}, out)
    inside = wait_sentinel(sentinel_paths(out)["inside_tx"], timeout=300)
    assert terminate_backend(int(inside["backend_pid"])), "backend 终止必须成功"
    res = wait_result(out, timeout=300)
    proc.wait(timeout=60)
    assert res["ok"], res
    r = res["result"]
    st = r["status_after_error"]

    engine, factory = _factory(env)
    driver = _driver(factory, world_id)
    info = driver.classify(0)

    if r["error"] is not None:
        # 异常逃出 run_cycle → 必须已置 RECOVERING/FAILED 并记录 recovery/ambiguity
        assert st["scheduler_state"] in ("RECOVERING", "FAILED"), (
            "连接故障异常逃出 run_cycle 且调度器未 fail-closed", r["error"], st)
        assert (st.get("recovery_count", 0) >= 1
                or st.get("commit_ambiguity_count", 0) >= 1), (
            "未记录 durable-truth 核对痕迹", r["error"], st)
    # 无论内部如何处理，durable truth 必须可判定，且后续必须能正确恢复
    assert info["outcome"] in (NOT_COMMITTED, RUNNING_STALE, ALREADY_COMMITTED), info
    if info["outcome"] != ALREADY_COMMITTED:
        submit = _submit_after_expiry(factory, world_id, driver, 0)
        assert submit["client_outcome"] == "SUCCESS", submit
    inv = invariants(factory, world_id, expected_years=1)
    _assert_clean(inv, years=1)
    engine.dispose()
    print(f"CA08_ERROR_TYPE={(r['error'] or {}).get('type')} "
          f"STATE_AFTER={st['scheduler_state']} "
          f"recovery_count={st.get('recovery_count')} "
          f"commit_ambiguity_count={st.get('commit_ambiguity_count')}")


# ---------------------------------------------------------------- CA-99
def test_ca99_pg011_regression_history_and_immutability():
    """PG-011 回归（decision_policy 宽度）+ 事件不可变性 + 历史完整性 + 无重复。"""
    world_id = "PGAMB-CA99"
    env = _amb(world_id)
    engine, factory = _factory(env)
    driver = _driver(factory, world_id)
    from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease
    session = factory()
    lease = WriterLease(session, world_id, 600)
    lease.acquire()
    years = int(os.environ.get("BLR_PG_AMBIG_CA99_YEARS", "12"))
    for year in range(years):
        sub = driver.submit_year(year, owner=lease.owner, token=lease.token,
                                 coordinator=_hist_coordinator())
        assert sub["client_outcome"] == "SUCCESS", sub
    lease.release()
    session.close()

    inv = invariants(factory, world_id, expected_years=years)
    _assert_clean(inv, years=years)
    audit = history_audit(factory, world_id)
    assert audit["clean"] is True, audit

    from sqlalchemy import exc as sa_exc
    from sqlalchemy import text as _text
    with factory() as s:
        width = s.execute(_text(
            "SELECT character_maximum_length FROM information_schema.columns "
            "WHERE table_name='tribulation_episodes' "
            "AND column_name='decision_policy'")).scalar()
        policies = s.execute(_text(
            "SELECT DISTINCT decision_policy FROM tribulation_episodes "
            "WHERE decision_policy IS NOT NULL")).fetchall()
    assert width == 64, width
    assert any(len(p[0]) > 24 for p in policies), policies

    from XiaoguangBlessedLandRuntime.database.invariants import (
        verify_event_immutability)
    verify_event_immutability(engine)
    for sql, op in (("UPDATE world_events SET event_type='MUT'", "UPDATE"),
                    ("DELETE FROM world_events", "DELETE"),
                    ("TRUNCATE TABLE world_events", "TRUNCATE")):
        with engine.connect() as c:
            with pytest.raises(sa_exc.DatabaseError) as exc:
                c.execute(_text(sql))
        assert "append-only" in str(exc.value) and op in str(exc.value)
    engine.dispose()

# -*- coding: utf-8 -*-
"""M6A-AC —— 正式世界激活契约（M6_ACTIVATION_CONTRACT）。

覆盖：
- AC-01 fresh activation：一次性原子创建（A4）后的 durable 真值；
- AC-02 单一事务：提交前任何注入点都不得留下部分状态（A5）；
- AC-03 A9：激活**不物化**任何人口/资源/经济/生态/社会/灾劫实例；
- AC-04 A3：激活前的现实等待时间绝不回溯补算（backlog ≡ 0）；
- AC-05 genesis 事件是正式历史的第一个事件（canon：WORLD_SEED_ACTIVATED）；
- AC-06/07 策略输入必须显式（canon 未定义 → 拒绝，绝不用默认值）；
- AC-08 A8：Seed MANIFEST / 版本 / 状态校验失败即拒绝且零写入；
- AC-09/10 前置状态不满足即拒绝（无 metadata / 时钟已初始化）；
- AC-11 激活后的世界满足冻结 CatchUpPlanner 年锚不变量（可被 scheduler 接管）；
- AC-12 结果对象只暴露指纹/版本/状态，不含 seed 原值。
"""
from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import select, text

from tests.conftest import W
from tests.m6_activation_support import (
    M6_EPOCH0_US, SYNTHETIC_DATA_FILES, build_synthetic_seed,
    business_row_counts, genesis_event, synthetic_request, world_counts,
    year_tick)

from XiaoguangBlessedLandRuntime.database.models_core import (
    RuntimeLock, WorldRuntime)
from XiaoguangBlessedLandRuntime.domain.constants import RuntimeStatus
from XiaoguangBlessedLandRuntime.domain.errors import (
    ActivationRefused, WorldSeedIntegrityError)
from XiaoguangBlessedLandRuntime.services.activation import (
    OUTCOME_COMMITTED, activate_formal_world, load_seed_package)
from XiaoguangBlessedLandRuntime.services.guard import require_world_activated
from XiaoguangBlessedLandRuntime.services.scheduler.planner import CatchUpPlanner
from XiaoguangBlessedLandRuntime.services.simulation.harness import YEAR_US


def _activate(seed_dir, factory, *, tick: int = 0, epoch0: int | None = None,
              **kw):
    """激活辅助：anchor 默认取合成世界原点；显式 ``epoch0`` 为等价别名。"""
    extra = {"epoch0_us": epoch0} if epoch0 is not None else {}
    req = synthetic_request(seed_dir, initial_blessed_tick=tick, **extra, **kw)
    return activate_formal_world(factory, request=req)


# ------------------------------------------------------------------ AC-01
def test_m6ac01_fresh_activation_commits_durable_truth(tmp_path,
                                                       m6_world):
    seed_dir = build_synthetic_seed(tmp_path)
    outcome = _activate(seed_dir, m6_world)
    assert outcome.outcome == OUTCOME_COMMITTED
    assert outcome.written is True
    assert outcome.seed_consumption_count == 1
    assert outcome.pre_activation_backlog_ticks == 0
    assert outcome.commit_outcome_was_ambiguous is False

    counts = world_counts(m6_world)
    assert counts["world_runtime_rows"] == 1
    assert counts["active_worlds"] == 1
    assert counts["genesis_events"] == 1
    assert counts["simulation_runs"] == 0
    assert counts["checkpoints"] == 0
    assert counts["runtime_lock_rows"] == 0      # 租约已释放（无残留锁）

    with m6_world() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        assert row.runtime_status == RuntimeStatus.ACTIVE
        assert row.world_seed_version == "1.0"
        assert row.current_blessed_tick == 0
        assert row.last_committed_real_us == M6_EPOCH0_US
        assert row.time_rate_remainder == 0
        assert row.current_time_ratio_id is not None
        # 激活后世界可被推进（guard 通过）
        require_world_activated(s, "m6ac01")


# ------------------------------------------------------------------ AC-02
@pytest.mark.parametrize("inject_at", ["before_transaction", "before_commit"])
def test_m6ac02_no_partial_state_on_failure(tmp_path, m6_world,
                                            monkeypatch, inject_at):
    """A5：失败必须整体 rollback —— 不允许 half world / 部分状态。"""
    seed_dir = build_synthetic_seed(tmp_path)

    if inject_at == "before_transaction":
        from XiaoguangBlessedLandRuntime.services.activation import service

        def boom(*a, **k):
            raise RuntimeError("injected failure before transaction")

        monkeypatch.setattr(service, "WorldMutationContext", boom)
    else:
        from XiaoguangBlessedLandRuntime.services.fencing import (
            WorldMutationContext)

        def failing_commit(self):
            raise RuntimeError("injected failure before commit")

        monkeypatch.setattr(WorldMutationContext, "commit", failing_commit)

    with pytest.raises(RuntimeError):
        _activate(seed_dir, m6_world)

    counts = world_counts(m6_world)
    assert counts["active_worlds"] == 0
    assert counts["genesis_events"] == 0
    assert counts["world_events"] == 0
    assert counts["rate_blessed_starts"] == [None]   # 速率行仍"未开始计"
    with m6_world() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        assert row.runtime_status == RuntimeStatus.NOT_ACTIVATED
        assert row.world_seed_version is None
        assert row.current_blessed_tick is None
        assert row.last_committed_real_us is None
        assert s.execute(select(RuntimeLock)).scalars().all() == []


# ------------------------------------------------------------------ AC-03
def test_m6ac03_activation_creates_no_world_instances(tmp_path,
                                                      m6_world):
    """A9：Runtime 不得自行补 UNKNOWN —— 激活不写任何实例数据。"""
    seed_dir = build_synthetic_seed(tmp_path)
    _activate(seed_dir, m6_world)
    counts = business_row_counts(m6_world)
    offending = {k: v for k, v in counts.items() if v > 0}
    assert offending == {}, offending


# ------------------------------------------------------------------ AC-04
def test_m6ac04_no_pre_activation_backlog(tmp_path, m6_world):
    """A3 + OWNER_CANON_DECISION_2：世界在 NOT_ACTIVATED 期间不累积 catch-up debt。

    激活的现实锚必须等于 activation canonical instant（anchor），而不是
    "metadata 播种时刻"或任何更早的时刻；tick 从 canon 原点 0 起。
    """
    seed_dir = build_synthetic_seed(tmp_path)
    anchor = M6_EPOCH0_US + 30 * YEAR_US      # 晚于速率行起点
    req = synthetic_request(seed_dir, activation_anchor_us=anchor)
    outcome = activate_formal_world(m6_world, request=req)
    assert outcome.pre_activation_backlog_ticks == 0
    assert outcome.activation_real_us == anchor
    with m6_world() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        assert row.last_committed_real_us == anchor
        assert row.current_blessed_tick == 0
        assert row.current_blessed_tick == row.current_blessed_tick  # NULL ≠ 0 语义
    # 激活不产生任何 simulation run / checkpoint（没有 retroactive catch-up）
    counts = world_counts(m6_world)
    assert counts["simulation_runs"] == 0
    assert counts["checkpoints"] == 0


# ------------------------------------------------------------------ AC-05
def test_m6ac05_genesis_event_is_canonical_first_event(tmp_path,
                                                       m6_world):
    seed_dir = build_synthetic_seed(tmp_path)
    tick = 0
    _activate(seed_dir, m6_world, tick=tick)
    ev = genesis_event(m6_world)
    assert ev is not None
    assert ev.event_type == "WORLD_SEED_ACTIVATED"
    assert ev.blessed_tick == tick
    assert ev.scope == "WORLD"
    assert ev.parent_event_ref is None
    # 激活前不得有任何事件；激活只创建这一个 genesis
    counts = world_counts(m6_world)
    assert counts["world_events"] == 1
    assert (ev.effect or {})["seed_consumption_index"] == 1
    assert (ev.effect or {})["pre_activation_backlog_ticks"] == 0
    assert (ev.effect or {})["initial_blessed_tick"] == tick
    assert (ev.cause or {})["activation_operation_id"]


# ------------------------------------------------------------------ AC-06
@pytest.mark.parametrize("tick", [-1, 1, 999_999, 1_500_000, True, 1_000_000])
def test_m6ac06_non_canon_initial_tick_is_refused(tmp_path, m6_world, tick):
    """OWNER_CANON_DECISION_1：初始 blessed tick 恒为 0 → 任何非 0 取值一律拒绝。"""
    from XiaoguangBlessedLandRuntime.services.activation import ActivationRequest

    seed_dir = build_synthetic_seed(tmp_path)
    req = ActivationRequest(world_id=W, seed_dir=seed_dir,
                            activation_anchor_us=M6_EPOCH0_US,
                            initial_blessed_tick=tick)
    with pytest.raises(ActivationRefused):
        activate_formal_world(m6_world, request=req)
    assert world_counts(m6_world)["world_events"] == 0
    assert world_counts(m6_world)["active_worlds"] == 0


def test_m6ac06a_tick_defaults_to_owner_canon(tmp_path):
    """canon 已裁决：省略 tick 即取 0（Runtime 内部正式时间原点）。"""
    from XiaoguangBlessedLandRuntime.domain.constants import (
        WorldActivationPolicy)
    from XiaoguangBlessedLandRuntime.services.activation import ActivationRequest

    seed_dir = build_synthetic_seed(tmp_path)
    req = ActivationRequest(world_id=W, seed_dir=seed_dir,
                            activation_anchor_us=M6_EPOCH0_US)
    assert req.initial_blessed_tick == WorldActivationPolicy.INITIAL_BLESSED_TICK
    assert req.initial_blessed_tick == 0


def test_m6ac06b_anchor_is_required(tmp_path, m6_world):
    """OWNER_CANON_DECISION_2：activation anchor 是必填输入（无默认值）。"""
    from XiaoguangBlessedLandRuntime.services.activation import ActivationRequest

    seed_dir = build_synthetic_seed(tmp_path)
    with pytest.raises(TypeError):
        ActivationRequest(world_id=W, seed_dir=seed_dir)   # 缺 anchor
    assert world_counts(m6_world)["world_events"] == 0


# ------------------------------------------------------------------ AC-07
@pytest.mark.parametrize("elapsed_years", [0, 2, 5])
def test_m6ac07_activated_world_satisfies_frozen_planner_anchor(
        tmp_path, m6_world, elapsed_years):
    """激活产生的 (tick, cursor) 必须让冻结 CatchUpPlanner 永远不 fail-closed。

    planner.plan 要求 ``tick % 1e6 == 0`` 且 ``cursor == epoch0 + k*YEAR_US``
    （services/scheduler/planner.py:94-102）。激活若不满足，世界一被 scheduler
    接管就会 FAILED。canon：tick 从 0 起，anchor = activation instant。
    """
    seed_dir = build_synthetic_seed(tmp_path)
    anchor = M6_EPOCH0_US + 12_345                # 任意 UTC anchor（非年整点）
    _activate(seed_dir, m6_world, tick=0, epoch0=anchor)

    planner = CatchUpPlanner(world_id=W, epoch0_us=anchor)
    with m6_world() as s:
        now = anchor + elapsed_years * YEAR_US
        plan = planner.plan(s, now_real_us=now, budget_ticks=10 * 1_000_000)
    assert plan.durable_tick == 0
    assert plan.due_ticks == elapsed_years * 1_000_000
    if elapsed_years == 0:
        assert plan.year_indices == ()            # 无需推进
    else:
        assert plan.year_indices[0] == 0          # 年序号从激活年（0）起


# ------------------------------------------------------------------ AC-08
def test_m6ac08_seed_manifest_tamper_rejected(tmp_path, m6_world):
    seed_dir = build_synthetic_seed(tmp_path, tamper=SYNTHETIC_DATA_FILES[0])
    with pytest.raises(WorldSeedIntegrityError):
        _activate(seed_dir, m6_world)
    assert world_counts(m6_world)["world_events"] == 0


def test_m6ac08b_seed_version_and_status_enforced(tmp_path,
                                                  m6_world):
    wrong_version = build_synthetic_seed(tmp_path, version="9.9",
                                         name="seed_wrong_version")
    with pytest.raises(WorldSeedIntegrityError):
        _activate(wrong_version, m6_world)

    wrong_status = build_synthetic_seed(tmp_path, status="ACTIVE",
                                        name="seed_wrong_status")
    with pytest.raises(WorldSeedIntegrityError):
        _activate(wrong_status, m6_world)

    assert world_counts(m6_world)["world_events"] == 0
    assert world_counts(m6_world)["active_worlds"] == 0


def test_m6ac08c_malformed_seed_package_maps_to_integrity_error(tmp_path,
                                                               m6_world):
    """畸形 MANIFEST / VERSION.json 必须归入 Seed 完整性失败（绝不裸抛异常）。"""
    bad_manifest = build_synthetic_seed(tmp_path, name="seed_bad_manifest")
    (bad_manifest / "MANIFEST.sha256.txt").write_text("not-a-valid-line\n",
                                                      encoding="utf-8")
    with pytest.raises(WorldSeedIntegrityError):
        _activate(bad_manifest, m6_world)

    bad_version = build_synthetic_seed(tmp_path, name="seed_bad_version")
    (bad_version / "VERSION.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(WorldSeedIntegrityError):
        _activate(bad_version, m6_world)

    assert world_counts(m6_world)["active_worlds"] == 0
    assert world_counts(m6_world)["world_events"] == 0


# ------------------------------------------------------------------ AC-09/10
def test_m6ac09_zero_row_activation_bootstraps_runtime(tmp_path,
                                                      session_factory):
    """M6A.1 契约更新（原「无 world_runtime 行 → 拒绝」）。

    原期望编码的是 CONTRACT_IMPLEMENTATION_DRIFT：它要求外部先建 NOT_ACTIVATED 行，
    与 canonical zero-row 契约（tests/formal_db.py：0 行 == 未激活）冲突，且使
    `activate_formal_world` 无法从正式 pre-activation 状态进入 ACTIVE。

    M6A.1 后：canonical zero-row 是**正式激活入口**；activation 在同一 authoritative
    事务内建立 transient runtime bootstrap，其 simulation_version 取自 request，
    world_bible/seed 元数据取自已验证 Seed 包 —— 不发明世界内容。
    """
    seed_dir = build_synthetic_seed(tmp_path)
    out = _activate(seed_dir, session_factory)
    assert getattr(out, "outcome", None) in ("COMMITTED",)
    with session_factory() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        assert row.runtime_status == "ACTIVE"
        assert row.current_blessed_tick == 0
        assert int(s.execute(text(
            "SELECT COUNT(*) FROM world_events")).scalar() or 0) == 1


def test_m6ac10_refuses_when_clock_already_initialized(tmp_path,
                                                       m6_world):
    with m6_world() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        row.current_blessed_tick = 0
        s.commit()
    seed_dir = build_synthetic_seed(tmp_path)
    with pytest.raises(ActivationRefused):
        _activate(seed_dir, m6_world)
    with m6_world() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        assert row.runtime_status == RuntimeStatus.NOT_ACTIVATED
        assert row.world_seed_version is None


# ------------------------------------------------------------------ AC-12
def test_m6ac12_outcome_exposes_only_fingerprint_version_status(
        tmp_path, m6_world):
    seed_dir = build_synthetic_seed(tmp_path)
    outcome = _activate(seed_dir, m6_world)
    manifest_sha = hashlib.sha256(
        (seed_dir / "MANIFEST.sha256.txt").read_bytes()).hexdigest()
    assert outcome.seed_fingerprint == manifest_sha
    assert set(outcome.seed) == {
        "seed_version", "declared_status", "seed_fingerprint",
        "seed_manifest_digest", "seed_manifest_entries"}
    # seed 数据文件内容绝不进入结果对象
    blob = repr(outcome.as_dict())
    for fname in SYNTHETIC_DATA_FILES:
        assert fname not in blob


def test_m6ac12b_loader_never_reads_seed_values(tmp_path):
    """Seed 装载器只读身份层：返回对象不含任何 data 文件内容。"""
    seed_dir = build_synthetic_seed(tmp_path)
    pkg = load_seed_package(seed_dir)
    assert pkg.declared_status == "PREPARED_NOT_ACTIVATED"
    assert pkg.manifest_entries == len(SYNTHETIC_DATA_FILES) + 1
    blob = repr(pkg.public_view())
    assert "SYNTHETIC TEST ONLY" not in blob


# ------------------------------------------------------------------ AC-13
def test_m6ac13_same_seed_yields_same_initial_world_hash(tmp_path):
    """§13：同一 synthetic seed → 同一 initial world hash（确定性出生）。

    两个**互相独立**的临时正式库、同一份 synthetic seed、同一激活请求参数
    → 冻结 ``world_state_hash_v6`` 必须给出同一初态哈希。
    """
    from tests.m6_activation_support import new_synthetic_world

    from XiaoguangBlessedLandRuntime.domain.constants import SimulationVersion
    from XiaoguangBlessedLandRuntime.services.simulation.snapshot import (
        read_snapshot)
    from XiaoguangBlessedLandRuntime.services.simulation.state_hash import (
        world_state_hash_v6)

    results = []
    for tag in ("a", "b"):
        env = new_synthetic_world(tmp_path / tag)
        seed_dir = build_synthetic_seed(tmp_path / tag)   # 同内容 → 同指纹
        out = activate_formal_world(env["factory"], request=synthetic_request(
            seed_dir))
        with env["factory"]() as s:
            digest = world_state_hash_v6(
                snapshot=read_snapshot(s, W),
                simulation_version=SimulationVersion.CURRENT,
                pipeline_version="m6a-initial-state-test-v1",
                engine_versions={})
        results.append((out.seed_fingerprint, digest, out.activation_real_us))
        env["engine"].dispose()

    assert results[0][0] == results[1][0], "同一 seed 内容必须有同一指纹"
    assert results[0][2] == results[1][2], "同一请求参数必须有同一激活时刻"
    assert results[0][1] == results[1][1], (
        "同一 seed + 同一请求 → 必须产生同一 initial world hash")


# ------------------------------------------------------------------ AC-14
def test_m6ac14_duplicate_genesis_uid_is_refused_with_zero_partial_state(
        tmp_path, m6_world):
    """DB 层 exactly-once 兜底：genesis ``event_uid`` 撞车必须是被拒绝，不是崩溃。

    模拟"库里已存在同 uid 的事件"（例如人工恢复/异常副本）：
    激活必须 fail-closed、零部分状态，且不得裸抛 SQLAlchemy 异常。
    """
    from XiaoguangBlessedLandRuntime.domain.constants import EventSources, Scopes
    from XiaoguangBlessedLandRuntime.services.activation.service import (
        _genesis_uid)
    from XiaoguangBlessedLandRuntime.services.repositories import EventRepository

    tick = 0
    req = synthetic_request(build_synthetic_seed(tmp_path),
                            initial_blessed_tick=tick)
    with m6_world() as s:
        EventRepository(s).append(
            world_id=W, event_type="WORLD_SEED_ACTIVATED",
            source=EventSources.OWNER_INPUT, blessed_tick=tick,
            scope=Scopes.WORLD, event_uid=_genesis_uid(req))
        s.commit()

    with pytest.raises(ActivationRefused):
        activate_formal_world(m6_world, request=req)

    counts = world_counts(m6_world)
    assert counts["active_worlds"] == 0            # 零部分状态
    assert counts["genesis_events"] == 1           # 只有预置的那一条
    assert counts["rate_blessed_starts"] == [None]
    assert counts["runtime_lock_rows"] == 0
    with m6_world() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        assert row.runtime_status == "NOT_ACTIVATED"
        assert row.current_blessed_tick is None


# ------------------------------------------------------------------ AC-15..19
def test_m6ac15_activation_anchor_is_durable_and_readable(tmp_path, m6_world):
    """OWNER_CANON_DECISION_2：anchor 必须与 activation operation 一起 durable 持久化。

    （M6B 的 OPTION A 接线据此让 RuntimeScheduler 读取同一个 anchor。）
    """
    from XiaoguangBlessedLandRuntime.services.durable_truth import (
        read_world_epoch_anchor)

    assert read_world_epoch_anchor(m6_world, world_id=W) is None  # 未激活
    seed_dir = build_synthetic_seed(tmp_path)
    anchor = M6_EPOCH0_US + 12_345_678
    out = _activate(seed_dir, m6_world, activation_anchor_us=anchor)
    assert out.outcome == OUTCOME_COMMITTED
    assert out.activation_real_us == anchor          # tick=0 → cursor = anchor
    assert read_world_epoch_anchor(m6_world, world_id=W) == anchor
    with m6_world() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        assert row.current_blessed_tick == 0
        assert row.last_committed_real_us == anchor


def test_m6ac16_world_id_mismatch_refused(tmp_path, m6_world):
    """F8：请求 world_id 与库中世界不一致 → 准确拒绝（不是被误报成租约竞争）。"""
    seed_dir = build_synthetic_seed(tmp_path)
    with pytest.raises(ActivationRefused) as ei:
        _activate(seed_dir, m6_world, world_id="OTHER-WORLD")
    assert "不一致" in ei.value.message
    with m6_world() as s:
        assert s.execute(select(RuntimeLock)).scalars().all() == []
    assert world_counts(m6_world)["active_worlds"] == 0


def test_m6ac17_simulation_version_mismatch_refused(tmp_path, m6_world):
    seed_dir = build_synthetic_seed(tmp_path)
    with pytest.raises(ActivationRefused):
        _activate(seed_dir, m6_world, simulation_version="9.9.9-bogus")
    assert world_counts(m6_world)["active_worlds"] == 0


def test_m6ac18_prior_genesis_with_different_uid_is_refused(tmp_path, m6_world):
    """F3/F10：A2/A10 —— 未激活世界若已有 genesis（哪怕 uid 不同）必须拒绝。

    这正是"event_uid 唯一约束"覆盖不到的场景（uid 把年锚算进哈希），
    因此必须由 durable truth 前置门禁兜住，绝不"绕过它再写第二个 genesis"。
    """
    from XiaoguangBlessedLandRuntime.domain.constants import (
        EventSources, Scopes)
    from XiaoguangBlessedLandRuntime.services.repositories import EventRepository

    tick = 0
    seed_dir = build_synthetic_seed(tmp_path)
    with m6_world() as s:
        EventRepository(s).append(
            world_id=W, event_type="WORLD_SEED_ACTIVATED",
            source=EventSources.OWNER_INPUT, blessed_tick=tick,
            scope=Scopes.WORLD, event_uid="f" * 32)      # 不同 uid
        s.commit()

    with pytest.raises(ActivationRefused) as ei:
        _activate(seed_dir, m6_world, tick=tick)
    assert "genesis" in ei.value.message
    counts = world_counts(m6_world)
    assert counts["genesis_events"] == 1        # 没有第二个 genesis
    assert counts["active_worlds"] == 0


def test_m6ac18b_prior_history_in_unactivated_world_is_refused(tmp_path,
                                                               m6_world):
    """A2/A10：未激活世界存在任何正式事件 → 拒绝（激活前官方历史必须为空）。"""
    from XiaoguangBlessedLandRuntime.domain.constants import EventSources
    from XiaoguangBlessedLandRuntime.services.repositories import EventRepository

    seed_dir = build_synthetic_seed(tmp_path)
    with m6_world() as s:
        EventRepository(s).append(
            world_id=W, event_type="TIME_ADVANCE", source=EventSources.SIMULATION,
            blessed_tick=0, event_uid="e" * 32)
        s.commit()
    with pytest.raises(ActivationRefused) as ei:
        _activate(seed_dir, m6_world)
    assert "官方历史" in ei.value.message
    assert world_counts(m6_world)["active_worlds"] == 0


def test_m6ac19_active_world_without_recorded_fingerprint_is_refused(
        tmp_path, m6_world):
    """F4：ACTIVE 但没有 genesis 指纹 → 绝不谎报"这个 Seed 已被消费"。"""
    from XiaoguangBlessedLandRuntime.domain.constants import (
        EventSources, RuntimeStatus, Scopes)
    from XiaoguangBlessedLandRuntime.services.repositories import EventRepository

    seed_dir = build_synthetic_seed(tmp_path)
    with m6_world() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        row.runtime_status = RuntimeStatus.ACTIVE
        row.world_seed_version = "1.0"
        row.current_blessed_tick = 0
        row.last_committed_real_us = M6_EPOCH0_US
        EventRepository(s).append(
            world_id=W, event_type="WORLD_SEED_ACTIVATED",
            source=EventSources.OWNER_INPUT, blessed_tick=0,
            scope=Scopes.WORLD, event_uid="d" * 32,
            effect={"note": "no fingerprint recorded"})
        s.commit()

    with pytest.raises(ActivationRefused) as ei:
        _activate(seed_dir, m6_world)
    assert "指纹" in ei.value.message

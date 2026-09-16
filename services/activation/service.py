# -*- coding: utf-8 -*-
"""M6A —— 正式世界激活协议（**唯一** public production entrypoint）。

```
PREPARED_NOT_ACTIVATED
  → one-shot activation request
  → consume official World Seed exactly once（校验身份/版本/完整性）
  → create authoritative formal world（A4：同一 durable 事务）
  → establish activation / time anchor
  → initialize canonical world bootstrap state
  → commit durable truth
  → ACTIVATED
```

## 本协议遵守的冻结 canon

| 规则 | 来源 | 本实现 |
|---|---|---|
| A1 激活前 tick = NULL | 14_activation_invariants A1 | 未激活态不变（repositories.assert_activatable 强制） |
| A2 激活前历史 = EMPTY | A2 | 激活前零事件；只有 genesis 事件被创建 |
| A3 现实等待时间不得回溯补算 | A3 | 现实锚 = 激活 canonical instant（年锚对齐）；backlog ≡ 0 |
| A4 一次性原子创建 seed/epoch/tick/cursor/initial state | A4 | 全部写入落在**同一个** ``WorldMutationContext`` 事务 |
| A5 失败整体 rollback（无部分状态） | A5 | ``WorldMutationContext.__exit__`` 未显式 commit 即回滚 |
| A6 同一 seed 不得激活两次 | A6 | 事务内门禁：已激活判定 + ``assert_activatable``（四条件）+ 未激活世界不得已有事件/genesis；DB 侧另由 ``world_id`` UNIQUE 与 genesis ``event_uid`` UNIQUE 兜底（后者只挡参数完全相同的重放） |
| A7 激活必须 idempotent（重试安全） | A7 | durable truth 先判；已 COMMITTED → 幂等返回，零写入 |
| A8 Seed 必须通过 MANIFEST checksum | A8 | ``seed_package.load_seed_package``（复用冻结校验算法） |
| A9 Runtime 不得自行补 UNKNOWN | A9 | 激活**不创建**任何人口/资源/经济/生态/社会/灾劫实例 |
| A10 动态历史只能在 activation epoch 之后 | A10 | genesis 事件即 epoch 起点；此前无任何历史 |

## commit 歧义（§16：复用 PG-012 纪律，不建第二套）

```
commit 结果未知 → 绝不盲重试 → 读 durable truth（services/durable_truth）
                → COMMITTED / NOT_COMMITTED → 再行动
durable truth 读不到 → ActivationOutcomeUnknown（fail-closed）
```

## 本协议**不**发明的东西

M6B：两个策略输入已由主人 canon 裁决（`domain.constants.WorldActivationPolicy`）——

- **initial blessed tick = 0**（OWNER_CANON_DECISION_1）：Runtime 内部正式时间原点；
  NULL ≠ 0（未激活时仍为 NULL）。非 0 取值一律拒绝。
- **activation anchor = 显式正式激活操作的 canonical UTC instant**
  （OWNER_CANON_DECISION_2）：durable authoritative fact，与 activation operation
  一起持久化；RuntimeScheduler 经 ``durable_truth.read_world_epoch_anchor()``
  读取它（OPTION A 接线），不按当前时间重算、不在 restart 后改变。
- **初始世界内容**：仍为 OPEN（``M6_DESIGN_GAP_INITIAL_WORLD_STATE``）。
  无任何生产原语可物化 Seed baseline，且 canon（A9 + 00 号 §3）明令不得把
  PROVISIONAL/UNKNOWN 数值写成世界事实 → 激活不创建任何实例。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError as SaIntegrityError
from sqlalchemy.orm import Session, sessionmaker

from ...database.models_core import WorldEvent
from ...domain.blessed_time import (
    MAX_TICK, TICKS_PER_BLESSED_YEAR, TimeRate, epoch_us_to_datetime)
from ...domain.constants import (
    EventSources, Scopes, SimulationVersion, WorldActivationPolicy,
    WorldSeedVersion)
from ...domain.errors import (
    ActivationOutcomeUnknown, ActivationRefused, WriterLockConflict)
from ..durable_truth import (
    GENESIS_EVENT_TYPE, count_events, count_genesis_events,
    read_activation_truth, read_world_epoch_anchor)
from ..fencing import WorldMutationContext
from ..guard import create_simulation_event
from ..identity import deterministic_hex_id
from ..repositories import RuntimeRepository, TimeRatioRepository
from ..simulation.event_stream import deterministic_event_uid
from ..simulation.harness import YEAR_US
from ..time_engine import RateWindow, rate_at
from ..writer_lock import WriterLease
from .seed_package import SeedPackage, load_seed_package

#: genesis 事件的确定性身份命名空间（不是世界规律，只是 identity schema 标签）
GENESIS_ENGINE_ID = "WORLD_ACTIVATION"
ACTIVATION_ID_SCHEMA = "world-activation-v1"

#: 结果枚举
OUTCOME_COMMITTED = "COMMITTED"
OUTCOME_ALREADY_COMMITTED = "ALREADY_COMMITTED"


@dataclass(frozen=True)
class ActivationRequest:
    """一次性激活请求（owner-only 控制面构造）。

    M6B：两个策略输入已由主人 canon 裁决（`domain.constants.WorldActivationPolicy`）：

    - ``initial_blessed_tick`` = **0**（内部正式时间原点；NULL ≠ 0）。
      非 0 值一律拒绝 —— 不再需要"无默认值"的占位策略。
    - ``activation_anchor_us`` = **显式**正式激活操作的 canonical UTC instant
      （OWNER_CANON_DECISION_2）。它与 activation operation 一起 durable 持久化，
      并且是 RuntimeScheduler 读取的**唯一**年锚来源（OPTION A 接线）：
      既不按当前时间重算，也不在 restart 后改变。
    """

    world_id: str
    seed_dir: Path
    activation_anchor_us: int           # OWNER_CANON_DECISION_2（现实 epoch µs）
    initial_blessed_tick: int = WorldActivationPolicy.INITIAL_BLESSED_TICK
    expected_seed_version: str = WorldSeedVersion.CURRENT
    simulation_version: str = SimulationVersion.CURRENT
    lease_seconds: int | None = None
    operator: str | None = None         # owner-only 控制面身份（审计用）

    @property
    def year_index(self) -> int:
        return self.initial_blessed_tick // TICKS_PER_BLESSED_YEAR

    @property
    def activation_real_us(self) -> int:
        """激活 canonical instant（= 现实游标起点；保证 A3：backlog ≡ 0）。"""
        return self.activation_anchor_us + self.year_index * YEAR_US

    @property
    def epoch0_us(self) -> int:
        """世界年锚（tick=0 时恒等于 activation anchor）。"""
        return self.activation_real_us


@dataclass(frozen=True)
class ActivationOutcome:
    outcome: str
    written: bool
    world_id: str
    world_seed_version: str
    seed_fingerprint: str
    initial_blessed_tick: int
    activation_real_us: int
    activation_operation_id: str
    genesis_event_uid: str | None
    seed_consumption_count: int
    pre_activation_backlog_ticks: int = 0
    commit_outcome_was_ambiguous: bool = False
    seed: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "outcome": self.outcome,
            "written": self.written,
            "world_id": self.world_id,
            "world_seed_version": self.world_seed_version,
            "seed_fingerprint": self.seed_fingerprint,
            "initial_blessed_tick": self.initial_blessed_tick,
            "activation_real_us": self.activation_real_us,
            "activation_operation_id": self.activation_operation_id,
            "genesis_event_uid": self.genesis_event_uid,
            "seed_consumption_count": self.seed_consumption_count,
            "pre_activation_backlog_ticks": self.pre_activation_backlog_ticks,
            "commit_outcome_was_ambiguous": self.commit_outcome_was_ambiguous,
            "seed": self.seed,
        }


# ------------------------------------------------------------------ validation
def _validate_request(request: ActivationRequest) -> None:
    """请求级校验（fail-closed；owner canon 之外的一切取值一律拒绝）。"""
    if not isinstance(request.world_id, str) or not request.world_id:
        raise ActivationRefused("world_id 必须为非空字符串")
    if len(request.world_id) > 64:      # world_runtime.world_id / runtime_lock VARCHAR(64)
        raise ActivationRefused(
            "world_id 超出列宽（VARCHAR(64)）；PG 会拒绝该值",
            detail={"length": len(request.world_id)})
    if isinstance(request.initial_blessed_tick, bool) or \
            not isinstance(request.initial_blessed_tick, int):
        raise ActivationRefused("initial_blessed_tick 必须为整数")
    # OWNER_CANON_DECISION_1：初始 blessed tick 恒为 0（不是可调参数）
    if request.initial_blessed_tick != WorldActivationPolicy.INITIAL_BLESSED_TICK:
        raise ActivationRefused(
            "initial_blessed_tick 必须等于 owner canon 值 "
            f"{WorldActivationPolicy.INITIAL_BLESSED_TICK}"
            "（OWNER_CANON_DECISION_1：tick=0 是 Runtime 内部正式时间原点）",
            detail={"initial_blessed_tick": request.initial_blessed_tick})
    if isinstance(request.activation_anchor_us, bool) or \
            not isinstance(request.activation_anchor_us, int) or \
            request.activation_anchor_us <= 0:
        raise ActivationRefused(
            "activation_anchor_us 必须显式提供正整数（OWNER_CANON_DECISION_2："
            "激活 anchor = 显式正式激活操作的 canonical UTC instant）")
    if request.activation_anchor_us > MAX_TICK:
        raise ActivationRefused(
            "activation_anchor_us 超出 64-bit 现实游标范围",
            detail={"activation_anchor_us": request.activation_anchor_us})
    # 冻结 planner 不变量（planner.py:94-102）：batch 只落在年边界
    if request.initial_blessed_tick % TICKS_PER_BLESSED_YEAR != 0:
        raise ActivationRefused(
            "initial_blessed_tick 必须整年对齐（tick % 1_000_000 == 0）",
            detail={"initial_blessed_tick": request.initial_blessed_tick})
    expected = request.activation_anchor_us + request.year_index * YEAR_US
    if request.activation_real_us != expected:
        raise ActivationRefused(
            "激活时刻与 anchor 不一致（冻结 planner 年锚不变量）",
            detail={"activation_real_us": request.activation_real_us,
                    "expected": expected})
    if not request.expected_seed_version:
        raise ActivationRefused("expected_seed_version 必须显式提供")
    if not isinstance(request.simulation_version, str) or \
            not request.simulation_version:
        raise ActivationRefused("simulation_version 必须为非空字符串")


def _activation_operation_id(request: ActivationRequest, seed: SeedPackage) -> str:
    """durable operation identity（§7）：同一 (世界, seed, tick) 只有一个 canonical id。"""
    return deterministic_hex_id(
        [request.world_id, seed.seed_version, seed.fingerprint,
         str(request.initial_blessed_tick)],
        bits=128, schema=ACTIVATION_ID_SCHEMA)


def _genesis_uid(request: ActivationRequest) -> str:
    """genesis 事件确定性 uid（event_type 参与身份；同一激活恒等）。"""
    anchor = request.activation_real_us
    return deterministic_event_uid(
        world_id=request.world_id,
        simulation_version=request.simulation_version,
        real_start_us=anchor, real_end_us=anchor,
        engine_id=GENESIS_ENGINE_ID, event_type=GENESIS_EVENT_TYPE, seq=0)


def _effective_ratio(session: Session, request: ActivationRequest) -> int:
    """激活时刻生效的速率行 id（冻结 time_engine 原语；无速率 → 拒绝）。

    覆盖守卫：世界原点**不得早于**其时间规则的有效起点 —— 否则
    ``rate_at`` 无法覆盖 ``[cursor, now]``，冻结 planner/catch_up 会在首个
    cycle fail-closed（世界永远无法被推进）。
    """
    repo = TimeRatioRepository(session)
    rows = repo.list_effective_up_to(request.world_id,
                                     request.activation_real_us)
    if not rows:
        earliest = None
        all_rows = repo.list_all()
        if all_rows:
            earliest = min(r.real_effective_from_us for r in all_rows)
        if earliest is not None and earliest > request.activation_real_us:
            raise ActivationRefused(
                "世界原点早于时间规则的有效起点（速率 canon 不覆盖该时刻）："
                "冻结 time_engine.rate_at 会拒绝积分",
                detail={"activation_real_us": request.activation_real_us,
                        "earliest_rate_start_us": earliest})
        raise ActivationRefused(
            "rate history 为空：未播种自然态速率行（先运行既有 seed 路径）",
            detail={"world_id": request.world_id})
    windows = [RateWindow(real_effective_from_us=r.real_effective_from_us,
                          rate=_rate_of(r), ratio_id=r.ratio_id, reason=r.reason)
               for r in rows]
    _rate, ratio_id = rate_at(windows, request.activation_real_us)
    return ratio_id


def _seed_canonical_initial_rate(session: Session,
                                 request: ActivationRequest) -> None:
    """在 activation 事务内建立 canonical initial rate binding（幂等）。

    使用 frozen M1 的自然态倍率语义（1 canonical blessed µy / 1 real µs =
    1_000_000 / 86_400_000_000），与既有 seed 路径同值；**不 invent 新倍率**。
    已存在 rate 行时不做任何事（第二次 activation 不新增 binding）。
    """
    from datetime import datetime, timezone
    repo = TimeRatioRepository(session)
    if repo.list_all():
        return
    repo.add(
        world_id=request.world_id,
        real_effective_from=datetime.fromtimestamp(
            request.activation_real_us / 1_000_000, tz=timezone.utc),
        rate_numerator=1_000_000, rate_denominator=86_400_000_000,
        reason="ACTIVATION", source="ACTIVATION")


def _rate_of(row):  # noqa: ANN001
    return TimeRate(row.rate_numerator, row.rate_denominator)


def _read_genesis_uid(session: Session, world_id: str) -> str | None:
    return session.execute(
        select(WorldEvent.event_uid)
        .where(WorldEvent.world_id == world_id,
               WorldEvent.event_type == GENESIS_EVENT_TYPE)
        .order_by(WorldEvent.id)
        .limit(1)).scalar_one_or_none()


# ------------------------------------------------------------------ entrypoint
def activate_formal_world(session_factory: sessionmaker[Session], *,
                          request: ActivationRequest) -> ActivationOutcome:
    """**唯一**正式世界激活入口（一次性、原子、幂等、可恢复、fail-closed）。

    返回 ``ActivationOutcome``：

    - ``COMMITTED``：本次调用完成了激活事务（``written=True``）；
    - ``ALREADY_COMMITTED``：durable truth 显示该世界（同一 Seed）已激活，
      本次**零写入**幂等返回（绝不产生第二个世界 / 第二次 seed 消费）。

    抛出：

    - ``ActivationRefused``：前置条件/策略输入不合法（零写入，可安全修正后重试）；
    - ``WriterLockConflict`` 包装为 ``ActivationRefused``（另一 Runtime 正在推进）；
    - ``FencingViolation``：提交前租约被接管（零写入）；
    - ``ActivationOutcomeUnknown``：commit 结果未知且 durable truth 不可读取
      （fail-closed，调用方必须人工核对，**禁止盲重试**）。
    """
    _validate_request(request)

    # ---- 1) A8：Seed 身份/版本/完整性（只读；失败即拒绝，零写入） --------------
    seed = load_seed_package(request.seed_dir,
                             expected_seed_version=request.expected_seed_version)

    # ---- 2) durable truth 预判（只读）：已激活 → 幂等返回 ---------------------
    truth = read_activation_truth(session_factory, world_id=request.world_id)
    if truth.committed:
        return _already_committed_outcome(session_factory, request, seed,
                                          truth.world_seed_version)
    _assert_world_identity(session_factory, request)

    operation_id = _activation_operation_id(request, seed)
    genesis_uid = _genesis_uid(request)

    # ---- 3) 单写者租约（§15）：两个 Activator 只有一个能拿到 -------------------
    # M6A.1 §3/§4/§5：canonical zero-row 入口。租约必须与 activation 处于**同一
    # 事务**，因此在事务内先建立 transient world_runtime 父行（未提交前对其它连接
    # 不可见 → TRANSIENT_RUNTIME_ROW_DURABLE_BEFORE_ACTIVATION_COMMIT = FALSE），
    # 再由同一 session 取得租约/fencing；失败即整体 rollback 回 canonical zero-row。
    _probe = session_factory()
    try:
        _zero_row = RuntimeRepository(_probe).get() is None
    finally:
        _probe.close()
    if _zero_row:
        _activation_session = session_factory()
        RuntimeRepository(_activation_session).create_not_activated(
            world_id=request.world_id, world_bible_version="1.0",
            simulation_version=request.simulation_version,
            world_bible_manifest_hash=getattr(seed, "manifest_digest", None))
        _activation_session.flush()
        lease_session = _activation_session
        lease = WriterLease(_activation_session, request.world_id,
                            lease_seconds=request.lease_seconds or 120)
        try:
            lease.acquire(commit=False)
        except WriterLockConflict as exc:
            _activation_session.rollback()
            _activation_session.close()
            raise ActivationRefused(
                "另一 Runtime 正在推进该世界；正式激活只允许单写者",
                detail={"world_id": request.world_id}) from exc
        except Exception:
            _activation_session.rollback()
            _activation_session.close()
            raise
    else:
        lease_session = session_factory()
        lease = WriterLease(lease_session, request.world_id,
                            lease_seconds=request.lease_seconds or 120)
    try:
        if not _zero_row:
            lease.acquire()
    except WriterLockConflict as exc:
        lease_session.close()
        raise ActivationRefused(
            "另一 Runtime 正在推进该世界；正式激活只允许单写者",
            detail={"world_id": request.world_id}) from exc
    except DBAPIError as exc:
        # 例如 FK 违规（world_id 与世界行不一致）或锁等待超时：**必须**关闭会话，
        # 绝不留下 checked-out 连接（否则每次尝试泄漏一个连接）。
        try:
            lease_session.close()
        except Exception:  # noqa: BLE001,S110
            pass
        raise ActivationRefused(
            "获取世界写租约失败（数据库错误；零写入）",
            detail={"world_id": request.world_id,
                    "error": type(exc).__name__}) from exc
    except Exception:
        try:
            lease_session.close()
        except Exception:  # noqa: BLE001,S110
            pass
        raise

    ambiguous = False
    try:
        # ---- 4) 单一 durable 事务（A4/A5）------------------------------------
        # zero-row 路径复用租约所在 session（runtime bootstrap 已在其事务内）
        session = _activation_session if _zero_row else session_factory()
        try:
            try:
                with WorldMutationContext(
                        session, world_id=request.world_id,
                        writer_id=lease.owner, fencing_token=lease.token,
                        lease_seconds=request.lease_seconds
                ) as ctx:
                    repo = RuntimeRepository(ctx.session)
                    # 事务内二次判定（并发激活的最终仲裁；已激活 → 不写任何东西）
                    existing_seed_version = _committed_seed_version(
                        ctx.session, request.world_id)
                    if existing_seed_version is not None:
                        ctx.session.rollback()
                        return _already_committed_outcome(
                            session_factory, request, seed,
                            existing_seed_version)
                    # M6A.1 §7：不再要求外部预播种 time_ratio_history ——
                    # activation 事务内建立 canonical initial rate binding（M1 自然态倍率）。
                    _seed_canonical_initial_rate(ctx.session, request)
                    ratio_id = _effective_ratio(ctx.session, request)
                    _assert_pristine_pre_activation_state(ctx.session, request)
                    repo.activate(
                        world_id=request.world_id,
                        world_seed_version=seed.seed_version,
                        initial_blessed_tick=request.initial_blessed_tick,
                        activation_real_us=request.activation_real_us,
                        current_time_ratio_id=ratio_id)
                    repo.sync_schema_version()
                    TimeRatioRepository(ctx.session).bind_blessed_start(
                        ratio_id=ratio_id,
                        blessed_effective_from_tick=request.initial_blessed_tick)
                    # genesis 事件：经唯一受保护事件入口（guard 已认可世界激活）
                    create_simulation_event(
                        ctx.session,
                        world_id=request.world_id,
                        event_type=GENESIS_EVENT_TYPE,
                        source=EventSources.OWNER_INPUT,
                        blessed_tick=request.initial_blessed_tick,
                        real_time=epoch_us_to_datetime(
                            request.activation_real_us),
                        severity=0.0, scope=Scopes.WORLD,
                        cause={"kind": "FORMAL_WORLD_ACTIVATION",
                               "activation_operation_id": operation_id,
                               "operator": (request.operator
                                            or "OWNER_CONTROL_PLANE")},
                        effect={
                            "world_seed_version": seed.seed_version,
                            "world_seed_id": seed.seed_id,
                            "world_seed_fingerprint": seed.fingerprint,
                            "world_seed_manifest_digest": seed.manifest_digest,
                            "initial_blessed_tick":
                                request.initial_blessed_tick,
                            "activation_real_us": request.activation_real_us,
                            # OWNER_CANON_DECISION_2：激活 anchor 是 durable 事实，
                            # 也是 RuntimeScheduler 读取年锚的**唯一**来源。
                            "activation_anchor_us": request.activation_anchor_us,
                            "epoch0_us": request.epoch0_us,
                            "anchor_policy": WorldActivationPolicy.ANCHOR_POLICY,
                            "seed_consumption_index": 1,
                            "pre_activation_backlog_ticks": 0,
                        },
                        participants=[],
                        state_changes=[{
                            "entity_type": "WORLD_RUNTIME",
                            "entity_id": request.world_id,
                            "field": "runtime_status",
                            "old_value": "NOT_ACTIVATED",
                            "new_value": "ACTIVE",
                        }],
                        event_uid=genesis_uid,
                    )
                    try:
                        ctx.commit()
                    except DBAPIError as exc:
                        # PG-012 纪律：COMMIT 结果未知 → 绝不盲重试，先读 durable truth。
                        # 先把本事务回滚掉（commit 失败后事务已中止，rollback 是无害的
                        # no-op；若 commit 实际成功，rollback 亦然）—— 这样 reconcile
                        # 即使复用同一条连接也只会读到服务器真值，绝不读到未提交状态。
                        ambiguous = True
                        try:
                            ctx.session.rollback()
                        except Exception:  # noqa: BLE001,S110
                            pass
                        truth2 = _reconcile_after_unknown_commit(
                            session_factory, request)
                        if truth2 is None:
                            raise ActivationOutcomeUnknown(
                                "激活 commit 结果未知且 durable truth 不可读取"
                                "（fail-closed；禁止盲重试）",
                                detail={"world_id": request.world_id,
                                        "error": type(exc).__name__}) from exc
                        if not truth2.committed:
                            raise ActivationOutcomeUnknown(
                                "激活 commit 结果未知且 durable truth 显示未提交"
                                "（fail-closed；禁止盲重试，需人工核对）",
                                detail={"world_id": request.world_id,
                                        "error": type(exc).__name__}) from exc
                        return _outcome_from_truth(
                            session_factory, request, seed, truth2,
                            written=False, ambiguous=True)
            except SaIntegrityError as exc:
                # 完整性约束拒绝（genesis event_uid 撞车 / 唯一约束 / FK）：
                # **不是** commit 歧义 —— 事务未提交（SQLAlchemy 抛错即回滚）。
                # 仍先核对 durable truth，再以契约错误拒绝（绝不裸抛 SQLAlchemy 异常）。
                truth3 = _reconcile_after_unknown_commit(session_factory,
                                                         request)
                if truth3 is not None and truth3.committed:
                    return _already_committed_outcome(
                        session_factory, request, seed,
                        truth3.world_seed_version, ambiguous=False)
                raise ActivationRefused(
                    "激活事务被数据库完整性约束拒绝（未提交，零写入）",
                    detail={"world_id": request.world_id,
                            "error": type(exc).__name__}) from exc
        finally:
            try:
                session.close()
            except Exception:  # noqa: BLE001,S110
                pass

        # ---- 5) 提交后核对 durable truth（唯一权威）--------------------------
        final = read_activation_truth(session_factory, world_id=request.world_id)
        if not final.committed:
            raise ActivationOutcomeUnknown(
                "激活事务返回但 durable truth 未显示 ACTIVE（fail-closed）",
                detail={"world_id": request.world_id})
        return _outcome_from_truth(session_factory, request, seed, final,
                                   written=True, ambiguous=ambiguous)
    finally:
        try:
            lease.release()
        except Exception:  # noqa: BLE001,S110
            # 释放失败不吞世界锁：租约自然过期后由 STALE_WRITER_RECOVERY 接管
            pass
        try:
            lease_session.close()
        except Exception:  # noqa: BLE001,S110
            pass


# ------------------------------------------------------------------ helpers
def _assert_world_identity(session_factory: sessionmaker[Session],
                           request: ActivationRequest) -> None:
    """只读身份核对：请求的 world_id 必须与正式库中的世界一致（F8）。

    用**不带 world_id 过滤**的读取（正式库只有一个世界）：若按请求的 world_id
    去过滤，不匹配时会读到"0 行"从而漏判，接着 `runtime_lock` 的 FK 会在 acquire
    内抛 IntegrityError 并被误报成"另一 Runtime 正在推进"—— 这里先给出准确理由。
    """
    truth = read_activation_truth(session_factory)
    if truth.world_id is not None and truth.world_id != request.world_id:
        raise ActivationRefused(
            "请求 world_id 与正式库中的世界不一致（禁止激活第二个世界）",
            detail={"requested": request.world_id, "db": truth.world_id})


def _assert_pristine_pre_activation_state(session: Session,
                                          request: ActivationRequest) -> None:
    """事务内前置不变量（A2/A10 + 版本一致性）：任何异常状态都 fail-closed。"""
    row = RuntimeRepository(session).get()
    if row is not None and row.simulation_version != request.simulation_version:
        raise ActivationRefused(
            "simulation_version 与世界中记录的版本不一致（禁止用错误算法版本出生）",
            detail={"request": request.simulation_version,
                    "db": row.simulation_version})
    genesis = count_genesis_events(session, request.world_id)
    if genesis:
        # 未激活却已存在 genesis 事件 = durable 状态不一致（例如人工恢复/被干预）。
        # 绝不"绕过它再写一个"：那会产生第二个 genesis（A6/A10）。
        raise ActivationRefused(
            "未激活世界中已存在 genesis 事件：durable 状态不一致，"
            "禁止二次 genesis（需人工核对后再决定）",
            detail={"world_id": request.world_id, "genesis_events": genesis})
    events = count_events(session, request.world_id)
    if events:
        raise ActivationRefused(
            "未激活世界已存在正式事件（A2/A10：激活前官方历史必须为空）",
            detail={"world_id": request.world_id, "events": events})


def _committed_seed_version(session: Session, world_id: str) -> str | None:
    """事务内判定（只读）：已激活则返回其 seed 版本，否则 None。"""
    row = RuntimeRepository(session).get()
    if row is None or row.world_id != world_id:
        return None
    if row.runtime_status == "ACTIVE" and row.world_seed_version is not None:
        return row.world_seed_version
    return None


def _reconcile_after_unknown_commit(session_factory: sessionmaker[Session],
                                    request: ActivationRequest):  # noqa: ANN001
    """commit 结果未知 → 读 durable truth（读不到即返回 None → fail-closed）。"""
    try:
        return read_activation_truth(session_factory, world_id=request.world_id)
    except Exception:  # noqa: BLE001
        return None


def _outcome_from_truth(session_factory: sessionmaker[Session],
                        request: ActivationRequest, seed: SeedPackage,
                        truth, *, written: bool, ambiguous: bool,
                        ) -> ActivationOutcome:  # noqa: ANN001
    genesis_uid = None
    genesis_count = 0
    with session_factory() as s:
        genesis_uid = _read_genesis_uid(s, request.world_id)
        genesis_count = count_genesis_events(s, request.world_id)
    return ActivationOutcome(
        outcome=OUTCOME_COMMITTED,
        written=written,
        world_id=request.world_id,
        world_seed_version=(truth.world_seed_version or seed.seed_version),
        seed_fingerprint=seed.fingerprint,
        initial_blessed_tick=request.initial_blessed_tick,
        activation_real_us=request.activation_real_us,
        activation_operation_id=_activation_operation_id(request, seed),
        genesis_event_uid=genesis_uid,
        seed_consumption_count=genesis_count,
        pre_activation_backlog_ticks=0,
        commit_outcome_was_ambiguous=ambiguous,
        seed=seed.public_view(),
    )


def _already_committed_outcome(session_factory: sessionmaker[Session],
                               request: ActivationRequest, seed: SeedPackage,
                               committed_seed_version: str | None,
                               *, ambiguous: bool = False) -> ActivationOutcome:
    """已激活 → 幂等返回。**绝不复用旧 seed 的指纹伪装成本次 seed**。

    M6B §13/§15：durable activation anchor 是**只读**事实 ——
    幂等重试必须复用同一个 anchor，**绝不**用当前时间或本次请求的 anchor 覆盖它。
    请求 anchor 与 durable anchor 不一致 → 拒绝（loser 不得改写 anchor）。
    """
    recorded = None
    with session_factory() as s:
        ev = s.execute(
            select(WorldEvent).where(
                WorldEvent.world_id == request.world_id,
                WorldEvent.event_type == GENESIS_EVENT_TYPE)
            .order_by(WorldEvent.id).limit(1)).scalar_one_or_none()
        if ev is not None:
            recorded = (ev.effect or {}).get("world_seed_fingerprint")
        genesis_count = count_genesis_events(s, request.world_id)
    if recorded is None:
        # 世界是 ACTIVE 却没有 genesis 指纹 = 不是本契约产生的状态。绝不借用
        # "请求中的 Seed 指纹" 冒充已消费的 Seed（那会谎报身份）。
        raise ActivationRefused(
            "世界已激活，但 genesis 事件未记录 seed 指纹：无法核对 Seed 身份"
            "（fail-closed；需人工核对 durable truth）",
            detail={"world_id": request.world_id,
                    "committed_seed_version": committed_seed_version})
    if recorded != seed.fingerprint:
        raise ActivationRefused(
            "该世界已用**另一个** Seed 激活；禁止二次消费 / 禁止换 Seed 重激活",
            detail={"world_id": request.world_id,
                    "committed_seed_version": committed_seed_version,
                    "requested_seed_fingerprint": seed.fingerprint})
    durable_anchor = read_world_epoch_anchor(session_factory,
                                             world_id=request.world_id)
    if durable_anchor is not None and \
            durable_anchor != request.activation_anchor_us:
        raise ActivationRefused(
            "世界已激活：本次请求的 activation anchor 与 durable anchor 不一致"
            "（禁止改写/覆盖既有 anchor —— 重试必须复用同一个 anchor）",
            detail={"world_id": request.world_id,
                    "durable_anchor_us": durable_anchor,
                    "requested_anchor_us": request.activation_anchor_us})
    row = None
    with session_factory() as s:
        row = RuntimeRepository(s).get()
    return ActivationOutcome(
        outcome=OUTCOME_ALREADY_COMMITTED,
        written=False,
        world_id=request.world_id,
        world_seed_version=committed_seed_version or (row.world_seed_version
                                                     if row else None) or "",
        seed_fingerprint=recorded,
        initial_blessed_tick=(row.current_blessed_tick if row else
                              request.initial_blessed_tick),
        activation_real_us=(row.last_committed_real_us if row else
                            request.activation_real_us),
        activation_operation_id=_activation_operation_id(request, seed),
        genesis_event_uid=None,
        seed_consumption_count=genesis_count,
        pre_activation_backlog_ticks=0,
        commit_outcome_was_ambiguous=ambiguous,
        seed=seed.public_view(),
    )

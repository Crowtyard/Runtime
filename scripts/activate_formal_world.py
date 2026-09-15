# -*- coding: utf-8 -*-
"""正式世界激活 —— **owner-only 维护 CLI**（M6A 控制面）。

这是正式世界激活的**唯一**人工入口，刻意做成 host 上的维护命令，而不是：

- Web API —— 插件对外 API 必须保持只读（``test_plugin_shell`` PL16/PL17 强制）；
- AstrBot 命令 / ProviderRequest / 自然语言意图路由 —— LLM 永不具备激活权限
  （owner §20：聊天说"启动福地吧"不得触发任何 authority mutation）；
- scheduler / 普通 runtime boot —— 部署了具备激活能力的版本 ≠ 自动激活
  （owner §18：RuntimeHost 继续报告 ``world_activation = LOCKED``）。

用法::

    # 只读查看激活状态（默认动作，零写入）
    python scripts/activate_formal_world.py --status --db <正式库路径>

    # 实际执行一次性激活（必须显式确认；缺参数即拒绝，绝不猜默认值）
    python scripts/activate_formal_world.py \
        --confirm-formal-world-activation \
        --db <正式库路径> \
        --initial-blessed-tick <整数，必须整年：N × 1_000_000> \
        --epoch0-us <世界年锚，现实 epoch µs>

退出码：0 = 已提交/幂等已提交；2 = 被拒绝（零写入）；3 = commit 结果未知
（fail-closed，需人工核对，**禁止盲重试**）。

注意：``--initial-blessed-tick`` 与 ``--epoch0-us`` **没有默认值** ——
canon（LOCAL_CANON / World Seed 包）只声明"由 Activation Transaction 创建"，
未定义数值；本 CLI 不发明世界起始值（见 M6_DESIGN_GAP_INITIAL_TICK /
M6_DESIGN_GAP_ACTIVATION_ANCHOR）。
"""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT.parent))
_PKG = PROJECT_ROOT.name

_settings = importlib.import_module(f"{_PKG}.config.settings")
_db = importlib.import_module(f"{_PKG}.database.db")
_lifecycle = importlib.import_module(f"{_PKG}.services.db_lifecycle")
_truth = importlib.import_module(f"{_PKG}.services.durable_truth")
_activation = importlib.import_module(f"{_PKG}.services.activation")
_errors = importlib.import_module(f"{_PKG}.domain.errors")
_constants = importlib.import_module(f"{_PKG}.domain.constants")
_blessed = importlib.import_module(f"{_PKG}.domain.blessed_time")

CONFIRM_FLAG = "--confirm-formal-world-activation"

#: OWNER_CANON_DECISION_1：初始 blessed tick 恒为 0（Runtime 内部时间原点）。
INITIAL_BLESSED_TICK = _constants.WorldActivationPolicy.INITIAL_BLESSED_TICK


def _resolve_url(db: str | None) -> str:
    if db:
        return "sqlite:///" + str(Path(db).resolve()).replace("\\", "/")
    return _settings.Settings().database_url


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="activate_formal_world",
        description="正式世界一次性激活（owner-only 控制面；默认只读）")
    p.add_argument("--status", action="store_true",
                   help="只读：打印 durable 激活状态后退出（零写入）")
    p.add_argument(CONFIRM_FLAG, dest="confirm", action="store_true",
                   help="显式确认执行正式世界激活（缺少即拒绝执行）")
    p.add_argument("--db", default=None, help="正式库文件路径（默认取 Settings）")
    p.add_argument("--world-id", default="BL-0001", help="canonical world_id")
    p.add_argument("--seed-dir", default=None, help="World Seed 包目录")
    p.add_argument("--expected-seed-version", default=None,
                   help="期望的 Seed 版本（省略时按 canonical "
                        "WorldSeedVersion.CURRENT = \"1.0\" 校验）")
    p.add_argument("--activation-anchor-utc", default=None,
                   help="OWNER_CANON_DECISION_2：正式激活操作的 canonical UTC "
                        "instant（ISO-8601，如 2026-12-01T00:00:00Z）。"
                        "**必须显式给出**：一次 activation operation 只确定一次 "
                        "anchor；ACK lost / crash 后重试必须复用同一个值")
    p.add_argument("--activation-anchor-us", type=int, default=None,
                   help="同上，但直接给现实 epoch µs（与 --activation-anchor-utc 互斥）")
    p.add_argument("--initial-blessed-tick", type=int, default=INITIAL_BLESSED_TICK,
                   help=f"初始 canonical blessed tick（canon 恒为 "
                        f"{INITIAL_BLESSED_TICK}；非该值一律拒绝）")
    p.add_argument("--operator", default=None, help="操作者标识（审计用）")
    p.add_argument("--prepare-metadata", action="store_true",
                   help="允许先用既有 seed 路径创建 NOT_ACTIVATED metadata"
                        "（非权威；缺失时否则直接拒绝）")
    p.add_argument("--bible-dir", default=None, help="World Bible 目录（metadata 用）")
    return p


def _parse_anchor_us(args) -> int | None:
    """把 --activation-anchor-utc / --activation-anchor-us 解析为 epoch µs。"""
    if args.activation_anchor_utc and args.activation_anchor_us is not None:
        raise ValueError("--activation-anchor-utc 与 --activation-anchor-us 不能同时使用")
    if args.activation_anchor_us is not None:
        return int(args.activation_anchor_us)
    if not args.activation_anchor_utc:
        return None
    from datetime import datetime, timezone
    raw = str(args.activation_anchor_utc).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return _blessed.datetime_to_epoch_us(dt.astimezone(timezone.utc))


def _print_truth(url: str) -> dict:
    engine = _db.create_db_engine(url)
    factory = _db.make_session_factory(engine)
    t = _truth.read_activation_truth(factory)
    anchor = _truth.read_world_epoch_anchor(factory)
    print("[activation-status]")
    print(f"  activation_state        = {t.state}")
    print(f"  world_id                = {t.world_id}")
    print(f"  runtime_status          = {t.runtime_status}")
    print(f"  world_seed_version      = {t.world_seed_version}")
    print(f"  current_blessed_tick    = {t.current_blessed_tick}")
    print(f"  last_committed_real_us  = {t.last_committed_real_us}")
    print(f"  world_epoch0_us         = {anchor}")
    print(f"  anchor_policy           = "
          f"{_constants.WorldActivationPolicy.ANCHOR_POLICY}")
    print(f"  genesis_events          = {t.genesis_events}")
    print(f"  seed_consumption_count  = {t.seed_consumption_count}")
    engine.dispose()
    return {
        "state": t.state, "world_id": t.world_id,
        "runtime_status": t.runtime_status,
        "seed_version": t.world_seed_version,
        "tick": t.current_blessed_tick, "cursor_us": t.last_committed_real_us,
        "epoch0_us": anchor,
        "genesis_events": t.genesis_events,
    }


def main() -> int:
    args = _parser().parse_args()
    url = _resolve_url(args.db)

    if args.status and args.confirm:
        print("REFUSED: --status 与 " + CONFIRM_FLAG + " 不能同时使用"
              "（--status 是只读动作，永不激活）")
        return 2

    if args.status or not args.confirm:
        _print_truth(url)
        if not args.status:
            print("")
            print("REFUSED: 需要显式确认标志 " + CONFIRM_FLAG)
            print("（本命令默认只读；正式世界激活必须由主人显式发起）")
            return 2
        return 0

    # ---- OWNER_CANON_DECISION_2：anchor 必须显式给出（一次 operation 只定一次） --
    try:
        anchor_us = _parse_anchor_us(args)
    except ValueError as exc:
        print(f"REFUSED: {exc}")
        return 2
    if anchor_us is None:
        print("REFUSED: 必须显式给出 --activation-anchor-utc（或 "
              "--activation-anchor-us）—— 激活 anchor 是一次 activation operation "
              "的 durable 事实，禁止用 now() 隐式生成/重算")
        return 2

    settings = _settings.Settings()
    seed_dir = Path(args.seed_dir) if args.seed_dir else \
        _activation.default_seed_dir(PROJECT_ROOT)
    bible_dir = Path(args.bible_dir) if args.bible_dir else settings.bible_dir

    # 迁移到 head（幂等；不 squash / 不 reset）
    _lifecycle.migrate_database(url, project_root=PROJECT_ROOT)
    engine = _db.create_db_engine(url)
    factory = _db.make_session_factory(engine)

    before = _truth.read_activation_truth(factory, world_id=args.world_id)
    if before.committed:
        print("[preflight] 世界已激活 → 本次为幂等核对（不写入）")
        _print_truth(url)
        engine.dispose()
        return 0

    if before.world_id is None:
        if not args.prepare_metadata:
            print("REFUSED: 未找到 world_runtime 行（metadata 未播种）。"
                  "先运行既有 seed 路径，或显式加 --prepare-metadata。")
            engine.dispose()
            return 2
        try:
            _lifecycle.seed_database(engine, factory, bible_dir=bible_dir,
                                     world_id=args.world_id)
            print("[prepare] metadata 已播种（NOT_ACTIVATED；非权威、绝不激活）")
        except Exception as exc:  # noqa: BLE001
            print(f"REFUSED: metadata 播种失败: {type(exc).__name__}")
            engine.dispose()
            return 2

    # ---- 一次性激活（唯一正式入口） ------------------------------------------
    try:
        request = _activation.ActivationRequest(
            world_id=args.world_id,
            seed_dir=seed_dir,
            activation_anchor_us=int(anchor_us),
            initial_blessed_tick=int(args.initial_blessed_tick),
            **({"expected_seed_version": args.expected_seed_version}
               if args.expected_seed_version else {}),
            operator=args.operator or "OWNER_CONTROL_PLANE",
        )
        print("[preflight] planned activation:")
        print(f"  world_id              = {request.world_id}")
        print(f"  initial_blessed_tick  = {request.initial_blessed_tick}")
        print(f"  activation_anchor_us  = {request.activation_anchor_us}")
        print(f"  activation_real_us    = {request.activation_real_us}")
        print(f"  word_epoch0_us        = {request.epoch0_us}")
        print(f"  seed_dir              = {seed_dir}")
        seed = _activation.load_seed_package(
            seed_dir,
            **({"expected_seed_version": args.expected_seed_version}
               if args.expected_seed_version else {}))
        for k, v in seed.public_view().items():
            print(f"  {k:22s}= {v}")
        outcome = _activation.activate_formal_world(factory, request=request)
    except _errors.ActivationRefused as exc:
        print(f"REFUSED: {exc.message}")
        if exc.detail:
            print(f"  detail = {exc.detail}")
        engine.dispose()
        return 2
    except _errors.WorldSeedIntegrityError as exc:
        print(f"REFUSED: World Seed 校验失败: {exc.message}")
        if exc.detail:
            print(f"  detail = {exc.detail}")
        engine.dispose()
        return 2
    except _errors.FencingViolation as exc:
        print(f"REFUSED: 写权限 fencing 校验失败（零写入）: {exc.message}")
        engine.dispose()
        return 2
    except _errors.ActivationOutcomeUnknown as exc:
        print(f"OUTCOME_UNKNOWN: {exc.message}")
        print("  → fail-closed：请人工核对 durable truth 后再决定；禁止盲重试")
        engine.dispose()
        return 3

    print("[outcome]")
    for k, v in outcome.as_dict().items():
        print(f"  {k:28s}= {v}")
    print("")
    _print_truth(url)
    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

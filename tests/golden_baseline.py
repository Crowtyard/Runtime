# -*- coding: utf-8 -*-
"""Golden Baseline 基础设施（TEST_INFRA_HARDENING；不改变任何 simulation
semantics——纯测试/夹具层设施）。

政策（详见 tests/GOLDEN_BASELINES.md）：

1. 普通 pytest 只读 committed golden baseline（tests/baselines/**）。
   candidate artifact 只允许写入 tmp_path（write_candidate），
   绝不允许覆盖 committed golden。
2. 非确定性 telemetry 绝不参与确定性相等比较：默认剥离键集
   DEFAULT_TELEMETRY_KEYS = {performance, wall_seconds, wall_seconds_queries,
   query_latency_ms, db_size_mb, db_growth}。
3. 更新 golden baseline 必须显式 opt-in：环境变量
   BLR_UPDATE_GOLDEN_BASELINES=1（普通 pytest 恒为关闭）；
   推荐入口 scripts/update_baselines.py。更新需人工 git diff review +
   独立 commit。
4. artifact 中的 world_state_hash_schema_version 必须记录“实际计算该
   final hash 所使用的 effective schema version”（M2b=3 / M2c=4 /
   M2d=5 / M3a=6），绝不引用代码库当前最高活值，避免未来 v7/v8
   漂移旧 milestone fixture 的标签（GB4–GB8）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

GOLDEN_DIR = Path(__file__).resolve().parent / "baselines"
UPDATE_ENV = "BLR_UPDATE_GOLDEN_BASELINES"

# 非确定性 telemetry 键（深剥离；不进确定性相等比较）
DEFAULT_TELEMETRY_KEYS = frozenset({
    "performance",          # M2a/M2b/M2c/M2d 120y 基线 {wall_seconds}
    "wall_seconds",         # M3a 300y summary / M2 long seed records
    "wall_seconds_queries",  # M3b 300y summary
    "query_latency_ms",     # M3b 300y summary
    "db_size_mb",           # M2 long seed records / endurance
    "db_growth",            # M3b growth_projection / M2 long summary
})

# M3a 冻结 effective hash schema version（test-side pin：与 M3a 冻结语义
# 绑定，不随未来代码库最高 hash schema 版本漂移）。
M3A_EFFECTIVE_HASH_SCHEMA_VERSION = 6


def update_mode_enabled() -> bool:
    """显式更新模式开关；普通 pytest 恒为 False。"""
    return os.environ.get(UPDATE_ENV) == "1"


def golden_path(rel: str) -> Path:
    return GOLDEN_DIR / rel


def load_artifact(path: Path):
    """只读加载 committed golden artifact。"""
    return json.loads(path.read_text(encoding="utf-8"))


def dump_artifact(artifact, path: Path) -> None:
    """把 artifact 写回 golden 路径。

    普通 pytest 调用即 RuntimeError（GB9：更新必须显式 opt-in）；
    只有 BLR_UPDATE_GOLDEN_BASELINES=1（scripts/update_baselines.py）可写。
    """
    if not update_mode_enabled():
        raise RuntimeError(
            "拒绝覆盖 golden baseline（普通 pytest 只读）："
            f"{path}\n更新必须显式 opt-in：{UPDATE_ENV}=1，"
            "或使用 scripts/update_baselines.py。")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=1),
                    encoding="utf-8")


def write_candidate(tmp_path: Path, name: str, artifact) -> Path:
    """candidate artifact 只写 tmp（调试用；绝不触碰仓库 golden）。"""
    d = Path(tmp_path) / "golden_candidates"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(json.dumps(artifact, ensure_ascii=False, indent=1),
                 encoding="utf-8")
    return p


def strip_telemetry(obj, keys=DEFAULT_TELEMETRY_KEYS):
    """深拷贝并移除 telemetry 键（dict 任意层级 / list 内 dict）。"""
    if isinstance(obj, dict):
        return {k: strip_telemetry(v, keys) for k, v in obj.items()
                if k not in keys}
    if isinstance(obj, list):
        return [strip_telemetry(v, keys) for v in obj]
    return obj


def _first_diff(g, c, path="$") -> str:
    """返回第一条差异的人类可读描述（深度优先，键排序后比较）。"""
    if isinstance(g, dict) and isinstance(c, dict):
        for k in sorted(set(g) | set(c)):
            if k not in g:
                return f"  first diff at {path}.{k}: golden 缺失（candidate 有）"
            if k not in c:
                return f"  first diff at {path}.{k}: candidate 缺失（golden 有）"
            sub = _first_diff(g[k], c[k], f"{path}.{k}")
            if sub:
                return sub
        return ""
    if isinstance(g, list) and isinstance(c, list):
        if len(g) != len(c):
            return (f"  first diff at {path}: list length "
                    f"{len(g)} != {len(c)}")
        for i, (a, b) in enumerate(zip(g, c)):
            sub = _first_diff(a, b, f"{path}[{i}]")
            if sub:
                return sub
        return ""
    if g != c:
        return f"  first diff at {path}: {g!r} != {c!r}"
    return ""


def assert_deterministic_equal(golden, candidate, *, label: str,
                               telemetry_keys=DEFAULT_TELEMETRY_KEYS,
                               golden_path=None,
                               candidate_path=None) -> None:
    """golden 与 candidate 的确定性字段必须完全一致，否则立即 FAIL。

    绝不自动覆盖 golden：任何确定性差异都是回归（GB10 语义）——
    要么是 simulation semantics 回归，要么需要走显式更新流程。
    """
    g = strip_telemetry(golden, telemetry_keys)
    c = strip_telemetry(candidate, telemetry_keys)
    if g != c:
        raise AssertionError(
            f"golden baseline deterministic mismatch: {label}\n"
            f"  golden    = {golden_path or '(committed)'}\n"
            f"  candidate = {candidate_path or '(this run)'}\n"
            + _first_diff(g, c))


def effective_world_state_hash_schema_version(*, engine_versions,
                                              tribulation_registered):
    """从 pipeline semantics 推导 effective hash schema version。

    镜像 coordinator 的冻结选择规则，但只引用冻结常量 / M3a test-side
    pin，绝不引用活值 WORLD_STATE_HASH_SCHEMA_VERSION（GB8）。
    """
    from XiaoguangBlessedLandRuntime.services.simulation.state_hash import (
        WORLD_STATE_HASH_SCHEMA_VERSION_V2,
        WORLD_STATE_HASH_SCHEMA_VERSION_V3,
        WORLD_STATE_HASH_SCHEMA_VERSION_V4,
        WORLD_STATE_HASH_SCHEMA_VERSION_V5)
    if tribulation_registered:
        return M3A_EFFECTIVE_HASH_SCHEMA_VERSION
    if "SOCIAL" in engine_versions:
        return WORLD_STATE_HASH_SCHEMA_VERSION_V5
    if "ECOLOGY" in engine_versions:
        return WORLD_STATE_HASH_SCHEMA_VERSION_V4
    if {"RESOURCE", "ECONOMY"} & set(engine_versions):
        return WORLD_STATE_HASH_SCHEMA_VERSION_V3
    return WORLD_STATE_HASH_SCHEMA_VERSION_V2


def baseline_snapshot() -> dict:
    """tests/baselines/ 下全部文件 → relpath:sha256（GB1 会话守卫输入）。"""
    snap: dict[str, str] = {}
    if not GOLDEN_DIR.exists():
        return snap
    import hashlib
    for p in sorted(GOLDEN_DIR.rglob("*")):
        if p.is_file():
            snap[str(p.relative_to(GOLDEN_DIR))] = hashlib.sha256(
                p.read_bytes()).hexdigest()
    return snap


def golden_bytes_guard(*paths: Path):
    """模块级 autouse fixture：每个测试前后 golden 文件字节必须不变（GB2）。

    显式更新模式（BLR_UPDATE_GOLDEN_BASELINES=1）豁免：更新流程本就允许写。
    """
    import pytest

    @pytest.fixture(autouse=True)
    def _guard():
        if update_mode_enabled():
            yield
            return
        before = {p: p.read_bytes() for p in paths}
        yield
        for p, blob in before.items():
            assert p.read_bytes() == blob, (
                f"golden baseline bytes modified during test run: {p}")
    return _guard

# -*- coding: utf-8 -*-
"""Golden Baseline Guard（GB1–GB10；TEST_INFRA_HARDENING）。

保证：
- 普通 pytest 全程不修改 tests/baselines/ 下任何 committed golden baseline
  （GB1 会话硬守卫 + GB2 模块级字节守卫）；
- 非确定性 telemetry（wall_seconds / query_latency_ms / db_size_mb 等）
  不参与确定性 fixture 相等比较（GB3）；
- world_state_hash_schema_version 记录 effective 值（M2b=3 / M2c=4 /
  M2d=5 / M3a=6），未来代码库最高 hash schema 版本变化不漂移旧 fixture
  标签（GB4–GB8）；
- baseline 刷新必须显式 opt-in（GB9）；
- candidate 与 golden 的确定性差异必须 FAIL，绝不自动覆盖（GB10）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests import golden_baseline as gb
from tests.golden_baseline import (
    M3A_EFFECTIVE_HASH_SCHEMA_VERSION, assert_deterministic_equal,
    dump_artifact, effective_world_state_hash_schema_version, load_artifact,
    strip_telemetry, update_mode_enabled)

REPO = gb.GOLDEN_DIR.parent.parent

M2_ENGINE_VERSIONS = {
    "DEMOGRAPHY": "m2a-1",
    "RESOURCE": "m2b-resource-1",
    "ECONOMY": "m2b-economy-1",
}

# 各 milestone 拥有的 golden 文件的模块（GB2 布线静态检查）
GOLDEN_OWNER_MODULES = (
    "test_m2a_population.py",
    "test_m2b_resource_economy.py",
    "test_m2c_ecology.py",
    "test_m2d_social.py",
    "test_m3a_tribulation.py",
    "test_m3b_history.py",
    "test_m3b_metric_audit.py",
    "test_m2_review_long.py",
)


# ---------------------------------------------------------------- GB1-GB2
def test_gb1_normal_pytest_never_modifies_baselines(request):
    """普通 pytest 会话必须保持 tests/baselines/ 字节不变。

    硬守卫：conftest.pytest_sessionstart 记录全目录 sha256 快照，
    pytest_sessionfinish 比对并把 exitstatus 置 1。本测试做即时复核。
    """
    assert not update_mode_enabled(), \
        "普通 pytest 不得启用 golden 更新模式（GB9）"
    snap = getattr(request.config, "_blr_baseline_snapshot", None)
    assert snap is not None, "会话快照缺失（conftest GB1 守卫未生效）"
    assert gb.baseline_snapshot() == snap, \
        "tests/baselines/ 在本测试执行前已被修改"


def test_gb2_artifact_tests_keep_golden_bytes_unchanged(request):
    """baseline artifact 测试运行前后 golden 字节不变：
    模块级 golden_bytes_guard（每测试前后校验）+ 会话级快照双重保证。"""
    for mod in GOLDEN_OWNER_MODULES:
        src = (REPO / "tests" / mod).read_text(encoding="utf-8")
        assert "_golden_bytes_guard = golden_bytes_guard(" in src, \
            f"{mod} 缺少 golden_bytes_guard 布线"
    snap = getattr(request.config, "_blr_baseline_snapshot", None)
    if snap is None:
        pytest.skip("update mode")
    assert gb.baseline_snapshot() == snap


# ---------------------------------------------------------------- GB3
def test_gb3_telemetry_excluded_from_deterministic_equality():
    golden = {
        "final_world_state_hash": "a" * 64,
        "performance": {"wall_seconds": 7.358},
    }
    candidate = {
        "final_world_state_hash": "a" * 64,
        "performance": {"wall_seconds": 99.9},
    }
    # telemetry 不同 → 相等（不参与确定性比较）
    assert_deterministic_equal(golden, candidate, label="gb3")
    # 确定性字段不同 → 必须 FAIL
    candidate["final_world_state_hash"] = "b" * 64
    with pytest.raises(AssertionError):
        assert_deterministic_equal(golden, candidate, label="gb3")
    # strip_telemetry 深剥离语义
    nested = {"a": {"wall_seconds": 1.0, "k": 1},
              "b": [{"db_size_mb": 2.0, "k": 2}]}
    assert strip_telemetry(nested) == {"a": {"k": 1}, "b": [{"k": 2}]}


# ---------------------------------------------------------------- GB4-GB7
def test_gb4_m2b_effective_hash_schema_3():
    assert effective_world_state_hash_schema_version(
        engine_versions=M2_ENGINE_VERSIONS, tribulation_registered=False) == 3
    m = load_artifact(gb.golden_path(
        "m2b_resource_economy_miniworld_120y_v1.json"))
    assert m["world_state_hash_schema_version"] == 3


def test_gb5_m2c_effective_hash_schema_4():
    ev = dict(M2_ENGINE_VERSIONS, ECOLOGY="m2c-ecology-1")
    assert effective_world_state_hash_schema_version(
        engine_versions=ev, tribulation_registered=False) == 4
    m = load_artifact(gb.golden_path("m2c_ecology_miniworld_120y_v1.json"))
    assert m["world_state_hash_schema_version"] == 4


def test_gb6_m2d_effective_hash_schema_5():
    ev = dict(M2_ENGINE_VERSIONS, ECOLOGY="m2c-ecology-1",
              SOCIAL="m2d-social-1")
    assert effective_world_state_hash_schema_version(
        engine_versions=ev, tribulation_registered=False) == 5
    m = load_artifact(gb.golden_path("m2d_social_miniworld_120y_v2.json"))
    assert m["world_state_hash_schema_version"] == 5


def test_gb7_m3a_effective_hash_schema_6():
    assert effective_world_state_hash_schema_version(
        engine_versions=dict(M2_ENGINE_VERSIONS, ECOLOGY="m2c-ecology-1",
                             SOCIAL="m2d-social-1"),
        tribulation_registered=True) == M3A_EFFECTIVE_HASH_SCHEMA_VERSION
    m = load_artifact(gb.golden_path(
        "m3a_tribulation_synthetic_300y_v1/summary.json"))
    assert m["world_state_hash_schema_version"] == 6
    # M2a 冻结标签同样不漂移（字段名 state_hash_schema_version=2）
    m2a = load_artifact(gb.golden_path("m2a_population_miniworld_120y_v1.json"))
    assert m2a["state_hash_schema_version"] == 2


# ---------------------------------------------------------------- GB8
def test_gb8_future_global_bump_does_not_drift_old_fixtures(monkeypatch):
    """代码库最高 hash schema 版本变化，不得改变旧 milestone fixture 标签。"""
    import XiaoguangBlessedLandRuntime.services.simulation.state_hash as sh
    monkeypatch.setattr(sh, "WORLD_STATE_HASH_SCHEMA_VERSION", 999)
    assert effective_world_state_hash_schema_version(
        engine_versions={"DEMOGRAPHY": "m2a-1"},
        tribulation_registered=False) == 2
    assert effective_world_state_hash_schema_version(
        engine_versions=M2_ENGINE_VERSIONS, tribulation_registered=False) == 3
    assert effective_world_state_hash_schema_version(
        engine_versions=dict(M2_ENGINE_VERSIONS, ECOLOGY="m2c-ecology-1"),
        tribulation_registered=False) == 4
    assert effective_world_state_hash_schema_version(
        engine_versions=dict(M2_ENGINE_VERSIONS, ECOLOGY="m2c-ecology-1",
                             SOCIAL="m2d-social-1"),
        tribulation_registered=False) == 5
    assert effective_world_state_hash_schema_version(
        engine_versions=dict(M2_ENGINE_VERSIONS, ECOLOGY="m2c-ecology-1",
                             SOCIAL="m2d-social-1"),
        tribulation_registered=True) == M3A_EFFECTIVE_HASH_SCHEMA_VERSION
    # committed golden 标签字段字面值完全不受活值影响
    for rel, field, expected in (
            ("m2a_population_miniworld_120y_v1.json",
             "state_hash_schema_version", 2),
            ("m2b_resource_economy_miniworld_120y_v1.json",
             "world_state_hash_schema_version", 3),
            ("m2c_ecology_miniworld_120y_v1.json",
             "world_state_hash_schema_version", 4),
            ("m2d_social_miniworld_120y_v2.json",
             "world_state_hash_schema_version", 5),
            ("m3a_tribulation_synthetic_300y_v1/summary.json",
             "world_state_hash_schema_version", 6)):
        m = load_artifact(gb.golden_path(rel))
        assert m[field] == expected, rel


# ---------------------------------------------------------------- GB9
def test_gb9_update_requires_explicit_opt_in(tmp_path):
    assert not update_mode_enabled()
    target = tmp_path / "x.json"
    with pytest.raises(RuntimeError):
        dump_artifact({}, target)
    assert not target.exists(), "非更新模式下 dump_artifact 不得写任何文件"
    script = REPO / "scripts" / "update_baselines.py"
    assert script.exists(), "缺少显式更新入口 scripts/update_baselines.py"
    src = script.read_text(encoding="utf-8")
    assert gb.UPDATE_ENV in src
    assert '"1"' in src


# ---------------------------------------------------------------- GB10
def test_gb10_candidate_mismatch_fails_without_overwrite(tmp_path):
    """candidate != golden 必须 FAIL，绝不能自动覆盖 golden 后 PASS。"""
    golden = {"final_world_state_hash": "x" * 64, "metric": 1,
              "performance": {"wall_seconds": 1.0}}
    candidate = {"final_world_state_hash": "y" * 64, "metric": 1,
                 "performance": {"wall_seconds": 2.0}}
    with pytest.raises(AssertionError) as ei:
        assert_deterministic_equal(golden, candidate, label="gb10")
    assert "first diff" in str(ei.value)
    # 比较过程纯只读：两侧数据不变
    assert golden["final_world_state_hash"] == "x" * 64
    assert candidate["final_world_state_hash"] == "y" * 64
    # committed golden 文件必须仍然只读（模块守卫 + 会话守卫兜底）
    committed = gb.golden_path("m2b_resource_economy_miniworld_120y_v1.json")
    assert json.loads(committed.read_text(encoding="utf-8"))[
        "world_state_hash_schema_version"] == 3

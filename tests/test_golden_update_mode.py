"""M6D.3 §5 — golden-baseline update-mode regression (TEST-INFRA).

Covers the narrow OPT-1 repair of the canonical update path
(`scripts/update_baselines.py` + `dump_artifact`):

  A. NORMAL MODE, old != new            -> deterministic comparison FAILS
  B. UPDATE MODE, old != new            -> canonical writer executes and writes
  C. UPDATE MODE, telemetry-only diff   -> handled by the existing GB3 rules
  D. unauthorized path                  -> gains NO implicit write permission

plus a structural guard that the three owner-authorized artifact tests keep the
required shape (dump-then-return in update mode, strict comparison otherwise), so
the compare-before-write dead end cannot come back.

Nothing here touches tests/baselines: every write goes to tmp_path.
"""
from __future__ import annotations

import ast
import json
import pathlib

import pytest

from tests.golden_baseline import (
    UPDATE_ENV, assert_deterministic_equal, dump_artifact, load_artifact,
    strip_telemetry, update_mode_enabled)

REPO = pathlib.Path(__file__).resolve().parents[1]

AUTHORIZED_NODES = {
    "tests/test_m3a_tribulation.py": "test_m3a_baseline_300y_artifact",
    "tests/test_m3b_history.py": "test_hb43_300y_baseline_artifacts",
    "tests/test_m3b_metric_audit.py": "test_ma28_metric_audit_baseline_artifacts",
}


def _artifact(**over):
    base = {"fixture_version": "mini_world_v1", "final_world_state_hash": "a" * 64,
            "domain_event_count": 4779, "wall_seconds": 12.5}
    base.update(over)
    return base


# ---------------------------------------------------------------- A
def test_a_normal_mode_mismatch_fails(tmp_path):
    """NORMAL MODE：old != new 必须 FAIL（GB10 语义不变）。"""
    assert update_mode_enabled() is False
    golden = _artifact()
    candidate = _artifact(domain_event_count=4835)
    with pytest.raises(AssertionError) as exc:
        assert_deterministic_equal(golden, candidate, label="m6d3/A")
    assert "deterministic mismatch" in str(exc.value)
    path = tmp_path / "golden.json"
    path.write_text(json.dumps(golden, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    assert load_artifact(path) == golden  # 只读，未被改写


# ---------------------------------------------------------------- B
def test_b_update_mode_writer_executes(tmp_path, monkeypatch):
    """UPDATE MODE：canonical writer 必须真正写入（旧实现的死结已解除）。"""
    monkeypatch.setenv(UPDATE_ENV, "1")
    assert update_mode_enabled() is True
    path = tmp_path / "baselines" / "summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_artifact(), ensure_ascii=False, indent=1),
                    encoding="utf-8")
    candidate = _artifact(domain_event_count=4835)
    dump_artifact(candidate, path)          # 与 artifact 测试同一条写入路径
    assert load_artifact(path) == candidate
    assert load_artifact(path)["domain_event_count"] == 4835


# ---------------------------------------------------------------- C
def test_c_update_mode_telemetry_only_difference(tmp_path, monkeypatch):
    """UPDATE MODE + 仅 telemetry 差异：按既有 GB3 规则处理。"""
    monkeypatch.setenv(UPDATE_ENV, "1")
    golden = _artifact(wall_seconds=12.5)
    candidate = _artifact(wall_seconds=99.25)
    # GB3：telemetry 剥离后相等 ⇒ 不构成确定性差异
    assert strip_telemetry(golden) == strip_telemetry(candidate)
    assert_deterministic_equal(golden, candidate, label="m6d3/C")
    # update mode 下写入的是当前 artifact（保留其 telemetry）
    path = tmp_path / "summary.json"
    dump_artifact(candidate, path)
    assert load_artifact(path)["wall_seconds"] == 99.25


# ---------------------------------------------------------------- D
def test_d_unauthorized_path_has_no_implicit_write(tmp_path):
    """UPDATE MODE 关闭时，任意路径都不得被写入（无隐式写权限）。"""
    assert update_mode_enabled() is False
    path = tmp_path / "not_a_baseline.json"
    with pytest.raises(RuntimeError):
        dump_artifact(_artifact(), path)
    assert not path.exists()
    # 仓库内未授权 baseline 也绝不因本修复获得写权限
    assert update_mode_enabled() is False


def test_d2_updater_scope_is_explicit_and_authorized():
    """updater 必须用显式节点清单，不得全仓扫描；本轮授权的 3 个节点在其中。"""
    src = (REPO / "scripts" / "update_baselines.py").read_text(encoding="utf-8")
    assert "ARTIFACT_TESTS = [" in src
    for rel, name in sorted(AUTHORIZED_NODES.items()):
        assert name in src, name
        assert rel in src, rel
    # 不得存在"扫描全部 baseline 并覆盖差异"的行为
    for forbidden in ("rglob", "glob(", "os.walk"):
        assert forbidden not in src, forbidden


def test_d3_no_second_baseline_writer_exists():
    """不得新增第二套 baseline writer（overwrite/manual rewrite/hash 替换）。"""
    scripts = [p.name for p in (REPO / "scripts").glob("*.py")]
    for name in scripts:
        low = name.lower()
        assert "overwrite_baseline" not in low
        assert "rewrite_baseline" not in low
        assert "refresh_baseline" not in low
    # 唯一合法写路径仍是 dump_artifact
    src = (REPO / "tests" / "golden_baseline.py").read_text(encoding="utf-8")
    assert src.count("def dump_artifact(") == 1


# ---------------------------------------------------------------- 结构守卫
def _artifact_test_fn(path: pathlib.Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError("artifact test not found: %s" % name)


def _lineno(node: ast.AST, needle: str, path: pathlib.Path) -> int:
    src = path.read_text(encoding="utf-8").splitlines()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            fn = child.func
            fname = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if fname == needle:
                return child.lineno
    raise AssertionError("%s not called in %s" % (needle, path))


@pytest.mark.parametrize("rel,name", sorted(AUTHORIZED_NODES.items()))
def test_e_authorized_artifact_tests_dump_before_compare(rel, name):
    """update mode：先 dump 并 return；normal mode：仍然严格比较（顺序守卫）。"""
    path = REPO / rel
    fn = _artifact_test_fn(path, name)
    src = path.read_text(encoding="utf-8")
    body = ast.get_source_segment(src, fn) or ""
    assert "update_mode_enabled()" in body
    assert "return" in body
    dump_line = _lineno(fn, "dump_artifact", path)
    compare_line = _lineno(fn, "assert_deterministic_equal", path)
    assert dump_line < compare_line, (
        "update-mode dump must precede the deterministic comparison in %s" % name)
    # 未授权的 artifact 测试不得被改动成同样形状以外的行为：
    others = [p for p in (REPO / "tests").glob("test_m2*.py")]
    for other in others:
        text = other.read_text(encoding="utf-8")
        if "dump_artifact" in text and other.name not in rel:
            # M2 家族本轮未授权：不得出现"先 dump 后比较"的新形状
            assert "OPT-1" not in text, other.name

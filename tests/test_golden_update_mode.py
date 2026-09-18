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
import re

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


# ------------------------------------------------- M6D.3 OPT-B anti-drift
METRIC_AUDIT_TESTS = (
    "test_ma5_entity_history_index_rows_correct",
    "test_ma6_distinct_entities_with_history_correct",
    "test_ma7_domain_entities_separated_from_index_references",
    "test_ma9_causal_link_density_metrics_correct",
    "test_ma12_growth_projection_reproducible",
    "test_ma20_causal_history_hash_stable",
)

#: 已被 baseline artifact 覆盖、因此不得再以内联字面量出现的期望值（owner §6）
FORBIDDEN_INLINE = {
    64_858, 66_005, 134, 145, 2_184, 2_224, 37_759, 37_826,
    4_479, 4_535, 37_818, 37_885, 65_742, 66_889,
    21_914, 22_296, 21_619, 22_002, 12_606, 12_628, 219_140, 222_963,
    1_095_700, 1_114_817,
}
FORBIDDEN_INLINE_STRINGS = {
    "c1293e59d96753e2b3488746f86f176bceb84d2ef6935c9760944c8727046a44",
    "d3b8a499257fe40cd7d3f4253438f9a99aca6e7592340a8f6cbdc4fd2ae130ba",
}


def test_f_metric_audit_expectations_come_from_baseline_artifact():
    """INLINE_GOLDEN_DUPLICATION = 0（AST 口径，非文本 grep）。

    6 个 metric-audit 测试的 expected 值必须来自 committed baseline artifact
    （`_expected(...)` helper），而不是第二份内联冻结字面量。
    """
    path = REPO / "tests" / "test_m3b_metric_audit.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}

    duplicated = []
    for name in METRIC_AUDIT_TESTS:
        fn = funcs.get(name)
        assert fn is not None, name
        uses_helper = False
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                fname = getattr(node.func, "id", None) or \
                    getattr(node.func, "attr", None)
                if fname == "_expected":
                    uses_helper = True
            if isinstance(node, ast.Constant):
                if isinstance(node.value, int) and not isinstance(node.value, bool):
                    if node.value in FORBIDDEN_INLINE:
                        duplicated.append((name, node.lineno, node.value))
                if isinstance(node.value, str) \
                        and node.value in FORBIDDEN_INLINE_STRINGS:
                    duplicated.append((name, node.lineno, node.value[:16]))
        assert uses_helper, "%s must read expected values via _expected(...)" % name
    assert duplicated == [], "inline golden duplication: %r" % duplicated[:8]


def test_g_expected_helper_reads_committed_baseline_only():
    """`_expected` 只读 committed baseline，绝不使用当前 run 的 artifact。"""
    path = REPO / "tests" / "test_m3b_metric_audit.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "_expected")
    calls = {getattr(n.func, "id", None) or getattr(n.func, "attr", None)
             for n in ast.walk(fn) if isinstance(n, ast.Call)}
    assert "load_artifact" in calls
    assert "BASELINE_DIR" in {n.id for n in ast.walk(fn)
                              if isinstance(n, ast.Name)}
    # 不得出现"regenerate/写回/计算当前 artifact"的路径
    for forbidden in ("dump_artifact", "entity_cardinality_audit",
                      "relation_density_audit", "growth_projection",
                      "causal_history_hash"):
        assert forbidden not in calls, forbidden


# ------------------------------------------- M6D.3 B2 anti-drift (query service)
HEXLIKE = re.compile(r"^[0-9a-f]{8,64}$")


def test_h_query_service_m3_expectation_has_no_inline_hash():
    """QUERY_SERVICE_INLINE_HASH_DUPLICATION = 0（AST 口径）。

    `test_m5q46_m3_baselines_unchanged` 的期望值必须来自 committed baseline
    artifact，且体内不得出现任何 hash 字面量/前缀（旧 `0fc6ece0…`、`c1293e59…`
    或替代它们的新字面量都算违规）。
    """
    path = REPO / "tests" / "test_query_service.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name == "test_m5q46_m3_baselines_unchanged")
    literals = [n.value for n in ast.walk(fn)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and HEXLIKE.match(n.value)]
    assert literals == [], "inline hash literal(s): %r" % literals
    calls = {getattr(n.func, "id", None) or getattr(n.func, "attr", None)
             for n in ast.walk(fn) if isinstance(n, ast.Call)}
    # EXPECTED：baseline loader；ACTUAL：production/query path（两者独立）
    assert "load_artifact" in calls
    assert "_fingerprint" in calls or "get_world_snapshot" in calls
    # 不得 regenerate/写回 baseline
    assert "dump_artifact" not in calls

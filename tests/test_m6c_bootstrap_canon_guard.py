# -*- coding: utf-8 -*-
"""M6C-GUARD —— Bootstrap Canon 硬门禁（owner §16/§17/§18）。

本阶段（M6C.0）**不实现 materializer**；本文件先把"正式 bootstrap 路径不得依赖
测试夹具"的边界钉死，并把 M6C.0 审计发现的 canon 缺口**钉成回归门禁**：
任何"把测试 profile 改名当正式 profile"或"静默给正式世界接上测试 registry"的改动
都会在这里失败，必须由主人显式授权后连同本门禁一起改。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from tests.conftest import PROJECT_ROOT

REPO = PROJECT_ROOT

#: 正式 bootstrap / activation 生产路径（M6C §10：materializer 只能属于这里）
BOOTSTRAP_PATH = (
    "services/activation/__init__.py",
    "services/activation/service.py",
    "services/activation/seed_package.py",
    "services/durable_truth.py",
    "services/scheduler/core.py",
    "scripts/activate_formal_world.py",
)

#: 测试夹具 token —— **依赖级**（registry 名/夹具模块名）：出现在正式生产路径即 FAIL
FIXTURE_TOKENS = (
    "TEST_PROFILES", "TEST_SPECIES", "TEST-SPECIES", "TEST_SOCIAL_PROFILE",
    "TEST_ECOLOGY_PROFILE", "TEST_RESOURCE_PROFILE", "TEST_ECONOMY_PROFILE",
    "TEST_SCHEDULE", "mini_world", "synthetic_world", "seed_mini_world",
)

#: 仅对正式 bootstrap 路径额外的 token（"TEST_FIXTURE_ONLY" 在只读查询层被用作
#: **provenance 标签**默认值 —— 那是标注而非依赖，故只在 bootstrap 路径禁止）
BOOTSTRAP_ONLY_TOKENS = ("TEST_FIXTURE_ONLY",)

#: 正式 bootstrap 路径（M6C §10：materializer 只能属于这里；不含 runtime scheduler）
ACTIVATION_PATH = (
    "services/activation/__init__.py",
    "services/activation/service.py",
    "services/activation/seed_package.py",
    "services/durable_truth.py",
    "scripts/activate_formal_world.py",
)

#: 引擎/管线模块（bootstrap 路径不得 import 或构造）
ENGINE_MODULES = (
    "population", "resource", "economy", "ecology", "social", "tribulation",
    "mini_world", "contracts", "coordinator",
)


def _code_strings_and_imports(path: Path) -> tuple[list[str], list[str], str]:
    """返回 (模块级字符串常量, import 名, 源码)。docstring 不计入字符串常量。"""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and \
                    isinstance(body[0].value, ast.Constant) and \
                    isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    strings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in docstrings:
            strings.append(node.value)
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = ("." * (node.level or 0)) + (node.module or "")
            imports.append(base)
            imports.extend(f"{base}.{a.name}" for a in node.names)
    return strings, imports, src


# ------------------------------------------------------------------ G-01
def test_m6cg01_no_test_fixture_reference_in_bootstrap_path():
    """§16：TEST_FIXTURE_REFERENCES_IN_BOOTSTRAP = 0（代码级，docstring 不计）。"""
    offenders: list[str] = []
    for rel in BOOTSTRAP_PATH:
        path = REPO / rel
        strings, imports, _ = _code_strings_and_imports(path)
        blob = "\n".join(strings + imports)
        tokens = FIXTURE_TOKENS + (BOOTSTRAP_ONLY_TOKENS
                                   if rel in ACTIVATION_PATH else ())
        for token in tokens:
            if token in blob:
                offenders.append(f"{rel}: {token}")
    assert offenders == [], (
        "正式 bootstrap/activation 路径出现测试夹具引用"
        "（TEST_FIXTURE_REFERENCES_IN_BOOTSTRAP 必须为 0）:\n"
        + "\n".join(offenders))


def test_m6cg01b_activation_path_imports_no_engine_module():
    """§10：activation/bootstrap 路径不得 import 或构造冻结引擎。

    （`services/simulation/harness` 仅提供常量 YEAR_US，生产 scheduler 既有依赖；
      `services/simulation/event_stream` 仅提供事件 uid 原语 —— 二者不在引擎之列。）
    """
    offenders: list[str] = []
    for rel in ACTIVATION_PATH:
        _, imports, src = _code_strings_and_imports(REPO / rel)
        joined = "|".join(imports)
        for mod in ENGINE_MODULES:
            if re.search(rf"[.|]{mod}\b", joined):
                offenders.append(f"{rel}: imports {mod}")
        if re.search(r"\b\w*Engine\(", src):
            offenders.append(f"{rel}: constructs an Engine")
    assert offenders == [], offenders


def test_m6cg01c_runtime_scheduler_constructs_no_engine():
    """runtime scheduler 只编排冻结 catch_up/adapter，绝不构造引擎。"""
    src = (REPO / "services/scheduler/core.py").read_text("utf-8")
    assert not re.search(r"\b\w*Engine\(", src)
    assert "coordinator_provider" in src      # 引擎由接线方提供（fail-closed 若缺失）


# ------------------------------------------------------------------ G-02
def test_m6cg02_known_canon_gaps_are_pinned():
    """§17/§18：把 M6C.0 审计发现的缺口钉住 —— 不得静默"改名当正式"。

    若这些断言失败，说明有人改了正式/测试 registry 的边界；那必须由主人显式授权，
    并连同本门禁一起修改（而不是让测试悄悄通过）。
    """
    src = {
        "population": (REPO / "services/simulation/population.py").read_text("utf-8"),
        "resource": (REPO / "services/simulation/resource.py").read_text("utf-8"),
        "economy": (REPO / "services/simulation/economy.py").read_text("utf-8"),
        "ecology": (REPO / "services/simulation/ecology.py").read_text("utf-8"),
        "social": (REPO / "services/simulation/social.py").read_text("utf-8"),
        "tribulation": (REPO / "services/simulation/tribulation.py").read_text("utf-8"),
    }
    # 每个域的 profile registry 都自声明为 TEST_FIXTURE_ONLY
    assert "TEST_FIXTURE_ONLY" in src["population"]
    assert "TEST_FIXTURE_ONLY" in src["resource"]
    assert "TEST_FIXTURE_ONLY" in src["economy"]
    assert "TEST_FIXTURE_ONLY" in src["ecology"]
    assert "TEST_FIXTURE_ONLY" in src["social"]
    assert "TEST_FIXTURE_ONLY" in src["tribulation"]
    # 正式 profile "未配置" 的语义在 message 中保留
    assert "正式种族保持 UNCONFIGURED" in src["population"]
    assert "正式资源保持 UNCONFIGURED" in src["resource"]
    assert "正式种族保持 UNCONFIGURED" in src["economy"]
    assert "正式生态保持 UNCONFIGURED" in src["ecology"]
    # 灾劫：production 构造默认回落到 TEST_PROFILES（未修复前的前置条件）
    assert "self._profiles = profiles or TEST_PROFILES" in src["tribulation"]
    # 社会：`or TEST_SOCIAL_PROFILE`（传 None/空都会回落测试档）
    assert "self._profile = profile or TEST_SOCIAL_PROFILE" in src["social"]


def test_m6cg02b_test_registries_are_not_referenced_outside_engines():
    """§16：除引擎模块自身外，production 路径不得引用 TEST_* registry。"""
    offenders: list[str] = []
    for path in (REPO / "services").rglob("*.py"):
        rel = path.relative_to(REPO).as_posix()
        if rel.startswith("services/simulation/"):
            continue
        strings, imports, _ = _code_strings_and_imports(path)
        blob = "\n".join(strings + imports)
        for token in FIXTURE_TOKENS:
            if token in blob:
                offenders.append(f"{rel}: {token}")
    for path in (REPO / "plugin_shell").rglob("*.py"):
        strings, imports, _ = _code_strings_and_imports(path)
        blob = "\n".join(strings + imports)
        for token in FIXTURE_TOKENS:
            if token in blob:
                offenders.append(f"{path.relative_to(REPO).as_posix()}: {token}")
    assert offenders == [], offenders


# ------------------------------------------------------------------ G-03
def test_m6cg03_no_materializer_exists_before_owner_authorization():
    """§29：M6C.0 只做审计 —— 仓库内**不得**出现 bootstrap materializer。

    以 AST 定义名判定（不误伤注释/文档/字符串散文）。
    """
    forbidden = re.compile(
        r"(materiali[sz]er|materialize_(world|bootstrap)|bootstrap_world|"
        r"seed_bootstrap|create_initial_state|bootstrap_roots)")
    hits: list[str] = []
    for path in (REPO / "services").rglob("*.py"):
        rel = path.relative_to(REPO).as_posix()
        if rel.startswith("services/simulation/"):
            continue          # 合成世界/测试夹具位于引擎目录内，不在此列
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                if forbidden.search(node.name.lower()):
                    hits.append(f"{rel}:{node.lineno} def/class {node.name}")
    assert hits == [], (
        "M6C.0 仅授权审计：未获主人授权前不得实现 materializer\n"
        + "\n".join(hits))

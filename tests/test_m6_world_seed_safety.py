# -*- coding: utf-8 -*-
"""M6A-GUARD —— ACTIVATION_BOUNDARY_GUARD（owner §17 / §18 / §19 / §20）。

把原 M4 ``test_scheduler_world_seed_safety.py``（"Scheduler 层零消费 Seed"）
**重构并推广**为全局访问边界门禁：

```
WORLD_SEED_ACTIVATION_ACCESS_ALLOWLIST = M6_ACTIVATION_SERVICE_ONLY
```

1. 只有 ``services/activation/`` 允许引用 World Seed 激活原语；
   scheduler / query / simulation / history / database / domain / config /
   plugin_shell boot / main（普通 runtime boot）—— 命中即 FAIL；
2. ``runtime_status = 'ACTIVE'`` 的唯一写入点是 ``services/repositories.py``
   （受保护的 repository 原语），其它 production 模块不得直接写；
3. RuntimeHost boot 仍为 ``world_activation = LOCKED``：部署了具备激活能力的版本
   ≠ 自动激活世界；
4. LLM / 聊天 / Web API 永远没有激活权限（无端点、无自然语言路由、无 schema 开关）；
5. 正式 World Seed 包字节冻结（MANIFEST 逐文件复算）且自声明状态仍为
   ``PREPARED_NOT_ACTIVATED``（本阶段未消费）。

原 M4 门禁 ``tests/test_scheduler_world_seed_safety.py`` 保留不删（scheduler 专项
窄门禁），本文件是其广义版本，两者同时生效。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from sqlalchemy import select, text

from tests.conftest import PROJECT_ROOT

from XiaoguangBlessedLandRuntime.database.models_core import WorldRuntime
from XiaoguangBlessedLandRuntime.services.activation import (
    WORLD_SEED_ACTIVATION_ACCESS_ALLOWLIST,
    WORLD_SEED_ACTIVATION_ALLOWED_PREFIXES)

REPO = PROJECT_ROOT
SEED_DIR = REPO.parent / "XIAOGUANG_CROW_KB" / "world_seed"

#: 生产（可部署）模块集合 —— 与 scripts/build_deployment_package 的 PACKAGE_DIRS 同构
PRODUCTION_DIRS = ("config", "database", "domain", "services", "plugin_shell")
PRODUCTION_TOP = ("main.py", "__init__.py")

#: §17：seed 激活访问 token（除 allowlist 外，任何 production 模块命中即 FAIL）。
#: 注意口径：``world_seed_version``（激活判定读取）是合法的，本表**不**把它当越界；
#: Bible 自己的 ``MANIFEST.sha256.txt`` / ``XIAOGUANG_CROW_KB`` 目录引用（World Bible
#: 校验机制，M0 既有）也**不**在此表内 —— 这里只识别"World Seed 包消费"本身。
SEED_ACCESS_TOKENS = (
    "world_seed/", "world_seed\"", "world_seed'",
    "SEED_PACKAGE_DIRNAME", "default_seed_dir",
    "04_population_baseline", "05_species_baseline", "06_settlement_baseline",
    "WORLD_SEED_INDEX", "UNRESOLVED_SEED",
    "consume_seed", "activate_seed", "seed_activation",
    "load_seed_package", "SeedPackage", "activate_formal_world",
    "ActivationRequest", "REQUIRED_DECLARED_STATUS",
)

#: 只允许出现在 services/activation/ 的模块内（否则视为越界访问 Seed）
ALLOWLIST_PREFIXES = WORLD_SEED_ACTIVATION_ALLOWED_PREFIXES


def _production_files() -> list[Path]:
    files: list[Path] = []
    for name in PRODUCTION_TOP:
        p = REPO / name
        if p.exists():
            files.append(p)
    for d in PRODUCTION_DIRS:
        base = REPO / d
        if base.is_dir():
            files.extend(p for p in base.rglob("*.py")
                         if "__pycache__" not in p.parts)
    return sorted(files)


def _rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# ------------------------------------------------------------------ G-01
def test_m6g01_seed_access_allowlist_is_declared():
    assert WORLD_SEED_ACTIVATION_ACCESS_ALLOWLIST == "M6_ACTIVATION_SERVICE_ONLY"
    assert ALLOWLIST_PREFIXES == ("services/activation/",)


def test_m6g01b_seed_activation_primitives_only_in_allowlist():
    """§17：任何非 allowlist 的 production 模块命中 seed 激活 token → FAIL。"""
    offenders: list[str] = []
    for path in _production_files():
        rel = _rel(path)
        if any(rel.startswith(p) for p in ALLOWLIST_PREFIXES):
            continue
        src = _read(path)
        for token in SEED_ACCESS_TOKENS:
            if token in src:
                offenders.append(f"{rel}: {token}")
    assert offenders == [], (
        "World Seed 激活原语逸出 M6_ACTIVATION_SERVICE_ONLY allowlist:\n"
        + "\n".join(offenders))


def test_m6g01c_scheduler_history_query_simulation_explicitly_clean():
    """把关键子系统显式单列（防止 allowlist 前缀未来被误放宽）。"""
    subsystems = ("services/scheduler", "services/history", "services/query",
                  "services/simulation", "plugin_shell", "database", "domain",
                  "config")
    offenders: list[str] = []
    for rel_dir in subsystems:
        base = REPO / rel_dir
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            src = _read(path)
            for token in SEED_ACCESS_TOKENS:
                if token in src:
                    offenders.append(f"{_rel(path)}: {token}")
    assert offenders == [], offenders


# ------------------------------------------------------------------ G-02
def test_m6g02_active_status_write_point_is_repository_only():
    """§6：禁止外部模块直接 ``row.runtime_status = 'ACTIVE'``。"""
    pattern = re.compile(r"\.runtime_status\s*=\s*(?!=)(?![\"']NOT_ACTIVATED)")
    offenders: list[str] = []
    for path in _production_files():
        rel = _rel(path)
        if rel == "services/repositories.py":
            continue
        for lineno, line in enumerate(_read(path).splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{rel}:{lineno} {line.strip()}")
    assert offenders == [], offenders


def test_m6g02b_activation_row_writer_is_runtime_repository():
    src = _read(REPO / "services" / "repositories.py")
    assert "def activate(" in src
    assert "def assert_activatable(" in src
    # 唯一受保护原语必须 fail-closed：拒绝二次激活 / 已生效 seed / 已初始化时钟
    assert "world_seed_version 已生效" in src
    assert "禁止二次激活" in src


# ------------------------------------------------------------------ G-03
def test_m6g03_runtime_host_boot_stays_locked():
    """§18：boot 永远不激活；宿主继续声明 world_activation = LOCKED。"""
    src = _read(REPO / "plugin_shell" / "runtime_host.py")
    assert src.count('"world_activation": "LOCKED"') == 2
    for token in ("activate_formal_world", "ActivationRequest",
                  "load_seed_package"):
        assert token not in src
    main_src = _read(REPO / "main.py")
    for token in ("activate_formal_world", "ActivationRequest",
                  "load_seed_package", "world_activation\": \"ENABLED"):
        assert token not in main_src


def test_m6g03b_no_activation_route_or_config_switch():
    """§19/§20：无 activate 端点、无配置开关（激活只能由 host 上的 owner CLI 发起）。"""
    main_src = _read(REPO / "main.py")
    registrations = re.findall(r'reg\(f?"(/[^"]+)"', main_src)
    assert registrations, "未找到任何 API 注册"
    for route in registrations:
        assert "activate" not in route.lower(), route
        assert "seed" not in route.lower(), route
    schema = json.loads((REPO / "_conf_schema.json").read_text(encoding="utf-8"))
    for key in schema:
        assert not any(t in key.lower() for t in
                       ("activate", "seed", "advance")), key


def test_m6g03c_llm_hook_has_no_activation_authority():
    """§20：LLM 路径永远无激活权限（静态：hook 与其后续查询路径不引用激活原语）。"""
    main_src = _read(REPO / "main.py")
    hook_at = main_src.find("@on_llm_request")
    assert hook_at != -1
    hook_src = main_src[hook_at:]
    for token in ("activate_formal_world", "ActivationRequest",
                  "load_seed_package", "SeedPackage"):
        assert token not in hook_src, token
    # 查询层（注入到 LLM 的上下文来源）同样只读、零激活
    for path in (REPO / "services" / "query").rglob("*.py"):
        src = _read(path)
        for token in ("activate_formal_world", "load_seed_package",
                      "ActivationRequest", "SeedPackage"):
            assert token not in src, _rel(path)


def test_m6g03d_owner_control_plane_is_explicit_and_host_side():
    """§19：唯一人工入口 = host 上的维护 CLI，且必须显式确认标志。"""
    cli = REPO / "scripts" / "activate_formal_world.py"
    assert cli.exists(), "缺少 owner-only 激活控制面"
    src = _read(cli)
    assert "--confirm-formal-world-activation" in src
    assert "activate_formal_world(" in src
    # 缺确认标志 → 只读并拒绝（不执行激活）
    assert "需要显式确认标志" in src
    # 不得出现在插件会被 LLM/聊天触达的注册面上
    main_src = _read(REPO / "main.py")
    assert "activate_formal_world" not in main_src


# ------------------------------------------------------------------ G-04
def test_m6g04_formal_seed_package_byte_frozen_and_unconsumed():
    """正式 Seed 包：MANIFEST 逐字节冻结 + 自声明仍为 PREPARED_NOT_ACTIVATED。"""
    manifest = SEED_DIR / "MANIFEST.sha256.txt"
    entries: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        h, name = line.split("  ", 1)
        entries[name] = h
    assert entries
    for name, expected in entries.items():
        p = SEED_DIR / name
        assert p.exists(), name
        assert hashlib.sha256(p.read_bytes()).hexdigest() == expected, name

    version = json.loads((SEED_DIR / "VERSION.json").read_text(encoding="utf-8"))
    assert version["status"] == "PREPARED_NOT_ACTIVATED"
    assert version["version"] == "1.0"


def test_m6g04b_genesis_event_type_has_single_canonical_literal():
    """genesis 事件类型只能有一个 canonical 字面量（禁止第二条 identity 路径）。"""
    hits: list[str] = []
    for path in _production_files():
        src = _read(path)
        if '"WORLD_SEED_ACTIVATED"' in src or "'WORLD_SEED_ACTIVATED'" in src:
            hits.append(_rel(path))
    assert hits == ["services/durable_truth.py"], hits


# ------------------------------------------------------------------ G-05
def _run_cli(tmp_path, args: list[str]) -> tuple[int, str]:
    """以**文件重定向**方式运行 owner 控制面 CLI，返回 (退出码, 合并输出)。

    为什么不用 ``capture_output=True``：本机在 detached 父进程（分块回归运行器）
    下**无法捕获孙进程的管道输出**（管道为空，子进程本身照常运行）—— 这是环境
    限制，不是 CLI 缺陷。文件重定向不经过管道，因此两种上下文下都可靠。
    显式注入 ``PYTHONIOENCODING=utf-8`` 使子进程输出编码确定。
    """
    import subprocess
    import sys

    log = tmp_path / "cli_output.txt"
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    with open(log, "w", encoding="utf-8") as fh:
        proc = subprocess.run(
            [sys.executable, "scripts/activate_formal_world.py", *args],
            cwd=str(REPO), stdout=fh, stderr=subprocess.STDOUT,
            env=env, timeout=300)
    return proc.returncode, log.read_text(encoding="utf-8", errors="replace")


def test_m6g05_control_plane_refuses_without_explicit_confirmation(tmp_path):
    """§19 行为证明：缺 ``--confirm-formal-world-activation`` 时零写入并拒绝。"""
    from tests.m6_activation_support import M6_EPOCH0_US, new_synthetic_world

    env = new_synthetic_world(tmp_path)
    db_path = Path(env["url"].replace("sqlite:///", ""))

    code, out = _run_cli(tmp_path, [
        "--db", str(db_path),
        "--initial-blessed-tick", "0",
        "--epoch0-us", str(M6_EPOCH0_US)])
    assert code == 2, out
    assert "REFUSED" in out
    assert "需要显式确认标志" in out

    # 零写入：世界仍未激活，且没有任何事件
    with env["factory"]() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        assert row.runtime_status == "NOT_ACTIVATED"
        assert row.world_seed_version is None
        assert row.current_blessed_tick is None
        assert row.last_committed_real_us is None
        assert s.execute(text(
            "SELECT COUNT(*) FROM world_events")).scalar() == 0
    env["engine"].dispose()


def test_m6g05b_cli_status_and_confirm_are_mutually_exclusive(tmp_path):
    """``--status`` 与确认标志互斥：不得静默返回 0（"看起来成功但其实没做事"）。"""
    code, out = _run_cli(tmp_path, [
        "--status", "--confirm-formal-world-activation",
        "--db", str(tmp_path / "nonexistent.db"),
        "--initial-blessed-tick", "0", "--epoch0-us", "1"])
    assert code == 2, out
    assert "不能同时使用" in out


def test_m6g05c_cli_maps_seed_integrity_error_to_refusal(tmp_path):
    """WorldSeedIntegrityError 必须映射为退出码 2（不是裸 traceback / 退出码 1）。"""
    from tests.m6_activation_support import (
        M6_EPOCH0_US, SYNTHETIC_DATA_FILES, build_synthetic_seed,
        new_synthetic_world)

    env = new_synthetic_world(tmp_path)
    db_path = Path(env["url"].replace("sqlite:///", ""))
    bad_seed = build_synthetic_seed(tmp_path, tamper=SYNTHETIC_DATA_FILES[0],
                                    name="tampered_seed")
    code, out = _run_cli(tmp_path, [
        "--confirm-formal-world-activation",
        "--db", str(db_path), "--seed-dir", str(bad_seed),
        "--initial-blessed-tick", "0", "--epoch0-us", str(M6_EPOCH0_US)])
    assert code == 2, out
    assert "REFUSED" in out
    assert "Traceback" not in out
    with env["factory"]() as s:
        row = s.execute(select(WorldRuntime)).scalar_one()
        assert row.runtime_status == "NOT_ACTIVATED"
        assert row.last_committed_real_us is None
    env["engine"].dispose()

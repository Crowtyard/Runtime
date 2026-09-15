# -*- coding: utf-8 -*-
"""PROCESS_KILL_SCOPE_REGRESSION：禁止按进程名批量终止（M5.1 误杀事故规则）。

事故（2026-09-12 22:30）：诊断脚本以“杀掉所有 python 进程”作为清理语句，
把主人正在运行的 live AstrBot 实例一并杀掉。

规则（docs/process_kill_scope.md）：

* 禁止 ``Stop-Process -Name python`` / ``Get-Process python | Stop-Process`` /
  ``taskkill /IM python.exe`` / ``pkill python`` / ``killall python``；
* 只允许操作 **显式 PID + 已核实的父子进程树 + 已知测试实例**；
* 启动测试实例前检测到非测试 AstrBot 进程 → ``ABORT TEST``，禁止清理。

本文件做两件事：

1. 静态回归：仓库内（含 scripts/ 与 tests/）任何**代码行**若出现进程终止命令，
   必须使用显式 PID（``-Id`` / ``/PID``）且不得按名终止；
   注释与 docstring 中的“反面示例”不算违规（用 AST 剔除 docstring）。
2. 行为回归：``scripts/process_scope.py`` 的作用域实现——守卫会 ABORT、
   ``kill_tree`` 只杀指定进程树（不误伤同族其它进程）。
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SELF = Path(__file__).resolve()

SCAN_SUFFIXES = {".py", ".ps1", ".sh", ".bat", ".cmd"}
SKIP_DIR_PARTS = {".git", ".pytest_cache", "__pycache__", "backups",
                  "baselines", "reports", "versions", "runtime_design"}

#: 进程终止命令字面量
TERMINATORS = ("Stop-Process", "taskkill", "pkill", "killall",
               "TerminateProcess", "os.kill")
#: 按名终止的标志（一律禁止）
NAME_TARGET_FLAGS = ("-Name", "/IM")
#: 显式 PID 标志（必须出现其一）
EXPLICIT_PID_FLAGS = ("-id", "/pid", "pid")


def _iter_scan_files() -> list[Path]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SCAN_SUFFIXES:
            continue
        if set(path.relative_to(REPO_ROOT).parts) & SKIP_DIR_PARTS:
            continue
        files.append(path)
    return sorted(files)


def _code_lines(path: Path) -> list[tuple[int, str]]:
    """返回 (行号, 行内容)，剔除注释行与 Python docstring（反面示例所在处）。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    skip: set[int] = set()
    if path.suffix.lower() == ".py":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            tree = None
        if tree is not None:
            for node in ast.walk(tree):
                body = getattr(node, "body", None)
                if not isinstance(body, list) or not body:
                    continue
                first = body[0]
                if isinstance(first, ast.Expr) and \
                        isinstance(first.value, ast.Constant) and \
                        isinstance(first.value.value, str):
                    start = first.lineno
                    end = getattr(first, "end_lineno", start) or start
                    skip.update(range(start, end + 1))
    return [(i, line) for i, line in enumerate(lines, 1)
            if i not in skip and not line.strip().startswith("#")]


def test_no_unscoped_process_kill_in_repo():
    violations: list[str] = []
    for path in _iter_scan_files():
        if path == SELF:
            continue  # 本文件即规则表，含反面示例字面量
        for lineno, line in _code_lines(path):
            if not any(tok in line for tok in TERMINATORS):
                continue
            lowered = line.lower()
            if any(flag.lower() in lowered for flag in NAME_TARGET_FLAGS):
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{lineno} 按名终止进程: "
                    f"{line.strip()}")
                continue
            if not any(flag in lowered for flag in EXPLICIT_PID_FLAGS):
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{lineno} 未使用显式 PID: "
                    f"{line.strip()}")
    assert violations == [], (
        "PROCESS_KILL_SCOPE 违规（禁止按名批量终止，必须显式 PID + 已核实进程树）:\n"
        + "\n".join(violations))


# ------------------------------------------------------- 行为回归（作用域实现）
def _spawn_sleeper() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _spawn_fake_astrbot_core(tmp_path: Path) -> subprocess.Popen:
    """模拟一个 AstrBot 实例进程（``<...>\\core\\main.py`` 形态的命令行）。"""
    core = tmp_path / "astrbot_core"
    core.mkdir(parents=True, exist_ok=True)
    (core / "main.py").write_text("import time\ntime.sleep(120)\n",
                                  encoding="utf-8")
    return subprocess.Popen([sys.executable, str(core / "main.py")],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _alive(pid: int) -> bool:
    import scripts.process_scope as ps
    return any(p["pid"] == pid for p in ps.python_processes())


@pytest.fixture()
def scoped(tmp_path):
    sys.path.insert(0, str(REPO_ROOT))
    import scripts.process_scope as ps
    yield ps


def test_detection_ignores_own_ancestry(scoped):
    """守卫不得把测试自身的解释器判成外来实例（否则永远无法启动测试实例）。

    注：本测试不假设机器上无 live AstrBot 实例（验收期它通常正在运行），
    只验证“自身进程链 + 命令行形态判定”这一逻辑本身。
    """
    assert os.getpid() in scoped.own_ancestry()
    own_cmdline = f'"{sys.executable}" -m pytest -q'
    assert scoped.looks_like_astrbot_instance(own_cmdline) is False
    assert scoped.looks_like_astrbot_instance(
        r"C:\x\instances\abc\core\main.py") is True


def test_guard_aborts_on_foreign_astrbot_instance(scoped, tmp_path):
    """存在非测试 AstrBot 实例进程时，守卫必须 ABORT（而不是去清理它）。

    容忍环境中已有 live 实例：把它登记为“环境既有”，
    只要求守卫对**本测试伪造的**那个实例进程报警。
    """
    fake = _spawn_fake_astrbot_core(tmp_path)
    try:
        preexisting = {p["pid"] for p in scoped.astrbot_processes()
                       if p["pid"] != fake.pid}
        with pytest.raises(scoped.ForeignProcessError) as exc:
            scoped.assert_no_foreign_python(allowed=preexisting)
        assert str(fake.pid) in str(exc.value)
        # 明确登记为“本测试所有”后不得再报警
        scoped.assert_no_foreign_python(allowed=preexisting | {fake.pid})
    finally:
        # 清理必须容忍目标**已自行退出**：PowerShell 的
        # `Stop-Process -Id <已消失 PID> -Force -ErrorAction SilentlyContinue`
        # 仍以退出码 1 结束（已实测），而 scripts/process_scope.py 的查询封装
        # 对此抛出 RuntimeError。本环境会周期性终止进程，故该竞态会表现为
        # cleanup 失败（断言本身已通过）。安全性不受影响：紧随其后的
        # `assert not _alive(fake.pid)` 仍强制要求进程确实消失。
        try:
            scoped.kill_tree(fake.pid)
        except RuntimeError:
            pass
    assert not _alive(fake.pid)


def test_guard_can_require_full_exclusivity(scoped):
    """严格模式：任何其它 python 进程都算外来（含本测试自己 spawn 的旁观者）。"""
    other = _spawn_sleeper()
    try:
        with pytest.raises(scoped.ForeignProcessError):
            scoped.assert_no_foreign_python(include_unknown_python=True)
    finally:
        scoped.kill_tree(other.pid)


def test_kill_tree_only_touches_its_own_tree(scoped):
    """kill_tree 只终止传入 PID 的进程树——绝不误伤同族其它进程（事故根因）。"""
    mine = _spawn_sleeper()
    bystander = _spawn_sleeper()
    try:
        assert bystander.pid in scoped.process_tree(os.getpid())
        killed = scoped.kill_tree(mine.pid)
        assert mine.pid in killed
        assert not _alive(mine.pid), "本树进程应已终止"
        assert _alive(bystander.pid), \
            " bystander 被误杀 → 正是 2026-09-12 事故的形态"
        assert _alive(os.getpid()), "测试进程自身不得被终止"
    finally:
        scoped.kill_tree(bystander.pid)
    assert not _alive(bystander.pid)

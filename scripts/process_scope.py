# -*- coding: utf-8 -*-
"""进程终止作用域守卫（M5.1 误杀事故流程规则，2026-09-12）。

规则（事故后新增，见 docs/process_kill_scope.md）：

* 任何测试/诊断脚本**禁止**按进程名批量终止：
  ``Stop-Process -Name python`` / ``Get-Process python | Stop-Process`` /
  ``taskkill /IM python.exe`` / ``pkill python`` / ``killall python``；
* 只允许操作：**显式 PID + 已核实的父子进程树 + 已知的测试实例**；
* 启动任何测试实例之前，若检测到**非测试**的 AstrBot 进程（主人的 live 实例），
  必须 ``ABORT TEST``，**绝不允许清理它**。

本模块提供该规则的唯一实现，供脚本与测试复用；
``tests/test_process_kill_scope.py`` 对实现与仓库现状做回归。
"""
from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterable

POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"

#: AstrBot 实例进程的典型宿主解释器镜像名（venvlauncher 桩与真实后端）。
PYTHON_IMAGE_NAMES = ("python.exe", "pythonw.exe")

_LIST_PROCESSES_PS = (
    "Get-CimInstance Win32_Process | ForEach-Object {{ "
    "\"$($_.ProcessId)|$($_.ParentProcessId)|$($_.Name)|"
    "$($_.ExecutablePath)|$($_.CommandLine)\" }}"
)
_LIST_PAIRS_PS = (
    "Get-CimInstance Win32_Process | ForEach-Object {{ "
    "\"$($_.ProcessId)|$($_.ParentProcessId)\" }}"
)


class ForeignProcessError(RuntimeError):
    """检测到非测试进程（很可能是主人的 live 实例）→ 调用方必须 ABORT。"""


def _run_ps(command: str) -> str:
    """执行 PowerShell 查询并以 UTF-8 容错解码。

    注意：不能依赖 ``text=True``（控制台代码页可能是 GBK，命令里含非 GBK 字节时
    子进程 reader 线程会抛 UnicodeDecodeError 并让 stdout 变成 None）。
    """
    full = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; " + command
    proc = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", full],
        capture_output=True, check=False)
    out = (proc.stdout or b"").decode("utf-8", errors="replace")
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"PowerShell 查询失败(rc={proc.returncode}): {err}")
    return out


def _parse_processes(raw: str) -> list[dict]:
    out: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|", 4)
        if len(parts) < 4:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        out.append({
            "pid": pid,
            "ppid": ppid,
            "name": parts[2],
            "exe": parts[3],
            "cmdline": parts[4] if len(parts) > 4 else "",
        })
    return out


def all_processes() -> list[dict]:
    """全量进程表：``{pid, ppid, name, exe, cmdline}``。"""
    return _parse_processes(_run_ps(_LIST_PROCESSES_PS.format()))


def python_processes() -> list[dict]:
    """当前所有 python/pythonw 进程。"""
    names = {n.lower() for n in PYTHON_IMAGE_NAMES}
    return [p for p in all_processes() if (p["name"] or "").lower() in names]


def own_ancestry() -> set[int]:
    """本进程及其全部祖先 PID（永远不算“外来实例”）。"""
    table = {p["pid"]: p for p in all_processes()}
    ancestry = {os.getpid()}
    cursor = os.getpid()
    for _ in range(64):
        parent = table.get(cursor, {}).get("ppid")
        if not parent or parent in ancestry:
            break
        ancestry.add(parent)
        cursor = parent
    return ancestry


def looks_like_astrbot_instance(cmdline: str) -> bool:
    """按命令行识别 AstrBot 实例进程（``...\\core\\main.py`` 形态）。

    只按“名字含 python”判断会误伤测试自身的解释器；按命令行形态判断才准确。
    """
    text = (cmdline or "").replace("/", "\\").lower()
    return "main.py" in text and ("astrbot" in text or "\\core\\" in text)


def astrbot_processes() -> list[dict]:
    """当前存在的 AstrBot 实例进程（排除本进程自身的进程链）。"""
    own = own_ancestry()
    return [p for p in python_processes()
            if p["pid"] not in own and looks_like_astrbot_instance(p["cmdline"])]


def assert_no_foreign_python(allowed: Iterable[int] = (), *,
                             include_unknown_python: bool = False) -> None:
    """启动测试实例前的守卫。

    外来实例 = 非本进程链、且（AstrBot 形态的 python 进程）；
    ``include_unknown_python=True`` 时把任何其它 python 进程也算外来
    （更严格，供需要绝对独占的场景使用）。

    检测到即抛 :class:`ForeignProcessError`（调用方必须 ABORT，不得清理）。
    """
    own = own_ancestry()
    allowed_set = {int(p) for p in allowed} | own
    foreign = [
        p for p in python_processes()
        if p["pid"] not in allowed_set
        and (include_unknown_python or looks_like_astrbot_instance(p["cmdline"]))
    ]
    if foreign:
        detail = "; ".join(
            f"pid={p['pid']} ppid={p['ppid']} exe={p['exe']}" for p in foreign)
        raise ForeignProcessError(
            "检测到非测试 AstrBot 实例进程 → ABORT TEST，禁止清理: " + detail)


def process_tree(root_pid: int) -> list[int]:
    """返回 ``root_pid`` 及其全部后代的 PID（先根后叶）。"""
    raw = _run_ps(_LIST_PAIRS_PS.format())
    children: dict[int, list[int]] = {}
    for line in raw.splitlines():
        line = line.strip()
        if "|" not in line:
            continue
        pid_s, ppid_s = line.split("|", 1)
        try:
            children.setdefault(int(ppid_s), []).append(int(pid_s))
        except ValueError:
            continue
    ordered: list[int] = []
    frontier = [int(root_pid)]
    while frontier:
        nxt: list[int] = []
        for pid in frontier:
            if pid in ordered:
                continue
            ordered.append(pid)
            nxt.extend(children.get(pid, []))
        frontier = nxt
    return ordered


def kill_tree(root_pid: int) -> list[int]:
    """**只**终止 ``root_pid`` 及其后代（显式 PID，叶子优先），返回被终止的 PID。

    绝不做按名批量终止；绝不动传入 PID 之外的任何进程。
    """
    tree = process_tree(root_pid)
    for pid in reversed(tree):
        _run_ps("Stop-Process -Id " + str(int(pid)) +
                " -Force -ErrorAction SilentlyContinue")
    return tree


def live_python_guard_exit() -> None:
    """供 CLI 脚本使用：检测到外来实例时打印并 ``sys.exit(9)``。"""
    try:
        assert_no_foreign_python()
    except ForeignProcessError as exc:
        print(f"ABORT TEST: {exc}")
        sys.exit(9)


__all__ = [
    "ForeignProcessError",
    "all_processes",
    "astrbot_processes",
    "assert_no_foreign_python",
    "kill_tree",
    "live_python_guard_exit",
    "looks_like_astrbot_instance",
    "own_ancestry",
    "process_tree",
    "python_processes",
]

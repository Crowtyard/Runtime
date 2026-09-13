# -*- coding: utf-8 -*-
"""隔离 AstrBot 实例验收：证明修复后 host startup marker 不再被 Runtime 迁移静默。

背景（M5.1 事故）：Runtime 在 AstrBot 进程内执行 alembic upgrade 时调用
``fileConfig(alembic.ini)``，默认 ``disable_existing_loggers=True`` → 禁用宿主
``astrbot`` 全树 logger + 替换 root handler → ``AstrBot started.`` 被静默丢弃 →
Launcher 判不出就绪 → 300s 超时强杀。

本脚本用**真实 AstrBot 核心**在隔离环境验收（绝不触碰 live 实例）：

* ``ASTRBOT_ROOT`` 指向临时目录 → 数据/插件/plugin_data 全部隔离；
* 端口独立（默认 6189），不与 live 的 6185 冲突；
* ``--webui-dir`` 复用只读的 WebUI 静态目录，避免联网下载；
* 启动前 ``assert_no_foreign_python()``：检测到任何外来 python 实例 → ABORT；
* 结束只终止本脚本拉起的进程树（``scripts.process_scope``），绝不做按名批量终止。

用法：
    python scripts/isolated_astrbot_marker_acceptance.py \
        --plugin <插件源码目录> [--core <AstrBot core 目录>] \
        [--python <解释器>] [--webui-dir <静态目录>] [--port 6189] [--runs 2]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.process_scope import (  # noqa: E402
    assert_no_foreign_python, kill_tree)

PLUGIN_DIR_NAME = "astrbot_plugin_blessed_land_runtime"
MARKER = "AstrBot started."
DEFAULT_CORE = Path(
    r"C:\Users\Crowtyard\.astrbot_launcher\instances"
    r"\f76fe2fd-8c03-4ba2-b4d6-467d1645ed0d\core")
DEFAULT_PYTHON = Path(
    r"C:\Users\Crowtyard\.astrbot_launcher\instances"
    r"\f76fe2fd-8c03-4ba2-b4d6-467d1645ed0d\venv\Scripts\python.exe")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _http_status(port: int, timeout: float = 3.0) -> object:
    """探测 dashboard；显式绕过环境代理（否则 localhost 请求会被代理拦截）。

    只把 200 视为就绪；其它状态码/异常返回 None（不足为凭）。
    """
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}))   # 直连，不走 http_proxy/https_proxy
    for host in ("127.0.0.1", "localhost"):
        try:
            with opener.open(f"http://{host}:{port}/", timeout=timeout) as resp:
                if resp.status == 200:
                    return 200
        except Exception:
            continue
    return None


def _deploy_plugin(plugin_src: Path, plugins_dir: Path) -> Path:
    dest = plugins_dir / PLUGIN_DIR_NAME
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(
        plugin_src, dest,
        ignore=shutil.ignore_patterns(
            "__pycache__", ".git", ".pytest_cache", "tests", "reports",
            "docs", "scripts", "runtime_design", "backups", "*.pyc",
            "*.db", "*.db-wal", "*.db-shm"))
    return dest


def run_once(*, tag: str, plugin_src: Path, core: Path, python_exe: Path,
             webui_dir: Path | None, port: int, root: Path,
             timeout_s: float = 180.0) -> dict:
    plugins_dir = root / "data" / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    _deploy_plugin(plugin_src, plugins_dir)

    out_file = root / f"{tag}.stdout.txt"
    err_file = root / f"{tag}.stderr.txt"
    for p in (out_file, err_file):
        if p.exists():
            p.unlink()

    env = dict(os.environ)
    env.update({
        "ASTRBOT_ROOT": str(root),
        "ASTRBOT_LAUNCHER": "1",
        "DASHBOARD_HOST": "127.0.0.1",
        "DASHBOARD_PORT": str(port),
        "PYTHONUNBUFFERED": "1",
        "VIRTUAL_ENV": str(python_exe.parent.parent),
    })
    for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
                "PYTHONIOENCODING"):
        env.pop(key, None)

    argv = [str(python_exe), str(core / "main.py")]
    if webui_dir is not None:
        argv += ["--webui-dir", str(webui_dir)]

    t0 = time.time()
    with open(out_file, "wb") as fo, open(err_file, "wb") as fe:
        proc = subprocess.Popen(argv, cwd=str(core), env=env,
                                stdout=fo, stderr=fe,
                                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)

    result = {
        "tag": tag,
        "pid": proc.pid,
        "marker_seen": False,
        "marker_at_s": None,
        "dashboard_http": None,
        "dashboard_at_s": None,
        "plugin_error": None,
        "startup_timeout": False,
        "shutdown": None,
    }
    try:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if proc.poll() is not None:
                result["process_exited_early"] = proc.returncode
                break
            text = _read(out_file)
            if not result["marker_seen"] and MARKER in text:
                result["marker_seen"] = True
                result["marker_at_s"] = round(time.time() - t0, 2)
            if result["dashboard_http"] is None:
                status = _http_status(port, timeout=1.5)
                if status is not None:
                    result["dashboard_http"] = status
                    result["dashboard_at_s"] = round(time.time() - t0, 2)
            if result["marker_seen"] and result["dashboard_http"] is not None:
                break
            time.sleep(1.0)
        else:
            result["startup_timeout"] = True

        tail = _read(out_file) + _read(err_file)
        for bad in ("Failed to load plugin", "插件加载失败", "初始化失败",
                    "ModuleNotFoundError"):
            if bad in tail:
                result["plugin_error"] = bad
                break
        # AstrBot 自身在 GBK 控制台上的 ✨ 横幅编码错误（与 Runtime 无关，记录但不算插件错误）
        result["core_loguru_gbk_encoding_error"] = (
            "UnicodeEncodeError: 'gbk' codec can't encode character '\\u2728'"
            in tail)
    finally:
        # 干净关闭：先 CTRL_BREAK 给进程组（AstrBot 会走 shutdown 路径），再兜底
        try:
            os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
        except Exception as exc:  # noqa: BLE001
            result["shutdown_ctrl_break_error"] = str(exc)
        try:
            proc.wait(timeout=20)
            result["shutdown"] = "clean_exit"
        except subprocess.TimeoutExpired:
            killed = kill_tree(proc.pid)   # 只杀本脚本拉起的树
            result["shutdown"] = f"scoped_kill:{killed}"
        result["exit_code"] = proc.returncode

    result["core_log_has_webui_ready"] = "WebUI is ready" in _read(out_file)
    result["core_log_lines"] = len(_read(out_file).splitlines())
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plugin", required=True)
    ap.add_argument("--core", default=str(DEFAULT_CORE))
    ap.add_argument("--python", default=str(DEFAULT_PYTHON))
    ap.add_argument("--webui-dir", default=str(DEFAULT_CORE / "data" / "dist"))
    ap.add_argument("--port", type=int, default=6189)
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--root", default=None)
    args = ap.parse_args()

    try:
        assert_no_foreign_python()
    except Exception as exc:  # noqa: BLE001
        print(f"ABORT TEST: {exc}")
        return 9

    plugin_src = Path(args.plugin).resolve()
    core = Path(args.core).resolve()
    python_exe = Path(args.python).resolve()
    webui = Path(args.webui_dir).resolve()
    root = Path(args.root).resolve() if args.root else \
        Path(os.environ.get("TEMP", ".")) / f"blr_iso_{int(time.time())}"

    results = []
    for i in range(args.runs):
        tag = f"run{i + 1}"
        res = run_once(tag=tag, plugin_src=plugin_src, core=core,
                       python_exe=python_exe, webui_dir=webui,
                       port=args.port, root=root)
        results.append(res)
        print(json.dumps(res, ensure_ascii=False))

    summary = {
        "plugin_src": str(plugin_src),
        "isolated_root": str(root),
        "port": args.port,
        "runs": results,
        "MARKER_PRESENT_IN_ALL_RUNS": all(r["marker_seen"] for r in results),
        "DASHBOARD_HTTP_OK_ALL_RUNS": all(
            r["dashboard_http"] == 200 for r in results),
        "PLUGIN_ERROR": next(
            (r["plugin_error"] for r in results if r["plugin_error"]), None),
        "STARTUP_TIMEOUT": any(r["startup_timeout"] for r in results),
    }
    print("SUMMARY " + json.dumps(summary, ensure_ascii=False))
    return 0 if (summary["MARKER_PRESENT_IN_ALL_RUNS"]
                 and not summary["STARTUP_TIMEOUT"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())

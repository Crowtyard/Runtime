# -*- coding: utf-8 -*-
"""PRE-M6 PostgreSQL portability 静态审计（PG-002）。

替代原先只扫描 3 个 simulation 文件的 ``test_ta59``。

规则（三层，全部为静态、零网络、零数据库）：

1. **扫描范围** = 授权生产路径（``main.py``、``config/``、``domain/``、
   ``database/``、``services/``、``plugin_shell/``）。显式排除 ``tests/``、
   ``docs/``、``scripts/``（运维脚本，非插件运行路径）、``__pycache__``。
2. **方言分支规则**：SQLite 专有构造只允许出现在**显式方言分支**内 ——
   即该字符串常量位于某个 ``if <test 含 "sqlite" 字面量>:`` 分支体内
   （``if dialect == "sqlite":``、``if url.startswith("sqlite"):`` 等）。
   这是 ``POSTGRESQL_COMPATIBILITY_CONTRACT.md`` §2/§7 明确许可的 adapter 形态。
3. **白名单**：仅 ``services/backup_service.py``（契约 §2 唯一许可的
   sqlite3/PRAGMA adapter，非 sqlite URL 时由 ``_require_sqlite`` fail-closed）。
   白名单必须保持最小，其防护函数存在性由测试单独断言，防止白名单静默腐烂。

只扫描**非 docstring 的字符串常量**（注释与文档不执行 SQL，不计入），
因此文档中的示例、说明不会被误判。
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: 授权生产路径（相对仓库根）
PRODUCTION_PATHS: tuple[str, ...] = (
    "main.py", "config", "domain", "database", "services", "plugin_shell",
)

#: 排除目录（相对仓库根）
EXCLUDED_DIRS: frozenset[str] = frozenset({
    "tests", "docs", "scripts", "__pycache__", ".git", "node_modules",
})

#: 允许出现 SQLite 专有 SQL 的模块（路径 → 理由）。必须保持最小。
ALLOWLIST: dict[str, str] = {
    "services/backup_service.py":
        "契约 §2 唯一许可的 sqlite3/PRAGMA adapter；非 sqlite URL 由 "
        "_require_sqlite fail-closed 拒绝（PG 备份属未来适配点）",
}

#: 白名单模块必须存在的 fail-closed 防护符号
ALLOWLIST_GUARDS: dict[str, tuple[str, ...]] = {
    "services/backup_service.py": ("def _require_sqlite", "raise BackupError"),
}

_SQLITE_ONLY_PATTERNS: tuple[tuple[str, str], ...] = (
    # SQLite JSON1 函数族
    ("json_extract", r"\bjson_extract\s*\("),
    ("json_each", r"\bjson_each\s*\("),
    ("json_tree", r"\bjson_tree\s*\("),
    ("json_set", r"\bjson_set\s*\("),
    ("json_insert", r"\bjson_insert\s*\("),
    ("json_replace", r"\bjson_replace\s*\("),
    ("json_remove", r"\bjson_remove\s*\("),
    ("json_patch", r"\bjson_patch\s*\("),
    ("json_array", r"\bjson_array\s*\("),
    ("json_object", r"\bjson_object\s*\("),
    ("json_quote", r"\bjson_quote\s*\("),
    ("json_type", r"\bjson_type\s*\("),
    ("json_valid", r"\bjson_valid\s*\("),
    ("json_group_array", r"\bjson_group_array\s*\("),
    ("json_group_object", r"\bjson_group_object\s*\("),
    # 引擎/元数据
    ("PRAGMA", r"\bpragma\b"),
    ("sqlite_master", r"\bsqlite_master\b"),
    ("sqlite_schema", r"\bsqlite_schema\b"),
    ("sqlite_sequence", r"\bsqlite_sequence\b"),
    ("sqlite_temp_master", r"\bsqlite_temp_master\b"),
    # SQLite 语法/冲突子句
    ("INSERT OR REPLACE", r"\binsert\s+or\s+replace\b"),
    ("INSERT OR IGNORE", r"\binsert\s+or\s+ignore\b"),
    ("INSERT OR ABORT", r"\binsert\s+or\s+abort\b"),
    ("INSERT OR FAIL", r"\binsert\s+or\s+fail\b"),
    ("INSERT OR ROLLBACK", r"\binsert\s+or\s+rollback\b"),
    ("UPDATE OR REPLACE", r"\bupdate\s+or\s+replace\b"),
    ("UPDATE OR IGNORE", r"\bupdate\s+or\s+ignore\b"),
    ("AUTOINCREMENT", r"\bautoincrement\b"),
    ("WITHOUT ROWID", r"\bwithout\s+rowid\b"),
    ("rowid", r"\browid\b"),
    ("RAISE(...)", r"\braise\s*\("),
    ("ATTACH", r"\battach\b"),
    ("DETACH", r"\bdetach\b"),
    ("VACUUM", r"\bvacuum\b"),
    # SQLite 专有函数
    ("strftime(", r"\bstrftime\s*\("),
    ("julianday(", r"\bjulianday\s*\("),
    ("unixepoch(", r"\bunixepoch\s*\("),
    ("datetime(", r"\bdatetime\s*\("),
    ("ifnull(", r"\bifnull\s*\("),
    ("instr(", r"\binstr\s*\("),
    ("iif(", r"\biif\s*\("),
    ("group_concat(", r"\bgroup_concat\s*\("),
    ("last_insert_rowid(", r"\blast_insert_rowid\s*\("),
    ("randomblob(", r"\brandomblob\s*\("),
    ("printf(", r"\bprintf\s*\("),
    ("GLOB", r"\bglob\b"),
)

_COMPILED: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern, re.IGNORECASE))
    for name, pattern in _SQLITE_ONLY_PATTERNS)


@dataclass(frozen=True)
class Violation:
    path: str
    lineno: int
    token: str
    snippet: str

    def __str__(self) -> str:  # pragma: no cover - 诊断用
        return f"{self.path}:{self.lineno}: [{self.token}] {self.snippet}"


def production_files(root: Path = PROJECT_ROOT) -> list[Path]:
    """返回授权生产路径下的全部 .py（排序稳定，便于断言与复现）。"""
    files: list[Path] = []
    for rel in PRODUCTION_PATHS:
        target = root / rel
        if target.is_file() and target.suffix == ".py":
            files.append(target)
            continue
        if not target.is_dir():
            continue
        for path in target.rglob("*.py"):
            if any(part in EXCLUDED_DIRS for part in path.parts):
                continue
            files.append(path)
    return sorted(set(files))


def _mentions_sqlite(test: ast.expr) -> bool:
    """判断条件表达式是否显式指向 sqlite 方言。"""
    for node in ast.walk(test):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and "sqlite" in node.value.lower():
            return True
    return False


def _dialect_gated_lines(tree: ast.AST) -> set[int]:
    """收集「显式 sqlite 方言分支」体内所有节点的行号。"""
    gated: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.If, ast.IfExp)):
            continue
        if not _mentions_sqlite(node.test):
            continue
        bodies = node.body if isinstance(node.body, list) else [node.body]
        for body in bodies:
            for sub in ast.walk(body):
                lineno = getattr(sub, "lineno", None)
                if lineno is not None:
                    gated.add(lineno)
    return gated


def _docstring_node_ids(tree: ast.AST) -> set[int]:
    """模块/类/函数 docstring 的节点 id（文档不计入扫描）。"""
    ids: set[int] = set()
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, holders) or not node.body:
            continue
        first = node.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                and isinstance(first.value.value, str):
            ids.add(id(first.value))
    return ids


def scan_source(source: str, *, path: str = "<source>") -> list[Violation]:
    """扫描单份源码文本（供测试与仓库扫描共用）。"""
    tree = ast.parse(source, filename=path)
    gated = _dialect_gated_lines(tree)
    docstrings = _docstring_node_ids(tree)
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstrings:
            continue
        text = node.value
        if not text.strip():
            continue
        for token, pattern in _COMPILED:
            if pattern.search(text):
                if node.lineno in gated:
                    continue
                snippet = " ".join(text.split())[:80]
                violations.append(Violation(path=path, lineno=node.lineno,
                                            token=token, snippet=snippet))
    return sorted(violations, key=lambda v: (v.path, v.lineno, v.token))


def scan_file(path: Path) -> list[Violation]:
    rel = str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    return scan_source(path.read_text(encoding="utf-8"), path=rel)


def scan_repository(root: Path = PROJECT_ROOT) -> tuple[list[Violation], int]:
    """扫描全生产路径；返回（违规列表，扫描文件数）。

    白名单文件只做存在性跳过；其防护符号由测试单独断言。
    """
    violations: list[Violation] = []
    files = production_files(root)
    for path in files:
        rel = str(path.relative_to(root)).replace("\\", "/")
        if rel in ALLOWLIST:
            continue
        violations.extend(scan_file(path))
    return violations, len(files)

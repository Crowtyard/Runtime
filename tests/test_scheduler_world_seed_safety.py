# -*- coding: utf-8 -*-
"""M4 World Seed 安全：Scheduler 层零消费正式 World Seed（§2.2 / §27）。

- Scheduler 源码静态扫描：不得引用 world_seed / seed baseline 文件 /
  激活语义之外任何消费路径；
- 正式 World Seed 包 MANIFEST 逐字节校验（与冻结一致）。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from tests.conftest import PROJECT_ROOT

REPO = PROJECT_ROOT
SEED_DIR = REPO.parent / "XIAOGUANG_CROW_KB" / "world_seed"
SCHEDULER_DIR = REPO / "services" / "scheduler"

FORBIDDEN = (
    # 正式 Seed 包消费路径（world_seed_version 字段名属激活判定读取，合法）
    "world_seed/", "XIAOGUANG_CROW_KB", "04_population_baseline",
    "05_species_baseline", "06_settlement_baseline", "consume_seed",
    "activate_seed", "seed_activation", "WORLD_SEED_INDEX",
    "UNRESOLVED_SEED", "MANIFEST.sha256",
)


def test_scheduler_source_never_consumes_world_seed():
    for py in SCHEDULER_DIR.rglob("*.py"):
        src = py.read_text(encoding="utf-8")
        for token in FORBIDDEN:
            assert token not in src, (py, token)


def test_world_seed_manifest_byte_frozen():
    manifest = SEED_DIR / "MANIFEST.sha256.txt"
    entries = {}
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

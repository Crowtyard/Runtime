# -*- coding: utf-8 -*-
"""PF20：整个测试套件结束后，正式世界库零变化 + 零 M2 实体。"""
from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path

import pytest


def test_pf20_formal_world_zero_m2_entities_after_suite(formal_db_guard):
    path = os.environ.get("BLR_FORMAL_DB_PATH", "")
    if not path or formal_db_guard is None:
        pytest.skip("BLR_FORMAL_DB_PATH 未设置（正式库守护跳过）")
    p = Path(path)
    after = hashlib.sha256(p.read_bytes()).hexdigest()
    assert after == formal_db_guard, "正式库在整个测试套件期间被修改！"

    conn = sqlite3.connect(str(p))
    try:
        row = conn.execute(
            "SELECT runtime_status, world_seed_version, current_blessed_tick, "
            "last_committed_real_us FROM world_runtime LIMIT 1").fetchone()
        assert row == ("NOT_ACTIVATED", None, None, None), row
        for t in ("persons", "population_groups", "settlements",
                  "resource_nodes", "tribulations", "world_events",
                  "timeline_entries", "simulation_run",
                  "simulation_checkpoints", "ecological_regions",
                  "industries", "institutions", "lineages"):
            n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            assert n == 0, f"正式库表 {t} 非空: {n}"
        m2_ckpts = conn.execute(
            "SELECT COUNT(*) FROM simulation_checkpoints "
            "WHERE json_extract(meta, '$.kind') = 'M2_PREFLIGHT'").fetchone()[0]
        assert m2_ckpts == 0
    finally:
        conn.close()

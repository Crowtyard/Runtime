# -*- coding: utf-8 -*-
"""PF20：整个测试套件结束后，正式世界库零变化 + 零官方实体。

口径（canonical，见 tests/formal_db.py）：
``world_runtime`` **0 行** == 官方世界从未激活；不得为使测试通过而插入
NOT_ACTIVATED 行。所有连接显式**只读**，因此「测试前后 SHA256 一致」
才是有效的「正式库未被触碰」证据。
"""
from __future__ import annotations

import os

import pytest

from tests.formal_db import (assert_tables_empty, assert_unactivated_canonical,
                            integrity_ok, readonly_connect, sha256_of)

M2_ENTITIES = ("persons", "population_groups", "settlements", "resource_nodes",
               "tribulations", "world_events", "timeline_entries",
               "simulation_run", "simulation_checkpoints", "ecological_regions",
               "industries", "institutions", "lineages")


def test_pf20_formal_world_zero_m2_entities_after_suite(formal_db_guard):
    path = os.environ.get("BLR_FORMAL_DB_PATH", "")
    if not path or formal_db_guard is None:
        pytest.skip("BLR_FORMAL_DB_PATH 未设置（正式库守护跳过）")

    # 1) 字节级不变（只读访问 ⇒ 该断言才有意义）
    assert sha256_of(path) == formal_db_guard, "正式库在整个测试套件期间被修改！"

    with readonly_connect(path) as conn:
        # 2) canonical 未激活表示 = world_runtime 0 行
        assert_unactivated_canonical(conn)
        # 3) 官方实体表全空（含 M2 层）
        assert_tables_empty(conn, M2_ENTITIES)
        # 4) 不得存在任何 M2_PREFLIGHT checkpoint
        m2_ckpts = conn.execute(
            "SELECT COUNT(*) FROM simulation_checkpoints "
            "WHERE json_extract(meta, '$.kind') = 'M2_PREFLIGHT'").fetchone()[0]
        assert m2_ckpts == 0, m2_ckpts
        # 5) 结构完整性
        assert integrity_ok(conn)

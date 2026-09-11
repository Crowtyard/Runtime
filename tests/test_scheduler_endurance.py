# -*- coding: utf-8 -*-
"""M4.8 Endurance（§32）：seed_001 5000 福地年 Scheduler-driven，
与 M3c 冻结 5000y golden 三哈希逐字节一致。

无 scheduler drift / memory-state drift / history orphan / cycle /
duplicate tick / lost tick（由三哈希等价 + 完整性审计覆盖）。
"""
from __future__ import annotations

from pathlib import Path

from tests.conftest import EPOCH0_US, PROJECT_ROOT
from tests.golden_baseline import load_artifact
from tests.test_m3_integrated_long import (_fresh_m3, M3_LONG_WORLD_IDS,
                                           _invariant_check)
from tests.test_m3b_history import _hist_coordinator
from tests.test_scheduler_catchup import run_scheduler_to

from XiaoguangBlessedLandRuntime.services.history.service import HistoryService

REPO = PROJECT_ROOT
WORLD = M3_LONG_WORLD_IDS[0]
M3C_5000Y = REPO / "tests" / "baselines" / \
    "m3_integrated_5000y_seed001_v1.json"


def test_scheduler_5000y_endurance_reproduces_frozen(tmp_path):
    golden = load_artifact(M3C_5000Y)
    env = _fresh_m3(tmp_path, 1, WORLD)
    sched = run_scheduler_to(env, budget_ticks=250_000_000,
                             target_years=5000, provider_years=5000,
                             state_dir=tmp_path / "runtime_state")
    snap = sched.get_scheduler_status()
    assert snap["durable_current_tick"] == 5_000_000_000
    assert snap["catchup_batches_total"] == 5000
    sched.stop()
    # 三哈希 == M3c 冻结 5000y golden（scheduler == frozen direct）
    assert _hashes3(env) == golden["hashes"]
    # 完整性
    audit = _invariant_check(env)
    assert audit["clean"], audit["issues"]
    with env["factory"]() as s:
        hi = HistoryService(env["factory"]).history_integrity_audit(
            world_id=WORLD)
    assert hi["orphan_links"] == 0 and hi["cycle_count"] == 0
    assert hi["tick_paradox_links"] == 0 and hi["supersede_loops"] == 0
    # 增长形态（线性；参考 300y 基线）
    counts = _record_counts(env)
    links_per_100y = counts["causal_history_links"] / 50
    idx_per_100y = counts["entity_history_index"] / 50
    assert links_per_100y < 21914 * 1.6
    assert idx_per_100y < 21619 * 1.6


def _hashes3(env) -> dict:
    from tests.test_m3_integrated_long import _hashes
    return _hashes(env)


def _record_counts(env) -> dict:
    from sqlalchemy import text
    out = {}
    with env["factory"]() as s:
        for t in ("causal_history_links", "entity_history_index"):
            out[t] = s.execute(text(
                f'SELECT COUNT(*) FROM "{t}"')).scalar()
    return out

# -*- coding: utf-8 -*-
"""M4 Scheduler Determinism（§23）：scheduler-driven == frozen direct driver，
且 1000y 复现 M3c 冻结 seed_001 golden（三哈希逐字节一致）。

固定 seed：M3LONG-001（与 M3c 冻结基线同一世界）。
"""
from __future__ import annotations

from pathlib import Path

from tests.conftest import EPOCH0_US, PROJECT_ROOT
from tests.test_m3_integrated_long import (_fresh_m3, _hashes, _m3_run,
                                           M3_LONG_WORLD_IDS)
from tests.test_m3b_history import _hist_coordinator
from tests.test_scheduler_catchup import run_scheduler_to

from tests.golden_baseline import load_artifact

REPO = PROJECT_ROOT
WORLD = M3_LONG_WORLD_IDS[0]
M3C_SEED_001 = REPO / "tests" / "baselines" / "m3_integrated_1000y_v1" / \
    "seed_001.json"


def test_scheduler_120y_matches_direct(tmp_path):
    env = _fresh_m3(tmp_path, 1, WORLD)
    sched = run_scheduler_to(env, budget_ticks=30_000_000,
                             target_years=120, provider_years=120,
                             state_dir=tmp_path / "runtime_state")
    sched.stop()
    ref = _fresh_m3(tmp_path, 2, WORLD)
    _m3_run(ref, years=120)
    assert _hashes(env) == _hashes(ref)


def test_scheduler_1000y_reproduces_frozen_seed001(tmp_path):
    """验收级：Scheduler 驱动 1000y == M3c 冻结 seed_001 golden。"""
    golden = load_artifact(M3C_SEED_001)
    env = _fresh_m3(tmp_path, 3, WORLD)
    sched = run_scheduler_to(env, budget_ticks=250_000_000,
                             target_years=1000, provider_years=1000,
                             state_dir=tmp_path / "runtime_state")
    snap = sched.get_scheduler_status()
    assert snap["durable_current_tick"] == 1_000_000_000
    assert snap["catchup_batches_total"] == 1000  # 1000 个 1 年批次（250y budget）
    sched.stop()
    assert _hashes(env) == golden["hashes"]

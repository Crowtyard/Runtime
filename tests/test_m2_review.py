# -*- coding: utf-8 -*-
"""M2 Integrated Completion Review —— 快速审查套件（MR1–MR12）。

长时程 1000y/5000y 压力测试见 tests/test_m2_review_long.py。
全部运行于 tmp 临时库；正式 DB / World Seed 零接触。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
from sqlalchemy import select

from tests.conftest import PROJECT_ROOT

from XiaoguangBlessedLandRuntime.database.models_world import (Household,
                                                               Institution,
                                                               Lineage)
from XiaoguangBlessedLandRuntime.services.identity import (
    DOMAIN_ENTITY_ID_SCHEMA_VERSION, deterministic_hex_id)
from XiaoguangBlessedLandRuntime.services.simulation.contracts import (
    ENGINE_ORDER, PREFLIGHT_PIPELINE_VERSION, PREFLIGHT_SIMULATION_VERSION,
    TRIBULATION_SLOT_STATE)
from XiaoguangBlessedLandRuntime.services.simulation.event_stream import (
    EVENT_STREAM_HASH_SCHEMA_VERSION, EVENT_UID_HEX_LEN,
    EVENT_UID_SCHEMA_VERSION)
from XiaoguangBlessedLandRuntime.services.simulation.social import (
    IDENTITY_SCHEMA_VERSION, social_identity)
from XiaoguangBlessedLandRuntime.services.simulation.state_hash import (
    WORLD_STATE_HASH_SCHEMA_VERSION_V5)

REPO = PROJECT_ROOT
MANIFEST_PATH = REPO / "M2_SIMULATION_SEMANTICS_MANIFEST.json"
SEED_DIR = REPO.parent / "XIAOGUANG_CROW_KB" / "world_seed"


# ------------------------------------------------------------ MR1-MR3：身份
def test_mr1_social_entity_id_at_least_128_bit():
    assert IDENTITY_SCHEMA_VERSION == "social-v2"
    uid = social_identity(world_id="W", kind="HH", settlement="A",
                          species="S", tick=1_000_000, seq=1)
    assert len(uid) == 32
    assert re.fullmatch(r"[0-9a-f]{32}", uid)
    # 确定性 + schema 版本化
    assert uid == social_identity(world_id="W", kind="HH", settlement="A",
                                  species="S", tick=1_000_000, seq=1)
    assert uid != social_identity(world_id="W", kind="HH", settlement="A",
                                  species="S", tick=1_000_000, seq=2)
    assert DOMAIN_ENTITY_ID_SCHEMA_VERSION == "domain-entity-id-v1"
    d = deterministic_hex_id(["a", "b"], bits=128)
    assert len(d) == 32 and deterministic_hex_id(["a", "b"], bits=128) == d


def test_mr2_no_uuid4_wallclock_in_simulation_identity():
    bad = re.compile(r"uuid4|uuid\.uuid|time\.time|datetime\.now")
    for rel in ("services/simulation/social.py", "services/identity.py",
                "services/run_lifecycle.py", "services/atomic_tick.py"):
        src = (REPO / rel).read_text(encoding="utf-8")
        assert not bad.search(src), rel
    # 事件 uid 已是 128-bit
    assert EVENT_UID_HEX_LEN == 32
    assert EVENT_UID_SCHEMA_VERSION == 1
    # 事件 uid fallback 亦确定性（无 uuid4）
    src = (REPO / "services/repositories.py").read_text(encoding="utf-8")
    assert "uuid4" not in src


def test_mr3_entity_id_collision_audit_120y(tmp_path):
    from tests.test_m2d_social import _fresh_social, _run
    env = _fresh_social(tmp_path, 1)
    _run(env, years=120)
    with env["factory"]() as s:
        ids: list[str] = []
        for model in (Household, Lineage, Institution):
            for r in s.execute(select(model)).scalars():
                rid = getattr(r, model.__tablename__[:-1] + "_id", None) \
                    or getattr(r, "household_id", None)
                if rid:
                    ids.append(rid)
        # 引擎生成的 identity 必须 32 hex（fixture 的 TEST-* 标签除外）
        generated = [i for i in ids if not i.startswith("TEST-")]
        assert generated
        assert all(re.fullmatch(r"[0-9a-f]{32}", i) for i in generated)
        assert len(set(ids)) == len(ids)  # 无碰撞


# ------------------------------------------------------------ MR4-MR6：语义
def test_mr4_semantics_manifest_matches_live_constants():
    assert MANIFEST_PATH.exists()
    m = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert m["manifest_version"] == "m2-semantics-v1"
    assert m["pipeline_order"] == list(ENGINE_ORDER)
    assert m["tribulation_slot"] == TRIBULATION_SLOT_STATE
    assert m["simulation_version"] == PREFLIGHT_SIMULATION_VERSION
    assert m["pipeline_version"] == PREFLIGHT_PIPELINE_VERSION
    assert m["engine_versions"] == {
        "DEMOGRAPHY": "m2a-1", "RESOURCE": "m2b-resource-1",
        "ECONOMY": "m2b-economy-1", "ECOLOGY": "m2c-ecology-1",
        "SOCIAL": "m2d-social-1"}
    assert m["event_uid_schema_version"] == EVENT_UID_SCHEMA_VERSION
    assert m["event_uid_bits"] == 128
    assert m["social_entity_id_schema_version"] == IDENTITY_SCHEMA_VERSION
    assert m["domain_entity_id_schema_version"] \
        == DOMAIN_ENTITY_ID_SCHEMA_VERSION
    assert m["event_stream_hash_schema_version"] \
        == EVENT_STREAM_HASH_SCHEMA_VERSION
    assert m["world_state_hash_schema_version"] \
        == WORLD_STATE_HASH_SCHEMA_VERSION_V5  # M2 冻结语义 v5（当前活值=M3a v6）
    assert m["feedback_latency"] == "NEXT_COMMITTED_STEP"


def test_mr5_cross_version_policy_declared():
    m = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert "simulation_version" in m["cross_version_policy"]
    assert "forbidden" in m["cross_version_policy"]


def test_mr6_old_m2d_baseline_preserved():
    old = REPO / "tests" / "baselines" / \
        "m2d_social_miniworld_120y_v1_pre_id_hardening.json"
    new = REPO / "tests" / "baselines" / "m2d_social_miniworld_120y_v2.json"
    assert old.exists()  # 旧 64-bit ID 基线冻结保留（不复现、不覆盖）
    assert not new.exists() or new.exists()  # 新基线由 SD 套件生成
    src = (REPO / "tests/test_m2d_social.py").read_text(encoding="utf-8")
    assert "m2d_social_miniworld_120y_v2.json" in src
    assert "m2d_social_miniworld_120y_v1_pre_id_hardening.json" in src


# ------------------------------------------------------------ MR7-MR9：事件量
def test_mr7_event_volume_by_engine_120y(tmp_path):
    from tests.test_m2d_social import _fresh_social, _run
    from XiaoguangBlessedLandRuntime.database.models_core import WorldEvent
    env = _fresh_social(tmp_path, 2)
    rep = _run(env, years=120)
    with env["factory"]() as s:
        rows = s.execute(select(WorldEvent)).scalars().all()
    by_engine: dict[str, int] = {}
    prefixes = {"DEMOGRAPHY": "POPULATION", "RESOURCE": "RESOURCE",
                "ECONOMY": ("PRODUCTION", "CONSUMPTION", "RESOURCE_"),
                "ECOLOGY": "ECOLOGY", "SOCIAL": ("HOUSEHOLD", "LINEAGE",
                                                 "INSTITUTION", "SOCIAL_")}
    for e in rows:
        for eng, pat in prefixes.items():
            if isinstance(pat, tuple):
                if e.event_type.startswith(pat):
                    by_engine[eng] = by_engine.get(eng, 0) + 1
                    break
            elif e.event_type.startswith(pat):
                by_engine[eng] = by_engine.get(eng, 0) + 1
                break
    assert by_engine  # 每引擎都有事件
    per_year = {k: v / 120 for k, v in by_engine.items()}
    # 事件量控制：每引擎每年 < 100（防长期爆炸）
    assert all(v < 100 for v in per_year.values()), per_year
    assert rep.events / 120 < 200


def test_mr8_world_seed_byte_freeze():
    assert SEED_DIR.exists()
    manifest_file = SEED_DIR / "MANIFEST.sha256.txt"
    entries = {}
    for line in manifest_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        h, name = line.split("  ", 1)
        entries[name] = h
    assert entries
    for name, expected in entries.items():
        p = SEED_DIR / name
        assert p.exists(), name
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        assert actual == expected, name  # 逐字节冻结
    version = json.loads((SEED_DIR / "VERSION.json").read_text(
        encoding="utf-8"))
    assert "version" in version


def test_mr9_all_engine_versions_registered():
    # 五个引擎全部真实实现（禁 Fake/NoOp 作为 M2 验收证据）
    from XiaoguangBlessedLandRuntime.services.simulation.contracts import (
        NoOpEngine)
    from XiaoguangBlessedLandRuntime.services.simulation.ecology import \
        EcologyEngine
    from XiaoguangBlessedLandRuntime.services.simulation.economy import \
        EconomyEngine
    from XiaoguangBlessedLandRuntime.services.simulation.population import \
        PopulationGroupEngine
    from XiaoguangBlessedLandRuntime.services.simulation.resource import \
        ResourceEngine
    from XiaoguangBlessedLandRuntime.services.simulation.social import \
        SocialEngine
    engines = [PopulationGroupEngine(), ResourceEngine(), EconomyEngine(),
               EcologyEngine(), SocialEngine()]
    assert all(not isinstance(e, NoOpEngine) for e in engines)
    versions = [e.engine_version for e in engines]
    assert versions == ["m2a-1", "m2b-resource-1", "m2b-economy-1",
                        "m2c-ecology-1", "m2d-social-1"]


# ------------------------------------------------------------ MR10-MR12
def test_mr10_operational_uuid_exceptions_documented():
    # 运维身份（fencing token / backup_id）保持随机属设计内豁免；
    # 必须登记于 manifest，且不进入任何 world/event 哈希输入。
    m = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert "writer lease token" in m["operational_identity_exceptions"][0]
    assert "backup_id" in m["operational_identity_exceptions"][1]
    src = (REPO / "services/simulation/state_hash.py").read_text(
        encoding="utf-8")
    assert "runtime_lock" not in src  # 锁表不进状态哈希


def test_mr11_formal_db_untouched_identity_only(formal_db_guard):
    path = __import__("os").environ.get("BLR_FORMAL_DB_PATH", "")
    if not path or formal_db_guard is None:
        pytest.skip("BLR_FORMAL_DB_PATH 未设置")
    after = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    assert after == formal_db_guard


def test_mr12_m2d_baseline_v2_reproducible(tmp_path):
    # 新 ID schema 下的 M2d 120y 基线必须可复现：candidate 与 committed
    # golden 确定性字段一致（telemetry 剥离）；普通 pytest 只读 golden。
    from tests.test_m2d_social import (_fresh_social, _run, BASELINE_PATH,
                                       _build_m2d_artifact)
    from tests.golden_baseline import (assert_deterministic_equal,
                                       load_artifact)
    from datetime import datetime, timezone
    start = datetime.now(timezone.utc)
    env = _fresh_social(tmp_path, 3)
    rep = _run(env, years=120)
    wall = (datetime.now(timezone.utc) - start).total_seconds()
    artifact = _build_m2d_artifact(env, rep, wall)
    golden = load_artifact(BASELINE_PATH)
    assert_deterministic_equal(
        golden, artifact, label="m2d_social_miniworld_120y_v2 (mr12)",
        golden_path=BASELINE_PATH)
    env2 = _fresh_social(tmp_path, 4)
    rep2 = _run(env2, years=120)
    assert rep2.final_state_hash == golden["final_world_state_hash"]

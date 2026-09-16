"""M6C.1 — SNAPSHOT_V1_CANDIDATE 守卫测试（owner §29）。

覆盖 owner §29 要求的六类：候选 schema / 人口-聚落-群体合计 / 确定性分配 /
无 TEST registry / 无 materializer / 无生产变更。

全部为**纯静态 + 内存**测试：不连数据库、不读 World Seed、不写任何文件。
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import pathlib
import sys
from fractions import Fraction

import pytest

from XiaoguangBlessedLandRuntime.services.activation import bootstrap_canon as BC

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build = _load("m6c1_build_snapshot_candidate", "scripts/build_snapshot_candidate.py")
validator = _load("m6c1_validate_snapshot_candidate",
                  "scripts/validate_snapshot_candidate.py")


@pytest.fixture(scope="module")
def candidate() -> dict:
    return validator.load_candidate()


@pytest.fixture(scope="module")
def report() -> dict:
    return validator.validate()


# ---------------------------------------------------------------- schema
def test_m6c101_candidate_is_valid_and_not_approved(report):
    assert report["status"] == "PASS"
    assert report["materialization_allowed"] is False


def test_m6c102_header_declares_candidate_state(candidate):
    header = candidate["header"]
    assert header["artifact"] == "SNAPSHOT_V1_CANDIDATE"
    assert header["status"] == "CANDIDATE_NOT_APPROVED"
    for flag in ("materialization_allowed", "formal_activation_allowed",
                 "world_seed_consumed", "agent_may_promote_to_snapshot_v1"):
        assert header[flag] is False, flag


def test_m6c103_formal_world_red_lines_unchanged(candidate):
    baseline = candidate["header"]["engine_baseline"]
    assert baseline["formal_world_runtime_rows"]["value"] == 0
    assert baseline["formal_world_status"]["value"] == "NOT_ACTIVATED"
    assert baseline["formal_world_current_blessed_tick"]["value"] is None
    assert baseline["formal_world_seed_status"]["value"] == "PREPARED_NOT_ACTIVATED"
    assert baseline["alembic_head"] == "a9d4f2b7c1e8"


def test_m6c104_no_approved_snapshot_artifact_exists():
    assert not (ROOT / "docs/world_creation/SNAPSHOT_V1.md").exists()
    assert not (ROOT / "docs/world_creation/SNAPSHOT_V1.json").exists()


def test_m6c105_candidate_is_reproducible_byte_for_byte():
    text_a = build.canonical_text(build.build())
    text_b = build.canonical_text(build.build())
    assert text_a == text_b
    on_disk = validator.CANDIDATE_PATH.read_text(encoding="utf-8")
    assert hashlib.sha256(on_disk.encode("utf-8")).hexdigest() == \
        hashlib.sha256(text_a.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- sums
def test_m6c106_population_settlement_group_sums(candidate):
    alloc = candidate["bootstrap_entity_plan"]["allocation"]
    assert sum(alloc["row_totals"]) == 12_000
    assert sum(alloc["column_totals"]) == 12_000
    assert alloc["row_totals"] == [4000, 3000, 2500, 2500]
    assert alloc["column_totals"] == [2000] * 4 + [500] * 8
    assert len(alloc["group_order"]) == 4
    assert len(alloc["settlement_order"]) == 12
    main = [n for n in alloc["settlement_order"] if n.startswith("MAIN-")]
    sat = [n for n in alloc["settlement_order"] if n.startswith("SAT-")]
    assert len(main) == 4 and len(sat) == 8
    assert candidate["world_layer_S1_S10"][0]["candidate"]["value"] == 12_000
    for slot in candidate["bootstrap_entity_plan"]["settlements"]:
        assert slot["working_name"]["state"] == "WORKING_NAME_ONLY"


def test_m6c107_matrix_is_double_marginal_exact(candidate):
    alloc = candidate["bootstrap_entity_plan"]["allocation"]
    matrix = alloc["matrix"]
    assert [sum(row) for row in matrix] == alloc["row_totals"]
    assert [sum(col) for col in zip(*matrix)] == alloc["column_totals"]
    BC.verify_allocation(matrix, alloc["row_totals"], alloc["column_totals"])


# ---------------------------------------------------------------- determinism
def test_m6c108_allocation_is_independently_recomputable(candidate):
    alloc = candidate["bootstrap_entity_plan"]["allocation"]
    groups = [int(g) for _, g in BC.GROUP_POPULATIONS]
    caps = [c for _, _, c in BC.SETTLEMENT_SLOTS]
    recomputed = BC.allocate(groups, caps)
    assert [list(r) for r in recomputed] == alloc["matrix"]
    assert BC.render_matrix(recomputed) == alloc["canonical_text"]
    assert BC.allocation_digest(recomputed) == alloc["matrix_sha256"]


def test_m6c109_allocation_is_byte_stable_over_many_runs():
    groups = [int(g) for _, g in BC.GROUP_POPULATIONS]
    caps = [c for _, _, c in BC.SETTLEMENT_SLOTS]
    digests = {BC.allocation_digest(BC.allocate(groups, caps)) for _ in range(50)}
    assert digests == {
        "8dfe3471c1ff9d9c93646df18e4f55335cb93ca634c4afc96a17c86b5b28c457"}


def test_m6c110_allocation_rejects_tampered_matrix(candidate):
    alloc = candidate["bootstrap_entity_plan"]["allocation"]
    tampered = [list(r) for r in alloc["matrix"]]
    tampered[0][0] += 1
    with pytest.raises(BC.AllocationError):
        BC.verify_allocation(tampered, alloc["row_totals"], alloc["column_totals"])


def test_m6c111_allocation_rejects_mismatched_totals():
    with pytest.raises(BC.AllocationError):
        BC.allocate([4000, 3000, 2500, 2499], [c for _, _, c in BC.SETTLEMENT_SLOTS])


def test_m6c112_cohort_rule_is_exact_and_deterministic():
    mortality = [Fraction(1, 200)] * 15 + [Fraction(1, 250)] * 20 + \
                [Fraction(1, 100)] * 4 + [Fraction(1, 50)]
    counts = BC.cohort_counts(mortality, 2000)
    assert sum(counts) == 2000
    assert len(counts) == len(mortality)
    assert counts == BC.cohort_counts(mortality, 2000)
    # 等权重 + 非整除 → 余额给下标小者（固定 tie-break）
    assert BC.apportion_largest_remainder([Fraction(1)] * 3, 4) == (2, 1, 1)


def test_m6c113_first_omen_is_derived_from_frozen_engine(candidate):
    s10 = candidate["world_layer_S1_S10"][9]["candidate"]
    assert s10["first_omen_tick"]["value"] == 10 * 1_000_000
    assert s10["first_omen_tick"]["source_class"] == "DETERMINISTIC_DERIVATION"
    per_tier = s10["first_window_tick_by_tier"]["value"]
    assert per_tier == {"REGULAR": 10_000_000, "MAJOR": 50_000_000,
                        "CENTENNIAL": 100_000_000}
    assert s10["tick0_active_tribulation_episodes"]["value"] == 0
    assert s10["pre_window_lead_time"]["state"] == \
        "CONCEPT_ABSENT_IN_FROZEN_ENGINE"


# ---------------------------------------------------------------- provenance
def test_m6c114_every_number_is_attributed(candidate):
    nodes = validator.check_provenance(candidate)
    assert len(nodes) >= 90
    assert validator.validate()["attributed_nodes"] == len(nodes)


def test_m6c115_unattributed_number_is_rejected(candidate):
    broken = json.loads(json.dumps(candidate))
    broken["bootstrap_entity_plan"]["smuggled"] = 7
    with pytest.raises(validator.CandidateInvalid) as exc:
        validator.check_provenance(broken)
    assert "UNATTRIBUTED_NUMBER" in str(exc.value)


def test_m6c116_derived_node_requires_full_derivation_block(candidate):
    broken = json.loads(json.dumps(candidate))
    node = broken["bootstrap_entity_plan"]["row_cardinality"]["ecology_zones"]
    del node["derivation"]["tie_break_policy"]
    with pytest.raises(validator.CandidateInvalid) as exc:
        validator.check_provenance(broken)
    assert "tie_break_policy" in str(exc.value)


def test_m6c117_every_blocked_node_maps_to_a_declared_owner_decision(candidate):
    declared = {d["id"] for d in candidate["minimal_owner_decisions"]}
    assert declared == {f"OD-{i}" for i in range(1, 11)}
    validator.check_blocking_disclosure(candidate)
    broken = json.loads(json.dumps(candidate))
    broken["world_layer_S1_S10"][1]["candidate"]["owner_decision_id"] = "OD-999"
    with pytest.raises(validator.CandidateInvalid):
        validator.check_blocking_disclosure(broken)


def test_m6c118_no_test_fixture_content(candidate):
    validator.check_no_test_fixtures(candidate)
    broken = json.loads(json.dumps(candidate))
    broken["bootstrap_entity_plan"]["settlements"][0]["working_name"]["value"] = \
        "TEST-MAIN-A"
    with pytest.raises(validator.CandidateInvalid) as exc:
        validator.check_no_test_fixtures(broken)
    assert "test fixtures" in str(exc.value)


def test_m6c119_no_test_registry_is_declared_as_a_source(candidate):
    """正式 registry 只能"替代"测试档，绝不能以测试档为来源。"""
    registries = candidate["profile_registries"]["registries"]
    assert len(registries) == 6
    for registry in registries:
        assert registry["name"].startswith("FORMAL_")
        fields = registry["fields"]
        for field in fields:
            assert field["class"] in ("METADATA", "IDENTITY", "WORLD_LAW",
                                      "COSMETIC")
            if field["class"] == "WORLD_LAW":
                assert field["state"] == "BLOCKED"
                assert field["owner_decision_id"].startswith("OD-")
    assert candidate["profile_registries"]["fallback_policy"].startswith(
        "PRODUCTION_TEST_PROFILE_FALLBACK = FORBIDDEN")


# ---------------------------------------------------------------- prohibitions
def test_m6c120_no_materializer_vocabulary():
    validator.check_no_materializer(validator.load_candidate())
    for rel in ("services/activation/bootstrap_canon.py",
                "scripts/build_snapshot_candidate.py",
                "docs/world_creation/SNAPSHOT_V1_CANDIDATE.md"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        for token in ("INSERT INTO", "session.commit", "create_initial_state",
                      "bootstrap_world", "materialize_world"):
            assert token not in src, f"{rel}: {token}"


def test_m6c121_rule_module_has_no_db_or_engine_capability():
    validator.check_no_production_mutation(validator.load_candidate())
    source = validator.RULE_MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "no relative imports in the rule module"
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"__future__", "hashlib", "json", "fractions", "typing"}, imported
    assert not any("database" in name or "sqlalchemy" in name
                   or "services" in name for name in imported)


def test_m6c122_production_mutation_capability_is_detected(tmp_path):
    fake = tmp_path / "fake_module.py"
    fake.write_text("import sqlalchemy\n", encoding="utf-8")
    original = validator.RULE_MODULE_PATH
    try:
        validator.RULE_MODULE_PATH = fake
        with pytest.raises(validator.CandidateInvalid) as exc:
            validator.check_no_production_mutation({})
        assert "sqlalchemy" in str(exc.value)
    finally:
        validator.RULE_MODULE_PATH = original


def test_m6c123_candidate_contains_no_sql_or_write_calls(candidate):
    text = json.dumps(candidate, ensure_ascii=False).upper()
    for token in ("INSERT INTO", "UPDATE ", "DELETE FROM", "COMMIT("):
        assert token not in text, token

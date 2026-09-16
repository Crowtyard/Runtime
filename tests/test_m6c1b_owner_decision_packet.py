"""M6C.1B — Owner Decision Packet 结构守卫（owner §7-§11、§23、§24、§27）。

纯静态 + 内存：不连数据库、不读 World Seed、不写任何文件。
"""
from __future__ import annotations

import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKET_JSON = ROOT / "docs/world_creation/M6C1B_OWNER_DECISION_PACKET.json"
PACKET_MD = ROOT / "docs/world_creation/M6C1B_OWNER_DECISION_PACKET.md"
ENGINES = ROOT / "services" / "simulation"

ALLOWED_OD_KEYS = {
    "ID", "NAME", "WHY_BLOCKING", "FROZEN_CONSUMER", "SCHEMA_FIELDS", "UNIT",
    "EXISTING_APPROVED_CONSTRAINTS", "CANDIDATES",
    "RECOMMENDED_NEUTRAL_CANDIDATE", "OWNER_MUST_CHOOSE",
}
ALLOWED_SOURCES = ("LOCAL_CANON", "APPROVED_LOCAL_DESIGN",
                   "OWNER_ALREADY_APPROVED_FACTS",
                   "FROZEN_ENGINE_NEUTRAL_CONSTRAINT",
                   "DETERMINISTIC_DERIVATION_FROM_APPROVED_FACTS", "OWNER")
ALLOWED_S_STATUS = ("ALREADY_OWNER_APPROVED", "DERIVABLE", "BLOCKED_BY_OD_",
                    "NON_BLOCKING_NO_ENGINE_REPRESENTATION")


@pytest.fixture(scope="module")
def packet() -> dict:
    return json.loads(PACKET_JSON.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ structure
def test_m6c1b20_packet_header_and_flags(packet):
    assert packet["artifact"] == "M6C1B_OWNER_DECISION_PACKET"
    assert packet["STATUS"] == "AWAITING_OWNER_DECISIONS"
    assert packet["SNAPSHOT_V1_CANDIDATE"] == "ACCEPTED_AS_CANDIDATE"
    assert packet["SNAPSHOT_V1"] == "NOT_APPROVED"
    assert packet["MATERIALIZER_ALLOWED"] is False
    assert packet["FORMAL_ACTIVATION_ALLOWED"] is False
    assert packet["FORMAL_WORLD_SEED_CONSUMED"] is False
    assert packet["NEXT_ACTION"] == "AWAIT_OWNER_FINAL_BOOTSTRAP_DECISIONS"


def test_m6c1b21_at_most_ten_decisions(packet):
    decisions = packet["owner_decisions"]
    assert len(decisions) <= 10
    assert len(decisions) == packet["OWNER_DECISION_COUNT"] == 9
    assert [d["ID"] for d in decisions] == [f"OD-{i}" for i in range(1, 10)]


def test_m6c1b22_every_decision_uses_the_owner_format(packet):
    for decision in packet["owner_decisions"]:
        missing = [k for k in ALLOWED_OD_KEYS if k not in decision]
        assert missing == [], (decision["ID"], missing)
        for key in ("WHY_BLOCKING", "FROZEN_CONSUMER", "SCHEMA_FIELDS", "UNIT",
                    "RECOMMENDED_NEUTRAL_CANDIDATE", "OWNER_MUST_CHOOSE"):
            assert decision[key], (decision["ID"], key)
        assert decision["EXISTING_APPROVED_CONSTRAINTS"], decision["ID"]
        choices = decision["OWNER_MUST_CHOOSE"]
        assert "CUSTOM" in choices and "A" in choices and "B" in choices


def test_m6c1b23_at_most_three_candidates_each_with_required_fields(packet):
    for decision in packet["owner_decisions"]:
        candidates = decision["CANDIDATES"]
        assert 1 <= len(candidates) <= 3, decision["ID"]
        labels = [c["LABEL"] for c in candidates]
        assert labels == list("ABC")[:len(candidates)], decision["ID"]
        for candidate in candidates:
            for key in ("LABEL", "VALUE", "SOURCE", "LONG_TERM_EFFECT"):
                assert candidate.get(key), (decision["ID"], candidate["LABEL"], key)


def test_m6c1b24_candidate_sources_are_restricted(packet):
    for decision in packet["owner_decisions"]:
        for candidate in decision["CANDIDATES"]:
            source = candidate["SOURCE"]
            assert any(token in source for token in ALLOWED_SOURCES), source
            for forbidden in ("TEST_PROFILE", "TEST-SPECIES", "TEST_FIXTURE",
                              "synthetic", "常识", "猜测", "mini_world"):
                assert forbidden not in source, (decision["ID"], forbidden)
                assert forbidden not in candidate["VALUE"], (decision["ID"], forbidden)


# ------------------------------------------------------------------ rulings
def test_m6c1b25_rule_status_matches_owner_rulings(packet):
    rules = packet["rule_status_from_owner"]
    assert rules["RA-ALLOC-001"]["status"] == "APPROVED_BOOTSTRAP_DERIVATION"
    for requirement in ("integer-only", "no RNG", "deterministic",
                        "fixed tie-break", "exact row marginals",
                        "exact column marginals", "independently reproducible"):
        assert requirement in rules["RA-ALLOC-001"]["requirements"]
    trib = rules["RA-TRIB-001"]
    assert trib["status"] == "APPROVED_BOOTSTRAP_DERIVATION"
    assert trib["FIRST_OMEN_BLESSED_YEAR"] == 10
    assert trib["FIRST_OMEN_TICK"] == 10_000_000
    assert "pre-T lead period" in trib["basis"]
    assert rules["RA-COHORT-001"]["status"] == "CANDIDATE_ONLY"
    assert rules["RA-MORTALITY-001"]["status"] == "PENDING_OWNER_DECISION"
    assert rules["RA-STRUCT-001"]["status"] == \
        "CANDIDATE_ONLY_PENDING_EXPLICIT_REVIEW"


def test_m6c1b26_resolved_decisions_are_not_re_asked(packet):
    resolved = packet["resolved_not_owner_decisions"]
    assert resolved["PRODUCTION_TEST_PROFILE_FALLBACK"] == "FORBIDDEN"
    assert resolved["FORMAL_PROFILE_MISSING_BEHAVIOR"] == "FAIL_CLOSED"
    assert resolved["OCCUPATION_BOOTSTRAP_OWNER_DECISION"] == "NOT_REQUIRED"
    assert resolved["HOUSEHOLD_BOOTSTRAP_OWNER_DECISION"] == "NOT_REQUIRED"
    for decision in packet["owner_decisions"]:
        assert "FALLBACK" not in decision["NAME"]
        assert "FALLBACK" not in decision["WHY_BLOCKING"]
    # 周期与首个前兆不得被重新请求
    for decision in packet["owner_decisions"]:
        assert "REGULAR" not in decision["WHY_BLOCKING"].upper() or \
            "不在此列" in decision["WHY_BLOCKING"] or \
            "不在本项" in decision["WHY_BLOCKING"]


# ------------------------------------------------------------------ neutral
def test_m6c1b27_technical_neutral_classification(packet):
    neutral = packet["neutral_reclassification"]
    technical = neutral["TECHNICAL_NEUTRAL"]
    assert neutral["TECHNICAL_NEUTRAL_COUNT"] == len(technical) == 3
    for entry in technical:
        assert entry["ENGINE_READ_COUNT"] == 0
        assert entry["AUTO_ACK_ELIGIBLE"] is True
        assert entry["WHY_NON_DYNAMIC"]
    fields = {e["FIELD"] for e in technical}
    assert fields == {"settlements.state", "settlements.region_ref",
                      "settlements.settlement_type"}


def test_m6c1b28_dynamic_neutral_classification(packet):
    neutral = packet["neutral_reclassification"]
    dynamic = neutral["DYNAMIC_NEUTRAL"]
    assert neutral["DYNAMIC_NEUTRAL_COUNT"] == len(dynamic) == 6
    for entry in dynamic:
        assert entry["OWNER_DECISION_ID"].startswith("OD-9")
        assert entry["ENGINE_CONSUMER"]
        assert entry["FAMILY"]
    traps = [e for e in dynamic if e.get("TRAP")]
    assert len(traps) == 2, [e["FAMILY"] for e in traps]


def test_m6c1b29_engine_never_reads_state_or_region_ref_from_settlements_rows():
    """§8 静态扫描：冻结引擎消费 settlements 行时**不得**读取
    state / region_ref / settlement_type（这三个键属于技术中性声明）。"""
    import re
    keys: set[str] = set()
    for path in sorted(ENGINES.glob("*.py")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if 'rows("settlements")' not in line:
                continue
            window = "\n".join(lines[i:i + 3])
            keys.update(re.findall(r'\["([a-z_]+)"\]', window))
            keys.update(re.findall(r'\.get\("([a-z_]+)"', window))
    # 已知窗口命中集合（含来自邻行的 population_groups 键）；任何漂移都会失败
    assert keys == {"working_name", "population_capacity", "species"}, sorted(keys)
    for field in ("state", "region_ref", "settlement_type"):
        assert field not in keys, field


def test_m6c1b29b_region_ref_reads_are_only_node_zone_and_tribulation():
    """region_ref 的引擎读取点必须与候选记录的 EVIDENCE 逐字一致（且均非 settlements）。"""
    hits = []
    for path in sorted(ENGINES.glob("*.py")):
        if path.name in ("snapshot.py", "state_hash.py", "mini_world.py",
                         "harness.py", "feedback.py", "contracts.py"):
            continue
        for i, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1):
            if "region_ref" in line:
                hits.append(f"{path.name}:{i}")
    assert hits == ["ecology.py:210", "resource.py:132", "resource.py:151",
                    "resource.py:152", "resource.py:168", "tribulation.py:553",
                    "tribulation.py:560", "tribulation.py:634",
                    "tribulation.py:648"], hits


def test_m6c1b30_cited_engine_evidence_lines_exist(packet):
    for entry in packet["neutral_reclassification"]["TECHNICAL_NEUTRAL"]:
        for citation in entry["EVIDENCE"].split(";"):
            citation = citation.strip()
            if ":" not in citation:
                continue
            name, _, spec = citation.partition(":")
            if "," in name:
                continue
            path = ENGINES / f"{name}.py"
            if not path.exists():
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
            for part in spec.split(","):
                part = part.strip()
                if not part.isdigit():
                    continue
                assert 1 <= int(part) <= len(lines), citation


# ------------------------------------------------------------------ S-1..S-10
def test_m6c1b31_s1_s10_complete_and_tracked(packet):
    mapping = packet["s1_s10_mapping"]
    assert [m["ID"] for m in mapping] == [f"S-{i}" for i in range(1, 11)]
    od_ids = {d["ID"] for d in packet["owner_decisions"]}
    for item in mapping:
        status = item["status"]
        assert any(status.startswith(s) for s in ALLOWED_S_STATUS), status
        if status.startswith("BLOCKED_BY_OD_"):
            assert status.replace("BLOCKED_BY_OD_", "OD-") in od_ids, status
        assert item["detail"]
    assert packet["S1_S10_UNTRACKED_BLOCKERS"] == 0
    non_blocking = {m["ID"] for m in mapping
                    if m["status"] == "NON_BLOCKING_NO_ENGINE_REPRESENTATION"}
    assert non_blocking == {"S-6", "S-8"}
    registry = {u["ID"] for u in packet["non_blocking_registry"]}
    assert {"U-1", "U-2", "U-3", "U-4"} <= registry


# ------------------------------------------------------------------ authority
def test_m6c1b32_authority_result_recorded(packet):
    authority = packet["authority"]
    assert authority["AUTHORITATIVE_DB_RESOLUTION"] == "PASS"
    assert authority["LEGACY_DB_DETECTED"] is True
    assert authority["LEGACY_DB_CLASSIFICATION"] == \
        "LEGACY_STALE_NON_AUTHORITATIVE_DB"
    assert authority["LEGACY_DB_PRESERVED"] is True
    assert authority["LEGACY_DB_AUTHORITATIVE"] is False
    assert authority["STALE_DB_FALSE_POSITIVE"] == 0
    assert authority["AMBIGUOUS_DB_FAIL_CLOSED"] == "PASS"
    assert authority["HARDCODED_PATH_FINDINGS_WITH_DB_CAPABILITY"] == 0


# ------------------------------------------------------------------ md parity
def test_m6c1b33_markdown_and_json_agree(packet):
    md = PACKET_MD.read_text(encoding="utf-8")
    assert "OWNER_DECISION_COUNT       = 9" in md
    for decision in packet["owner_decisions"]:
        assert decision["ID"] in md, decision["ID"]
        assert decision["NAME"].split("（")[0][:12] in md, decision["ID"]
    for key, value in packet["rule_status_from_owner"].items():
        assert key in md, key
        assert value["status"] in md, (key, value["status"])

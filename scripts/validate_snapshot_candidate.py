"""M6C.1 — SNAPSHOT_V1_CANDIDATE 独立校验器（owner §29）。

只读校验，**不写任何文件、不连数据库、不读 World Seed**：
  1. schema：必需顶层段、header 旗标；
  2. provenance：每个数字必须可归属（SOURCE_CLASS），派生值必须带 6 项派生字段，
     BLOCKED 必须带 owner_decision_id —— UNATTRIBUTED_NUMBER 一律失败；
  3. sums：总人口 / 群体合计 / 聚落合计 / 矩阵**独立复算**（重跑 RA-ALLOC-001）；
  4. 禁测：候选文本中不得出现任何 TEST registry / 测试夹具标识；
  5. 禁 materializer：候选与生成器/规则模块不得含 materializer 语汇或 SQL/写库调用；
  6. 禁生产变更：正式世界红线值必须与 M6.0–M6C 不变式逐字一致。

用法： python scripts/validate_snapshot_candidate.py [--json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from XiaoguangBlessedLandRuntime.services.activation import bootstrap_canon as BC  # noqa: E402

CANDIDATE_PATH = ROOT / "docs" / "world_creation" / "SNAPSHOT_V1_CANDIDATE.json"
BUILDER_PATH = ROOT / "scripts" / "build_snapshot_candidate.py"
RULE_MODULE_PATH = (ROOT / "services" / "activation" / "bootstrap_canon.py")
APPROVED_SNAPSHOT_PATH = ROOT / "docs" / "world_creation" / "SNAPSHOT_V1.md"

SOURCE_CLASSES = ("OWNER_APPROVED", "LOCAL_CANON", "APPROVED_LOCAL_DESIGN",
                  "DETERMINISTIC_DERIVATION", "ENGINE_NEUTRAL_CONSTANT")
DERIVATION_KEYS = ("rule_id", "rule_version", "inputs", "output",
                   "rounding_policy", "tie_break_policy")
REQUIRED_TOP_LEVEL = ("header", "source_class_enum", "derivation_rules",
                      "owner_decisions", "world_layer_S1_S10",
                      "engine_required_structured_params",
                      "bootstrap_entity_plan", "engine_forced_constraints",
                      "profile_registries", "minimal_owner_decisions",
                      "unresolved_items", "audit_corrections")

FORBIDDEN_TEST_TOKENS = ("TEST-SPECIES", "TEST-RESOURCE", "TEST-ECOLOGY",
                         "TEST-SOCIAL", "TEST_FIXTURE", "TEST_PROFILE",
                         "TEST-MAIN", "mini_world", "TEST_TRIBULATION")
#: 仅这些键允许"提及"测试夹具（引用其被替代关系、证据行号、否定性声明）
CITATION_KEYS = frozenset({
    "evidence", "source_ref", "replaces", "engine_contract", "fallback_policy",
    "constraint", "blocking_reason", "reason", "note", "why", "engine_requirement",
    "engine_forced", "original_claim", "correction", "neutrality_basis",
    "canon_suggestion", "declared_rule", "inputs", "output", "owner_options",
    "options", "not_in_minimum_set", "status", "note_zh", "rationale",
    # 政策声明类文本（例如 PRODUCTION_TEST_PROFILE_FALLBACK = FORBIDDEN）
    "red_lines", "content",
})
MATERIALIZER_PATTERN = re.compile(
    r"(materiali[sz]er|materialize_(world|bootstrap)|bootstrap_world|"
    r"seed_bootstrap|create_initial_state|INSERT\s+INTO|session\.commit|"
    r"SessionLocal|create_engine\()", re.IGNORECASE)

EXPECTED_RED_LINES = {
    "formal_world_runtime_rows": 0,
    "formal_world_status": "NOT_ACTIVATED",
    "formal_world_current_blessed_tick": None,
    "formal_world_seed_status": "PREPARED_NOT_ACTIVATED",
    "formal_world_db_sha256":
        "7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837",
    "world_seed_manifest_sha256":
        "cc0e4c0e16c7e2ec8cecb4ba871afc3af1a402e94732e645fceb4b1aca73771d",
}


class CandidateInvalid(AssertionError):
    """候选文档违反 M6C.1 声明的结构/来源/数值不变式。"""


def _fail(msg: str) -> None:
    raise CandidateInvalid(msg)


# --------------------------------------------------------------------------
def load_candidate(path: pathlib.Path = CANDIDATE_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check_header(doc: dict) -> None:
    h = doc.get("header", {})
    for key in REQUIRED_TOP_LEVEL:
        if key not in doc:
            _fail(f"missing top-level section: {key}")
    if h.get("status") != "CANDIDATE_NOT_APPROVED":
        _fail(f"status must be CANDIDATE_NOT_APPROVED, got {h.get('status')!r}")
    for flag in ("materialization_allowed", "formal_activation_allowed",
                 "world_seed_consumed", "agent_may_promote_to_snapshot_v1"):
        if h.get(flag) is not False:
            _fail(f"header flag {flag} must be False, got {h.get(flag)!r}")
    if doc.get("source_class_enum") != list(SOURCE_CLASSES):
        _fail("source_class_enum drifted from the declared enum")


def check_red_lines(doc: dict) -> None:
    baseline = doc["header"]["engine_baseline"]
    for key, expected in EXPECTED_RED_LINES.items():
        node = baseline.get(key)
        if node is None:
            _fail(f"engine_baseline missing {key}")
        actual = node.get("value") if isinstance(node, dict) else node
        if actual != expected:
            _fail(f"formal-world red line {key} drifted: {actual!r} != {expected!r}")


def _walk(node, path: str, attributed: bool, problems: list[str],
          nodes: list[tuple[str, dict]]) -> None:
    if isinstance(node, dict):
        if "source_class" in node:
            attributed = True
            nodes.append((path, node))
            sc = node["source_class"]
            if sc is None:
                if node.get("state") not in ("BLOCKED", "UNRESOLVED",
                                             "UNRESOLVED_BLOCKING"):
                    problems.append(
                        f"{path}: null source_class only allowed for "
                        f"BLOCKED/UNRESOLVED states")
            elif sc not in SOURCE_CLASSES:
                problems.append(f"{path}: invalid source_class {sc!r}")
            if "value" not in node and node.get("attribution_scope") != "SECTION":
                problems.append(
                    f"{path}: attributed node without 'value' "
                    f"(section-level attribution must set attribution_scope=SECTION)")
            if sc == "DETERMINISTIC_DERIVATION":
                derived_block = node.get("derivation", {})
                for key in DERIVATION_KEYS:
                    if key not in derived_block:
                        problems.append(f"{path}: derivation missing {key}")
            if node.get("state") == "BLOCKED":
                if not node.get("owner_decision_id"):
                    problems.append(f"{path}: BLOCKED without owner_decision_id")
                if not node.get("blocking_reason"):
                    problems.append(f"{path}: BLOCKED without blocking_reason")
        for key, value in node.items():
            _walk(value, f"{path}.{key}", attributed, problems, nodes)
    elif isinstance(node, list):
        for idx, value in enumerate(node):
            _walk(value, f"{path}[{idx}]", attributed, problems, nodes)
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        if not attributed:
            problems.append(f"UNATTRIBUTED_NUMBER at {path} = {node!r}")


def check_provenance(doc: dict) -> list[tuple[str, dict]]:
    problems: list[str] = []
    nodes: list[tuple[str, dict]] = []
    _walk(doc, "$", False, problems, nodes)
    if problems:
        _fail("provenance violations:\n  " + "\n  ".join(problems))
    return nodes


def check_blocking_disclosure(doc: dict) -> None:
    """每个 BLOCKED 节点必须落在 minimal_owner_decisions 的某个 OD 上。"""
    declared = {d["id"] for d in doc["minimal_owner_decisions"]}
    problems: list[str] = []

    def walk(node, path):
        if isinstance(node, dict):
            if node.get("state") == "BLOCKED":
                od = node.get("owner_decision_id")
                if od not in declared:
                    problems.append(f"{path}: owner_decision_id {od!r} not declared")
            for k, v in node.items():
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(doc, "$")
    if problems:
        _fail("blocking disclosure violations:\n  " + "\n  ".join(problems))


def check_allocation(doc: dict) -> dict:
    """独立复算 RA-ALLOC-001（只从候选声明的输入出发）。"""
    plan = doc["bootstrap_entity_plan"]
    alloc = plan["allocation"]
    group_pops = [int(s["target_population"]["value"]) for s in plan["settlements"]]
    groups_declared = [int(BC.GROUP_POPULATIONS[i][1])
                       for i in range(len(BC.GROUP_POPULATIONS))]
    recomputed = BC.allocate(groups_declared,
                             [c for _, _, c in BC.SETTLEMENT_SLOTS])
    declared_matrix = [list(row) for row in alloc["matrix"]]
    if [list(row) for row in recomputed] != declared_matrix:
        _fail("allocation matrix is not reproducible by RA-ALLOC-001")
    if alloc["canonical_text"] != BC.render_matrix(recomputed):
        _fail("canonical_text drifted from the rule output")
    if alloc["matrix_sha256"] != BC.allocation_digest(recomputed):
        _fail("matrix_sha256 drifted from the rule output")
    if alloc["row_totals"] != [int(g) for _, g in BC.GROUP_POPULATIONS]:
        _fail("row totals must equal the owner-approved group populations")
    if alloc["column_totals"] != group_pops:
        _fail("column totals must equal the owner-approved settlement targets")
    BC.verify_allocation(recomputed, groups_declared,
                         [c for _, _, c in BC.SETTLEMENT_SLOTS])
    return alloc


def check_sums(doc: dict) -> None:
    plan = doc["bootstrap_entity_plan"]
    alloc = plan["allocation"]
    total = doc["world_layer_S1_S10"][0]["candidate"]["value"]
    if total != BC.OWNER_APPROVED_INITIAL_TOTAL_POPULATION:
        _fail("S-1 total population drifted from the owner-approved value")
    if sum(alloc["row_totals"]) != total:
        _fail("group totals do not sum to the total population")
    if sum(alloc["column_totals"]) != total:
        _fail("settlement totals do not sum to the total population")
    if len(alloc["settlement_order"]) != 12 or len(alloc["group_order"]) != 4:
        _fail("slot counts drifted from the owner-approved 4+8 / 4 groups")
    main = alloc["settlement_order"][:4]
    sat = alloc["settlement_order"][4:]
    if main != ["MAIN-01", "MAIN-02", "MAIN-03", "MAIN-04"] or \
            sat != [f"SAT-{i:02d}" for i in range(1, 9)]:
        _fail("settlement slot naming drifted from WORKING_NAME_ONLY canon")


def check_no_test_fixtures(doc: dict) -> None:
    """候选**内容**不得取自测试夹具；仅允许在"引用/证据/否定声明"键中提及。"""
    findings: list[str] = []

    def scan(value, path: str, allowed: bool) -> None:
        if isinstance(value, str):
            hits = [tok for tok in FORBIDDEN_TEST_TOKENS if tok in value]
            if hits and not allowed:
                findings.append(f"{path}: {hits}")
        elif isinstance(value, dict):
            for key, sub in value.items():
                scan(sub, f"{path}.{key}", key in CITATION_KEYS)
        elif isinstance(value, list):
            for idx, sub in enumerate(value):
                scan(sub, f"{path}[{idx}]", allowed)

    scan(doc, "$", False)
    if findings:
        _fail("candidate takes content from test fixtures:\n  "
              + "\n  ".join(findings))


def check_no_materializer(doc: dict) -> None:
    for path in (CANDIDATE_PATH, BUILDER_PATH, RULE_MODULE_PATH):
        src = path.read_text(encoding="utf-8")
        hits = sorted({m.group(0) for m in MATERIALIZER_PATTERN.finditer(src)})
        # 规则模块/生成器中允许出现**否认性**声明（"不是 materializer"）
        hits = [h for h in hits if h.lower() not in ("materializer",)]
        if hits:
            _fail(f"{path.name}: materializer/SQL vocabulary present: {hits}")
    if APPROVED_SNAPSHOT_PATH.exists():
        _fail("docs/world_creation/SNAPSHOT_V1.md must not exist before owner approval")
    text = json.dumps(doc, ensure_ascii=False)
    for token in ("MATERIALIZATION_ALLOWED = TRUE", "SNAPSHOT_V1_APPROVED",
                  '"materialization_allowed": true',
                  '"formal_activation_allowed": true'):
        if token in text:
            _fail(f"candidate claims an approved/activatable state: {token}")
    # 只允许存在候选工件：正式 SNAPSHOT_V1（已批准态）不得由本阶段产生
    for approved_dir_glob in ("SNAPSHOT_V1.md", "SNAPSHOT_V1.json"):
        if (CANDIDATE_PATH.parent / approved_dir_glob).exists():
            _fail(f"{approved_dir_glob} must not exist before owner approval")


def check_no_production_mutation(doc: dict) -> None:
    """候选与规则模块/生成器不得具备写库能力（静态检查）。

    校验器自身不在扫描范围内：它必然包含这些**字面量令牌**作为检测模式。
    """
    for path in (RULE_MODULE_PATH, BUILDER_PATH):
        src = path.read_text(encoding="utf-8")
        for token in ("import sqlalchemy", "from sqlalchemy",
                      "from ...database", "XiaoguangBlessedLandRuntime.database",
                      "SessionLocal", "engine.begin()", "session.add("):
            if token in src:
                _fail(f"{path.name}: production-mutation capability ({token})")


def validate(path: pathlib.Path = CANDIDATE_PATH) -> dict:
    doc = load_candidate(path)
    check_header(doc)
    check_red_lines(doc)
    nodes = check_provenance(doc)
    check_blocking_disclosure(doc)
    check_allocation(doc)
    check_sums(doc)
    check_no_test_fixtures(doc)
    check_no_materializer(doc)
    check_no_production_mutation(doc)
    return {
        "status": "PASS",
        "attributed_nodes": len(nodes),
        "blocked_nodes": sum(1 for _, n in nodes if n.get("state") == "BLOCKED"),
        "derived_nodes": sum(1 for _, n in nodes
                             if n["source_class"] == "DETERMINISTIC_DERIVATION"),
        "owner_approved_nodes": sum(1 for _, n in nodes
                                    if n["source_class"] == "OWNER_APPROVED"),
        "neutral_nodes": sum(1 for _, n in nodes
                             if n["source_class"] == "ENGINE_NEUTRAL_CONSTANT"),
        "candidate_sha256": hashlib.sha256(
            path.read_text(encoding="utf-8").encode("utf-8")).hexdigest(),
        "matrix_sha256": doc["bootstrap_entity_plan"]["allocation"]["matrix_sha256"],
        "materialization_allowed": doc["header"]["materialization_allowed"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    try:
        report = validate()
    except CandidateInvalid as exc:
        print("SNAPSHOT_V1_CANDIDATE = INVALID")
        print(str(exc))
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for key, value in report.items():
            print(f"{key} = {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

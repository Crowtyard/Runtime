"""M6C.1 — 生成 SNAPSHOT_V1_CANDIDATE.json（BOOTSTRAP CONFIGURATION 候选 · 只读派生）。

本脚本**不是** materializer：
  * 不连接任何数据库、不读 World Seed、不读正式库、不写任何世界行；
  * 只把"主人已批准的输入 + 冻结引擎的完整性要求"展开为**候选文档**；
  * 每个数字都带 SOURCE_CLASS 与来源；无来源者标 BLOCKED（owner §26：存在
    REQUIRED root 的 blocking field → 停止，禁止进入 materializer）。

用法： python scripts/build_snapshot_candidate.py [--check]
       --check 只校验已落盘 JSON 与本次生成结果逐字节一致（不写文件）。
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from XiaoguangBlessedLandRuntime.services.activation import bootstrap_canon as BC  # noqa: E402

CANDIDATE_PATH = ROOT / "docs" / "world_creation" / "SNAPSHOT_V1_CANDIDATE.json"

TICKS_PER_BLESSED_YEAR = 1_000_000

# ==========================================================================
# 来源节点构造器（owner §22/§23：每个数字必须可归属）
# ==========================================================================
def owner(value, ref):
    return {"value": value, "source_class": "OWNER_APPROVED",
            "state": "APPROVED_BY_OWNER", "source_ref": ref}


def neutral(value, basis, ref="frozen engine scale/default"):
    return {"value": value, "source_class": "ENGINE_NEUTRAL_CONSTANT",
            "state": "NEUTRAL_REQUIRES_OWNER_ACK", "neutrality_basis": basis,
            "source_ref": ref}


def derived(value, rule_id, rule_version, inputs, output, rounding, tie_break):
    return {"value": value, "source_class": "DETERMINISTIC_DERIVATION",
            "state": "DERIVED", "derivation": {
                "rule_id": rule_id, "rule_version": rule_version,
                "inputs": inputs, "output": output,
                "rounding_policy": rounding, "tie_break_policy": tie_break}}


def blocked(decision_id, reason, evidence, options=None):
    node = {"value": None, "source_class": None, "state": "BLOCKED",
            "owner_decision_id": decision_id, "blocking_reason": reason,
            "evidence": evidence}
    if options:
        node["owner_options"] = options
    return node


def unresolved(item_id, reason, evidence, blocking=False):
    return {"value": None, "source_class": None,
            "state": "UNRESOLVED" if not blocking else "UNRESOLVED_BLOCKING",
            "unresolved_id": item_id, "reason": reason, "evidence": evidence}


def formal(value, ref):
    """已落地的正式 canon（LOCAL_CANON，非本次 owner 直接指令）。"""
    return {"value": value, "source_class": "LOCAL_CANON",
            "state": "APPROVED_LOCAL_CANON", "source_ref": ref}


# ==========================================================================
# 主体
# ==========================================================================
def build() -> dict:
    alloc = BC.allocation_section()
    periods = dict(BC.OWNER_APPROVED_TRIBULATION_PERIODS)
    first_omen_tick = min(periods.values()) * TICKS_PER_BLESSED_YEAR
    first_omen_by_tier = {tier: p * TICKS_PER_BLESSED_YEAR
                          for tier, p in BC.OWNER_APPROVED_TRIBULATION_PERIODS}

    settlements = []
    for slot, kind, cap in BC.SETTLEMENT_SLOTS:
        settlements.append({
            "settlement_slot": slot,
            "settlement_type": kind,
            "working_name": {"value": f"{slot}-WORKING", "source_class": "LOCAL_CANON",
                             "state": "WORKING_NAME_ONLY",
                             "source_ref": "owner §12 WORKING_NAME_ONLY（非最终世界内名称；"
                                           "改名不得重建聚落 identity）"},
            "target_population": owner(cap, "M6C.1 owner：每聚落人口"),
            "population_capacity": blocked(
                "OD-4",
                "population_capacity 是世界法则（出生 logistics 收缩）；"
                "若设为 == 初始人口 → room=0 → 出生恒为 0（人口冻结陷阱）；"
                "NULL = 引擎中性（无容量约束，factor=1）。",
                "population.py:187-189,329-332",
                ["(a) NULL = 无容量法则（引擎中性）",
                 "(b) 按聚落类型的容量数值（须 > 初始人口，否则人口永久冻结）"]),
            "region_ref": {"value": None, "source_class": "ENGINE_NEUTRAL_CONSTANT",
                           "state": "NEUTRAL_REQUIRES_OWNER_ACK",
                           "neutrality_basis": "REGION_REF_NULL_EVERYWHERE："
                                               "生态区/聚落/资源节点 region_ref 全为 NULL，"
                                               "不创建 ecological_regions 行（该表无业务键，"
                                               "见 UNRESOLVED U-3）",
                           "source_ref": "ecology.py:210; models_world.py:478-490"},
            "state": {"value": "ACTIVE", "source_class": "ENGINE_NEUTRAL_CONSTANT",
                      "state": "NEUTRAL_REQUIRES_OWNER_ACK",
                      "neutrality_basis": "无引擎读取 settlements.state；"
                                          "ACTIVE 为中性初始态",
                      "source_ref": "models_world.py:26"},
        })

    doc = {
        "header": {
            "artifact": "SNAPSHOT_V1_CANDIDATE",
            "status": "CANDIDATE_NOT_APPROVED",
            "materialization_allowed": False,
            "formal_activation_allowed": False,
            "world_seed_consumed": False,
            "agent_may_promote_to_snapshot_v1": False,
            "produced_by": "M6C.1 SNAPSHOT_V1 CANDIDATE CONSTRUCTION",
            "rule_set_version": {
                BC.RULE_ALLOC_ID: BC.RULE_ALLOC_VERSION,
                BC.RULE_COHORT_ID: BC.RULE_COHORT_VERSION,
            },
            "engine_baseline": {
                "runtime_commit": "1eb8472adc9e895a87dac15ad74fa4fae2670a39",
                "alembic_head": "a9d4f2b7c1e8",
                "formal_world_runtime_rows": owner(0, "M6.0–M6C 不变式"),
                "formal_world_status": owner("NOT_ACTIVATED", "M6.0–M6C 不变式"),
                "formal_world_current_blessed_tick": owner(None, "M6.0–M6C 不变式"),
                "formal_world_seed_status": owner("PREPARED_NOT_ACTIVATED",
                                                  "M6.0–M6C 不变式"),
                "formal_world_db_sha256":
                    "7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837",
                "world_seed_manifest_sha256":
                    "cc0e4c0e16c7e2ec8cecb4ba871afc3af1a402e94732e645fceb4b1aca73771d",
            },
            "red_lines": [
                "不得实现 materializer（owner §26）",
                "不得激活正式世界、不得消费正式 Seed、不得部署 live（owner §28）",
                "不得自行把 SNAPSHOT_V1_CANDIDATE 升级为 SNAPSHOT_V1（owner §25）",
                "PRODUCTION_TEST_PROFILE_FALLBACK = FORBIDDEN（owner 本轮）",
                "不得修改冻结引擎语义（M2/M3）",
            ],
        },
        "source_class_enum": ["OWNER_APPROVED", "LOCAL_CANON",
                              "APPROVED_LOCAL_DESIGN", "DETERMINISTIC_DERIVATION",
                              "ENGINE_NEUTRAL_CONSTANT"],
        "derivation_rules": [
            alloc["rule"],
            BC.cohort_rule_record(),
            {
                "rule_id": "RA-MORTALITY-001", "rule_version": "1.0",
                "inputs": ["owner 指定的年龄带边界（福地年）",
                           "owner 指定的每带年死亡概率（有理数）",
                           "SpeciesDemographyProfile.cohort_buckets"],
                "output": "SpeciesDemographyProfile.mortality_by_bucket（逐 bucket 年死亡概率）",
                "rounding_policy": "NONE_PIECEWISE_CONSTANT_EXPANSION",
                "tie_break_policy": "BAND_BOUNDARY_INCLUSIVE_LOWER_BOUND",
                "status": "DECLARED_AWAITING_OWNER_RATIFICATION（owner §19："
                          "压缩 owner 决策数量；输入仍必须是 owner 数值）",
                "uses_rng": False, "uses_float": False, "uses_hash_of_seed": False,
            },
            {
                "rule_id": "RA-TRIB-001", "rule_version": "1.0",
                "inputs": ["已批准周期 {REGULAR:10, MAJOR:50, CENTENNIAL:100} 福地年",
                           "冻结窗口谓词 tick % (period_years*1e6) == 0",
                           "max-tier tie-break"],
                "output": "首个 omen（PRECURSOR_STARTED）tick 与每 tier 首个窗口",
                "rounding_policy": "EXACT_INTEGER_MULTIPLE",
                "tie_break_policy": "MAX_TIER_REGULAR_LT_MAJOR_LT_CENTENNIAL",
                "uses_rng": False, "uses_float": False,
                "evidence": "tribulation.py:170-177,356,385-388,420-425; "
                            "tests/baselines/m3b_causal_history_300y_v1/"
                            "episode_history_samples.json:8-10",
            },
            {
                "rule_id": "RA-STRUCT-001", "rule_version": "1.0",
                "inputs": ["已启用聚落集合", "冻结引擎完整性要求（fail-closed 行）"],
                "output": "bootstrap 必须提供的行集合基数（zone/state/feedback/pressure 等）",
                "rounding_policy": "EXACT_CARDINALITY",
                "tie_break_policy": "NOT_APPLICABLE",
                "uses_rng": False, "uses_float": False,
                "evidence": "economy.py:164-170,359-362; ecology.py:191-199; "
                            "social.py:568-575; population.py:181-185",
            },
        ],
        "owner_decisions": [
            {"id": "D-A", "title": "SNAPSHOT 流程", "status": "APPROVED",
             "content": "WORLD_CREATION_REVIEW → S-1..S-10 → "
                        "SNAPSHOT_V1_CANDIDATE → OWNER APPROVAL → SNAPSHOT_V1 → "
                        "Materializer → Activation"},
            {"id": "D-B1", "title": "canon 冲突 S-3", "status": "APPROVED",
             "content": "WS-0406 胜出；旧 S-3（2~6 聚落）标记 "
                        "SUPERSEDED_FOR_FORMAL_BOOTSTRAP（保留历史记录）"},
            {"id": "D-B2", "title": "初始聚落数", "status": "APPROVED",
             "content": "INITIAL_SETTLEMENT_COUNT = 12 = MAIN 4 + SATELLITE 8"},
            {"id": "D-B3", "title": "工作名", "status": "APPROVED",
             "content": "MAIN-01..04 / SAT-01..08 = WORKING_NAME_ONLY"},
            {"id": "D-B4", "title": "初始总人口", "status": "APPROVED",
             "content": "INITIAL_TOTAL_POPULATION = 12000（设计基线升级为 bootstrap canon）"},
            {"id": "D-B5", "title": "群体名额", "status": "APPROVED",
             "content": "GROUP_1..4 = 4000/3000/2500/2500（沿用既有 group 槽位，不重命名）"},
            {"id": "D-B6", "title": "每聚落人口", "status": "APPROVED",
             "content": "MAIN 2000×4 + SATELLITE 500×8 = 12000"},
            {"id": "D-B7", "title": "分配规则", "status": "APPROVED",
             "content": "确定性最大余额；固定顺序 + 固定 tie-break；无 RNG / 无 hash(seed)；"
                        "逐字节相同"},
            {"id": "D-C", "title": "正式 profile registry", "status": "APPROVED",
             "content": "建立六个 FORMAL_*_PROFILE_REGISTRY 作为 BOOTSTRAP CONFIGURATION"
                        "（非 engine law；不改冻结引擎）"},
            {"id": "D-C2", "title": "测试档回落", "status": "APPROVED",
             "content": "PRODUCTION_TEST_PROFILE_FALLBACK = FORBIDDEN："
                        "正式 profile 存在则使用；缺失 = FAIL CLOSED"},
            {"id": "D-D", "title": "确定性派生", "status": "APPROVED_WITH_CONSTRAINTS",
             "content": "允许显式输入/输出、版本化、确定性、可独立复算、记入 SNAPSHOT_V1、"
                        "不得用测试夹具、不得改 M2/M3 语义；禁止随机生成 / 未批准 RNG / "
                        "hash-mod 内容生成"},
            {"id": "D-E", "title": "灾劫周期", "status": "APPROVED",
             "content": "REGULAR=10 / MAJOR=50 / CENTENNIAL=100 福地年"},
            {"id": "D-F", "title": "首个前兆时间", "status": "APPROVED_AS_DERIVED",
             "content": "由冻结引擎派生（见 RA-TRIB-001）；不再作为 owner 选择题"},
        ],
        "world_layer_S1_S10": [
            {"snapshot_id": "S-1", "title": "大致总人口",
             "canon_suggestion": "小型(数百)/中型(数千)/较大(上万)",
             "candidate": owner(12_000, "M6C.1 owner：INITIAL_TOTAL_POPULATION=12000"),
             "status": "APPROVED_BY_OWNER"},
            {"snapshot_id": "S-2", "title": "异人种族组合",
             "canon_suggestion": "OPTION_A/B/C（12 号文档；SVH-003 11 族候选）",
             "candidate": blocked(
                 "OD-1", "species 是 population_groups.species（NOT NULL）且必须命中 "
                         "正式 species profile registry；未知 species → "
                         "DemographyProfileUnconfigured（fail-closed）",
                 "population.py:166-172; models_world.py:36",
                 ["A/B/C 三个 OPTION（12 号文档）", "四族名额已批准但族**身份**未批准"]),
             "status": "BLOCKED"},
            {"snapshot_id": "S-3", "title": "主要聚落数量",
             "canon_suggestion": "核心神社区 + 2~6 聚落（草案）",
             "candidate": owner(12, "M6C.1 owner：WS-0406 胜出（4 主 + 8 卫星）；"
                                   "旧草案 SUPERSEDED_FOR_FORMAL_BOOTSTRAP"),
             "status": "APPROVED_BY_OWNER"},
            {"snapshot_id": "S-4", "title": "主要产业",
             "canon_suggestion": "农业/药园/林产/水产/工坊/贸易（草案骨架）",
             "candidate": blocked(
                 "OD-5", "产业只能由 production_recipes + industries 表达；"
                         "无批准清单 → 不得代填（owner §19 禁止发明产业）",
                 "models_world.py:119-131,223-243",
                 ["批准草案骨架", "改为不设初始产业（配方集合为空 = 合法空转）"]),
             "status": "BLOCKED"},
            {"snapshot_id": "S-5", "title": "主要资源区",
             "canon_suggestion": "灵田/药园/果园/林区/湖区/矿脉（如选石人）",
             "candidate": blocked(
                 "OD-6", "resource_profiles + resource_nodes 无批准集合；"
                         "resource_stocks 必须是完整矩阵，否则经济引擎 KeyError",
                 "economy.py:297-305; resource.py:138-142",
                 ["批准资源清单与 profile 数值", "不设资源（RESOURCE 合法空转）"]),
             "status": "BLOCKED"},
            {"snapshot_id": "S-6", "title": "荒兽/异兽层级",
             "canon_suggestion": "维持 BL-011 语义（豢养异兽）；默认不引入母世界战力映射",
             "candidate": unresolved(
                 "U-1", "冻结引擎无荒兽/异兽实体表或规则（NOT_FOUND）；"
                        "该项只影响叙事层，不阻塞 materialization",
                 "services/simulation/* 无对应字段"),
             "status": "UNRESOLVED"},
            {"snapshot_id": "S-7", "title": "社会组织",
             "canon_suggestion": "神社为管理核心 + 村落自治（草案）",
             "candidate": blocked(
                 "OD-9", "社会派生只用 population 计数 + economic_pressure_state + "
                         "ecology_feedback_state + 自身状态行；组织形态只能由 "
                         "formal SocialProfile 阈值表达（现仅存在于 TEST_SOCIAL_PROFILE）",
                 "social.py:157-200,566-609",
                 ["批准正式社会阈值", "明确「正式世界不使用阈值」（= 不启用社会派生）"]),
             "status": "BLOCKED"},
            {"snapshot_id": "S-8", "title": "基础设施",
             "canon_suggestion": "道路/水渠/仓/集市场地（草案清单）",
             "candidate": unresolved(
                 "U-2", "冻结引擎无基础设施表/字段（NOT_FOUND）；"
                        "若需表达应复用 institutions（SOCIAL 自建）或留待后续阶段",
                 "models_world.py 无 infra 表"),
             "status": "UNRESOLVED"},
            {"snapshot_id": "S-9", "title": "发展水平",
             "canon_suggestion": "「安居传统小社会 + 现代物零星融入」基调",
             "candidate": derived(
                 "不设独立数值：发展水平由 S-4 产业 + S-5 资源 + S-8 基础设施的"
                 "具体集合共同表达（本候选不新增字段）",
                 "RA-STRUCT-001", "1.0", ["S-4/S-5/S-8 的批准结果"],
                 "无独立数值输出（避免发明口径）", "NOT_APPLICABLE", "NOT_APPLICABLE"),
             "status": "DERIVED"},
            {"snapshot_id": "S-10", "title": "灾劫状态",
             "canon_suggestion": "mode=UNDECIDED；默认无活跃灾劫叙事",
             "candidate": {
                 "tick0_active_tribulation_episodes":
                     derived(0, "RA-TRIB-001", "1.0",
                             ["窗口谓词仅在 step END tick 求值；tick 0 无 step"],
                             "tick0 不创建 episode", "NOT_APPLICABLE",
                             "NOT_APPLICABLE"),
                 "first_omen_tick":
                     derived(first_omen_tick, "RA-TRIB-001", "1.0",
                             ["periods", "窗口谓词", "max-tier tie-break"],
                             "首个 PRECURSOR_STARTED tick（= REGULAR 首个窗口）",
                             "EXACT_INTEGER_MULTIPLE", "MAX_TIER"),
                 "first_window_tick_by_tier":
                     derived(first_omen_by_tier, "RA-TRIB-001", "1.0",
                             ["periods"], "每 tier 首个窗口 tick",
                             "EXACT_INTEGER_MULTIPLE", "MAX_TIER"),
                 "pre_window_lead_time": {
                     "value": None, "source_class": "ENGINE_NEUTRAL_CONSTANT",
                     "state": "CONCEPT_ABSENT_IN_FROZEN_ENGINE",
                     "neutrality_basis": "冻结引擎**没有**窗口前导期/预警窗口概念："
                                         "PRECURSOR（omen）阶段**始于**窗口 tick T，"
                                         "entered_tick = T，transition_tick = "
                                         "T + precursor_steps*1e6（向后延伸）",
                     "source_ref": "tribulation.py:385-388; 无 pre-T 偏移列"},
                 "mode": blocked(
                     "OD-10", "S-10 的 mode（UNDECIDED）与正式灾劫 profile 数值未裁决；"
                              "周期已批准，但 profile 的世界法则数值（intensity/risk/"
                              "precursor_steps 等）无来源",
                     "tribulation.py:87-107; docs/m6c_minimal_bootstrap_canon_audit.md:84,345",
                     ["批准正式灾劫 profile（每 tier 一套数值）",
                      "授权建立 FORMAL_TRIBULATION_PROFILE_REGISTRY 并去除 "
                      "profiles or TEST_PROFILES 静默回落（owner §18）"]),
             },
             "status": "BLOCKED"},
        ],
        "engine_required_structured_params": [
            {"id": "D-B1", "title": "人口年龄结构（cohort 划分与占比）",
             "domain": "POPULATION",
             "state": "BLOCKED", "owner_decision_id": "OD-3",
             "engine_requirement":
                 "population_groups 必须覆盖**每一个** bucket 0..N-1（每 "
                 "(species, settlement_ref) 各 N 行）；缺行 = 静默丢人口（违 P_INV_12）；"
                 "同一 bucket 出现两行会**重复计数**",
             "evidence": "population.py:181-185,289-292,339,344-346,402-424; "
                         "mini_world.py:154-155; snapshot.py:257-264",
             "candidate_rule": BC.RULE_COHORT_ID,
             "blocked_inputs": ["正式 species profile 的 cohort_buckets 与 "
                                "mortality_by_bucket"]},
            {"id": "D-B2", "title": "人口每聚落分配（含物种×聚落交叉）",
             "domain": "POPULATION", "state": "DERIVED",
             "rule": BC.RULE_ALLOC_ID,
             "note": "双边际严格精确：行 = 群体人数、列 = 聚落目标人口；"
                     "（一维最大余额无法同时满足主人已批准的两组约束，故规则采用"
                     "两阶段：列内最大余额 + 行边际最小偏离修复）"},
            {"id": "D-B3", "title": "职业组划分与户统计口径",
             "domain": "POPULATION/SOCIAL", "state": "NOT_REQUIRED",
             "note": "M6C.1 更正：occupation_group 全仓**无引擎读取**（WRITE_ONLY；"
                     "只影响 snapshot 排序与 world_state_hash）；household_stats "
                     "**零读零写**且不在 snapshot 投影内。二者**不阻塞** tick=0 "
                     "物化。已批准的“不发明职业结构”原则因此自动满足："
                     "occupation_group 保持 NULL/常量即可",
             "evidence": "snapshot.py:88-91,263-264; state_hash.py:40,66; "
                         "economy.py:133-136,188-211（劳动力 = 聚落总人口，"
                         "与职业无关）"},
            {"id": "D-B4", "title": "四族精确名额", "domain": "POPULATION",
             "state": "APPROVED_BY_OWNER",
             "note": "名额已批准（4000/3000/2500/2500）；**族身份**（species 值）仍缺"
                     " → 与 S-2 合并为同一决策 OD-1"},
            {"id": "D-B5", "title": "启用聚落集合与类型", "domain": "SETTLEMENT",
             "state": "APPROVED_BY_OWNER",
             "note": "12 槽位 + MAIN/SATELLITE 类型 + WORKING_NAME_ONLY 已批准；"
                     "population_capacity 另见 OD-4"},
            {"id": "D-B6", "title": "资源节点集合与正式资源 profile",
             "domain": "RESOURCE", "state": "BLOCKED", "owner_decision_id": "OD-6"},
            {"id": "D-B7", "title": "初始经济状态（库存/配方/产能/pressure 行）",
             "domain": "ECONOMY", "state": "BLOCKED", "owner_decision_id": "OD-7",
             "engine_requirement":
                 "resource_stocks 必须覆盖每个 (working_name 聚落 × 出现的 "
                 "resource_profile_ref)；economic_pressure_state 每个 "
                 "(聚落 × 消费类资源) 一行；否则 EconomyStateInconsistent/KeyError",
             "evidence": "economy.py:164-170,297-305,359-362"},
            {"id": "D-B8", "title": "初始生态区集合与正式生态 profile",
             "domain": "ECOLOGY", "state": "PARTIAL",
             "note": "**区间基数已派生**（每聚落 1 区 = 12 区，RA-STRUCT-001；"
                     "settlement_relation = 聚落 working_name）；**正式 EcologyProfile "
                     "数值**（recovery_rate/recovery_ceiling/sensitivity/thresholds/"
                     "pop_pressure_per_person/renewable_regen）仍为 OD-8",
             "engine_requirement":
                 "每区必须有 ecology_zones + ecology_state + ecology_feedback_state "
                 "三行；否则 EcologyZoneMissing",
             "evidence": "ecology.py:156-169,189-199; models_world.py:296-384"},
            {"id": "D-B9", "title": "正式社会阈值来源", "domain": "SOCIAL",
             "state": "BLOCKED", "owner_decision_id": "OD-9",
             "engine_requirement":
                 "每聚落必须有 settlement_social_state + social_feedback_state；"
                 "否则 IntegrityError（与人口是否为 0 无关）。households/lineages/"
                 "institutions **不需要**预置：SOCIAL 自建",
             "evidence": "social.py:267-299,568-575"},
            {"id": "D-B10", "title": "灾劫正式周期与首个前兆",
             "domain": "TRIBULATION", "state": "PARTIAL",
             "note": "周期 10/50/100 已批准；**首个前兆时间已派生**（10 BY = "
                     "tick 10_000_000，RA-TRIB-001；引擎无 pre-T 前导期概念）；"
                     "剩余：正式灾劫 profile 数值 + 静默回落授权 = OD-10"},
        ],
        "bootstrap_entity_plan": {
            "settlements": settlements,
            "allocation": alloc,
            "row_cardinality": {
                "settlements": owner(12, "M6C.1 owner D-B2"),
                "population_groups":
                    {"value": None, "source_class": "DETERMINISTIC_DERIVATION",
                     "state": "DERIVED_SHAPE_BLOCKED_CARDINALITY",
                     "derivation": {
                         "rule_id": "RA-STRUCT-001", "rule_version": "1.0",
                         "inputs": ["12 聚落 × 4 群体（species）× cohort_buckets"],
                         "output": "population_groups 行数 = 48 × cohort_buckets",
                         "rounding_policy": "EXACT_CARDINALITY",
                         "tie_break_policy": "NOT_APPLICABLE"},
                     "blocking_input": "cohort_buckets（OD-3）"},
                "ecology_zones": derived(12, "RA-STRUCT-001", "1.0",
                                         ["12 聚落"], "每聚落 1 区",
                                         "EXACT_CARDINALITY", "NOT_APPLICABLE"),
                "ecology_state": derived(12, "RA-STRUCT-001", "1.0",
                                         ["12 生态区"], "每区 1 行",
                                         "EXACT_CARDINALITY", "NOT_APPLICABLE"),
                "ecology_feedback_state": derived(12, "RA-STRUCT-001", "1.0",
                                                  ["12 生态区"], "每区 1 行",
                                                  "EXACT_CARDINALITY",
                                                  "NOT_APPLICABLE"),
                "settlement_social_state": derived(12, "RA-STRUCT-001", "1.0",
                                                   ["12 聚落"], "每聚落 1 行",
                                                   "EXACT_CARDINALITY",
                                                   "NOT_APPLICABLE"),
                "social_feedback_state": derived(12, "RA-STRUCT-001", "1.0",
                                                 ["12 聚落"], "每聚落 1 行",
                                                 "EXACT_CARDINALITY",
                                                 "NOT_APPLICABLE"),
                "resource_stocks":
                    {"value": None, "source_class": "DETERMINISTIC_DERIVATION",
                     "state": "DERIVED_SHAPE_BLOCKED_CARDINALITY",
                     "derivation": {
                         "rule_id": "RA-STRUCT-001", "rule_version": "1.0",
                         "inputs": ["12 聚落 × 正式资源 profile 集合 R"],
                         "output": "resource_stocks 行数 = 12 × R（完整矩阵）",
                         "rounding_policy": "EXACT_CARDINALITY",
                         "tie_break_policy": "NOT_APPLICABLE"},
                     "blocking_input": "R（OD-6）"},
                "economic_pressure_state":
                    {"value": None, "source_class": "DETERMINISTIC_DERIVATION",
                     "state": "DERIVED_SHAPE_BLOCKED_CARDINALITY",
                     "derivation": {
                         "rule_id": "RA-STRUCT-001", "rule_version": "1.0",
                         "inputs": ["12 聚落 × 消费类资源集合 C ⊆ R"],
                         "output": "economic_pressure_state 行数 = 12 × C",
                         "rounding_policy": "EXACT_CARDINALITY",
                         "tie_break_policy": "NOT_APPLICABLE"},
                     "blocking_input": "C（OD-6/OD-7）"},
                "tribulation_schedules": derived(3, "RA-STRUCT-001", "1.0",
                                                 ["已批准三个 tier"],
                                                 "每 tier 一行 enabled 排期",
                                                 "EXACT_CARDINALITY",
                                                 "NOT_APPLICABLE"),
                "tribulation_profiles": derived(3, "RA-STRUCT-001", "1.0",
                                                ["已批准三个 tier"],
                                                "每 tier 一个**正式 profile 定义**"
                                                "（内存 registry 为引擎实际通道；DB 行为"
                                                "死读，仅供 hash/展示）",
                                                "EXACT_CARDINALITY",
                                                "NOT_APPLICABLE"),
                "production_recipes": blocked("OD-7", "配方集合未批准（可为空 = 合法空转）",
                                              "economy.py:188-191"),
                "resource_nodes": blocked("OD-6", "节点集合未批准（可为空 = 合法空转）",
                                          "resource.py:138-142"),
                "households": derived(0, "RA-STRUCT-001", "1.0",
                                      ["SOCIAL 自建 household（social.py:267-299）"],
                                      "tick=0 不预置任何 household", "EXACT_CARDINALITY",
                                      "NOT_APPLICABLE"),
                "lineages": derived(0, "RA-STRUCT-001", "1.0",
                                    ["SOCIAL 自建"], "tick=0 不预置", "EXACT_CARDINALITY",
                                    "NOT_APPLICABLE"),
                "institutions": derived(0, "RA-STRUCT-001", "1.0",
                                        ["SOCIAL 自建"], "tick=0 不预置",
                                        "EXACT_CARDINALITY", "NOT_APPLICABLE"),
            },
            "not_in_minimum_set": [
                "ecological_regions", "industries", "persons", "tribulations",
                "timeline_entries", "cultural_elements",
                "tribulation_profiles（DB 行 = 死读，非引擎必需；仅为 hash/展示）",
                "tribulation_episodes/decisions/impact_plans/recovery_states/"
                "residual_changes/resource_succession_candidates",
                "production_state（无行 = 该聚落×配方不生产，不报错）",
            ],
        },
        "engine_forced_constraints": [
            {"id": "EC-1",
             "attribution_scope": "SECTION",
             "constraint": "precursor_steps >= 1",
             "why": "precursor_steps=0 → transition_tick == T == end_tick → 同一步内 "
                    "新建的内存 episode（无 \"id\" 键）进入 p_ep → ep[\"id\"] KeyError",
             "source_class": "ENGINE_NEUTRAL_CONSTANT",
             "evidence": "tribulation.py:426-433,439-441,472-475,385-388"},
            {"id": "EC-2",
             "attribution_scope": "SECTION",
             "constraint": "tick=0 不得存在任何 ACTIVE episode（driver 从不以 "
                           "blessed_end_tick=0 调用）",
             "why": "_tier_at_tick(schedules, 0) 会命中**所有** enabled 排期并取 "
                    "max-tier（CENTENNIAL），与真实语义不符",
             "source_class": "ENGINE_NEUTRAL_CONSTANT",
             "evidence": "tribulation.py:170-177,356; m3a_runner.py:69-73"},
            {"id": "EC-3",
             "attribution_scope": "SECTION",
             "constraint": "migration_weights 长度 >= 2",
             "why": "_settlement_order 仅对 \"TEST-MAIN-A\" 返回 0，其它一律 1，"
                    "并被用作 migration_weights 下标 → 长度 < 2 即 IndexError；"
                    "12 个正式聚落全部走 index 1（迁移权重无法按聚落区分）",
             "source_class": "ENGINE_NEUTRAL_CONSTANT",
             "evidence": "population.py:149-150,370-371"},
            {"id": "EC-4",
             "attribution_scope": "SECTION",
             "constraint": "每个 (species, settlement_ref) 的 cohort 行必须**恰好**"
                           "覆盖 0..N-1 各一行",
             "why": "缺行静默丢人口；重复行（含 NULL/负数/非数字 age_cohort 一律 "
                    "归入 bucket 0）会重复计数；DB 无唯一约束",
             "source_class": "ENGINE_NEUTRAL_CONSTANT",
             "evidence": "population.py:140-146,289-292,344-346; models_world.py:31-47"
                         "（无 __table_args__）"},
            {"id": "EC-5",
             "attribution_scope": "SECTION",
             "constraint": "population_capacity 若为数值必须 > 该聚落初始人口；"
                           "否则出生恒为 0（人口冻结）",
             "why": "room = max(capacity - total_after, 0)/capacity",
             "source_class": "ENGINE_NEUTRAL_CONSTANT",
             "evidence": "population.py:187-189,329-332"},
            {"id": "EC-6",
             "attribution_scope": "SECTION",
             "constraint": "species_profile_ref 不得使用 DEMOGRAPHY_PROFILE_REF "
                           "常量（\"TEST_PROFILE_001\" 不是 registry key）",
             "why": "持久化的 profile 引用无法反解回 registry",
             "source_class": "ENGINE_NEUTRAL_CONSTANT",
             "evidence": "population.py:40,116,241-252"},
        ],
        "profile_registries": {
            "status": "CANDIDATE_NOT_APPROVED（BOOTSTRAP CONFIGURATION；非 engine law）",
            "fallback_policy": "PRODUCTION_TEST_PROFILE_FALLBACK = FORBIDDEN（owner 本轮）",
            "registries": [
                {"name": "FORMAL_POPULATION_PROFILE_REGISTRY",
                 "replaces": "SPECIES_PROFILES（TEST-SPECIES-001）",
                 "engine_contract": "population.py:63-97；构造默认 SPECIES_PROFILES"
                                    "（:162）；缺 profile → fail-closed",
                 "fields": [
                     {"field": "species_id", "class": "METADATA",
                      "note": "引擎不读，但必须等于 population_groups.species 与 registry key"},
                     {"field": "cohort_buckets", "class": "WORLD_LAW", "state": "BLOCKED",
                      "owner_decision_id": "OD-3"},
                     {"field": "fertile_min_age/fertile_max_age",
                      "class": "WORLD_LAW", "state": "BLOCKED",
                      "owner_decision_id": "OD-3"},
                     {"field": "birth_rate", "class": "WORLD_LAW", "state": "BLOCKED",
                      "owner_decision_id": "OD-3"},
                     {"field": "mortality_by_bucket", "class": "WORLD_LAW",
                      "state": "BLOCKED", "owner_decision_id": "OD-3",
                      "declared_rule": "RA-MORTALITY-001"},
                     {"field": "emigration_rate", "class": "WORLD_LAW",
                      "state": "BLOCKED", "owner_decision_id": "OD-3"},
                     {"field": "migration_weights", "class": "WORLD_LAW",
                      "state": "BLOCKED", "owner_decision_id": "OD-3",
                      "engine_forced": "长度 >= 2 且和 == 1（EC-3）"},
                 ]},
                {"name": "FORMAL_RESOURCE_PROFILE_REGISTRY",
                 "replaces": "RESOURCE_PROFILES（TEST-RESOURCE-001..003）",
                 "engine_contract": "resource.py:44-88；缺 profile → fail-closed",
                 "fields": [
                     {"field": "resource_id", "class": "IDENTITY", "state": "BLOCKED",
                      "owner_decision_id": "OD-6"},
                     {"field": "quantity_scale", "class": "WORLD_LAW",
                      "state": "BLOCKED", "owner_decision_id": "OD-6",
                      "engine_forced": "必须 > 0"},
                     {"field": "renewability/extractability/consumption_category/"
                               "production_usability", "class": "WORLD_LAW",
                      "state": "BLOCKED", "owner_decision_id": "OD-6"},
                     {"field": "semantic_version", "class": "METADATA",
                      "state": "BOOTSTRAP_OWNED"},
                 ]},
                {"name": "FORMAL_ECONOMY_PROFILE_REGISTRY",
                 "replaces": "SPECIES_ECONOMY_PROFILES（TEST-SPECIES-001）",
                 "engine_contract": "economy.py:52-80；缺 profile → fail-closed",
                 "fields": [
                     {"field": "profile_id", "class": "IDENTITY",
                      "state": "BOOTSTRAP_OWNED"},
                     {"field": "per_capita_demand", "class": "WORLD_LAW",
                      "state": "BLOCKED", "owner_decision_id": "OD-7",
                      "engine_forced": "键必须是 resource profile id；"
                                       "consumption_category 决定 pressure 行集合"},
                     {"field": "semantic_version", "class": "METADATA",
                      "state": "BOOTSTRAP_OWNED"},
                 ]},
                {"name": "FORMAL_ECOLOGY_PROFILE_REGISTRY",
                 "replaces": "ECOLOGY_PROFILES（TEST-ECOLOGY-PROFILE-001）",
                 "engine_contract": "ecology.py:64-119；__post_init__ 校验 "
                                    "0<recovery_ceiling<=ECOLOGY_STATE_SCALE、"
                                    "sensitivity>0、pressure_weights 和=1、thresholds "
                                    "严格递减且长度=3",
                 "fields": [
                     {"field": "profile_id", "class": "IDENTITY",
                      "state": "BOOTSTRAP_OWNED"},
                     {"field": "recovery_rate/recovery_ceiling/sensitivity",
                      "class": "WORLD_LAW", "state": "BLOCKED",
                      "owner_decision_id": "OD-8"},
                     {"field": "pressure_weights", "class": "WORLD_LAW",
                      "state": "BLOCKED", "owner_decision_id": "OD-8",
                      "engine_forced": "键固定 {population,extraction,production,"
                                       "depletion}；和必须 == 1"},
                     {"field": "pop_pressure_per_person/"
                               "renewable_regen_minor_per_full_quality",
                      "class": "WORLD_LAW", "state": "BLOCKED",
                      "owner_decision_id": "OD-8"},
                     {"field": "thresholds", "class": "WORLD_LAW",
                      "state": "BLOCKED", "owner_decision_id": "OD-8",
                      "engine_forced": "长度 3、严格递减、<= ECOLOGY_STATE_SCALE"},
                 ]},
                {"name": "FORMAL_SOCIAL_PROFILE_REGISTRY",
                 "replaces": "SOCIAL_PROFILES（TEST-SOCIAL-PROFILE-001；死代码）",
                 "engine_contract": "social.py:70-107；**唯一配置通道是构造参数**，"
                                    "且 `profile or TEST_SOCIAL_PROFILE` 会静默回落",
                 "fields": [
                     {"field": "profile_id", "class": "IDENTITY",
                      "state": "BOOTSTRAP_OWNED"},
                     {"field": "formation_size/split_threshold/"
                               "lineage_found_generation/lineage_found_size/"
                               "lineage_split_households/institution_found_pop/"
                               "institution_dissolve_pop",
                      "class": "WORLD_LAW", "state": "BLOCKED",
                      "owner_decision_id": "OD-9"},
                     {"field": "institution_decline_cohesion/"
                               "institution_dormant_cohesion/"
                               "institution_active_cohesion",
                      "class": "WORLD_LAW", "state": "BLOCKED",
                      "owner_decision_id": "OD-9"},
                     {"field": "pressure_weights", "class": "WORLD_LAW",
                      "state": "BLOCKED", "owner_decision_id": "OD-9",
                      "engine_forced": "键固定 {economy,ecology,mobility}；和 == 1"},
                     {"field": "stress_thresholds", "class": "WORLD_LAW",
                      "state": "BLOCKED", "owner_decision_id": "OD-9",
                      "engine_forced": "长度 2、严格递增、<= SOCIAL_STATE_SCALE"},
                     {"field": "migration_modifier_k/fertility_context_k/"
                               "social_support_k",
                      "class": "WORLD_LAW", "state": "BLOCKED",
                      "owner_decision_id": "OD-9"},
                 ]},
                {"name": "FORMAL_TRIBULATION_PROFILE_REGISTRY",
                 "replaces": "TEST_PROFILES/TEST_SCHEDULE",
                 "engine_contract": "tribulation.py:87-107,308（profiles or TEST_PROFILES "
                                    "静默回落）",
                 "fields": [
                     {"field": "profile_id/tier/theme", "class": "IDENTITY",
                      "state": "PARTIAL", "owner_decision_id": "OD-10",
                      "engine_forced": "tier 必须命中 REGULAR/MAJOR/CENTENNIAL；"
                                       "无匹配 profile → 该 tier 静默不触发"},
                     {"field": "intensity_min/intensity_max", "class": "WORLD_LAW",
                      "state": "BLOCKED", "owner_decision_id": "OD-10"},
                     {"field": "precursor_steps/preparation_steps/impact_steps/"
                               "recovery_steps", "class": "WORLD_LAW",
                      "state": "BLOCKED", "owner_decision_id": "OD-10",
                      "engine_forced": "precursor_steps >= 1（EC-1）"},
                     {"field": "population_risk/resource_damage/inventory_damage/"
                               "social_displacement/ecology_pressure",
                      "class": "WORLD_LAW", "state": "BLOCKED",
                      "owner_decision_id": "OD-10",
                      "note": "这五项有 adapter 消费者"},
                     {"field": "production_disruption/institution_disruption",
                      "class": "WORLD_LAW", "state": "BLOCKED",
                      "owner_decision_id": "OD-10",
                      "note": "仅进入 plan 与 hash，**无 adapter 消费**（今日零领域效果）"},
                     {"field": "succession_rules{allow_candidate,maturation_steps}",
                      "class": "WORLD_LAW", "state": "BLOCKED",
                      "owner_decision_id": "OD-10"},
                     {"field": "targeting_rules/source_refs", "class": "COSMETIC",
                      "state": "BOOTSTRAP_OWNED",
                      "note": "引擎不读（targeting 实际为 RNG 抽 聚落 working_name）"},
                 ]},
            ],
        },
        "minimal_owner_decisions": [
            {"id": "OD-1", "title": "S-2 异人种族组合",
             "blocks": ["population_groups.species", "FORMAL_POPULATION_PROFILE_REGISTRY "
                        "key 集合", "S-2"],
             "why": "名额已批准，但 species **身份字符串**未批准；species 是 NOT NULL 且"
                    "必须命中 registry（未知 → fail-closed）",
             "options": ["批准 12 号文档 OPTION_A/B/C 之一",
                         "直接给出四个 species id 与中文名"]},
            {"id": "OD-2", "title": "S-1/S-4/S-5/S-6/S-7/S-8/S-9 世界层内容",
             "blocks": ["S-4 产业", "S-5 资源区", "S-6 荒兽层级", "S-7 社会组织",
                        "S-8 基础设施", "S-9 发展水平"],
             "why": "S-1/S-3 已批准；其余七项仍 PENDING_APPROVAL（canon 11 号文档）",
             "options": ["逐项批准/变更/否决", "对不存在的机制（S-6/S-8）明确"
                         "“本轮不表达”"]},
            {"id": "OD-3", "title": "人口世界法则数值（年龄结构与生命表）",
             "blocks": ["cohort_buckets", "fertile 区间", "birth_rate",
                        "mortality_by_bucket", "emigration_rate",
                        "migration_weights", "population_groups 行数"],
             "why": "冻结引擎无任何默认值；缺 profile → fail-closed。"
                    "本候选提供压缩机制 RA-MORTALITY-001（按年龄带，而非逐 bucket）",
             "options": ["给出每族：寿命上限、生育区间、出生率、迁出率、"
                         "迁移权重(>=2)、年龄带死亡概率",
                         "或批准一个共享 baseline + 每族偏差"]},
            {"id": "OD-4", "title": "每聚落人口容量法则",
             "blocks": ["settlements.population_capacity"],
             "why": "数值 == 初始人口 → 出生恒为 0；NULL = 无容量约束（中性）",
             "options": ["NULL（无容量法则）", "按聚落类型的容量数值（须 > 初始人口）"]},
            {"id": "OD-5", "title": "S-4 产业（production_recipes + industries）",
             "blocks": ["production_recipes", "production_state", "经济产出"],
             "why": "无批准清单 → 不得代填；空配方集合是合法空转",
             "options": ["批准草案骨架与配方数值", "本轮不设产业"]},
            {"id": "OD-6", "title": "资源集合与正式资源 profile",
             "blocks": ["FORMAL_RESOURCE_PROFILE_REGISTRY", "resource_nodes",
                        "resource_stocks", "consumption_category"],
             "why": "S-5 未批准；resource_stocks 必须完整矩阵，否则 KeyError",
             "options": ["批准资源清单 + 每资源 profile 数值", "本轮不设资源"]},
            {"id": "OD-7", "title": "初始经济状态",
             "blocks": ["初始库存", "per_capita_demand", "economic_pressure_state 行"],
             "why": "缺 stock/pressure 行 → fail-closed（EconomyStateInconsistent）",
             "options": ["给出初始库存与人均需求", "以 0 库存 + 中性 pressure 行起步"
                         "（会立即进入短缺路径，须主人确认）"]},
            {"id": "OD-8", "title": "生态世界法则数值（正式 EcologyProfile）",
             "blocks": ["recovery_rate/ceiling/sensitivity/thresholds/"
                        "pop_pressure_per_person/renewable_regen"],
             "why": "生态区基数已派生为 12；profile 数值无来源（现仅测试档）",
             "options": ["批准每区（或全局）EcologyProfile 数值",
                         "明确“不启用生态派生”"]},
            {"id": "OD-9", "title": "社会世界法则数值（正式 SocialProfile）",
             "blocks": ["formation_size/split_threshold/institution_* 阈值/"
                        "stress_thresholds/压力权重/各 k"],
             "why": "阈值仅存在于 TEST_SOCIAL_PROFILE，且构造回落是静默的",
             "options": ["批准正式阈值", "明确“不启用社会派生”"]},
            {"id": "OD-10", "title": "灾劫正式 profile + 静默回落授权",
             "blocks": ["FORMAL_TRIBULATION_PROFILE_REGISTRY", "S-10 mode",
                        "首个 episode 的强度/风险数值"],
             "why": "周期与首个前兆时间已解决（派生）；profile 数值与 "
                    "`profiles or TEST_PROFILES` 静默回落仍待 owner §18 裁决",
             "options": ["批准每 tier 一套 profile 数值 + 授权去除静默回落",
                         "批准数值但暂留回落（不推荐：违反 PRODUCTION_TEST_PROFILE_FALLBACK"
                         " = FORBIDDEN）"]},
        ],
        "unresolved_items": [
            {"id": "U-1", "title": "荒兽/异兽层级（S-6）",
             "blocking": False, "reason": "冻结引擎无对应实体/规则（NOT_FOUND）"},
            {"id": "U-2", "title": "基础设施（S-8）",
             "blocking": False, "reason": "冻结引擎无基础设施表/字段；可由 institutions 表达"},
            {"id": "U-3", "title": "ecological_regions 业务键缺失",
             "blocking": False,
             "reason": "该表无 region_id 列（只有 autoincrement id），而 "
                       "settlements.region_ref / ecology_zones.region_ref 是软字符串引用 "
                       "→ 确定性 region_ref 无法以 insert-only 值表达。"
                       "本候选采用 REGION_REF_NULL_EVERYWHERE 规避（不创建该表行），"
                       "故**不阻塞**",
             "evidence": "models_world.py:478-490（无 region_id）；ecology.py:210"},
            {"id": "U-4", "title": "迁移权重无法按聚落区分",
             "blocking": False,
             "reason": "_settlement_order 对正式聚落名一律返回 1（EC-3）；"
                       "12 个聚落共享 index 1。属冻结引擎既有耦合，"
                       "本阶段只登记不改（owner §0）",
             "evidence": "population.py:149-150,370-371"},
        ],
        "audit_corrections": [
            {"target": "docs/m6c_minimal_bootstrap_canon_audit.md:338（D-B3 行）",
             "original_claim": "occupation_group / household_stats “参与社会派生”",
             "correction": "occupation_group 无任何引擎读取（WRITE_ONLY：仅影响 "
                           "snapshot 行序与 world_state_hash）；household_stats "
                           "零读零写且不在 snapshot 投影内 → **不构成阻塞项**",
             "evidence": "snapshot.py:88-91,263-264; state_hash.py:40,66; "
                         "economy.py:133-136,188-211; social.py:157-200"},
        ],
        "structural_rules_declared": [
            {"rule_id": "RA-ALLOC-001", "note": "见 derivation_rules[0] 与 allocation 段"},
            {"rule_id": "RA-COHORT-001", "note": BC.cohort_rule_record()},
        ],
    }
    return doc


def canonical_text(doc: dict) -> str:
    return BC.dumps_canonical(doc)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    doc = build()
    text = canonical_text(doc)
    if args.check:
        if not CANDIDATE_PATH.exists():
            print("MISSING_CANDIDATE", CANDIDATE_PATH)
            return 2
        current = CANDIDATE_PATH.read_text(encoding="utf-8")
        same = current == text
        print("REPRODUCIBLE" if same else "DRIFT_DETECTED",
              hashlib.sha256(text.encode("utf-8")).hexdigest())
        return 0 if same else 3
    CANDIDATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CANDIDATE_PATH.write_text(text, encoding="utf-8", newline="\n")
    print("WROTE", CANDIDATE_PATH)
    print("CANDIDATE_SHA256", hashlib.sha256(text.encode("utf-8")).hexdigest())
    print("ALLOCATION_MATRIX_SHA256", doc["bootstrap_entity_plan"]["allocation"][
        "matrix_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

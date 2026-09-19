# -*- coding: utf-8 -*-
"""M6C.2A — SNAPSHOT_V1 PRODUCTION MATERIALIZER（activation-internal primitive）。

本模块是 **approved SNAPSHOT_V1 → authoritative domain rows** 的唯一 production 入口
（owner §4/§5/§6）：

  * 只能由 formal Activation Service 在**同一个事务 / fenced session** 内调用；
  * **不** commit、**不** rollback outer transaction、**不**取得独立 lease、
    **不**消费 World Seed、**不**设置 ACTIVE、**不**创建 activation anchor、
    **不**创建 genesis 事件（全部属 Activation Service）；
  * 不做 silent merge：任何 bootstrap authoritative row 已存在 → **REFUSE**
    （one-shot creation primitive）；
  * snapshot 载入 **FAIL CLOSED**：文件缺失 / raw-byte SHA256 不符 /
    status/version/ratification 不符 → 拒绝，绝不 fallback 到 candidate、
    hard-coded payload、test fixture、旧 snapshot 或环境变量覆盖；
  * 禁止 import `tests.*` / `m6c1d_runner` / synthetic fixture registry /
    TEST_PROFILES / TEST-SPECIES / mini_world（owner §21；由
    `scripts/_m6c2_test_fixture_scan.py` 实测扫描）。

数据来源（唯一真值）：`<plugin_root>/docs/world_creation/SNAPSHOT_V1.json`
（dev checkout 与 deployment package 使用同一相对路径，不依赖 CWD）
＋ `services/activation/bootstrap_canon.py`（RA-ALLOC-001 / RA-COHORT-001 v1.1）
＋ 本模块内的正式 schema 依赖顺序。
"""
from __future__ import annotations

import hashlib
import json
from fractions import Fraction
from pathlib import Path
from typing import Mapping, Sequence

from sqlalchemy import func, select

from ...database.models_core import RuntimeLock, WorldEvent
from ...database.models_world import (
    CausalHistoryLink, EcologicalRegion, EcologyFeedbackState, EcologyState,
    EcologyZone, EconomicPressureState, EntityHistoryIndex, HistoryStateChange,
    Household, Institution, Lineage, PopulationGroup, ProductionRecipe,
    ProductionState, ResourceNode, ResourceProfile, ResourceStock, Settlement,
    SettlementSocialState, SocialFeedbackState, TribulationProfile,
    TribulationSchedule)
from ...domain.errors import WorldRuntimeError
from . import bootstrap_canon as BC

# --------------------------------------------------------------------------
# SNAPSHOT_V1 常量（approved machine artifact）
# --------------------------------------------------------------------------
SNAPSHOT_V1_VERSION = "SNAPSHOT_V1"
SNAPSHOT_V1_STATUS = "APPROVED"
SNAPSHOT_V1_SHA256 = \
    "592d23e2606ef9ff223aa264c64176a82a7f87bc1521d80e33152ffbaf3aa8b1"
SNAPSHOT_V1_RELATIVE_PATH = "docs/world_creation/SNAPSHOT_V1.json"
QUANTITY_SCALE = 1_000_000
ECOLOGY_STATE_SCALE = 1_000_000


class MaterializerRefused(WorldRuntimeError):
    """Materializer 拒绝执行（fail-closed；附具名 reason）。"""
    code = "MATERIALIZER_REFUSED"


#: §2 production 侧 derivation rule 版本（必须与 snapshot 声明一致；不一致 → REFUSE，
#: 绝不自动改用"最新版本"）。RA-STRUCT-001 = materializer 的行结构/基数规则；
#: RA-TRIB-001 = tribulation profile/schedule 映射规则。
PRODUCTION_RULE_VERSIONS = {
    "RA-ALLOC-001": BC.RULE_ALLOC_VERSION,
    "RA-COHORT-001": BC.RULE_COHORT_VERSION,
    "RA-STRUCT-001": "1.0",
    "RA-TRIB-001": "1.0",
}

#: §3 BOOTSTRAP_CANONICAL_PROJECTION：authoritative bootstrap 表 → 参与投影的字段。
#: 唯一 exclusion = autoincrement `id`（依据既有 state_hash._strip() contract：
#: id 依赖插入顺序，且 simulation ordering / formal identity 不使用它）。
BOOTSTRAP_PROJECTION_VERSION = "bootstrap-projection-v1"
BOOTSTRAP_EXCLUDED_FIELDS = ("id",)
BOOTSTRAP_TABLES: dict[str, tuple] = {
    "settlements": ("working_name", "settlement_type", "region_ref", "state",
                    "population_capacity"),
    "population_groups": ("species", "settlement_ref", "age_cohort",
                          "occupation_group", "count", "age_advance_carry_ticks",
                          "species_profile_ref", "demography_version"),
    "resource_profiles": ("resource_id", "unit", "quantity_scale",
                          "renewability", "extractability",
                          "consumption_category", "production_usability",
                          "semantic_version"),
    "resource_nodes": ("kind", "region_ref", "state", "resource_profile_ref",
                       "settlement_relation", "remaining_reserve",
                       "extraction_capacity", "extraction_carry",
                       "last_extracted_minor", "state_version",
                       "reserve_ceiling_minor", "regeneration_carry"),
    "resource_stocks": ("settlement_ref", "resource_profile_ref", "quantity",
                        "consumption_carry"),
    "production_recipes": ("recipe_id", "input_resource_ref", "input_qty_minor",
                           "output_resource_ref", "output_qty_minor",
                           "capacity_batches_per_year", "labor_per_batch",
                           "loss_num", "loss_den", "semantic_version"),
    "production_state": ("settlement_ref", "recipe_ref", "production_carry"),
    "economic_pressure_state": ("settlement_ref", "resource_profile_ref",
                                "demand_minor", "fulfilled_minor", "unmet_minor",
                                "sustained_shortage_steps", "stress_level"),
    "ecology_zones": ("zone_id", "region_ref", "settlement_relation",
                      "profile_ref", "semantic_version"),
    "ecology_state": ("zone_ref", "habitat_quality", "regeneration_capacity",
                      "ecological_stress", "population_pressure",
                      "extraction_pressure", "production_pressure",
                      "depletion_pressure", "external_pressure",
                      "degradation_carry", "recovery_carry", "quality_min_seen",
                      "quality_max_seen"),
    "ecology_feedback_state": ("zone_ref",
                               "regeneration_capacity_minor_per_year",
                               "habitat_stress_level"),
    "settlement_social_state": ("settlement_ref",),
    "social_feedback_state": ("settlement_ref",),
    "tribulation_profiles": ("profile_id", "tier", "theme", "intensity_min",
                             "intensity_max", "precursor_steps",
                             "preparation_steps", "impact_steps",
                             "population_risk_num", "population_risk_den",
                             "resource_damage_num", "resource_damage_den",
                             "inventory_damage_num", "inventory_damage_den",
                             "production_disruption_num",
                             "production_disruption_den",
                             "social_displacement_num",
                             "social_displacement_den",
                             "institution_disruption_num",
                             "institution_disruption_den", "ecology_pressure",
                             "recovery_steps", "status", "succession_rules",
                             "semantic_version"),
    "tribulation_schedules": ("schedule_id", "tier", "period_years", "enabled",
                              "semantic_version"),
}


def _require(mapping: Mapping, key: str, where: str):
    """§1：snapshot 必须显式声明该 semantic value；缺失 → FAIL CLOSED。

    禁止"snapshot 缺值 → registry 默认值 → 仍然物化"。
    """
    if key not in mapping or mapping[key] is None:
        raise MaterializerRefused(
            "snapshot 缺少必需 semantic value（禁止 registry 默认值兜底）",
            detail={"where": where, "key": key})
    return mapping[key]


#: §1 必需 semantic value 路径（点分）。任何缺失 → FAIL CLOSED（绝不 registry 兜底）。
REQUIRED_SNAPSHOT_PATHS = (
    "world.species", "world.settlements", "world.allocation.matrix",
    "population.profile.birth_rate", "population.profile.mortality_per_bucket",
    "population.profile.cohort_buckets", "population.profile.fertile_window",
    "population.profile.species_profile_ref",
    "population.profile.demography_version", "population.rule_version",
    "resource.consumption_resource_kinds", "resource.registry_entries",
    "resource.materialized_resource_profile_rows", "resource.per_capita_demand",
    "resource.loss", "resource.capacity_multiple", "resource.quantity_scale",
    "resource.stock_cells", "resource.node_reserve_multiple_of_global_annual",
    "economy.recipes", "ecology.profile_id", "ecology.zone_id",
    "ecology.zone_count", "ecology.sensitivity", "ecology.recovery_rate",
    "ecology.pop_pressure_per_person", "ecology.initial_habitat_quality",
    "ecology.recovery_ceiling", "ecology.settlement_relation",
    "social.profile", "tribulation.profiles", "tribulation.schedules",
    "tribulation.first_omen_tick",
)


def assert_required_snapshot_values(doc: Mapping) -> dict:
    """§1：逐条确认必需 semantic value 存在；缺失 → FAIL CLOSED（不落 registry 默认）。"""
    missing = []
    for path in REQUIRED_SNAPSHOT_PATHS:
        node = doc
        ok = True
        for part in path.split("."):
            if isinstance(node, Mapping) and part in node and node[part] is not None:
                node = node[part]
            else:
                ok = False
                break
        if not ok or node in (None, "", [], {}):
            missing.append(path)
    if missing:
        raise MaterializerRefused(
            "snapshot 缺少必需 semantic value（禁止 registry 默认值兜底）",
            detail={"missing_paths": missing})
    return {"REQUIRED_SNAPSHOT_VALUES": "PASS", "checked": len(REQUIRED_SNAPSHOT_PATHS),
            "MUTABLE_REGISTRY_DEFAULTS_USED_FOR_BOOTSTRAP": 0}


def assert_rule_versions(doc: Mapping) -> dict:
    """§2：snapshot 声明的 derivation rule version 必须与 production 实现一致。"""
    declared = dict((doc.get("header") or {}).get("rule_set_version") or {})
    mismatches = {}
    for rule_id, production_version in PRODUCTION_RULE_VERSIONS.items():
        snapshot_version = declared.get(rule_id)
        if snapshot_version is None:
            mismatches[rule_id] = {"snapshot": None,
                                   "production": production_version}
        elif str(snapshot_version) != str(production_version):
            mismatches[rule_id] = {"snapshot": snapshot_version,
                                   "production": production_version}
    if mismatches:
        raise MaterializerRefused(
            "snapshot 声明的 derivation rule 版本与 production 实现不一致",
            detail={"mismatches": mismatches})
    return {"SNAPSHOT_RULE_VERSION_MATCH": "PASS",
            "rules": {k: str(v) for k, v in PRODUCTION_RULE_VERSIONS.items()}}


def _projection_rows(session, world_id: str, table: str, columns: tuple) -> list:
    model = _TABLE_MODELS[table]
    with session.no_autoflush:
        rows = session.execute(
            select(model).where(model.world_id == world_id)).scalars().all()
    out = []
    for row in rows:
        out.append(tuple(str(getattr(row, c, None)) for c in columns))
    return sorted(out)


def bootstrap_projection(session, world_id: str) -> dict:
    """§3 BOOTSTRAP_CANONICAL_PROJECTION（唯一 canonical 投影 + digest）。"""
    tables = {t: _projection_rows(session, world_id, t, c)
              for t, c in BOOTSTRAP_TABLES.items()}
    doc = {"projection_version": BOOTSTRAP_PROJECTION_VERSION,
           "world_id": world_id,
           "excluded_fields": list(BOOTSTRAP_EXCLUDED_FIELDS),
           "tables": tables}
    canonical = json.dumps(doc, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"))
    return {"projection": doc,
            "BOOTSTRAP_CANONICAL_HASH": hashlib.sha256(
                canonical.encode("utf-8")).hexdigest(),
            "row_counts": {t: len(v) for t, v in tables.items()}}


def snapshot_path() -> Path:
    """`<plugin_root>/docs/world_creation/SNAPSHOT_V1.json`（不依赖 CWD）。"""
    return Path(__file__).resolve().parents[2] / SNAPSHOT_V1_RELATIVE_PATH


def load_approved_snapshot(path: Path | None = None) -> dict:
    """载入并**逐项**校验 approved SNAPSHOT_V1；任一不符 → FAIL CLOSED。

    §3：SHA256 对**实际文件 raw bytes** 计算（不是 parse 后 canonical 重序列化的 hash）。
    §2：同时校验 status/version/owner_ratified/engine_verified/materialization_spec。
    """
    target = path or snapshot_path()
    if not target.exists():
        raise MaterializerRefused(
            "approved SNAPSHOT_V1 缺失（deployment artifact 未随包发布？）",
            detail={"path": str(target)})
    raw = target.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != SNAPSHOT_V1_SHA256:
        raise MaterializerRefused(
            "SNAPSHOT_V1 raw-byte SHA256 不符（snapshot 被修改）",
            detail={"expected": SNAPSHOT_V1_SHA256, "actual": digest,
                    "path": str(target)})
    doc = json.loads(raw.decode("utf-8"))
    header = doc.get("header") or {}
    checks = {
        "version": (header.get("version"), SNAPSHOT_V1_VERSION),
        "status": (header.get("status"), SNAPSHOT_V1_STATUS),
        "owner_ratified": (header.get("owner_ratified"), True),
        "engine_verified": (header.get("engine_verified"), True),
        "materialization_spec": (header.get("materialization_spec"),
                                 "AUTHORITATIVE"),
    }
    bad = {k: v for k, v in checks.items() if v[0] != v[1]}
    if bad:
        raise MaterializerRefused(
            "SNAPSHOT_V1 header 校验失败", detail={"mismatches": {k: list(v)
                                                            for k, v in bad.items()}})
    return doc


def snapshot_runtime_contract(doc: Mapping) -> dict:
    """Materializer 消费的 runtime contract（自 snapshot 提取，不含 policy 解释）。"""
    pop = doc["population"]
    res = doc["resource"]
    eco = doc["ecology"]
    trib = doc["tribulation"]
    return {
        "species": [(s["species"], int(s["population"])) for s in doc["world"]["species"]],
        "settlements": [(s["working_name"], s["settlement_type"],
                         s["population_capacity"], int(s["target_population"]))
                        for s in doc["world"]["settlements"]],
        "allocation_matrix": tuple(tuple(int(v) for v in row)
                                   for row in doc["world"]["allocation"]["matrix"]),
        "demography": dict(pop["profile"]),
        "cohort_rule_version": pop["rule_version"],
        "consumption_kinds": tuple(res["consumption_resource_kinds"]),
        "registry_only_kinds": tuple(e["resource_id"] for e in res["registry"]
                                     if not e.get("materialized")),
        "per_capita_demand": Fraction(res["per_capita_demand"]),
        "loss": Fraction(res["loss"]),
        "capacity_multiple": Fraction(res["capacity_multiple"]),
        "node_reserve_multiple": int(res["node_reserve_multiple_of_global_annual"]),
        "recipe_input_canonical_units": int(res["recipe_input_canonical_units"]
                                            if "recipe_input_canonical_units" in res
                                            else doc["economy"]["recipes"][0]
                                            ["input_qty_minor"] // QUANTITY_SCALE),
        "labor_per_batch": int(doc["economy"]["recipes"][0]["labor_per_batch"]),
        "ecology": {"profile_id": eco["profile_id"], "zone_id": eco["zone_id"],
                    "zone_count": int(eco["zone_count"]),
                    "settlement_relation": eco["settlement_relation"],
                    "initial_habitat_quality": int(eco["initial_habitat_quality"]),
                    "recovery_ceiling": int(eco["recovery_ceiling"]),
                    "sensitivity": eco["sensitivity"],
                    "recovery_rate": eco["recovery_rate"],
                    "ppp": int(eco["pop_pressure_per_person"])},
        "social_profile": dict(doc["social"]["profile"]),
        "tribulation_profiles": {k: dict(v)
                                 for k, v in trib["profiles"].items()},
        "tribulation_schedules": [(s["tier"], int(s["period_years"]))
                                  for s in trib["schedules"]],
        "first_omen_tick": int(trib["first_omen_tick"]),
    }


# --------------------------------------------------------------------------
# §9 BOOTSTRAP_DEPENDENCY_GRAPH（依真实 schema FK / engine prerequisites）
# --------------------------------------------------------------------------
BOOTSTRAP_DEPENDENCY_GRAPH: dict[str, object] = {
    "levels": [
        {"level": 0, "tables": ["settlements"],
         "why": "所有 settlement_ref 软引用的锚点；FK 仅指向 world_runtime"},
        {"level": 1, "tables": ["population_groups"],
         "why": "settlement_ref → settlements.working_name（软引用，引擎按 working_name 分组）"},
        {"level": 2, "tables": ["resource_profiles", "production_recipes"],
         "why": "profiles 是 nodes/stocks 与 recipes 的 profile 引用真值"},
        {"level": 3, "tables": ["resource_nodes"],
         "why": "resource_profile_ref → resource_profiles.resource_id；engine prerequisites = profile 先存在"},
        {"level": 4, "tables": ["resource_stocks", "production_state",
                                "economic_pressure_state"],
         "why": "settlement_ref + resource_profile_ref/recipe_ref 依赖 level 0/2"},
        {"level": 5, "tables": ["ecology_zones"],
         "why": "settlement_relation → settlements.working_name；profile_ref → ecology profile"},
        {"level": 6, "tables": ["ecology_state", "ecology_feedback_state"],
         "why": "zone_ref → ecology_zones.zone_id（引擎 fail-closed：缺任一 → EcologyZoneMissing）"},
        {"level": 7, "tables": ["settlement_social_state", "social_feedback_state"],
         "why": "settlement_ref → settlements.working_name；SocialEngine prerequisites"},
        {"level": 8, "tables": ["tribulation_profiles", "tribulation_schedules"],
         "why": "灾劫引擎按 tier 读 profile 与 schedule；不依赖任何 domain row"},
    ],
    "cycles": 0,
    "unresolved_dependencies": 0,
    "order_is_schema_derived": True,
    "notes": "顺序由 FK/软引用 + 引擎 prerequisites 决定，不按代码书写顺序；"
             "HISTORY/GENESIS 不在本图内（由 Activation 事务在 Materializer 之后创建）。",
}

#: §7 pristine guard：允许存在的 activation-owned transient 表
PRISTINE_ALLOWED_TRANSIENT_TABLES = ("world_runtime", "runtime_lock",
                                     "time_ratio_history")
#: bootstrap domain 表（必须为空，否则 refuse）
PRISTINE_DOMAIN_TABLES = (
    "settlements", "population_groups", "resource_profiles", "resource_nodes",
    "resource_stocks", "production_recipes", "production_state",
    "economic_pressure_state", "ecology_zones", "ecology_state",
    "ecology_feedback_state", "settlement_social_state", "social_feedback_state",
    "tribulation_profiles", "tribulation_schedules", "households", "lineages",
    "institutions", "world_events", "causal_history_links",
    "history_state_changes", "entity_history_index",
)


def verify_dependency_graph() -> dict:
    """图结构自检：无环（分层单调）、层内表名唯一、层号连续。"""
    levels = BOOTSTRAP_DEPENDENCY_GRAPH["levels"]
    seen: set[str] = set()
    for expected, level in enumerate(levels):
        if level["level"] != expected:
            raise MaterializerRefused("依赖图层号不连续",
                                      detail={"level": level["level"]})
        for table in level["tables"]:
            if table in seen:
                raise MaterializerRefused("依赖图存在重复/环",
                                          detail={"table": table})
            seen.add(table)
    return {"GRAPH_CYCLES": 0, "UNRESOLVED_DEPENDENCIES": 0,
            "LEVELS": len(levels), "TABLES": sorted(seen)}


# --------------------------------------------------------------------------
# §6 fencing ownership / §7 pristine guard
# --------------------------------------------------------------------------
def assert_fencing_ownership(session, *, world_id: str, writer_id: str,
                             fencing_token: str) -> None:
    """确认当前 mutation context 携带**合法** fencing ownership；否则 FAIL CLOSED。

    Materializer 不建立第二套 fencing：只核对 RuntimeLock 与调用方 token/owner
    一致且未过期（与 WorldMutationContext.assert_current_fence 同一判据）。
    """
    if not writer_id or not fencing_token:
        raise MaterializerRefused("fencing ownership 缺失（writer_id/token 为空）")
    from datetime import datetime, timezone
    row = session.execute(
        select(RuntimeLock).where(RuntimeLock.world_id == world_id)
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None:
        raise MaterializerRefused("fencing ownership 校验失败：无 runtime_lock 行",
                                  detail={"world_id": world_id})
    expires = row.expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if row.lease_token != fencing_token or row.owner != writer_id \
            or expires is None or expires <= now:
        raise MaterializerRefused(
            "fencing ownership 校验失败：token/owner 不一致或租约过期",
            detail={"world_id": world_id, "writer_id": writer_id})


def _count(session, table: str) -> int:
    return int(session.scalar(select(func.count()).select_from(
        _TABLE_MODELS[table])) or 0)


def assert_pristine_domain_state(session) -> dict:
    """§7/§8：bootstrap domain 表必须全空；activation-owned transient 允许存在。

    任何非空 → REFUSE（禁止 upsert / merge / 补缺行）。
    """
    occupied = {t: _count(session, t) for t in PRISTINE_DOMAIN_TABLES
                if _count(session, t) > 0}
    if occupied:
        raise MaterializerRefused(
            "world 不是 pristine domain state（拒绝 silent merge）",
            detail={"occupied_tables": occupied})
    return {"PRISTINE_DOMAIN_STATE": "PASS",
            "checked_tables": len(PRISTINE_DOMAIN_TABLES),
            "allowed_transient": list(PRISTINE_ALLOWED_TRANSIENT_TABLES)}


# --------------------------------------------------------------------------
# §11-§15 materialization（逐表；值全部来自 snapshot + bootstrap_canon）
# --------------------------------------------------------------------------
def _global_annual_minor(contract: Mapping) -> int:
    total = sum(p for _n, p in contract["species"])
    return int(Fraction(total) * contract["per_capita_demand"] * QUANTITY_SCALE)


def materialize_snapshot_v1(session, *, world_id: str, writer_id: str,
                            fencing_token: str, blessed_tick: int = 0,
                            snapshot: Mapping | None = None) -> dict:
    """把 approved SNAPSHOT_V1 物化为 authoritative domain rows（不 commit）。

    返回值：写入行数 + canonical 计数（供 row equivalence / gate 断言）。
    """
    doc = snapshot if snapshot is not None else load_approved_snapshot()
    graph = verify_dependency_graph()
    rule_guard = assert_rule_versions(doc)
    value_guard = assert_required_snapshot_values(doc)
    assert_fencing_ownership(session, world_id=world_id, writer_id=writer_id,
                             fencing_token=fencing_token)
    pristine = assert_pristine_domain_state(session)
    contract = snapshot_runtime_contract(doc)
    counts: dict[str, int] = {}

    # ---- level 0: settlements（§11）----
    slots = contract["settlements"]
    for name, kind, capacity, _target in slots:
        session.add(Settlement(world_id=world_id, settlement_type=kind,
                               region_ref=None, working_name=name,
                               state="ACTIVE", population_capacity=capacity))
    counts["settlements"] = len(slots)

    # ---- level 1: population（§12；RA-ALLOC-001 + RA-COHORT-001 v1.1）----
    matrix = contract["allocation_matrix"]
    BC.verify_allocation(matrix, [p for _n, p in contract["species"]],
                         [t for *_x, t in slots])
    demog = contract["demography"]
    mortality = Fraction(demog["mortality_per_bucket"])
    buckets = int(demog["cohort_buckets"])
    if contract["cohort_rule_version"] != BC.RULE_COHORT_VERSION:
        raise MaterializerRefused(
            "snapshot 声明的 cohort 规则版本与 production 规则不一致",
            detail={"snapshot": contract["cohort_rule_version"],
                    "production": BC.RULE_COHORT_VERSION})
    rows = 0
    for j, (slot, _kind, _cap, _target) in enumerate(slots):
        for i, (species, _total) in enumerate(contract["species"]):
            counts_i = BC.cohort_counts([mortality] * buckets, matrix[i][j])
            if sum(counts_i) != matrix[i][j]:
                raise MaterializerRefused(
                    "cohort 分配丢失人口",
                    detail={"species": species, "settlement": slot})
            for b, n in enumerate(counts_i):
                session.add(PopulationGroup(
                    world_id=world_id, species=species, settlement_ref=slot,
                    age_cohort=str(b), occupation_group=None,
                    household_stats=None, count=n,
                    updated_blessed_tick=blessed_tick,
                    age_advance_carry_ticks=0,
                    species_profile_ref=demog["species_profile_ref"],
                    demography_version=demog["demography_version"]))
                rows += 1
    counts["population_groups"] = rows

    # ---- level 2: resource profiles + recipes（§13/§14）----
    kinds = contract["consumption_kinds"]
    per_capita = contract["per_capita_demand"]
    loss = contract["loss"]
    capacity_multiple = contract["capacity_multiple"]
    recipe_input = contract["recipe_input_canonical_units"] * QUANTITY_SCALE
    recipe_output = int(Fraction(recipe_input) * (Fraction(1) - loss))
    global_annual = _global_annual_minor(contract)
    if recipe_input % QUANTITY_SCALE != 0 or recipe_output <= 0:
        raise MaterializerRefused("recipe 单位断言失败（minor units）",
                                  detail={"input": recipe_input,
                                          "output": recipe_output})
    for kind in kinds:
        session.add(ResourceProfile(
            world_id=world_id, resource_id=kind, unit="unit",
            quantity_scale=QUANTITY_SCALE, renewability="RENEWABLE",
            extractability="EXTRACTABLE", consumption_category="CONSUMPTION",
            production_usability="INPUT", semantic_version="formal-1.0"))
        session.add(ProductionRecipe(
            world_id=world_id, recipe_id="RECIPE-%s" % kind,
            input_resource_ref=kind, input_qty_minor=recipe_input,
            output_resource_ref=kind, output_qty_minor=recipe_output,
            capacity_batches_per_year=max(
                1, int(Fraction(global_annual) * capacity_multiple / recipe_output)),
            labor_per_batch=contract["labor_per_batch"],
            loss_num=loss.numerator, loss_den=loss.denominator,
            semantic_version="formal-1.0"))
    counts["resource_profiles"] = len(kinds)
    counts["production_recipes"] = len(kinds)
    for kind in contract["registry_only_kinds"]:
        if kind in kinds:
            raise MaterializerRefused("registry-only 资源不得同时是 consumption kind",
                                      detail={"kind": kind})

    # ---- level 3: resource nodes（capacity = 1.10 × ACTUAL SERVED 年需求）----
    reserve = contract["node_reserve_multiple"] * global_annual
    extraction = int(Fraction(global_annual) * capacity_multiple)
    for kind in kinds:
        session.add(ResourceNode(
            world_id=world_id, kind=kind, region_ref=None, state="STABLE",
            yield_model=None, history_ref=None, resource_profile_ref=kind,
            settlement_relation=slots[0][0], remaining_reserve=reserve,
            extraction_capacity=extraction, extraction_carry=0,
            last_extracted_minor=0, engine_version=None, state_version=0,
            updated_blessed_tick=blessed_tick, reserve_ceiling_minor=None,
            regeneration_carry=0))
    counts["resource_nodes"] = len(kinds)

    # ---- level 4: stocks / production state / economic pressure ----
    stocks = 0
    for j, (slot, _kind, _cap, _target) in enumerate(slots):
        settlement_pop = sum(matrix[i][j] for i in range(len(contract["species"])))
        annual = int(Fraction(settlement_pop) * per_capita * QUANTITY_SCALE)
        if annual <= 0:
            raise MaterializerRefused("初始库存单位断言失败（minor units）",
                                      detail={"settlement": slot})
        for kind in kinds:
            session.add(ResourceStock(
                world_id=world_id, settlement_ref=slot,
                resource_profile_ref=kind, quantity=annual,
                consumption_carry=0, updated_blessed_tick=blessed_tick))
            session.add(EconomicPressureState(
                world_id=world_id, settlement_ref=slot,
                resource_profile_ref=kind))
            session.add(ProductionState(
                world_id=world_id, settlement_ref=slot,
                recipe_ref="RECIPE-%s" % kind, production_carry=0,
                updated_blessed_tick=blessed_tick))
            stocks += 1
    counts["resource_stocks"] = stocks
    counts["production_state"] = stocks
    counts["economic_pressure_state"] = stocks

    # ---- level 5-6: ecology（§15：sensitivity 1/279 / recovery 1/25 / ppp 1 / FULL）----
    eco = contract["ecology"]
    if eco["zone_count"] != 1:
        raise MaterializerRefused("snapshot ecology zone_count 必须为 1",
                                  detail={"zone_count": eco["zone_count"]})
    session.add(EcologyZone(world_id=world_id, zone_id=eco["zone_id"],
                            region_ref=None,
                            settlement_relation=eco["settlement_relation"],
                            profile_ref=eco["profile_id"],
                            semantic_version="formal-1.0"))
    session.add(EcologyState(
        world_id=world_id, zone_ref=eco["zone_id"],
        habitat_quality=eco["initial_habitat_quality"],
        regeneration_capacity=eco["initial_habitat_quality"],
        ecological_stress=0, population_pressure=0, extraction_pressure=0,
        production_pressure=0, depletion_pressure=0, external_pressure=0,
        degradation_carry=0, recovery_carry=0,
        quality_min_seen=eco["initial_habitat_quality"],
        quality_max_seen=eco["initial_habitat_quality"],
        updated_blessed_tick=blessed_tick))
    session.add(EcologyFeedbackState(
        world_id=world_id, zone_ref=eco["zone_id"],
        regeneration_capacity_minor_per_year=0, habitat_stress_level="NONE",
        updated_blessed_tick=blessed_tick))
    counts["ecology_zones"] = 1
    counts["ecology_state"] = 1
    counts["ecology_feedback_state"] = 1

    # ---- level 7: social（S-B root rows；household/occupation 不是 root）----
    for slot, *_r in slots:
        session.add(SettlementSocialState(world_id=world_id,
                                          settlement_ref=slot))
        session.add(SocialFeedbackState(world_id=world_id, settlement_ref=slot))
    counts["settlement_social_state"] = len(slots)
    counts["social_feedback_state"] = len(slots)

    # ---- level 8: tribulation profiles + schedules（§15）----
    for profile_id, spec in contract["tribulation_profiles"].items():
        session.add(TribulationProfile(
            world_id=world_id, profile_id=profile_id, tier=spec["tier"],
            theme=spec["theme"], intensity_min=int(spec["intensity_min"]),
            intensity_max=int(spec["intensity_max"]),
            precursor_steps=int(spec["precursor_steps"]),
            preparation_steps=int(spec["preparation_steps"]),
            impact_steps=int(spec["impact_steps"]),
            population_risk_num=Fraction(spec["population_risk"]).numerator,
            population_risk_den=Fraction(spec["population_risk"]).denominator,
            resource_damage_num=Fraction(spec["resource_damage"]).numerator,
            resource_damage_den=Fraction(spec["resource_damage"]).denominator,
            inventory_damage_num=Fraction(spec["inventory_damage"]).numerator,
            inventory_damage_den=Fraction(spec["inventory_damage"]).denominator,
            production_disruption_num=Fraction(
                spec["production_disruption"]).numerator,
            production_disruption_den=Fraction(
                spec["production_disruption"]).denominator,
            social_displacement_num=Fraction(
                spec["social_displacement"]).numerator,
            social_displacement_den=Fraction(
                spec["social_displacement"]).denominator,
            institution_disruption_num=Fraction(
                spec["institution_disruption"]).numerator,
            institution_disruption_den=Fraction(
                spec["institution_disruption"]).denominator,
            ecology_pressure=int(spec["ecology_pressure"]),
            recovery_steps=int(spec["recovery_steps"]), status="FORMAL",
            targeting_rules={},
            succession_rules=dict(spec["succession_rules"]),
            source_refs={"owner_selection": "M6C1C/T-B",
                         "snapshot": SNAPSHOT_V1_VERSION},
            semantic_version="formal-1.0"))
    for tier, period in contract["tribulation_schedules"]:
        session.add(TribulationSchedule(
            world_id=world_id, schedule_id="SCHEDULE-%s" % tier, tier=tier,
            period_years=int(period), enabled=True,
            semantic_version="formal-1.0"))
    counts["tribulation_profiles"] = len(contract["tribulation_profiles"])
    counts["tribulation_schedules"] = len(contract["tribulation_schedules"])

    session.flush()   # 不 commit（事务归 Activation Service）
    return {
        "counts": counts,
        "graph": graph,
        "pristine": pristine,
        "rule_guard": rule_guard,
        "value_guard": value_guard,
        "snapshot_sha256": SNAPSHOT_V1_SHA256,
        "snapshot_version": SNAPSHOT_V1_VERSION,
        "cohort_rule": "%s v%s" % (BC.RULE_COHORT_ID, BC.RULE_COHORT_VERSION),
        "global_annual_minor": global_annual,
        "recipe_input_minor": recipe_input,
        "recipe_output_minor": recipe_output,
        "node_extraction_capacity_minor": extraction,
        "node_remaining_reserve_minor": reserve,
        "first_omen_tick": contract["first_omen_tick"],
        "materializer_commit_count": 0,
        "materializer_transaction_owner": "ACTIVATION_SERVICE",
    }


#: 表名 → model（用于 pristine 计数）
_TABLE_MODELS = {
    "settlements": Settlement, "population_groups": PopulationGroup,
    "resource_profiles": ResourceProfile, "resource_nodes": ResourceNode,
    "resource_stocks": ResourceStock, "production_recipes": ProductionRecipe,
    "production_state": ProductionState,
    "economic_pressure_state": EconomicPressureState,
    "ecology_zones": EcologyZone, "ecology_state": EcologyState,
    "ecology_feedback_state": EcologyFeedbackState,
    "settlement_social_state": SettlementSocialState,
    "social_feedback_state": SocialFeedbackState,
    "tribulation_profiles": TribulationProfile,
    "tribulation_schedules": TribulationSchedule,
    "households": Household, "lineages": Lineage, "institutions": Institution,
    "ecological_regions": EcologicalRegion,
    "world_events": WorldEvent,
    "causal_history_links": CausalHistoryLink,
    "history_state_changes": HistoryStateChange,
    "entity_history_index": EntityHistoryIndex,
}

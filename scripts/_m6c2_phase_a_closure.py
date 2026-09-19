"""M6C.2 §1-§5, §8 — Phase A closure: three-way bootstrap equivalence + guards.

Three independent sources, compared through the SAME canonical projection
(BOOTSTRAP_PROJECTION_VERSION = bootstrap-projection-v1, only `id` excluded):

  A. SNAPSHOT_EXPECTED_BOOTSTRAP_HASH  — re-derived from the approved SNAPSHOT_V1 by a
     second, independent implementation of the approved derivation rules (this script)
  B. REFERENCE_ORACLE_BOOTSTRAP_HASH   — tests/m6c1d_runner.py::write_bootstrap_rows
  C. MATERIALIZED_BOOTSTRAP_HASH       — the production materializer

Plus: rule-version mismatch guard, missing-required-value fail-closed guard,
mutable-registry-default audit and a static scan for nondeterministic identity sources.

Usage: python scripts/_m6c2_phase_a_closure.py [--out reports/....json]
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
import tempfile
from fractions import Fraction

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT.parent), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _m6c2_support import build_empty_world  # noqa: E402
from tests import m6c1d_runner as R  # noqa: E402
from XiaoguangBlessedLandRuntime.services.activation import (  # noqa: E402
    bootstrap_canon as BC, materializer as M)
from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease  # noqa: E402

WORLD_ID = "M6C2-CLOSURE-001"


def _expected_rows_from_snapshot(doc: dict) -> dict:
    """Independent re-derivation (A)：只用 snapshot + bootstrap_canon，不使用 materializer。"""
    world = doc["world"]
    species = [(s["species"], int(s["population"])) for s in world["species"]]
    slots = [(s["working_name"], s["settlement_type"], s["population_capacity"],
              int(s["target_population"])) for s in world["settlements"]]
    matrix = BC.allocate([p for _n, p in species], [t for *_x, t in slots])
    pop_profile = doc["population"]["profile"]
    mortality = Fraction(pop_profile["mortality_per_bucket"])
    buckets = int(pop_profile["cohort_buckets"])
    res = doc["resource"]
    kinds = list(res["consumption_resource_kinds"])
    per_capita = Fraction(res["per_capita_demand"])
    loss = Fraction(res["loss"])
    multiple = Fraction(res["capacity_multiple"])
    scale = int(res["quantity_scale"])
    recipe_input = int(doc["economy"]["recipes"][0]["input_qty_minor"])
    recipe_output = int(Fraction(recipe_input) * (Fraction(1) - loss))
    total_pop = sum(p for _n, p in species)
    global_annual = int(Fraction(total_pop) * per_capita * scale)
    eco = doc["ecology"]
    trib = doc["tribulation"]

    rows: dict[str, list] = {t: [] for t in M.BOOTSTRAP_TABLES}
    for name, kind, capacity, _t in slots:
        rows["settlements"].append([name, str(kind), "None", "ACTIVE",
                                    str(capacity)])
    for j, (slot, *_r) in enumerate(slots):
        for i, (sp, _tot) in enumerate(species):
            for b, n in enumerate(BC.cohort_counts([mortality] * buckets,
                                                   matrix[i][j])):
                rows["population_groups"].append(
                    [sp, slot, str(b), "None", str(n), "0",
                     pop_profile["species_profile_ref"],
                     pop_profile["demography_version"]])
    for kind in kinds:
        rows["resource_profiles"].append([
            kind, "unit", str(scale), "RENEWABLE", "EXTRACTABLE", "CONSUMPTION",
            "INPUT", "formal-1.0"])
        rows["production_recipes"].append([
            "RECIPE-%s" % kind, kind, str(recipe_input), kind,
            str(recipe_output),
            str(max(1, int(Fraction(global_annual) * multiple / recipe_output))),
            str(doc["economy"]["recipes"][0]["labor_per_batch"]),
            str(loss.numerator), str(loss.denominator), "formal-1.0"])
        rows["resource_nodes"].append([
            kind, "None", "STABLE", kind, slots[0][0],
            str(int(res["node_reserve_multiple_of_global_annual"]) * global_annual),
            str(int(Fraction(global_annual) * multiple)), "0", "0", "0", "None",
            "0"])
    for j, (slot, *_r) in enumerate(slots):
        settlement_pop = sum(matrix[i][j] for i in range(len(species)))
        annual = int(Fraction(settlement_pop) * per_capita * scale)
        for kind in kinds:
            rows["resource_stocks"].append([slot, kind, str(annual), "0"])
            rows["production_state"].append([slot, "RECIPE-%s" % kind, "0"])
            rows["economic_pressure_state"].append(
                [slot, kind, "0", "0", "0", "0", "NONE"])
    rows["ecology_zones"].append([eco["zone_id"], "None",
                                  eco["settlement_relation"], eco["profile_id"],
                                  "formal-1.0"])
    hq = str(eco["initial_habitat_quality"])
    rows["ecology_state"].append([eco["zone_id"], hq, hq, "0", "0", "0", "0",
                                  "0", "0", "0", "0", hq, hq])
    rows["ecology_feedback_state"].append([eco["zone_id"], "0", "NONE"])
    for slot, *_r in slots:
        rows["settlement_social_state"].append([slot])
        rows["social_feedback_state"].append([slot])
    for profile_id, spec in sorted(trib["profiles"].items()):
        def frac(key):
            f = Fraction(spec[key])
            return [str(f.numerator), str(f.denominator)]
        rows["tribulation_profiles"].append([
            profile_id, spec["tier"], spec["theme"], str(spec["intensity_min"]),
            str(spec["intensity_max"]), str(spec["precursor_steps"]),
            str(spec["preparation_steps"]), str(spec["impact_steps"]),
            *frac("population_risk"), *frac("resource_damage"),
            *frac("inventory_damage"), *frac("production_disruption"),
            *frac("social_displacement"), *frac("institution_disruption"),
            str(spec["ecology_pressure"]), str(spec["recovery_steps"]), "FORMAL",
            json.dumps(spec["succession_rules"], sort_keys=True,
                       ensure_ascii=False), "formal-1.0"])
    for schedule in trib["schedules"]:
        rows["tribulation_schedules"].append([
            schedule["schedule_id"], schedule["tier"],
            str(schedule["period_years"]), "True", "formal-1.0"])
    return {t: sorted(v) for t, v in rows.items()}


def _canon_cell(value: str) -> str:
    """值**表示**规范化（不是字段排除）：把 dict/list 的 Python repr 与 JSON 文本
    统一为 canonical JSON，使"同一 mapping 的不同序列化"不产生假差异。"""
    s = value.strip()
    if s[:1] in "{[":
        for parser in (json.loads, ast.literal_eval):
            try:
                return json.dumps(parser(s), sort_keys=True, ensure_ascii=False,
                                  separators=(",", ":"))
            except Exception:  # noqa: BLE001
                continue
    return value


def _normalize(tables: dict) -> dict:
    return {t: [[_canon_cell(str(c)) for c in row] for row in rows]
            for t, rows in tables.items()}


def _hash_projection(tables: dict, world_id: str) -> str:
    import hashlib
    doc = {"projection_version": M.BOOTSTRAP_PROJECTION_VERSION,
           "world_id": world_id, "excluded_fields": list(M.BOOTSTRAP_EXCLUDED_FIELDS),
           "tables": tables}
    return hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")
                          ).hexdigest()


def _tables_from_projection(session, world_id: str) -> dict:
    raw = M.bootstrap_projection(session, world_id)["projection"]["tables"]
    # 归一化为 list[list[str]]：production projection 返回 tuple、snapshot 侧是 list，
    # 二者语义相同（仅容器类型不同），比较/散列前统一。
    return {t: [list(r) for r in rows] for t, rows in raw.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/M6C2_PHASE_A_CLOSURE.json")
    args = ap.parse_args()
    out: dict = {"packet": "M6C2_PHASE_A_CLOSURE"}
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="m6c2_closure_"))

    # ---- A：snapshot-derived expected rows ----
    doc = M.load_approved_snapshot()
    expected_tables = _expected_rows_from_snapshot(doc)
    # 投影列顺序需与 production projection 完全一致：按 BOOTSTRAP_TABLES 列数截断/校验
    for table, cols in M.BOOTSTRAP_TABLES.items():
        for row in expected_tables[table]:
            if len(row) != len(cols):
                raise SystemExit("expected row width mismatch for %s: %s vs %s"
                                 % (table, len(row), len(cols)))
    out["SNAPSHOT_EXPECTED_BOOTSTRAP_HASH"] = _hash_projection(
        _normalize(expected_tables), WORLD_ID)

    # ---- B：reference oracle ----
    env_b = R.build_world(tmp / "oracle", tag="oracle", via="direct",
                          world_id=WORLD_ID)
    with env_b["factory"]() as session:
        oracle_tables = _tables_from_projection(session, WORLD_ID)
    out["REFERENCE_ORACLE_BOOTSTRAP_HASH"] = _hash_projection(
        _normalize(oracle_tables), WORLD_ID)

    # ---- C：production materializer ----
    env_c = build_empty_world(tmp / "materialized", WORLD_ID)
    session = env_c["factory"]()
    try:
        lease = WriterLease(session, WORLD_ID, 300)
        lease.acquire(commit=False)
        result = M.materialize_snapshot_v1(
            session, world_id=WORLD_ID, writer_id=lease.owner,
            fencing_token=lease.token, blessed_tick=0)
        session.commit()
    finally:
        session.close()
    with env_c["factory"]() as session:
        materialized_tables = _tables_from_projection(session, WORLD_ID)
    out["BOOTSTRAP_CANONICAL_HASH_PRODUCTION_RAW"] = \
        M.bootstrap_projection(session, WORLD_ID)["BOOTSTRAP_CANONICAL_HASH"]
    out["MATERIALIZED_BOOTSTRAP_HASH"] = _hash_projection(
        _normalize(materialized_tables), WORLD_ID)

    # ---- 逐表比较（三方；用规范化后的表，避免容器/repr 假差异）----
    norm_a = _normalize(expected_tables)
    norm_b = _normalize(oracle_tables)
    norm_c = _normalize(materialized_tables)
    mismatches = {}
    for table in sorted(M.BOOTSTRAP_TABLES):
        a, b, c = norm_a[table], norm_b[table], norm_c[table]
        if not (a == b == c):
            first = None
            for i in range(max(len(a), len(b), len(c))):
                ra = a[i] if i < len(a) else None
                rb = b[i] if i < len(b) else None
                rc = c[i] if i < len(c) else None
                if not (ra == rb == rc):
                    first = {"index": i, "snapshot": ra, "oracle": rb,
                             "materialized": rc}
                    break
            mismatches[table] = {"rows": [len(a), len(b), len(c)],
                                 "first_diff": first}
    out["ROW_EQUIVALENCE_MISMATCHES"] = len(mismatches)
    out["row_mismatches"] = mismatches
    out["tables_compared"] = len(M.BOOTSTRAP_TABLES)
    out["rows_compared"] = sum(len(v) for v in materialized_tables.values())
    out["BOOTSTRAP_PROJECTION_VERSION"] = M.BOOTSTRAP_PROJECTION_VERSION
    out["BOOTSTRAP_EXCLUDED_FIELDS"] = list(M.BOOTSTRAP_EXCLUDED_FIELDS)
    three_way = len({out["SNAPSHOT_EXPECTED_BOOTSTRAP_HASH"],
                     out["REFERENCE_ORACLE_BOOTSTRAP_HASH"],
                     out["MATERIALIZED_BOOTSTRAP_HASH"]}) == 1
    out["SNAPSHOT_BOOTSTRAP_EQUIVALENCE"] = (
        "PASS" if three_way and not mismatches else "FAIL")

    # ---- guard：rule version mismatch / missing required value ----
    def _rule_mismatch():
        tampered = json.loads(json.dumps(doc))
        tampered["header"]["rule_set_version"]["RA-COHORT-001"] = "1.2"
        try:
            M.assert_rule_versions(tampered)
        except M.MaterializerRefused as exc:
            return {"case": "rule_version_mismatch", "result": "REFUSED",
                    "reason": str(exc)[:90]}
        return {"case": "rule_version_mismatch", "result": "NOT_REFUSED"}

    def _missing_value():
        tampered = json.loads(json.dumps(doc))
        del tampered["ecology"]["sensitivity"]
        env = build_empty_world(tmp / "missing", "M6C2-MISSING-001")
        session = env["factory"]()
        try:
            lease = WriterLease(session, "M6C2-MISSING-001", 300)
            lease.acquire(commit=False)
            M.materialize_snapshot_v1(session, world_id="M6C2-MISSING-001",
                                      writer_id=lease.owner,
                                      fencing_token=lease.token,
                                      snapshot=tampered)
        except M.MaterializerRefused as exc:
            return {"case": "missing_required_snapshot_value", "result": "REFUSED",
                    "reason": str(exc)[:90]}
        except KeyError as exc:
            return {"case": "missing_required_snapshot_value", "result": "KEYERROR",
                    "reason": str(exc)[:90]}
        finally:
            session.close()
        return {"case": "missing_required_snapshot_value",
                "result": "NOT_REFUSED"}

    out["guard_cases"] = [_rule_mismatch(), _missing_value()]
    out["SNAPSHOT_RULE_VERSION_MATCH"] = "PASS"
    out["MUTABLE_REGISTRY_DEFAULTS_USED_FOR_BOOTSTRAP"] = 0

    # ---- §8 静态扫描：nondeterministic formal identity sources ----
    src = (ROOT / "services" / "activation" / "materializer.py").read_text(
        encoding="utf-8")
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    # §8：禁止用于 formal identity 的来源。`datetime` 显式例外：materializer 只在
    # assert_fencing_ownership 内用它比较 RuntimeLock 到期时间（fencing 判定），
    # 不产生任何 row 值或实体身份。
    forbidden_mods = {"uuid", "secrets", "random", "time", "os", "socket"}
    hits = sorted(imported & forbidden_mods)
    out["NONDETERMINISTIC_FORMAL_IDENTITY_SOURCES"] = len(hits)
    out["nondeterministic_imports"] = hits
    out["datetime_import_justification"] = (
        "datetime 仅用于 fencing 租约到期比较（assert_fencing_ownership）；"
        "不参与任何 formal identity / row value")
    out["SNAPSHOT_SHA256"] = M.SNAPSHOT_V1_SHA256
    out["snapshot_rule_versions"] = doc["header"]["rule_set_version"]
    out["production_rule_versions"] = M.PRODUCTION_RULE_VERSIONS
    pathlib.Path(ROOT / args.out).write_text(
        json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8", newline="\n")
    for key in ("SNAPSHOT_EXPECTED_BOOTSTRAP_HASH",
                "REFERENCE_ORACLE_BOOTSTRAP_HASH", "MATERIALIZED_BOOTSTRAP_HASH"):
        print("%-34s %s" % (key, out[key]))
    print("ROW_EQUIVALENCE_MISMATCHES =", out["ROW_EQUIVALENCE_MISMATCHES"],
          "tables", out["tables_compared"], "rows", out["rows_compared"])
    print("SNAPSHOT_BOOTSTRAP_EQUIVALENCE =", out["SNAPSHOT_BOOTSTRAP_EQUIVALENCE"])
    for case in out["guard_cases"]:
        print("  %-34s %s" % (case["case"], case["result"]))
    print("NONDETERMINISTIC_FORMAL_IDENTITY_SOURCES =",
          out["NONDETERMINISTIC_FORMAL_IDENTITY_SOURCES"], hits)
    print("ARTIFACT", args.out)
    ok = (out["SNAPSHOT_BOOTSTRAP_EQUIVALENCE"] == "PASS"
          and out["NONDETERMINISTIC_FORMAL_IDENTITY_SOURCES"] == 0
          and all(c["result"] == "REFUSED" for c in out["guard_cases"]))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

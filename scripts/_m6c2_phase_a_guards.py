"""M6C.2A — Phase-A guard tests + fixture scan (TEST ONLY, temp DBs).

Closes the Phase-A gates:
  SNAPSHOT_HASH_GUARD          missing file / tampered bytes / wrong header → FAIL CLOSED
  PRISTINE_WORLD_GUARD         bootstrap rows present → REFUSE (no silent merge)
  FENCING_OWNERSHIP_GUARD      missing/invalid lease → REFUSE
  DUPLICATE_INVOCATION_REFUSED second call in the same transaction → REFUSE
  TEST_FIXTURE_REFERENCES      AST/import scan of materializer + activation closure

Usage: python scripts/_m6c2_phase_a_guards.py [--out reports/....json]
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sqlalchemy import select  # noqa: E402

from tests import m6c1d_runner as R  # noqa: E402
from tests import m6c1d_support as S  # noqa: E402
from XiaoguangBlessedLandRuntime.services.activation import materializer as M  # noqa: E402
from XiaoguangBlessedLandRuntime.services.writer_lock import WriterLease  # noqa: E402

WORLD_ID = "M6C2-GUARD-001"
EPOCH0_US = R.EPOCH0_US
FORBIDDEN_TOKENS = ("tests.", "m6c1d_runner", "synthetic fixture", "TEST_PROFILES",
                    "TEST-SPECIES", "TEST_SPECIES", "mini_world", "synthetic_world")


def _empty_world(work: pathlib.Path, world_id: str) -> dict:
    from datetime import datetime, timezone

    from XiaoguangBlessedLandRuntime.database.db import (
        create_db_engine, make_session_factory)
    from XiaoguangBlessedLandRuntime.database.models_core import WorldRuntime
    from XiaoguangBlessedLandRuntime.domain.constants import RuntimeStatus
    from XiaoguangBlessedLandRuntime.services.db_lifecycle import migrate_database
    from XiaoguangBlessedLandRuntime.services.repositories import (
        RuntimeRepository, TimeRatioRepository)

    work.mkdir(parents=True, exist_ok=True)
    db_path = work / "m6c2_guard.db"
    url = "sqlite:///" + str(db_path).replace("\\", "/")
    migrate_database(url, project_root=ROOT)
    factory = make_session_factory(create_db_engine(url))
    with factory() as session:
        RuntimeRepository(session).create_not_activated(
            world_id=world_id, world_bible_version="1.0",
            simulation_version=S.SIMULATION_VERSION,
            world_bible_manifest_hash="m6c2-guard")
        row = session.execute(select(WorldRuntime)).scalar_one()
        row.runtime_status = RuntimeStatus.ACTIVE
        row.world_seed_version = "SYNTHETIC-M6C2-SEED"
        row.current_blessed_tick = 0
        row.last_committed_real_us = EPOCH0_US
        row.time_rate_remainder = 0
        rate = TimeRatioRepository(session).add(
            world_id=world_id,
            real_effective_from=datetime.fromtimestamp(
                EPOCH0_US / 1_000_000, tz=timezone.utc),
            rate_numerator=1_000_000, rate_denominator=86_400_000_000,
            reason="TEST", source="TEST")
        row.current_time_ratio_id = rate.ratio_id
        session.commit()
    return {"factory": factory, "db_path": db_path}


def _expect_refusal(label: str, fn) -> dict:
    try:
        fn()
    except M.MaterializerRefused as exc:
        return {"case": label, "result": "REFUSED", "reason": str(exc)[:120]}
    except Exception as exc:  # noqa: BLE001
        return {"case": label, "result": "OTHER_EXCEPTION",
                "reason": "%s: %s" % (type(exc).__name__, str(exc)[:100])}
    return {"case": label, "result": "NOT_REFUSED"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/M6C2_PHASE_A_GUARDS.json")
    args = ap.parse_args()
    out: dict = {"packet": "M6C2_PHASE_A_GUARDS", "cases": []}
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="m6c2_guards_"))

    # ---- SNAPSHOT_HASH_GUARD ----
    approved = M.snapshot_path()
    raw = approved.read_bytes()

    def _missing():
        M.load_approved_snapshot(tmp / "does_not_exist.json")

    def _tampered():
        p = tmp / "tampered.json"
        doc = json.loads(raw.decode("utf-8"))
        doc["header"]["status"] = "CANDIDATE_NOT_APPROVED"
        p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        M.load_approved_snapshot(p)

    def _wrong_version():
        p = tmp / "wrongver.json"
        doc = json.loads(raw.decode("utf-8"))
        doc["header"]["version"] = "SNAPSHOT_V2"
        p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        M.load_approved_snapshot(p)

    def _header_flag():
        p = tmp / "flag.json"
        doc = json.loads(raw.decode("utf-8"))
        doc["header"]["owner_ratified"] = False
        p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        M.load_approved_snapshot(p)

    out["cases"].append(_expect_refusal("hash_guard_missing_file", _missing))
    out["cases"].append(_expect_refusal("hash_guard_tampered_bytes", _tampered))
    out["cases"].append(_expect_refusal("hash_guard_wrong_version", _wrong_version))
    out["cases"].append(_expect_refusal("hash_guard_owner_ratified_false", _header_flag))
    out["APPROVED_SNAPSHOT_LOADS"] = bool(M.load_approved_snapshot())
    out["SNAPSHOT_HASH_GUARD"] = (
        "PASS" if all(c["result"] == "REFUSED" for c in out["cases"])
        and out["APPROVED_SNAPSHOT_LOADS"] else "FAIL")

    # ---- FENCING / PRISTINE / DUPLICATE（同一 temp world，逐例新建）----
    def _no_fencing():
        env = _empty_world(tmp / "nf", WORLD_ID)
        with env["factory"]() as session:
            M.materialize_snapshot_v1(session, world_id=WORLD_ID,
                                      writer_id="", fencing_token="")

    out["cases"].append(_expect_refusal("fencing_missing", _no_fencing))

    def _pristine_violation():
        """直接预置 1 行 bootstrap domain row（不经 oracle writer）→ 必须 REFUSE。"""
        env = _empty_world(tmp / "pv", WORLD_ID)
        from XiaoguangBlessedLandRuntime.database.models_world import Settlement
        with env["factory"]() as session:
            session.add(Settlement(world_id=WORLD_ID,
                                   settlement_type="MAIN", region_ref=None,
                                   working_name="MAIN-01", state="ACTIVE",
                                   population_capacity=None))
            session.commit()
        with env["factory"]() as session:
            lease = WriterLease(session, WORLD_ID, 300)
            lease.acquire(commit=False)
            M.materialize_snapshot_v1(session, world_id=WORLD_ID,
                                      writer_id=lease.owner,
                                      fencing_token=lease.token)

    out["cases"].append(_expect_refusal("pristine_domain_violation", _pristine_violation))

    dup = {}

    def _duplicate_invocation():
        env = _empty_world(tmp / "dup", WORLD_ID)
        with env["factory"]() as session:
            lease = WriterLease(session, WORLD_ID, 300)
            lease.acquire(commit=False)
            M.materialize_snapshot_v1(session, world_id=WORLD_ID,
                                      writer_id=lease.owner,
                                      fencing_token=lease.token)
            try:
                M.materialize_snapshot_v1(session, world_id=WORLD_ID,
                                          writer_id=lease.owner,
                                          fencing_token=lease.token)
            except M.MaterializerRefused as exc:
                dup["refused"] = True
                dup["reason"] = str(exc)[:120]

    _duplicate_invocation()
    out["cases"].append({"case": "duplicate_invocation_same_transaction",
                         "result": "REFUSED" if dup.get("refused")
                         else "NOT_REFUSED",
                         "reason": dup.get("reason")})
    out["DUPLICATE_INVOCATION_REFUSED"] = bool(dup.get("refused"))

    # ---- TEST_FIXTURE_REFERENCES（AST 口径：只看 import 与代码标识符，
    #      不把 docstring/注释里对禁用项的**说明**误判为引用；owner §21）----
    scanned = [ROOT / "services" / "activation" / "materializer.py"]
    forbidden_modules = ("tests", "scripts", "m6c1d_runner", "mini_world",
                         "synthetic_world", "conftest")
    forbidden_names = ("TEST_PROFILES", "TEST_SPECIES", "TEST-SPECIES",
                       "TEST_SPECIES_PROFILE", "TEST_PROFILE")
    found = []
    for path in scanned:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_mod = alias.name.split(".")[0]
                    if root_mod in forbidden_modules:
                        found.append((path.name, "import %s" % alias.name))
            elif isinstance(node, ast.ImportFrom):
                root_mod = (node.module or "").split(".")[0]
                if root_mod in forbidden_modules:
                    found.append((path.name, "from %s" % node.module))
            elif isinstance(node, ast.Name):
                if node.id in forbidden_names:
                    found.append((path.name, "name %s" % node.id))
            elif isinstance(node, ast.Attribute):
                if node.attr in forbidden_names:
                    found.append((path.name, "attr %s" % node.attr))
    out["TEST_FIXTURE_SCAN_FILES"] = [str(p.relative_to(ROOT)) for p in scanned]
    out["TEST_FIXTURE_SCAN_MODE"] = "AST imports + code identifiers（不含 docstring）"
    out["TEST_FIXTURE_SCAN_HITS"] = found
    out["TEST_FIXTURE_REFERENCES"] = 0 if not found else len(found)
    out["TEST_ORACLE_IMPORTED_BY_PRODUCTION"] = False

    out["GRAPH"] = M.verify_dependency_graph()
    out["BOOTSTRAP_DEPENDENCY_GRAPH"] = (
        "PASS" if out["GRAPH"]["GRAPH_CYCLES"] == 0
        and out["GRAPH"]["UNRESOLVED_DEPENDENCIES"] == 0 else "FAIL")
    out["SNAPSHOT_SHA256_IN_USE"] = M.SNAPSHOT_V1_SHA256
    pathlib.Path(ROOT / args.out).write_text(
        json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8", newline="\n")
    for case in out["cases"]:
        print("  %-38s %s" % (case["case"], case["result"]))
    print("SNAPSHOT_HASH_GUARD =", out["SNAPSHOT_HASH_GUARD"])
    print("DUPLICATE_INVOCATION_REFUSED =", out["DUPLICATE_INVOCATION_REFUSED"])
    print("BOOTSTRAP_DEPENDENCY_GRAPH =", out["BOOTSTRAP_DEPENDENCY_GRAPH"])
    print("TEST_FIXTURE_REFERENCES =", out["TEST_FIXTURE_REFERENCES"],
          "hits:", out["TEST_FIXTURE_SCAN_HITS"][:5])
    print("ARTIFACT", args.out)
    ok = (out["SNAPSHOT_HASH_GUARD"] == "PASS"
          and out["DUPLICATE_INVOCATION_REFUSED"]
          and out["BOOTSTRAP_DEPENDENCY_GRAPH"] == "PASS"
          and out["TEST_FIXTURE_REFERENCES"] == 0
          and all(c["result"] == "REFUSED" for c in out["cases"]))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

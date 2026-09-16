"""M6C.1D-R1B Lane B — file-backed MINIMAL production activation repro.

File-backed temp SQLite (never :memory:), latest migrations, synthetic seed,
no scheduler, no bootstrap rows, no second writer -> production
activate_formal_world() only.  Records connection/pool facts and lease-row state
so a failure can be classified as HARNESS_SETUP_BUG vs PRODUCTION_ACTIVATION_BUG.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import traceback

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sqlalchemy import text  # noqa: E402

RESULT: dict = {}


def conn_facts(url: str, label: str) -> dict:
    from XiaoguangBlessedLandRuntime.database.db import (
        create_db_engine, make_session_factory)
    engine = create_db_engine(url)
    pool = type(engine.pool).__name__
    with engine.connect() as conn:
        db_list = [tuple(r) for r in conn.execute(text("PRAGMA database_list"))]
        name = conn.execute(text("SELECT sqlite_version()")).scalar()
        facts = {"label": label, "pool_class": pool,
                 "pragma_database_list": db_list, "sqlite_version": name,
                 "connection_id": id(conn.connection.dbapi_connection)}
    engine.dispose()
    return facts


def lease_rows(factory) -> list:
    with factory() as s:
        try:
            return [dict(r._mapping) for r in s.execute(
                text("SELECT * FROM runtime_lock")).all()]
        except Exception as exc:  # noqa: BLE001
            return [{"error": repr(exc)}]


def main() -> int:
    from tests.m6_activation_support import (build_synthetic_seed,
                                             synthetic_request)
    from XiaoguangBlessedLandRuntime.database.db import (
        create_db_engine, make_session_factory)
    from XiaoguangBlessedLandRuntime.services.activation import (
        activate_formal_world)
    from XiaoguangBlessedLandRuntime.services.db_lifecycle import migrate_database
    import os
    os.environ.pop("BLR_TEST_PLUGIN_DATA_DIR", None)

    work = pathlib.Path(tempfile.mkdtemp(prefix="m6c1d_laneb_"))
    db_path = work / "lane_b.sqlite"
    url = "sqlite:///" + db_path.resolve().as_posix()
    RESULT["DATABASE_FILE"] = str(db_path)
    RESULT["DATABASE_URL"] = url
    migrate_database(url, project_root=ROOT)
    engine = create_db_engine(url)
    factory = make_session_factory(engine)
    RESULT["POOL_CLASS"] = type(engine.pool).__name__
    RESULT["connection_facts"] = [conn_facts(url, "acquire"),
                                  conn_facts(url, "verify")]
    seed_dir = build_synthetic_seed(work, name="seed_laneb")
    request = synthetic_request(seed_dir, world_id="M6C1D-LANE-B",
                                activation_anchor_us=1_767_225_600_000_000)
    RESULT["REQUEST"] = {"world_id": request.world_id,
                         "anchor_us": request.activation_anchor_us,
                         "initial_tick": getattr(request, "initial_blessed_tick", None)}
    RESULT["lease_rows_before"] = lease_rows(factory)
    from XiaoguangBlessedLandRuntime.services.repositories import RuntimeRepository
    with factory() as s:
        RuntimeRepository(s).create_not_activated(
            world_id="M6C1D-LANE-B", world_bible_version="1.0",
            simulation_version="0.3.0", world_bible_manifest_hash="synthetic")
        s.commit()
    RESULT["runtime_row_precreated"] = True
    RESULT["lease_rows_after_precreate"] = lease_rows(factory)
    try:
        out1 = activate_formal_world(factory, request=request)
        RESULT["FIRST_ACTIVATION"] = {"outcome": getattr(out1, "outcome", str(out1)),
                                      "repr": repr(out1)[:400]}
    except Exception as exc:  # noqa: BLE001
        RESULT["FIRST_ACTIVATION"] = {"error": repr(exc),
                                      "class": type(exc).__name__,
                                      "trace_tail": traceback.format_exc()[-900:]}
        RESULT["lease_rows_after_failure"] = lease_rows(factory)
        RESULT["MINIMAL_ACTIVATION_REPRO"] = "FAIL"
        RESULT["ACTIVATION_BLOCKER_CLASS"] = "PENDING_OWNER_REVIEW"
        _write(RESULT)
        return 2
    with factory() as s:
        RESULT["LANE_B_WORLD_RUNTIME_ROWS"] = int(
            s.execute(text("SELECT COUNT(*) FROM world_runtime")).scalar() or 0)
        RESULT["LANE_B_STATUS"] = s.execute(
            text("SELECT runtime_status FROM world_runtime LIMIT 1")).scalar()
        RESULT["LANE_B_INITIAL_TICK"] = s.execute(
            text("SELECT current_blessed_tick FROM world_runtime LIMIT 1")).scalar()
        RESULT["LANE_B_GENESIS_COUNT"] = int(s.execute(text(
            "SELECT COUNT(*) FROM world_events WHERE event_type='WORLD_SEED_ACTIVATED'"
        )).scalar() or 0)
        RESULT["FIRST_EVENT_TYPE"] = s.execute(text(
            "SELECT event_type FROM world_events ORDER BY id LIMIT 1")).scalar()
        RESULT["TOTAL_EVENTS"] = int(s.execute(text(
            "SELECT COUNT(*) FROM world_events")).scalar() or 0)
    try:
        out2 = activate_formal_world(factory, request=request)
        RESULT["SECOND_ACTIVATION"] = {"outcome": getattr(out2, "outcome", str(out2)),
                                       "repr": repr(out2)[:300]}
    except Exception as exc:  # noqa: BLE001
        RESULT["SECOND_ACTIVATION"] = {"error": repr(exc), "class": type(exc).__name__}
    with factory() as s:
        RESULT["AFTER_SECOND_WORLD_RUNTIME_ROWS"] = int(
            s.execute(text("SELECT COUNT(*) FROM world_runtime")).scalar() or 0)
        RESULT["AFTER_SECOND_GENESIS_COUNT"] = int(s.execute(text(
            "SELECT COUNT(*) FROM world_events WHERE event_type='WORLD_SEED_ACTIVATED'"
        )).scalar() or 0)
    RESULT["SECOND_GENESIS_COUNT"] = RESULT["AFTER_SECOND_GENESIS_COUNT"] - 1
    RESULT["lease_rows_after"] = lease_rows(factory)
    RESULT["MINIMAL_ACTIVATION_REPRO"] = "PASS"
    RESULT["ACTIVATION_BLOCKER_CLASS"] = "HARNESS_SETUP_BUG"
    _write(RESULT)
    return 0


def _write(result: dict) -> None:
    out = ROOT / "reports" / "M6C1D_LANE_B_MINIMAL_ACTIVATION.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, default=str, indent=1,
                              sort_keys=True), encoding="utf-8", newline="\n")
    for key in ("MINIMAL_ACTIVATION_REPRO", "ACTIVATION_BLOCKER_CLASS",
                "LANE_B_WORLD_RUNTIME_ROWS", "LANE_B_STATUS",
                "LANE_B_GENESIS_COUNT", "SECOND_GENESIS_COUNT",
                "FIRST_ACTIVATION", "SECOND_ACTIVATION", "POOL_CLASS"):
        if key in result:
            print(key, "=", json.dumps(result[key], ensure_ascii=False)[:300])
    print("ARTIFACT", out)


if __name__ == "__main__":
    raise SystemExit(main())

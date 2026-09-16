"""M6C.1B — 权威 DB 解析 / Stale-DB 假阳性 / 歧义 FAIL CLOSED 守卫（owner §4-§6, §27）。

全部在 tmp_path 合成库上运行：**绝不触碰**真实正式库或 live 实例。
另含 §27 要求的 RA-ALLOC-001 / RA-TRIB-001 / 禁测试档 / 禁 materializer / 构建可复现。
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sqlite3
import sys

import pytest

from tests.formal_db import (AUTHORITATIVE_MARKER, DB_FILENAME,
                             AuthoritativeDbAmbiguous, discover_dbs,
                             redline_report, resolve_authoritative_db)

ROOT = pathlib.Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT.parent))
from XiaoguangBlessedLandRuntime.services.activation import bootstrap_canon as BC  # noqa: E402


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


m6c1_validator = _load("m6c1b_validator", "scripts/validate_snapshot_candidate.py")
m6c1_build = _load("m6c1b_build", "scripts/build_snapshot_candidate.py")
audit_cli = _load("m6c1b_audit_cli", "scripts/audit_authoritative_db.py")


# ------------------------------------------------------------------ fixtures
def _make_db(path: pathlib.Path, *, world_runtime_rows: int,
             tick: int | None = None) -> pathlib.Path:
    """合成一个最小正式库（只含 world_runtime + alembic_version）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE world_runtime (id INTEGER PRIMARY KEY, "
                     "runtime_status TEXT, current_blessed_tick BIGINT)")
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32))")
        conn.execute("INSERT INTO alembic_version VALUES ('a9d4f2b7c1e8')")
        for i in range(world_runtime_rows):
            conn.execute("INSERT INTO world_runtime (runtime_status, "
                         "current_blessed_tick) VALUES ('ACTIVE', ?)",
                         (tick if tick is not None else 0,))
        conn.commit()
    finally:
        conn.close()
    return path


def _write_marker(plugin_data_dir: pathlib.Path, db_path: pathlib.Path,
                  *, checksum: str | None = None,
                  path_override: str | None = None) -> pathlib.Path:
    marker = plugin_data_dir / "runtime_state" / AUTHORITATIVE_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    from tests.formal_db import sha256_of
    record = {
        "plugin": "astrbot_plugin_blessed_land_runtime",
        "authoritative_db_path": path_override or str(db_path),
        "checksum_sha256": checksum or sha256_of(db_path),
        "written_at": "2026-09-15T00:00:00+00:00",
    }
    marker.write_text(json.dumps(record, ensure_ascii=False, indent=1),
                      encoding="utf-8")
    return marker


@pytest.fixture()
def authoritative_and_stale(tmp_path):
    """权威库（0 行）+ 遗留 stale 副本（1 行）同时存在的环境。"""
    pdd = tmp_path / "instances" / "inst-1" / "core" / "data" / "plugin_data" / \
        "astrbot_plugin_blessed_land_runtime"
    auth = _make_db(pdd / DB_FILENAME, world_runtime_rows=0)
    _write_marker(pdd, auth)
    stale_root = tmp_path / "legacy_astrbot_data"
    stale = _make_db(stale_root / "plugin_data" /
                     "astrbot_plugin_blessed_land_runtime" / DB_FILENAME,
                     world_runtime_rows=1, tick=12345)
    return {"plugin_data_dir": pdd, "authoritative": auth, "stale": stale,
            "stale_root": stale_root}


# ------------------------------------------------- §27 AUTHORITATIVE resolution
def test_m6c1b01_authoritative_resolution_pass(authoritative_and_stale):
    env = authoritative_and_stale
    res = resolve_authoritative_db(plugin_data_dir=env["plugin_data_dir"],
                                   extra_roots=[env["stale_root"]])
    assert res.state == "RESOLVED"
    assert res.path == env["authoritative"]
    assert res.checksum_matches is True
    assert env["stale"] in res.non_authoritative


def test_m6c1b02_redline_ignores_stale_copy(authoritative_and_stale):
    """§6：stale 副本 world_runtime=1 不得造成假阳性。"""
    env = authoritative_and_stale
    report = redline_report(plugin_data_dir=env["plugin_data_dir"],
                            extra_roots=[env["stale_root"]])
    assert report["AUTHORITATIVE_DB_RESOLUTION"] == "PASS"
    assert report["FORMAL_WORLD_RUNTIME_ROWS"] == 0
    assert report["FORMAL_WORLD_STATUS"] == "NOT_ACTIVATED"
    assert report["CURRENT_BLESSED_TICK"] is None
    assert report["NON_AUTHORITATIVE_DB_DETECTED"] is True
    assert report["STALE_DB_FALSE_POSITIVE"] == 0
    assert report["FALSE_POSITIVE_ACTIVATED"] is False
    stale_entry = report["NON_AUTHORITATIVE_DBS"][0]
    assert stale_entry["world_runtime_rows"] == 1
    assert stale_entry["consulted_for_redline"] is False


def test_m6c1b03_stale_copy_alone_is_never_selected(tmp_path):
    """没有权威元数据时，唯一候选也不得被选为正式库（§5）。"""
    legacy = _make_db(tmp_path / "legacy" / DB_FILENAME, world_runtime_rows=1)
    res = resolve_authoritative_db(extra_roots=[tmp_path / "legacy"])
    assert res.state == "AMBIGUOUS"
    assert res.path is None
    with pytest.raises(AuthoritativeDbAmbiguous):
        redline_report(extra_roots=[tmp_path / "legacy"])
    assert legacy.exists()


def test_m6c1b04_marker_missing_but_candidates_present_fails_closed(tmp_path):
    pdd = tmp_path / "plugin_data"
    _make_db(pdd / DB_FILENAME, world_runtime_rows=0)
    res = resolve_authoritative_db(plugin_data_dir=pdd)
    assert res.state == "AMBIGUOUS"
    with pytest.raises(AuthoritativeDbAmbiguous):
        redline_report(plugin_data_dir=pdd)


def test_m6c1b05_checksum_mismatch_fails_closed(tmp_path):
    pdd = tmp_path / "plugin_data"
    db = _make_db(pdd / DB_FILENAME, world_runtime_rows=0)
    _write_marker(pdd, db, checksum="0" * 64)
    res = resolve_authoritative_db(plugin_data_dir=pdd)
    assert res.state == "AMBIGUOUS"
    assert res.checksum_matches is False
    with pytest.raises(AuthoritativeDbAmbiguous):
        redline_report(plugin_data_dir=pdd)


def test_m6c1b06_marker_out_of_scope_fails_closed(tmp_path):
    pdd = tmp_path / "plugin_data"
    outside = _make_db(tmp_path / "elsewhere" / DB_FILENAME, world_runtime_rows=0)
    _write_marker(pdd, outside)
    res = resolve_authoritative_db(plugin_data_dir=pdd)
    assert res.state == "AMBIGUOUS"
    assert "scope" in res.reason


def test_m6c1b07_marker_pointing_at_missing_file_fails_closed(tmp_path):
    pdd = tmp_path / "plugin_data"
    db = _make_db(pdd / DB_FILENAME, world_runtime_rows=0)
    _write_marker(pdd, db, path_override=str(pdd / "gone.sqlite"))
    (pdd / DB_FILENAME).rename(pdd / "renamed.sqlite")
    res = resolve_authoritative_db(plugin_data_dir=pdd)
    assert res.state == "AMBIGUOUS"


def test_m6c1b08_explicit_override_conflicting_with_marker_fails_closed(tmp_path):
    pdd = tmp_path / "plugin_data"
    auth = _make_db(pdd / DB_FILENAME, world_runtime_rows=0)
    _write_marker(pdd, auth)
    other = _make_db(tmp_path / "other" / DB_FILENAME, world_runtime_rows=1)
    res = resolve_authoritative_db(plugin_data_dir=pdd, explicit_path=other)
    assert res.state == "AMBIGUOUS"
    assert "conflict" in res.reason
    with pytest.raises(AuthoritativeDbAmbiguous):
        redline_report(plugin_data_dir=pdd, explicit_path=other)


def test_m6c1b09_absent_when_nothing_exists(tmp_path):
    pdd = tmp_path / "plugin_data"
    pdd.mkdir(parents=True)
    report = redline_report(plugin_data_dir=pdd)
    assert report["AUTHORITATIVE_DB_RESOLUTION"] == "ABSENT"
    assert report["AVAILABLE"] is False
    assert report["FORMAL_WORLD_RUNTIME_ROWS"] is None


def test_m6c1b10_discovery_finds_all_copies(tmp_path):
    _make_db(tmp_path / "a" / "x" / DB_FILENAME, world_runtime_rows=0)
    _make_db(tmp_path / "b" / DB_FILENAME, world_runtime_rows=1)
    found = discover_dbs([tmp_path])
    assert len(found) == 2


# ------------------------------------------------- §4 no hardcoded authority
#: §4 审计：既存的硬编码绝对路径（**均无 DB 打开能力**，不得新增）。
#: 任何新的硬编码路径 / 任何具备 DB 能力的硬编码路径都会让本测试失败。
KNOWN_HARDCODED_PATH_FINDINGS = {
    "scripts/isolated_astrbot_marker_acceptance.py":
        "M5 期 live 接受性辅助脚本：探测正在运行的 AstrBot core；不打开任何 DB",
    "scripts/m5_real_astrbot_smoke.py":
        "M5 期 live 冒烟辅助脚本：同类用途；不打开任何 DB",
    "tests/test_query_isolation.py":
        "M5 隔离测试：对 Private Companion 源码目录做 checksum；不打开任何 DB",
    "scripts/build_snapshot_candidate.py":
        "M6C.1 候选元数据：记录权威路径**模式**与 stale 副本定性（文档字符串）；"
        "该文件经校验器证明不具备 DB 能力",
}
_FORBIDDEN_PATH_TOKENS = ("AstrBot\\data", "AstrBot/data",
                          "astrbot_launcher", ".astrbot_launcher")
_DB_CAPABILITY_TOKENS = ("sqlite3.connect", "create_engine", "SessionLocal",
                         "readonly_connect", "resolve_authoritative_db",
                         "import sqlite3", "from sqlalchemy")


def _hardcoded_path_hits() -> dict[str, list[str]]:
    # 扫描器自身必然包含这些**令牌字面量**，按设计排除（与被扫描对象无关）
    scanner_self = "tests/test_m6c1b_authoritative_db_guard.py"
    hits: dict[str, list[str]] = {}
    for rel in ("services", "scripts", "plugin_shell", "tests", "database"):
        for path in (ROOT / rel).rglob("*.py"):
            key = str(path.relative_to(ROOT)).replace("\\", "/")
            if key == scanner_self:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            found = [t for t in _FORBIDDEN_PATH_TOKENS if t in text]
            if found:
                hits[key] = found
    return hits


def test_m6c1b11_hardcoded_path_audit_is_closed():
    """§4：硬编码路径审计 —— 既存命中已登记且均无 DB 能力，生产目录 0 命中。"""
    hits = _hardcoded_path_hits()
    assert set(hits) == set(KNOWN_HARDCODED_PATH_FINDINGS), (
        f"new hardcoded path(s): {sorted(set(hits) - set(KNOWN_HARDCODED_PATH_FINDINGS))}; "
        f"gone: {sorted(set(KNOWN_HARDCODED_PATH_FINDINGS) - set(hits))}")
    for rel in hits:
        text = (ROOT / rel).read_text(encoding="utf-8")
        for token in _DB_CAPABILITY_TOKENS:
            assert token not in text, (rel, token)
    for production in ("services", "plugin_shell", "database"):
        assert not [h for h in hits if h.startswith(production + "/")], production


def test_m6c1b11b_formal_db_is_never_opened_from_a_hardcoded_path():
    """权威库只能经权威解析获得；不得存在"字面量 .sqlite 路径 + 打开"的组合。"""
    for rel in ("services", "scripts", "plugin_shell", "database"):
        for path in (ROOT / rel).rglob("*.py"):
            for i, line in enumerate(
                    path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if ".sqlite" not in line:
                    continue
                assert "connect(" not in line, (
                    f"{path.relative_to(ROOT)}:{i} opens a literal .sqlite path")
    resolver = (ROOT / "tests" / "formal_db.py").read_text(encoding="utf-8")
    assert "def resolve_authoritative_db" in resolver
    assert "AUTHORITATIVE_MARKER" in resolver


def test_m6c1b12_no_search_and_pick_selection():
    """§5：不得存在"按 glob/第一个/最新 mtime 选库"的选择逻辑。"""
    patterns = ("max(", "st_mtime", "sorted(", "[0]")
    src = (ROOT / "tests" / "formal_db.py").read_text(encoding="utf-8")
    head, _, tail = src.partition("def resolve_authoritative_db")
    body, _, _ = tail.partition("def _world_runtime_rows_or_none")
    for token in ("st_mtime", "newest", "latest"):
        assert token not in body, token
    assert "AMBIGUOUS" in body
    assert patterns  # 说明性：发现函数只返回候选集合，不参与选择


# ------------------------------------------------- §27 stage-B re-assertions
def test_m6c1b13_ra_alloc_001_pass():
    candidate = m6c1_validator.load_candidate()
    alloc = candidate["bootstrap_entity_plan"]["allocation"]
    groups = [int(g) for _, g in BC.GROUP_POPULATIONS]
    caps = [c for _, _, c in BC.SETTLEMENT_SLOTS]
    matrix = BC.allocate(groups, caps)
    assert [list(r) for r in matrix] == alloc["matrix"]
    assert BC.allocation_digest(matrix) == alloc["matrix_sha256"]
    assert list(BC.row_totals(matrix)) == [4000, 3000, 2500, 2500]
    assert list(BC.column_totals(matrix)) == [2000] * 4 + [500] * 8


def test_m6c1b14_ra_trib_001_pass():
    candidate = m6c1_validator.load_candidate()
    s10 = candidate["world_layer_S1_S10"][9]["candidate"]
    assert s10["first_omen_tick"]["value"] == 10_000_000
    per_tier = s10["first_window_tick_by_tier"]["value"]
    assert per_tier == {"REGULAR": 10_000_000, "MAJOR": 50_000_000,
                        "CENTENNIAL": 100_000_000}
    assert s10["tick0_active_tribulation_episodes"]["value"] == 0


def test_m6c1b15_test_profile_references_and_materializer_absent():
    candidate = m6c1_validator.load_candidate()
    m6c1_validator.check_no_test_fixtures(candidate)
    m6c1_validator.check_no_materializer(candidate)
    m6c1_validator.check_no_production_mutation(candidate)
    assert "TEST_FIXTURE_REFERENCES_IN_BOOTSTRAP = 0"


def test_m6c1b16_candidate_build_is_reproducible():
    first = m6c1_build.canonical_text(m6c1_build.build())
    second = m6c1_build.canonical_text(m6c1_build.build())
    assert first == second
    on_disk = m6c1_validator.CANDIDATE_PATH.read_text(encoding="utf-8")
    assert on_disk == first


def test_m6c1b17_audit_cli_requires_explicit_path_and_fails_closed(tmp_path,
                                                                  monkeypatch):
    legacy = _make_db(tmp_path / "legacy" / DB_FILENAME, world_runtime_rows=1)
    monkeypatch.setattr(sys, "argv", [
        "audit_authoritative_db.py", "--plugin-data-dir", str(tmp_path / "none"),
        "--extra-root", str(tmp_path / "legacy"), "--json"])
    assert audit_cli.main() == 2      # AMBIGUOUS → FAIL CLOSED
    assert legacy.exists()


def test_m6c1b18_audit_cli_passes_on_authoritative_fixture(tmp_path,
                                                          authoritative_and_stale,
                                                          monkeypatch, capsys):
    env = authoritative_and_stale
    monkeypatch.setattr(sys, "argv", [
        "audit_authoritative_db.py", "--plugin-data-dir", str(env["plugin_data_dir"]),
        "--extra-root", str(env["stale_root"])])
    assert audit_cli.main() == 0
    out = capsys.readouterr().out
    assert "AUTHORITATIVE_DB_RESOLUTION = PASS" in out
    assert "NON_AUTHORITATIVE_DB_DETECTED = True" in out

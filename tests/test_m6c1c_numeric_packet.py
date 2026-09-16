"""M6C.1C — FINAL NUMERIC CANON PACKET 守卫（owner §12/§14/§17/§19）。

纯静态 + 内存：不连数据库、不读 World Seed、不写任何文件、不物化。
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from fractions import Fraction

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "docs/world_creation/M6C1C_NUMERIC_PACKET_DATA.json"
MD = ROOT / "docs/world_creation/M6C1C_FINAL_NUMERIC_CANON_PACKET.md"


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sweep = _load("m6c1c_sweep", "scripts/m6c1c_sweep.py")


@pytest.fixture(scope="module")
def packet() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ structure
def test_m6c1c01_at_most_five_numeric_decisions(packet):
    keys = [k for k in packet if k.startswith("NUMERIC_OD_")]
    assert sorted(keys) == ["NUMERIC_OD_E1", "NUMERIC_OD_P1", "NUMERIC_OD_RE1",
                            "NUMERIC_OD_S1", "NUMERIC_OD_T1"]
    assert packet["OWNER_NUMERIC_DECISION_COUNT"] == len(keys) == 5
    assert packet["OWNER_NUMERIC_DECISION_COUNT"] <= 5


def test_m6c1c02_flags_and_evidence_class(packet):
    assert packet["STATUS"] == "AWAITING_OWNER_FINAL_NUMERIC_CANON_SELECTION"
    assert packet["MATERIALIZER_ALLOWED"] is False
    assert packet["FORMAL_ACTIVATION_ALLOWED"] is False
    assert packet["PROJECTION_EVIDENCE_CLASS"] == \
        "ANALYTIC_REIMPLEMENTATION_OF_FROZEN_STEP_EQUATIONS"
    assert "DEFERRED" in packet["ENGINE_RUN_VERIFICATION"]


def test_m6c1c03_each_decision_has_at_most_three_candidates(packet):
    for key in ("NUMERIC_OD_P1", "NUMERIC_OD_RE1", "NUMERIC_OD_E1",
                "NUMERIC_OD_S1", "NUMERIC_OD_T1"):
        candidates = packet[key]["candidates"]
        assert 1 <= len(candidates) <= 3, key
        prefix = {"NUMERIC_OD_P1": "P", "NUMERIC_OD_RE1": "RE",
                  "NUMERIC_OD_E1": "E", "NUMERIC_OD_S1": "S",
                  "NUMERIC_OD_T1": "T"}[key]
        labels = [c["LABEL"] for c in candidates]
        assert labels == [f"{prefix}-{x}" for x in "ABC"[:len(candidates)]], (key, labels)
        for candidate in candidates:
            assert candidate["CANON_STATUS"] == "NOT_CANON_UNTIL_OWNER_APPROVAL"
            assert candidate["EVIDENCE_CLASS"]
            assert (candidate.get("CONSEQUENCES") or candidate.get("ENVELOPES")
                    or candidate.get("THRESHOLDS") or candidate.get("VALUES"))


def test_m6c1c04_no_test_fixture_values_are_used(packet):
    text = json.dumps(packet, ensure_ascii=False)
    for forbidden in ("TEST_SPECIES", "TEST-SPECIES", "TEST_SOCIAL", "TEST_ECOLOGY",
                      "TEST_PROFILE", "mini_world", "mini-world"):
        assert forbidden not in text, forbidden


def test_m6c1c05_demography_consequences_are_present(packet):
    for candidate in packet["NUMERIC_OD_P1"]["candidates"]:
        k = candidate["CONSEQUENCES"]
        for key in ("expected_lifespan_years", "population_4y", "population_100y",
                    "population_300y", "net_growth_year0", "cohort_rows_total",
                    "capacity_ratio_effect"):
            assert key in k, (candidate["LABEL"], key)
        assert k["population_100y"] > 0 and k["population_300y"] > 0
        # 无立即爆炸 / 无立即灭绝（owner §15）
        assert k["population_4y"] < 3 * 12_000
        assert k["population_4y"] > 12_000 // 3
        assert set(candidate["PROFILE"]) >= {
            "cohort_buckets", "mortality_per_bucket", "fertile_window", "birth_rate",
            "emigration_rate", "migration_weights", "population_capacity"}


def test_m6c1c06_demography_is_near_stationary_and_solved_numerically(packet):
    """第一年净变化必须很小（|net| <= 1% 人口），且 birth_rate 非人为整数。"""
    for candidate in packet["NUMERIC_OD_P1"]["candidates"]:
        net = candidate["CONSEQUENCES"]["net_growth_year0"]
        assert abs(net) <= 120, (candidate["LABEL"], net)
        br = Fraction(candidate["PROFILE"]["birth_rate"])
        assert 0 < br < Fraction(1, 10)


def test_m6c1c07_demography_projection_is_reproducible():
    prof = sweep.demography_profile(61, Fraction(1, 60), 15, 45, Fraction(1))
    br = sweep.solve_stationary_birth_rate(prof)
    prof["birth_rate_exact"] = f"{br.numerator}/{br.denominator}"
    a = sweep.project_population(prof, 100, capacity=None)
    b = sweep.project_population(prof, 100, capacity=None)
    assert a == b
    assert abs(a["net_year1"]) <= 120


def test_m6c1c08_resource_economy_policy_is_ratio_based_and_shortage_free(packet):
    re1 = packet["NUMERIC_OD_RE1"]
    topology = re1["node_topology"]
    assert topology["RESOURCE_NODE_COUNT"] == 7
    assert len(topology["RESOURCE_NODE_KIND_MAP"]) == 7
    assert topology["nodes_for_non_consumption_kinds"] == 0
    assert topology["WHY_MINIMAL"]
    for candidate in re1["candidates"]:
        v, k = candidate["VALUES"], candidate["CONSEQUENCES"]
        assert v["initial_stock"] == v["annual_demand"] * v["buffer_years"]
        assert k["first_year_shortage"] is False
        assert k["shortage_years_in_100"] == 0, candidate["LABEL"]
        assert v["production_per_year"] >= v["annual_demand"] * Fraction(1, 1), \
            "production must at least cover annual demand"


def test_m6c1c09_ecology_is_closed_form_and_trajectories_present(packet):
    for candidate in packet["NUMERIC_OD_E1"]["candidates"]:
        v, k = candidate["VALUES"], candidate["CONSEQUENCES"]
        assert v["pop_pressure_per_person"] == 1
        assert Fraction(v["sensitivity"]) > 0
        assert 0 < k["analytic_fixed_point_share"] <= 1
        assert abs(k["projected_100y_share"]
                   - k["target_equilibrium_share"]) <= 0.03, candidate["LABEL"]
        assert "analytic_fixed_point_share" in k
        assert k["quality_100y"] and k["quality_300y"]
        assert k["quality_min"] <= k["quality_max"]


def test_m6c1c10_social_thresholds_scale_with_population(packet):
    for candidate in packet["NUMERIC_OD_S1"]["candidates"]:
        t = candidate["THRESHOLDS"]
        assert t["MAIN"]["population"] == 2000 and t["SATELLITE"]["population"] == 500
        for label in ("MAIN", "SATELLITE"):
            entry = t[label]
            assert entry["formation_size"] >= 2
            assert entry["households_at_first_step"] == (
                entry["population"] + entry["formation_size"] - 1) // entry["formation_size"]
            assert entry["institution_found_pop"] >= 2
            assert entry["split_threshold_households"] >= 2
        assert t["MAIN"]["institution_found_pop"] >= t["SATELLITE"][
            "institution_found_pop"] / 4


def test_m6c1c11_tribulation_risks_are_not_all_zero(packet):
    for candidate in packet["NUMERIC_OD_T1"]["candidates"]:
        tiers = {e["tier"] for e in candidate["ENVELOPES"]}
        assert tiers == {"REGULAR", "MAJOR", "CENTENNIAL"}
        for entry in candidate["ENVELOPES"]:
            assert entry["population_loss"] > 0
            assert entry["ecology_pressure"] > 0
            assert entry["intensity_range"][0] < entry["intensity_range"][1]
            assert entry["precursor_years"] >= 1          # engine EC-1
        losses = {e["tier"]: e["population_loss"] for e in candidate["ENVELOPES"]}
        assert losses["REGULAR"] < losses["MAJOR"] < losses["CENTENNIAL"]


def test_m6c1c12_periods_and_first_omen_are_unmodified(packet):
    t1 = packet["NUMERIC_OD_T1"]
    assert t1["periods"] == {"REGULAR": 10, "MAJOR": 50, "CENTENNIAL": 100}
    assert t1["first_omen_tick"] == 10_000_000


def test_m6c1c13_markdown_matches_data(packet):
    md = MD.read_text(encoding="utf-8")
    assert "OWNER_NUMERIC_DECISION_COUNT = 5" in md
    for key in ("NUMERIC_OD_P1", "NUMERIC_OD_RE1", "NUMERIC_OD_E1",
                "NUMERIC_OD_S1", "NUMERIC_OD_T1"):
        assert key in md, key
    md_flat = md.replace(",", "")
    for candidate in packet["NUMERIC_OD_P1"]["candidates"]:
        assert candidate["LABEL"] in md
        assert str(candidate["CONSEQUENCES"]["population_100y"]) in md_flat, \
            (candidate["LABEL"], candidate["CONSEQUENCES"]["population_100y"])
    assert "MATERIALIZER_ALLOWED         = FALSE" in md


def test_m6c1c14_no_materializer_or_db_capability():
    validator = _load("m6c1c_validator", "scripts/validate_snapshot_candidate.py")
    validator.check_no_production_mutation(validator.load_candidate())
    source = pathlib.Path(sweep.__file__).read_text(encoding="utf-8")
    for token in ("sqlalchemy", "sqlite3", "SessionLocal", "INSERT INTO",
                  "session.commit", "materialize_world", "bootstrap_world"):
        assert token not in source, token

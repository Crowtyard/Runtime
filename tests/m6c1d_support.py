"""M6C.1D — test-only synthetic bootstrap harness for REAL ENGINE verification.

THIS_IS_NOT_FORMAL_MATERIALIZATION.

* lives under tests/ (never in services/activation, never on the activation path)
* never reads the formal World Seed and never touches the formal DB or live plugin_data
* builds a TEMPORARY SQLite world, activates it through the real activation service
  with a synthetic seed, writes the owner-selected bootstrap payload, then runs the
  REAL production pipeline (TIME -> DEMOGRAPHY -> RESOURCE -> ECONOMY -> ECOLOGY ->
  SOCIAL -> TRIBULATION -> HISTORY) via the real coordinator.

Owner selections (M6C.1C): P-A, RE-A, E-B, S-B, T-B read from the audited machine
payload (docs/world_creation/M6C1C_NUMERIC_PACKET_DATA.json).
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from fractions import Fraction

ROOT = pathlib.Path(__file__).resolve().parents[1]

from XiaoguangBlessedLandRuntime.database.models_world import (  # noqa: E402
    EcologyFeedbackState, EcologyState, EcologyZone, EconomicPressureState,
    PopulationGroup, ProductionRecipe, ProductionState, ResourceNode,
    ResourceProfile, ResourceStock, Settlement, SettlementSocialState,
    SocialFeedbackState, TribulationProfile, TribulationSchedule)
from XiaoguangBlessedLandRuntime.services.simulation.coordinator import (  # noqa: E402
    SimulationCoordinator)
from XiaoguangBlessedLandRuntime.services.simulation.economy import (  # noqa: E402
    EconomyEngine, EconomyProfile)
from XiaoguangBlessedLandRuntime.services.simulation.ecology import (  # noqa: E402
    ECOLOGY_STATE_SCALE, EcologyEngine, EcologyProfile)
from XiaoguangBlessedLandRuntime.services.simulation.population import (  # noqa: E402
    PopulationGroupEngine, SpeciesDemographyProfile)
from XiaoguangBlessedLandRuntime.services.simulation.resource import (  # noqa: E402
    ResourceEngine, ResourceProfile as ResourceProfileSpec)
from XiaoguangBlessedLandRuntime.services.simulation.social import (  # noqa: E402
    SOCIAL_STATE_SCALE, SocialEngine, SocialProfile)
from XiaoguangBlessedLandRuntime.services.simulation.tribulation import (  # noqa: E402
    TribulationEngine, TribulationProfileSpec)
from XiaoguangBlessedLandRuntime.services.simulation.tribulation_adapters import (  # noqa: E402
    DOMAIN_ADAPTERS)

PACKET_DATA = ROOT / "docs" / "world_creation" / "M6C1C_NUMERIC_PACKET_DATA.json"
WORLD_ID = "M6C1D-SYNTHETIC-WORLD"
SIMULATION_VERSION = "0.3.0"

SETTLEMENT_SLOTS = tuple(
    [(f"MAIN-{i:02d}", "MAIN", 2000) for i in range(1, 5)]
    + [(f"SAT-{i:02d}", "SATELLITE", 500) for i in range(1, 9)])
SPECIES = (("Hairy Men", 4_000), ("Rockmen", 3_000),
           ("Mermen", 2_500), ("Mushroommen", 2_500))
CONSUMPTION_KINDS = ("灵田", "药园", "果园", "矿脉", "水源", "林产", "菌类点")


def _load_sweep():
    spec = importlib.util.spec_from_file_location(
        "m6c1d_sweep", ROOT / "scripts" / "m6c1c_sweep.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["m6c1d_sweep"] = module
    spec.loader.exec_module(module)
    return module


sweep = _load_sweep()


def packet() -> dict:
    return json.loads(PACKET_DATA.read_text(encoding="utf-8"))


def candidate(key: str, label: str) -> dict:
    """Read the AUDITED machine payload for one owner-selected candidate."""
    for entry in packet()[f"NUMERIC_OD_{key}"]["candidates"]:
        if entry["LABEL"] == label:
            return entry
    raise KeyError(f"{key}/{label}")


# ------------------------------------------------------------------ demography
def formal_species_profile() -> SpeciesDemographyProfile:
    """P-A payload -> one shared formal SpeciesDemographyProfile (OD-2 = OPTION A)."""
    payload = candidate("P1", "P-A")
    mort = Fraction(payload["PROFILE"]["mortality_per_bucket"])
    lo, hi = payload["PROFILE"]["fertile_window"]
    buckets = payload["PROFILE"]["cohort_buckets"]
    br = Fraction(payload["PROFILE"]["birth_rate"])
    return SpeciesDemographyProfile(
        species_id="FORMAL-SPECIES-001", cohort_buckets=buckets,
        fertile_min_age=lo, fertile_max_age=hi, birth_rate=br,
        mortality_by_bucket=tuple(mort for _ in range(buckets)),
        emigration_rate=Fraction(0),
        migration_weights=(Fraction(1, 2), Fraction(1, 2)))


def demography_registry() -> dict:
    profile = formal_species_profile()
    return {name: profile for name, _ in SPECIES}


def cohort_counts(total: int) -> list[int]:
    """RA-COHORT-001 v1.1 (audited implementation used for the owner payload)."""
    payload = candidate("P1", "P-A")["PROFILE"]
    return sweep.cohort_distribution(int(payload["cohort_buckets"]),
                                     Fraction(payload["mortality_per_bucket"]),
                                     total)


def allocation() -> tuple[tuple[int, ...], ...]:
    from XiaoguangBlessedLandRuntime.services.activation import bootstrap_canon as BC
    return BC.allocate([p for _, p in SPECIES],
                       [c for _, _, c in SETTLEMENT_SLOTS])


# ------------------------------------------------------------------ other domains
def resource_registry() -> dict:
    return {kind: ResourceProfileSpec(
        resource_id=kind, unit="unit", quantity_scale=1_000_000,
        renewability="RENEWABLE", extractability="EXTRACTABLE",
        consumption_category="CONSUMPTION", production_usability="INPUT",
        semantic_version="formal-1.0") for kind in CONSUMPTION_KINDS}


def economy_registry() -> dict:
    payload = candidate("RE1", "RE-A")["VALUES"]
    per_capita = Fraction(payload["per_capita_demand"])
    demand = {kind: per_capita for kind in CONSUMPTION_KINDS}
    return {name: EconomyProfile(profile_id=f"FORMAL-ECONOMY-{name}",
                                 per_capita_demand=demand,
                                 semantic_version="formal-1.0")
            for name, _ in SPECIES}


def ecology_profile() -> EcologyProfile:
    payload = candidate("E1", "E-B")["VALUES"]
    return EcologyProfile(
        profile_id="FORMAL-ECOLOGY-001",
        recovery_rate=Fraction(payload["recovery_rate"]),
        recovery_ceiling=int(payload["recovery_ceiling"]),
        sensitivity=Fraction(payload["sensitivity"]),
        pressure_weights={"population": Fraction(2, 8), "extraction": Fraction(3, 8),
                          "production": Fraction(2, 8), "depletion": Fraction(1, 8)},
        pop_pressure_per_person=int(payload["pop_pressure_per_person"]),
        renewable_regen_minor_per_full_quality=220_000_000,
        thresholds=(800_000, 500_000, 200_000),
        semantic_version="formal-1.0")


def social_profile() -> SocialProfile:
    t = candidate("S1", "S-B")["THRESHOLDS"]["MAIN"]
    return SocialProfile(
        profile_id="FORMAL-SOCIAL-001",
        formation_size=int(t["formation_size"]),
        split_threshold=int(t["split_threshold_households"]),
        lineage_found_generation=3, lineage_found_size=int(t["lineage_found_size"]),
        lineage_split_households=max(2, int(t["split_threshold_households"]) * 2),
        institution_found_pop=int(t["institution_found_pop"]),
        institution_dissolve_pop=int(t["institution_dissolve_pop"]),
        institution_decline_cohesion=500_000, institution_dormant_cohesion=300_000,
        institution_active_cohesion=600_000,
        pressure_weights={"economy": Fraction(4, 8), "ecology": Fraction(3, 8),
                          "mobility": Fraction(1, 8)},
        stress_thresholds=(300_000, 600_000),
        migration_modifier_k=Fraction(1, 2), fertility_context_k=Fraction(1, 4),
        social_support_k=Fraction(1, 2), semantic_version="formal-1.0")


def tribulation_registry() -> dict:
    """T-B payload -> one formal spec per tier (six risk fractions, non-zero)."""
    payload = candidate("T1", "T-B")
    out = {}
    for env in payload["ENVELOPES"]:
        tier = env["tier"]
        out[f"FORMAL-TRIB-{tier}"] = TribulationProfileSpec(
            profile_id=f"FORMAL-TRIB-{tier}", tier=tier, theme=env["theme"],
            intensity_min=int(env["intensity_range"][0]),
            intensity_max=int(env["intensity_range"][1]),
            precursor_steps=int(env["precursor_years"]),
            preparation_steps=int(env["preparation_years"]),
            impact_steps=int(env["impact_years"]),
            recovery_steps=int(env["recovery_years"]),
            population_risk=Fraction(1, 250) if tier == "REGULAR" else
            (Fraction(1, 50) if tier == "MAJOR" else Fraction(1, 20)),
            resource_damage=Fraction(1, 1000) if tier == "REGULAR" else
            (Fraction(1, 200) if tier == "MAJOR" else Fraction(1, 80)),
            inventory_damage=Fraction(1, 500) if tier == "REGULAR" else
            (Fraction(1, 100) if tier == "MAJOR" else Fraction(1, 40)),
            production_disruption=Fraction(1, 500),
            social_displacement=Fraction(1, 500),
            institution_disruption=Fraction(1, 1000),
            ecology_pressure=int(ECOLOGY_STATE_SCALE
                                 * (Fraction(1, 250) if tier == "REGULAR" else
                                    (Fraction(1, 50) if tier == "MAJOR"
                                     else Fraction(1, 20)))),
            succession_rules={"allow_candidate": True, "maturation_steps": 3})
    return out


def build_coordinator() -> SimulationCoordinator:
    """Real production engines wired with the FORMAL (owner-selected) profiles."""
    return SimulationCoordinator(
        [PopulationGroupEngine(profiles=demography_registry()),
         ResourceEngine(profiles=resource_registry()),
         EconomyEngine(profiles=economy_registry()),
         EcologyEngine(profiles={"FORMAL-ECOLOGY-001": ecology_profile()}),
         SocialEngine(profile=social_profile())],
        simulation_version=SIMULATION_VERSION,
        tribulation_engine=TribulationEngine(profiles=tribulation_registry()),
        tribulation_adapters=DOMAIN_ADAPTERS)

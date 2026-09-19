"""M6C.2 — extract the ratified T-B / S-B machine payload for the SNAPSHOT_V1 freeze.

READ-ONLY probe: prints the exact profile values the M6D3 reference run used, so the
approved snapshot can carry them concretely (the materializer must consume the frozen
snapshot rather than any test helper).
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tests import m6c1d_support as S  # noqa: E402

out = {"tribulation": {}, "social": {}, "economy": {}, "ecology": {}}
for profile_id, spec in S.tribulation_registry().items():
    out["tribulation"][profile_id] = {
        "tier": spec.tier, "theme": spec.theme,
        "intensity_min": spec.intensity_min, "intensity_max": spec.intensity_max,
        "precursor_steps": spec.precursor_steps,
        "preparation_steps": spec.preparation_steps,
        "impact_steps": spec.impact_steps,
        "population_risk": "%s/%s" % (spec.population_risk.numerator,
                                      spec.population_risk.denominator),
        "resource_damage": "%s/%s" % (spec.resource_damage.numerator,
                                      spec.resource_damage.denominator),
        "inventory_damage": "%s/%s" % (spec.inventory_damage.numerator,
                                       spec.inventory_damage.denominator),
        "production_disruption": "%s/%s" % (
            spec.production_disruption.numerator,
            spec.production_disruption.denominator),
        "social_displacement": "%s/%s" % (
            spec.social_displacement.numerator,
            spec.social_displacement.denominator),
        "institution_disruption": "%s/%s" % (
            spec.institution_disruption.numerator,
            spec.institution_disruption.denominator),
        "ecology_pressure": spec.ecology_pressure,
        "recovery_steps": spec.recovery_steps,
        "succession_rules": spec.succession_rules,
    }
social = S.social_profile()
out["social"] = {k: (str(v) if not isinstance(v, (dict, list, str, int, bool))
                     else v) for k, v in vars(social).items()} \
    if hasattr(social, "__dict__") else {"repr": repr(social)}
econ = S.economy_registry()
first = next(iter(econ.values()))
out["economy"] = {"profile_count": len(econ),
                  "per_capita_demand": {k: "%s/%s" % (v.numerator, v.denominator)
                                        for k, v in first.per_capita_demand.items()},
                  "profile_id_sample": first.profile_id,
                  "semantic_version": getattr(first, "semantic_version", None)}
eco = S.ecology_profile()
out["ecology"] = {
    "profile_id": eco.profile_id,
    "sensitivity": "%s/%s" % (eco.sensitivity.numerator, eco.sensitivity.denominator),
    "recovery_rate": "%s/%s" % (eco.recovery_rate.numerator,
                                eco.recovery_rate.denominator),
    "recovery_ceiling": eco.recovery_ceiling,
    "pop_pressure_per_person": eco.pop_pressure_per_person,
    "pressure_weights": {k: "%s/%s" % (v.numerator, v.denominator)
                         for k, v in eco.pressure_weights.items()},
    "thresholds": list(eco.thresholds),
    "regen_minor_per_full_quality": eco.renewable_regen_minor_per_full_quality,
    "semantic_version": eco.semantic_version,
}
print(json.dumps(out, ensure_ascii=False, indent=1, default=str))

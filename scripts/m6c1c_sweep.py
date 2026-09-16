"""M6C.1C numeric sweep: frozen-equation projector for the final numeric packet.

READ-ONLY w.r.t. the world: no formal DB, no seed, no materializer, no live.
Every formula mirrors a frozen engine line (cited inline).

EVIDENCE_CLASS = ANALYTIC_REIMPLEMENTATION_OF_FROZEN_STEP_EQUATIONS
(engine-run verification with coordinator + real DB is deferred to the next stage;
all candidates are NOT_CANON_UNTIL_OWNER_APPROVAL)

Usage: python scripts/m6c1c_sweep.py
"""
from __future__ import annotations

import json
import pathlib
from fractions import Fraction

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "world_creation" / "M6C1C_NUMERIC_PACKET_DATA.json"

TICKS_PER_BLESSED_YEAR = 1_000_000     # population.py:41
ECOLOGY_STATE_SCALE = 1_000_000        # ecology.py
INITIAL_TOTAL_POPULATION = 12_000      # owner D-B4
MAIN_POPULATION = 2_000                # owner D-B6
SAT_POPULATION = 500


def cohort_distribution(buckets: int, q: Fraction, total: int) -> list[int]:
    """RA-COHORT-001 v1.1 stationary weights.

    w[b] = (1-q)^b for b < N-1, and w[N-1] = (1-q)^(N-1)/q for the OPEN-ENDED last
    bucket (it accumulates survivors of ages >= N-1, which is what makes
    deaths == births hold exactly).  v1.0 omitted the tail term.
    """
    weights, acc = [], Fraction(1)
    for b in range(buckets):
        weights.append(acc)
        acc *= (Fraction(1) - q)
    weights[-1] = weights[-1] / q
    denom = sum(weights)
    ideals = [Fraction(w * total, denom) for w in weights]
    out = [int(i) for i in ideals]
    residual = total - sum(out)
    order = sorted(range(buckets), key=lambda k: (-(ideals[k] - out[k]), k))
    for k in order[:residual]:
        out[k] += 1
    return out


def demography_profile(buckets: int, q: Fraction, lo: int, hi: int,
                       factor: Fraction) -> dict:
    """Stationary birth_rate: deaths == births (population.py:311-338).

    deaths = q*P ; births = fertile*birth_rate*factor ; factor = (r-1)/r
    => birth_rate* = q*P*r / (fertile*(r-1))
    """
    counts = cohort_distribution(buckets, q, INITIAL_TOTAL_POPULATION)
    fertile = sum(counts[lo:hi + 1])
    pop = sum(counts)
    deaths = Fraction(pop) * q
    br = deaths / (Fraction(fertile) * factor) if fertile else Fraction(0)
    return {"cohort_buckets": buckets, "mortality": str(q),
            "fertile_window": [lo, hi], "cohort_counts": counts, "population": pop,
            "fertile_count": fertile, "deaths_year0": int(deaths),
            "birth_rate_exact": f"{br.numerator}/{br.denominator}",
            "capacity_factor": str(factor),
            "expected_lifespan_years": round(1 / float(q), 2) if q else None}


def project_population(prof: dict, years: int, capacity: int | None,
                       birth_rate: Fraction | None = None) -> dict:
    """Frozen annual step order (population.py:284-339): age -> deaths -> births.

    Aging accumulates into min(b+1, N-1), so the open-ended last bucket keeps its
    own survivors (engine: `aged_new[min(b + years, buckets - 1)] += n`).
    RNG +-1 jitter (population.py:319,337) is excluded (floor-only lower bound).
    """
    n = prof["cohort_buckets"]
    aged = list(prof["cohort_counts"])
    q = Fraction(prof["mortality"])
    br = Fraction(prof["birth_rate_exact"]) if birth_rate is None else birth_rate
    lo, hi = prof["fertile_window"]
    series = []
    for year in range(1, years + 1):
        moved = [0] * n
        for b in range(n):
            if aged[b]:
                moved[min(b + 1, n - 1)] += aged[b]
        aged = moved
        deaths = 0
        for b in range(n):
            c = aged[b]
            if c <= 0:
                continue
            exp = Fraction(c) * q
            d = min(exp.numerator // exp.denominator, c)
            aged[b] = c - d
            deaths += d
        fertile = sum(aged[lo:hi + 1])
        factor = Fraction(1)
        if capacity is not None:
            factor = Fraction(max(capacity - sum(aged), 0), capacity)
        exp = Fraction(fertile) * br * factor
        births = exp.numerator // exp.denominator
        aged[0] += births
        series.append({"year": year, "population": sum(aged), "births": births,
                       "deaths": deaths})
    return {"at_1y": series[0]["population"],
            "net_year1": series[0]["population"] - INITIAL_TOTAL_POPULATION,
            "at_4y": series[3]["population"] if years >= 4 else None,
            "at_100y": series[99]["population"] if years >= 100 else None,
            "at_300y": series[299]["population"] if years >= 300 else None,
            "min": min(p["population"] for p in series),
            "max": max(p["population"] for p in series)}


def solve_stationary_birth_rate(prof: dict, *, capacity: int | None = None) -> Fraction:
    """Bisect birth_rate so that one frozen year leaves the population unchanged."""
    lo, hi = Fraction(0), Fraction(1)
    for _ in range(80):
        mid = (lo + hi) / 2
        net = project_population(prof, 1, capacity, birth_rate=mid)["net_year1"]
        if net > 0:
            hi = mid
        elif net < 0:
            lo = mid
        else:
            return mid
    return (lo + hi) / 2


def economy_candidate(per_capita: Fraction, buffer_years: int,
                      capacity_multiple: Fraction, recipe_input: int,
                      loss: Fraction, labor_per_batch: int) -> dict:
    """Demand = per_capita * pop (economy.py:266-294); batches = min(...) (:188-211)."""
    annual_demand = int(Fraction(INITIAL_TOTAL_POPULATION) * per_capita)
    stock = annual_demand * buffer_years
    batches = int(Fraction(annual_demand) * capacity_multiple / recipe_input)
    produced = int(Fraction(batches * recipe_input) * (Fraction(1) - loss))
    labor_need = batches * labor_per_batch
    return {"per_capita_demand": str(per_capita), "annual_demand": annual_demand,
            "buffer_years": buffer_years, "initial_stock": stock,
            "capacity_multiple": str(capacity_multiple),
            "batches_per_year": batches, "production_per_year": produced,
            "loss": str(loss), "labor_per_batch": labor_per_batch,
            "labor_need": labor_need, "labor_available": INITIAL_TOTAL_POPULATION,
            "labor_limited": labor_need > INITIAL_TOTAL_POPULATION}


def project_stock(econ: dict, years: int) -> dict:
    stock = econ["initial_stock"]
    prod, dem = econ["production_per_year"], econ["annual_demand"]
    series, shortage = [], []
    for year in range(1, years + 1):
        stock += prod - dem
        if stock < 0:
            shortage.append(year)
        series.append(stock)
    return {"at_10y": series[9] if years >= 10 else None,
            "at_100y": series[99] if years >= 100 else None,
            "first_shortage_year": shortage[0] if shortage else None,
            "shortage_years": len(shortage)}


def minimal_node_topology(kinds: tuple[str, ...]) -> dict:
    return {"RESOURCE_NODE_COUNT": len(kinds),
            "RESOURCE_NODE_KIND_MAP": {k: f"NODE-{k}-01" for k in kinds},
            "WHY_MINIMAL": "frozen RESOURCE produces per node; cross-settlement "
                           "transfer moves stock only and cannot create output "
                           "(M2B:102-107) => one node per consumption resource kind "
                           "is the minimum that keeps every economy chain alive; "
                           "extra nodes add output only",
            "nodes_for_non_consumption_kinds": 0}


def ecology_pressure_share(population: int, ppp: int, weights: dict,
                           extraction=Fraction(0), production=Fraction(0),
                           depletion=Fraction(0)) -> Fraction:
    p_pop = min(Fraction(population * ppp), ECOLOGY_STATE_SCALE)
    total = int(weights["population"] * p_pop + weights["extraction"] * extraction
                + weights["production"] * production
                + weights["depletion"] * depletion)
    return Fraction(min(max(total, 0), ECOLOGY_STATE_SCALE), ECOLOGY_STATE_SCALE)


def ecology_equilibrium(P: Fraction, sensitivity: Fraction, rr: Fraction,
                        ceiling: int) -> dict:
    """deg == rec fixed point (ecology.py:262-283)."""
    S = Fraction(ECOLOGY_STATE_SCALE)
    a = P * sensitivity / (2 * S)
    b = rr * (Fraction(1) - P)
    if a == b:
        return {"quality": None, "share": None, "stable": False}
    q = (2 * a * S - b * Fraction(ceiling)) / (a - b)
    qi = max(0, min(ECOLOGY_STATE_SCALE, int(q)))
    return {"quality": qi, "share": round(qi / ECOLOGY_STATE_SCALE, 4),
            "stable": 0 <= q <= ceiling}


def solve_sensitivity(weight_population: Fraction, ppp: int, population: int,
                      target_share: float, rr: Fraction, ceiling: int) -> dict:
    """Closed form for sensitivity given a target equilibrium quality.

    deg = P*sens*(2S-q)/2  (ecology.py:264-267)   [P = total_pressure/S]
    rec = rr*(1-P)*(ceiling-q)                     (ecology.py:274-278)
    => sens = 2*rr*(1-P)*(ceiling-q*) / (P*(2S-q*))
    """
    S = Fraction(ECOLOGY_STATE_SCALE)
    p_pop = min(Fraction(population * ppp), ECOLOGY_STATE_SCALE)
    P = weight_population * p_pop / S
    qs = Fraction(int(target_share * ECOLOGY_STATE_SCALE))
    if P == 0:
        return {"sens": None, "P": Fraction(0), "clamped": False}
    sens = 2 * rr * (Fraction(1) - P) * (Fraction(ceiling) - qs) / (P * (2 * S - qs))
    return {"sens": sens, "P": P,
            "clamped": p_pop >= ECOLOGY_STATE_SCALE}


def project_ecology(P0: Fraction, sensitivity: Fraction, rr: Fraction,
                    ceiling: int, years: int) -> dict:
    """Iterate frozen degradation/recovery with integer quality."""
    quality = ECOLOGY_STATE_SCALE
    series = []
    for _ in range(years):
        vuln = Fraction(2 * ECOLOGY_STATE_SCALE - quality,
                        2 * ECOLOGY_STATE_SCALE)
        deg = int(P0 * ECOLOGY_STATE_SCALE * sensitivity * vuln)
        quality = max(0, quality - deg)
        rec = int(rr * (Fraction(1) - P0) * Fraction(max(ceiling - quality, 0), 1))
        quality = min(ceiling, quality + rec)
        series.append(quality)
    return {"at_100y": series[99] if years >= 100 else None,
            "at_300y": series[299] if years >= 300 else None,
            "min": min(series), "max": max(series)}


def social_thresholds(rule: dict) -> dict:
    out = {}
    for label, pop in (("MAIN", MAIN_POPULATION), ("SATELLITE", SAT_POPULATION)):
        formation = max(2, int(round(pop * rule["formation_share"])))
        households = (pop + formation - 1) // formation
        out[label] = {"population": pop, "formation_size": formation,
                      "households_at_first_step": households,
                      "split_threshold_households": max(2, int(round(
                          households * rule["split_share"]))),
                      "institution_found_pop": max(2, int(round(
                          pop * rule["institution_found_share"]))),
                      "institution_dissolve_pop": max(1, int(round(
                          pop * rule["institution_dissolve_share"]))),
                      "lineage_found_size": max(2, int(round(
                          pop * rule["lineage_found_share"])))}
    return out


def trib_envelope(tier: str, theme: str, lo: int, hi: int, typical: int,
                  pop_risk: Fraction, population: int, stock: int) -> dict:
    """f = intensity/100 scales the six risks (tribulation.py:696-707)."""
    fr = Fraction(typical, 100)
    return {"tier": tier, "theme": theme, "intensity_range": [lo, hi],
            "intensity_typical": typical, "intensity_fraction": str(fr),
            "population_loss": int(Fraction(population) * pop_risk * fr),
            "resource_damage": int(Fraction(stock) * (pop_risk / 4) * fr),
            "inventory_damage": int(Fraction(stock) * (pop_risk / 2) * fr),
            "ecology_pressure": int(Fraction(ECOLOGY_STATE_SCALE) * pop_risk * fr),
            "precursor_years": 1, "preparation_years": 1, "impact_years": 1,
            "recovery_years": 3}


def build() -> dict:
    p_cands = []
    for label, ceiling, q, lo, hi in (("P-A", 60, Fraction(1, 60), 15, 45),
                                      ("P-B", 100, Fraction(1, 100), 15, 50),
                                      ("P-C", 300, Fraction(1, 300), 18, 90)):
        prof = demography_profile(ceiling + 1, q, lo, hi, Fraction(1))
        prof["birth_rate_exact"] = str(solve_stationary_birth_rate(prof))
        prof["birth_rate_exact"] = (lambda f: f"{f.numerator}/{f.denominator}")(
            solve_stationary_birth_rate(prof))
        prof["stationary_birth_rate_solved"] = True
        traj = project_population(prof, 300, capacity=None)   # 无容量法则 → 真驻定
        counts = prof["cohort_counts"]
        capacity_effect = {}
        for ratio in ("125", "150", "200"):
            r = Fraction(int(ratio), 100)
            cap = int(Fraction(INITIAL_TOTAL_POPULATION) * r)
            capacity_effect[f"r={r}"] = {
                "capacity": cap,
                "population_100y": project_population(prof, 100, capacity=cap)["at_100y"],
                "population_300y": project_population(prof, 300, capacity=cap)["at_300y"]}
        p_cands.append({
            "LABEL": label,
            "PROFILE": {"cohort_buckets": prof["cohort_buckets"],
                        "mortality_per_bucket": prof["mortality"],
                        "fertile_window": prof["fertile_window"],
                        "birth_rate": prof["birth_rate_exact"],
                        "emigration_rate": "0",
                        "migration_weights": ["1/2", "1/2"],
                        "population_capacity": "NULL (no capacity law) for the "
                                               "stationary candidate"},
            "CONSEQUENCES": {
                "expected_lifespan_years": prof["expected_lifespan_years"],
                "young_lt15_share": round(sum(counts[:15])
                                          / INITIAL_TOTAL_POPULATION, 4),
                "fertile_share": round(prof["fertile_count"]
                                       / INITIAL_TOTAL_POPULATION, 4),
                "elder_share": round(sum(counts[hi + 1:])
                                     / INITIAL_TOTAL_POPULATION, 4),
                "net_growth_year0": int(Fraction(prof["fertile_count"])
                                        * Fraction(prof["birth_rate_exact"]))
                                    - prof["deaths_year0"],
                "population_4y": traj["at_4y"], "population_100y": traj["at_100y"],
                "population_300y": traj["at_300y"], "trajectory_min": traj["min"],
                "trajectory_max": traj["max"],
                "capacity_ratio_effect": capacity_effect,
                "cohort_rows_total": 48 * prof["cohort_buckets"]},
            "EVIDENCE_CLASS": "ENGINE_CONSTRAINT_DERIVATION (stationary birth_rate) + "
                              "EXPERIMENTAL_CANDIDATE (q, fertile window)",
            "CANON_STATUS": "NOT_CANON_UNTIL_OWNER_APPROVAL"})

    re_cands = []
    for label, buffer_years, mult in (("RE-A", 1, Fraction(11, 10)),
                                      ("RE-B", 2, Fraction(3, 2)),
                                      ("RE-C", 3, Fraction(2))):
        econ = economy_candidate(Fraction(1, 4), buffer_years, mult, 100,
                                 Fraction(1, 20), 10)
        s100 = project_stock(econ, 100)
        re_cands.append({
            "LABEL": label,
            "POLICY": {"buffer_years": buffer_years,
                       "capacity_multiple": str(mult)},
            "VALUES": econ,
            "CONSEQUENCES": {
                "first_year_shortage": econ["initial_stock"]
                + econ["production_per_year"] - econ["annual_demand"] < 0,
                "stock_10y": project_stock(econ, 10)["at_10y"],
                "stock_100y": s100["at_100y"],
                "first_shortage_year": s100["first_shortage_year"],
                "shortage_years_in_100": s100["shortage_years"]},
            "EVIDENCE_CLASS": "DIMENSIONAL_DERIVATION (N years of demand) + "
                              "EXPERIMENTAL_CANDIDATE (per-capita demand, recipe qty)",
            "CANON_STATUS": "NOT_CANON_UNTIL_OWNER_APPROVAL"})

    weights = {"population": Fraction(2, 8), "extraction": Fraction(3, 8),
               "production": Fraction(2, 8), "depletion": Fraction(1, 8)}
    e_cands = []
    for label, target, rr, zones in (("E-A", 0.98, Fraction(1, 25), 1),
                                     ("E-B", 0.95, Fraction(1, 25), 1),
                                     ("E-C", 0.90, Fraction(1, 25), 1)):
        solved = solve_sensitivity(weights["population"], 1, MAIN_POPULATION,
                                   target, rr, ECOLOGY_STATE_SCALE)
        sens = solved["sens"] or Fraction(0)
        P = solved["P"]
        eq = ecology_equilibrium(P, sens, rr, ECOLOGY_STATE_SCALE)
        traj = project_ecology(P, sens, rr, ECOLOGY_STATE_SCALE, 300)
        proj100 = round(traj["at_100y"] / ECOLOGY_STATE_SCALE, 4)
        # 每聚落 1 区（12 区）时单区人口压力更低 → 平衡更高
        P12 = weights["population"] * min(
            Fraction(MAIN_POPULATION * 1), ECOLOGY_STATE_SCALE) / ECOLOGY_STATE_SCALE
        eq12 = ecology_equilibrium(P12, sens, rr, ECOLOGY_STATE_SCALE)
        e_cands.append({
            "LABEL": label,
            "POLICY": {"zone_count": zones, "ppp_semantics":
                       "1 minor pressure unit per person (ppp = 1)",
                       "carrying_capacity":
                           "2 x settlement population (no engine consumer)"},
            "VALUES": {"pop_pressure_per_person": 1,
                       "sensitivity": f"{sens.numerator}/{sens.denominator}",
                       "sensitivity_decimal": round(float(sens), 6),
                       "recovery_rate": str(rr),
                       "recovery_ceiling": ECOLOGY_STATE_SCALE,
                       "pressure_share_at_MAIN": round(float(P), 8)},
            "CONSEQUENCES": {"target_equilibrium_share": target,
                             "analytic_fixed_point_share": eq["share"],
                             "projected_100y_share": proj100,
                             "stable": eq["stable"],
                             "quality_100y": traj["at_100y"],
                             "quality_300y": traj["at_300y"],
                             "quality_min": traj["min"],
                             "quality_max": traj["max"],
                             "equilibrium_if_12_zones": eq12["share"],
                             "solve_note": "clamped" if solved["clamped"]
                                           else "closed-form sensitivity"},
            "EVIDENCE_CLASS": "STATIONARY_STATE_SOLUTION (inverse-solved sensitivity "
                              "for the owner's quality target) + "
                              "ENGINE_CONSTRAINT_DERIVATION",
            "CANON_STATUS": "NOT_CANON_UNTIL_OWNER_APPROVAL"})

    s_cands = []
    for label, rule in (("S-A", {"formation_share": 0.0025, "split_share": 0.5,
                                 "institution_found_share": 0.04,
                                 "institution_dissolve_share": 0.025,
                                 "lineage_found_share": 0.03}),
                        ("S-B", {"formation_share": 0.005, "split_share": 0.4,
                                 "institution_found_share": 0.06,
                                 "institution_dissolve_share": 0.03,
                                 "lineage_found_share": 0.05}),
                        ("S-C", {"formation_share": 0.01, "split_share": 0.3,
                                 "institution_found_share": 0.08,
                                 "institution_dissolve_share": 0.04,
                                 "lineage_found_share": 0.08})):
        s_cands.append({"LABEL": label, "RULE": rule,
                        "THRESHOLDS": social_thresholds(rule),
                        "EVIDENCE_CLASS":
                            "DIMENSIONAL_DERIVATION (population share) + "
                            "OWNER_ALREADY_APPROVED_VALUE (method)",
                        "CANON_STATUS": "NOT_CANON_UNTIL_OWNER_APPROVAL"})

    stock_ref = re_cands[1]["VALUES"]["initial_stock"]
    t_cands = []
    for label, spec in (
            ("T-A", {"REGULAR": (5, 15, 10, Fraction(1, 500)),
                     "MAJOR": (20, 40, 30, Fraction(1, 100)),
                     "CENTENNIAL": (50, 70, 60, Fraction(3, 100))}),
            ("T-B", {"REGULAR": (10, 25, 15, Fraction(1, 250)),
                     "MAJOR": (30, 50, 40, Fraction(1, 50)),
                     "CENTENNIAL": (60, 85, 75, Fraction(1, 20))}),
            ("T-C", {"REGULAR": (20, 40, 30, Fraction(1, 100)),
                     "MAJOR": (45, 70, 60, Fraction(1, 20)),
                     "CENTENNIAL": (80, 100, 90, Fraction(1, 10))})):
        themes = {"REGULAR": "灵气潮汐", "MAJOR": "地脉波动",
                  "CENTENNIAL": "生态失衡"}
        envs = [trib_envelope(t, themes[t], v[0], v[1], v[2], v[3],
                              INITIAL_TOTAL_POPULATION, stock_ref)
                for t, v in spec.items()]
        t_cands.append({"LABEL": label, "ENVELOPES": envs,
                        "EVIDENCE_CLASS":
                            "ENGINE_CONSTRAINT_DERIVATION (f = intensity/100) + "
                            "EXPERIMENTAL_CANDIDATE (intensity, risk ratios)",
                        "CANON_STATUS": "NOT_CANON_UNTIL_OWNER_APPROVAL"})

    return {
        "artifact": "M6C1C_NUMERIC_PACKET_DATA",
        "STATUS": "AWAITING_OWNER_FINAL_NUMERIC_CANON_SELECTION",
        "PROJECTION_EVIDENCE_CLASS":
            "ANALYTIC_REIMPLEMENTATION_OF_FROZEN_STEP_EQUATIONS",
        "ENGINE_RUN_VERIFICATION": "DEFERRED_TO_NEXT_STAGE",
        "MATERIALIZER_ALLOWED": False, "FORMAL_ACTIVATION_ALLOWED": False,
        "OWNER_NUMERIC_DECISION_COUNT": 5,
        "NUMERIC_OD_P1": {
            "name": "DEMOGRAPHY",
            "capacity_semantics":
                "population_capacity factor = max(capacity-pop,0)/capacity "
                "(population.py:187-189,329-332); NULL -> 1; "
                "capacity == initial population -> births = 0",
            "capacity_candidates": ["r = 1.25", "r = 1.5", "r = 2"],
            "stationary_note":
                "RA-COHORT-001 survivor curve IS the stationary distribution for "
                "constant mortality, so the solved birth_rate makes tick=0 net "
                "growth ~ 0",
            "candidates": p_cands},
        "NUMERIC_OD_RE1": {
            "name": "RESOURCE_ECONOMY_BASELINE",
            "demand_basis": "demand = per_capita_demand x pop x 1 blessed year "
                            "(economy.py:266-294), minor units",
            "node_topology": minimal_node_topology(
                ("灵田", "药园", "果园", "矿脉", "水源", "林产", "菌类点")),
            "candidates": re_cands},
        "NUMERIC_OD_E1": {"name": "ECOLOGY",
                          "initial_habitat_quality":
                              "FULL_QUALITY (owner approved)",
                          "candidates": e_cands},
        "NUMERIC_OD_S1": {"name": "SOCIAL_THRESHOLDS",
                          "method": "POPULATION_SCALED_DETERMINISTIC_DERIVATION",
                          "candidates": s_cands},
        "NUMERIC_OD_T1": {"name": "TRIBULATION_PROFILE_INTENSITY",
                          "periods": {"REGULAR": 10, "MAJOR": 50,
                                      "CENTENNIAL": 100},
                          "first_omen_tick": 10_000_000,
                          "candidates": t_cands},
    }


def main() -> int:
    packet = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(packet, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    print("WROTE", OUT)
    for c in packet["NUMERIC_OD_P1"]["candidates"]:
        k = c["CONSEQUENCES"]
        print("P1 %s br=%s lifespan=%s 4y=%s 100y=%s 300y=%s net0=%s rows=%d"
              % (c["LABEL"], c["PROFILE"]["birth_rate"],
                 k["expected_lifespan_years"], k["population_4y"],
                 k["population_100y"], k["population_300y"], k["net_growth_year0"],
                 k["cohort_rows_total"]))
    for c in packet["NUMERIC_OD_RE1"]["candidates"]:
        v, k = c["VALUES"], c["CONSEQUENCES"]
        print("RE1 %s stock0=%s prod=%s dem=%s yr1short=%s stock100=%s short_years=%s"
              % (c["LABEL"], v["initial_stock"], v["production_per_year"],
                 v["annual_demand"], k["first_year_shortage"], k["stock_100y"],
                 k["shortage_years_in_100"]))
    for c in packet["NUMERIC_OD_E1"]["candidates"]:
        v, k = c["VALUES"], c["CONSEQUENCES"]
        print("E1 %s ppp=%s P=%s proj100=%s q100=%s q300=%s"
              % (c["LABEL"], v["pop_pressure_per_person"],
                 v["pressure_share_at_MAIN"], k["projected_100y_share"],
                 k["quality_100y"], k["quality_300y"]))
    for c in packet["NUMERIC_OD_S1"]["candidates"]:
        t = c["THRESHOLDS"]
        print("S1 %s MAIN form=%s hh=%s split=%s inst=%s | SAT form=%s hh=%s inst=%s"
              % (c["LABEL"], t["MAIN"]["formation_size"],
                 t["MAIN"]["households_at_first_step"],
                 t["MAIN"]["split_threshold_households"],
                 t["MAIN"]["institution_found_pop"],
                 t["SATELLITE"]["formation_size"],
                 t["SATELLITE"]["households_at_first_step"],
                 t["SATELLITE"]["institution_found_pop"]))
    for c in packet["NUMERIC_OD_T1"]["candidates"]:
        print("T1 %s %s" % (c["LABEL"], " | ".join(
            "%s pop_loss=%s inv_dmg=%s" % (e["tier"], e["population_loss"],
                                           e["inventory_damage"])
            for e in c["ENVELOPES"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

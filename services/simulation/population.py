# -*- coding: utf-8 -*-
"""POPULATION_GROUP_ENGINE（M2a）—— Aggregate Population Simulation。

恢复自 runtime_design/06：cohort = population_groups 行
（species × settlement × age_cohort）；出生/死亡/迁移率来自可标定 profile；
随机只做概率抽样（派生 seed，DEMOGRAPHY substream）。

M2a 冻结（NEW_PROPOSAL 已标注于 M2A_POPULATION_GROUP_ENGINE.md）：
- 年龄模型：bucket 宽 1 福地年；age_cohort = bucket 序号字符串；buckets 由
  SpeciesDemographyProfile 决定（不硬编码"80 岁死亡"）；亚年区间经
  age_advance_carry_ticks 整数进位（零浮点累计）。
- 内部顺序（进入引擎语义版本）：年龄推进 → 死亡 → 出生 → 迁移 → 守恒对账。
- 出生/死亡/迁移：floor(期望) + Bernoulli(余数)（确定性离散化；counts 恒整数）。
- 出生受 settlement.population_capacity 软约束（logistic 收缩）。
- 迁出从最高 bucket 向下扣减；迁入进入首个 fertile bucket（最大余数法分配）。
- Modifiers：只读 PopulationModifiers（当前 neutral），不查其他引擎 DB。
- 事件：aggregate domain events；绝不逐人产生事件；绝不创建 Persistent Person。
- 零 LLM/网络/wall-clock；零 commit；正式种族 profile=UNCONFIGURED。

population conservation（P_INV_12）：
  ending = starting + births - deaths + immigration - emigration
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from ...domain.errors import WorldRuntimeError
from .contracts import (DomainEventDraft, EngineResult, SimulationContext,
                        StateChange)
from .feedback import (demography_ecology_pressure_modifier,
                       demography_ecology_stress_level,
                       demography_mortality_pressure_modifier,
                       settlement_pressure_stress)

ENGINE_ID = "DEMOGRAPHY"
ENGINE_VERSION = "m2a-1"
DEMOGRAPHY_PROFILE_REF = "TEST_PROFILE_001"
TICKS_PER_BLESSED_YEAR = 1_000_000

EV_BIRTHS = "POPULATION_BIRTHS"
EV_DEATHS = "POPULATION_DEATHS"
EV_MIGRATION = "POPULATION_MIGRATION"


class DemographyProfileUnconfigured(WorldRuntimeError):
    code = "DEMOGRAPHY_UNCONFIGURED"


@dataclass(frozen=True)
class PopulationModifiers:
    """跨引擎只读输入 DTO（M2a 默认 neutral；未来由其他引擎经 coordinator
    staged context 供给）。"""
    food_pressure: Fraction = Fraction(0)
    ecology_pressure: Fraction = Fraction(0)
    social_pressure: Fraction = Fraction(0)
    disaster_pressure: Fraction = Fraction(0)
    external_mortality_modifier: Fraction = Fraction(0)


@dataclass(frozen=True)
class SpeciesDemographyProfile:
    """种族人口学 profile（M2a 仅 synthetic TEST 参数；正式种族 UNCONFIGURED）。

    cohort_buckets：bucket 数 N；bucket i 覆盖 [i, i+1) 福地年，末位 [N-1, ∞)。
    """
    species_id: str
    cohort_buckets: int
    fertile_min_age: int
    fertile_max_age: int  # 含
    birth_rate: Fraction
    mortality_by_bucket: tuple[Fraction, ...]
    emigration_rate: Fraction
    migration_weights: tuple[Fraction, ...]

    def __post_init__(self) -> None:
        if self.cohort_buckets <= 0:
            raise ValueError("cohort_buckets 必须为正")
        if len(self.mortality_by_bucket) != self.cohort_buckets:
            raise ValueError("mortality_by_bucket 长度必须等于 cohort_buckets")
        if sum(self.migration_weights) != 1:
            raise ValueError("migration_weights 必须和为 1")
        if not (0 <= self.fertile_min_age <= self.fertile_max_age):
            raise ValueError("fertile 年龄区间非法")

    def bucket_of(self, age: int) -> int:
        return min(max(age, 0), self.cohort_buckets - 1)

    def fertile_buckets(self) -> range:
        return range(self.bucket_of(self.fertile_min_age),
                     self.bucket_of(self.fertile_max_age) + 1)

    def mortality_of(self, bucket: int) -> Fraction:
        return self.mortality_by_bucket[min(max(bucket, 0),
                                            self.cohort_buckets - 1)]


# TEST_FIXTURE_ONLY：synthetic species 参数（不得作为正式种族 Canon）
TEST_SPECIES_PROFILE = SpeciesDemographyProfile(
    species_id="TEST-SPECIES-001",
    cohort_buckets=40,                # 0..38 逐年 + 39+ 聚合
    fertile_min_age=15, fertile_max_age=39,
    birth_rate=Fraction(3, 50),       # 0.06 / fertile / 年（capacity 收缩前）
    mortality_by_bucket=tuple(
        Fraction(1, 200) if b < 15 else
        (Fraction(1, 250) if b < 35 else
         (Fraction(1, 100) if b < 39 else Fraction(1, 50)))
        for b in range(40)),
    emigration_rate=Fraction(1, 100),
    migration_weights=(Fraction(1, 2), Fraction(1, 2)),
)

SPECIES_PROFILES: dict[str, SpeciesDemographyProfile] = {
    "TEST-SPECIES-001": TEST_SPECIES_PROFILE,
}

# 初始年龄结构（TEST_FIXTURE_ONLY）：bucket 15..39 均匀分布
TEST_INITIAL_BUCKETS = range(15, 40)
TEST_INITIAL_COUNT_A_PER_BUCKET = 12     # 25 buckets × 12 = 300
TEST_INITIAL_COUNT_B_PER_BUCKET = 4      # 25 buckets × 4 = 100


@dataclass(frozen=True)
class GroupStepOutcome:
    """一个 demographic group（settlement × species）的一步结果。"""
    settlement_ref: str | None
    species: str
    start: int
    end: int
    births: int
    deaths: int
    emigrated: int
    immigrated: int
    row_updates: dict[int, int] = field(default_factory=dict)  # row_id -> count
    new_carry_ticks: int = 0


def _bucket_of(age_cohort: str | None) -> int:
    if age_cohort is None:
        return 0
    try:
        return max(int(age_cohort), 0)
    except ValueError:
        return 0


def _settlement_order(ref: str | None) -> int:
    return 0 if ref == "TEST-MAIN-A" else 1


class PopulationGroupEngine:
    """Aggregate Population Group Engine（Engine Protocol 实现）。"""

    engine_id: str = ENGINE_ID
    engine_version: str = ENGINE_VERSION

    def __init__(self, *, profiles: dict[str, SpeciesDemographyProfile]
                 | None = None,
                 modifiers: PopulationModifiers | None = None):
        self._profiles = profiles if profiles is not None else SPECIES_PROFILES
        self._modifiers = modifiers if modifiers is not None \
            else PopulationModifiers()

    def _profile_of(self, species: str) -> SpeciesDemographyProfile:
        profile = self._profiles.get(species)
        if profile is None:
            raise DemographyProfileUnconfigured(
                f"种族 {species!r} 无人口学 profile（正式种族保持 UNCONFIGURED）",
                detail=species)
        return profile

    def simulate(self, ctx: SimulationContext) -> EngineResult:
        staged = ctx.staged
        rows = sorted(
            [r for r in staged.rows("population_groups")],
            key=lambda r: (_settlement_order(r["settlement_ref"]),
                           r["species"], _bucket_of(r["age_cohort"]),
                           r["id"]))
        if not rows:
            return EngineResult(
                engine_id=ENGINE_ID, engine_version=ENGINE_VERSION,
                metrics={"births": 0, "deaths": 0, "immigration": 0,
                         "emigration": 0, "groups": 0})

        capacity = {r["working_name"]: int(r["population_capacity"])
                    for r in staged.rows("settlements")
                    if r.get("population_capacity")}

        group_keys = sorted({(r["settlement_ref"], r["species"])
                             for r in rows},
                            key=lambda k: (_settlement_order(k[0]), k[1]))
        outcomes = [self._step_group(ctx, rows, key[0], key[1],
                                     capacity.get(key[0]))
                    for key in group_keys]
        outcomes = self._allocate_migration(ctx, rows, outcomes)

        proposed: list[StateChange] = []
        events: list[DomainEventDraft] = []
        totals = {"births": 0, "deaths": 0, "immigration": 0, "emigration": 0}
        for oc in outcomes:
            for row_id, new_count in oc.row_updates.items():
                proposed.append(StateChange(
                    table="population_groups", entity_id=row_id,
                    field="count", old_value=None, new_value=new_count))
            totals["births"] += oc.births
            totals["deaths"] += oc.deaths
            totals["immigration"] += oc.immigrated
            totals["emigration"] += oc.emigrated
            if oc.births:
                events.append(DomainEventDraft(
                    engine_id=ENGINE_ID, event_type=EV_BIRTHS,
                    cause={"settlement": oc.settlement_ref},
                    effect={"count": oc.births, "from": oc.start}))
            if oc.deaths:
                events.append(DomainEventDraft(
                    engine_id=ENGINE_ID, event_type=EV_DEATHS,
                    cause={"settlement": oc.settlement_ref},
                    effect={"count": oc.deaths, "from": oc.start}))
            if oc.emigrated or oc.immigrated:
                events.append(DomainEventDraft(
                    engine_id=ENGINE_ID, event_type=EV_MIGRATION,
                    cause={"settlement": oc.settlement_ref},
                    effect={"emigrated": oc.emigrated,
                            "immigrated": oc.immigrated,
                            "from": oc.start}))

        # 每行持久化引擎元数据（参与 state hash：profile/版本/carry/更新刻度）
        for r in rows:
            proposed.append(StateChange(
                table="population_groups", entity_id=r["id"],
                field="age_advance_carry_ticks", old_value=None,
                new_value=_carry_for(r, outcomes)))
            proposed.append(StateChange(
                table="population_groups", entity_id=r["id"],
                field="species_profile_ref", old_value=None,
                new_value=DEMOGRAPHY_PROFILE_REF))
            proposed.append(StateChange(
                table="population_groups", entity_id=r["id"],
                field="demography_version", old_value=None,
                new_value=ENGINE_VERSION))
            proposed.append(StateChange(
                table="population_groups", entity_id=r["id"],
                field="updated_blessed_tick", old_value=None,
                new_value=ctx.blessed_end_tick))

        stress_map = {key[0]: settlement_pressure_stress(ctx.snapshot, key[0])
                      for key in group_keys}
        _order = {"NONE": 0, "LOW": 1, "HIGH": 2}
        max_stress = max((s for s in stress_map.values()), key=_order.get,
                         default="NONE")
        pressured = sum(1 for s in stress_map.values() if s != "NONE")
        max_eco_level = max((demography_ecology_stress_level(
            ctx.snapshot, settlement_ref=key[0]) for key in group_keys),
            default=0)
        return EngineResult(
            engine_id=ENGINE_ID, engine_version=ENGINE_VERSION,
            proposed_changes=proposed, domain_events=events,
            metrics={"births": totals["births"], "deaths": totals["deaths"],
                     "immigration": totals["immigration"],
                     "emigration": totals["emigration"],
                     "groups": len(outcomes),
                     "max_pressure_level": _order[max_stress],
                     "pressured_settlements": pressured,
                     "max_ecology_stress_level": max_eco_level})

    # ------------------------------------------------------------ 内部步骤
    def _step_group(self, ctx: SimulationContext, rows, settlement_ref,
                    species, capacity: int | None) -> GroupStepOutcome:
        group_rows = [r for r in rows
                      if r["settlement_ref"] == settlement_ref
                      and r["species"] == species]
        profile = self._profile_of(species)
        start = sum(r["count"] for r in group_rows)

        delta_ticks = ctx.blessed_end_tick - ctx.blessed_start_tick
        carry = group_rows[0].get("age_advance_carry_ticks", 0) + delta_ticks
        years = carry // TICKS_PER_BLESSED_YEAR
        new_carry = carry % TICKS_PER_BLESSED_YEAR

        bucket_counts: dict[int, int] = {}
        for r in group_rows:
            b = min(_bucket_of(r["age_cohort"]), profile.cohort_buckets - 1)
            bucket_counts[b] = bucket_counts.get(b, 0) + r["count"]

        # 1) 年龄推进
        aged: dict[int, int] = {}
        for b, n in bucket_counts.items():
            target = min(b + years, profile.cohort_buckets - 1)
            aged[target] = aged.get(target, 0) + n
        # 2) 死亡（floor + Bernoulli(余数)；含上一 committed step 的经济压力
        #    与生态压力 —— CROSS_ENGINE_FEEDBACK_LATENCY = NEXT_COMMITTED_STEP，
        #    绝不读取本步 staged ECONOMY/ECOLOGY 结果）
        deaths = 0
        pressure_modifier = demography_mortality_pressure_modifier(
            ctx.snapshot, species=species, settlement_ref=settlement_ref)
        ecology_modifier = demography_ecology_pressure_modifier(
            ctx.snapshot, species=species, settlement_ref=settlement_ref)
        for b in range(profile.cohort_buckets):
            n = aged.get(b, 0)
            if n <= 0:
                continue
            q = profile.mortality_of(b) \
                + self._modifiers.external_mortality_modifier \
                + pressure_modifier + ecology_modifier
            if q < 0:
                q = Fraction(0)
            expected = Fraction(n) * q
            d = expected.numerator // expected.denominator
            frac = expected - d
            if frac > 0 and ctx.rng.chance(float(frac)):
                d += 1
            d = min(d, n)
            aged[b] = n - d
            deaths += d
        # 3) 出生（fertile 总量 × rate × capacity 收缩）
        fertile = sum(aged.get(b, 0) for b in profile.fertile_buckets())
        births = 0
        if fertile > 0:
            factor = Fraction(1)
            if capacity is not None:
                total_after = sum(aged.values())
                room = Fraction(max(capacity - total_after, 0), capacity)
                factor = room
            expected = Fraction(fertile) * profile.birth_rate * factor
            births = expected.numerator // expected.denominator
            frac = expected - births
            if frac > 0 and ctx.rng.chance(float(frac)):
                births += 1
        aged[0] = aged.get(0, 0) + births
        return GroupStepOutcome(
            settlement_ref=settlement_ref, species=species,
            start=start, end=sum(aged.values()), births=births, deaths=deaths,
            emigrated=0, immigrated=0,
            row_updates={r["id"]: aged.get(
                min(_bucket_of(r["age_cohort"]),
                    profile.cohort_buckets - 1), 0) for r in group_rows},
            new_carry_ticks=new_carry)

    def _allocate_migration(self, ctx: SimulationContext, rows,
                            outcomes: list[GroupStepOutcome]
                            ) -> list[GroupStepOutcome]:
        profiles = {oc.species: self._profile_of(oc.species)
                    for oc in outcomes}
        # 迁出（floor + Bernoulli；从最高 bucket 向下扣减）
        emigrated: list[int] = []
        for oc in outcomes:
            profile = profiles[oc.species]
            expected = Fraction(oc.end) * profile.emigration_rate
            e = expected.numerator // expected.denominator
            frac = expected - e
            if frac > 0 and ctx.rng.chance(float(frac)):
                e += 1
            e = min(e, oc.end)
            emigrated.append(e)
        total = sum(emigrated)
        # 最大余数法分配迁入（确定性；进入首个 fertile bucket）
        weights = [profiles[oc.species].migration_weights[
            _settlement_order(oc.settlement_ref)] for oc in outcomes]
        shares = [Fraction(w * total) for w in weights]
        base = [s.numerator // s.denominator for s in shares]
        rem = sorted(range(len(shares)),
                     key=lambda i: (-(shares[i] - base[i]), i))
        allocated = list(base)
        for i in range(total - sum(base)):
            allocated[rem[i % len(rem)]] += 1

        results = []
        for i, oc in enumerate(outcomes):
            updates = dict(oc.row_updates)
            profile = profiles[oc.species]
            group_rows = sorted(
                [r for r in rows
                 if r["settlement_ref"] == oc.settlement_ref
                 and r["species"] == oc.species],
                key=lambda r: _bucket_of(r["age_cohort"]))
            _subtract_from_high_buckets(updates, group_rows, profile,
                                        emigrated[i])
            _add_to_fertile_bucket(updates, group_rows, profile,
                                   allocated[i])
            results.append(GroupStepOutcome(
                settlement_ref=oc.settlement_ref, species=oc.species,
                start=oc.start, end=oc.end - emigrated[i] + allocated[i],
                births=oc.births, deaths=oc.deaths,
                emigrated=emigrated[i], immigrated=allocated[i],
                row_updates=updates, new_carry_ticks=oc.new_carry_ticks))
        return results


def _subtract_from_high_buckets(updates: dict[int, int], group_rows,
                                profile, amount: int) -> None:
    remain = amount
    for r in reversed(group_rows):
        if remain <= 0:
            break
        bucket = min(_bucket_of(r["age_cohort"]), profile.cohort_buckets - 1)
        current = updates.get(r["id"], 0)
        take = min(current, remain)
        updates[r["id"]] = current - take
        remain -= take


def _add_to_fertile_bucket(updates: dict[int, int], group_rows,
                           profile, amount: int) -> None:
    if amount <= 0:
        return
    target_bucket = profile.bucket_of(profile.fertile_min_age)
    for r in group_rows:
        if min(_bucket_of(r["age_cohort"]),
               profile.cohort_buckets - 1) == target_bucket:
            updates[r["id"]] = updates.get(r["id"], 0) + amount
            return


def _carry_for(row: dict, outcomes) -> int:
    for oc in outcomes:
        if oc.settlement_ref == row["settlement_ref"] \
                and oc.species == row["species"]:
            return oc.new_carry_ticks
    return row.get("age_advance_carry_ticks", 0)

# -*- coding: utf-8 -*-
"""ECONOMY_ENGINE（M2b）—— PHYSICAL STOCK-FLOW ECONOMY（无货币/无价格）。

恢复自 runtime_design/08（生产链 STORAGE → CONSUMPTION/RESERVE 环节）：
- 08 号「市场简化模型（价格=基准价×调节因子）」本阶段推迟 —— M2b 只建
  实物 stock-flow 层（NEW_PROPOSAL，见 M2B 文档）；货币/价格/企业/工资/
  利润/税/信贷/所有权/市场出清一律禁止。
- 只写 resource_stocks / production_state / economic_pressure_state；
  不修改人口/资源节点/生态/社会；跨系统影响只经 EconomicPressureSignal
  （committed economic_pressure_state）+ domain events。

M2b 冻结（NEW_PROPOSAL 已标注于 M2B_RESOURCE_ECONOMY_ENGINE.md）：
- 权威数量 = 整数 minor units；库存恒 >= 0；需求超库存 → 形成
  fulfilled_demand + unmet_demand，绝不写负库存（RE_INV_05/06/07）。
- 生产：batches = min(容量进位, 输入库存, 劳动力代理)；input/output/loss
  全部显式整数（RE_INV_12/13）；labor 只按 aggregate population 折算，
  绝不生成职业 NPC/工人名单（§13）。
- 消费：demand = Σ_species(rate × pop × interval)（整数有理，亚年 carry
  持久化于 resource_stocks.consumption_carry）。
- 转移策略（TRANSFER_POLICY_VERSION="m2b-transfer-v1"，NEW_PROPOSAL，
  非市场）：每资源单趟贪心 —— 有库存余量的聚落 → 存在缺口的聚落；
  source_delta = −X、destination_delta = +X，全局净变化 0（RE_INV_10/11）。
- 短缺：ECONOMY STATE（unmet/ratio/sustained/stress），不是"饥荒/战争/
  瘟疫"叙事；surplus 同样只是机器状态。
- 经济压力 = committed authoritative state（economic_pressure_state）；
  DEMOGRAPHY 于下一 committed step 经 snapshot 读取
  （CROSS_ENGINE_FEEDBACK_LATENCY = NEXT_COMMITTED_STEP）。
- 引擎零 RNG（确定性规则优先，§45）；零 commit / LLM / 网络 / wall-clock。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction

from ...domain.errors import WorldRuntimeError
from .contracts import (DomainEventDraft, EngineResult, SimulationContext,
                        StateChange)

ENGINE_ID = "ECONOMY"
ENGINE_VERSION = "m2b-economy-1"
TICKS_PER_BLESSED_YEAR = 1_000_000
TRANSFER_POLICY_VERSION = "m2b-transfer-v1"

EV_PRODUCTION = "PRODUCTION_COMPLETED"
EV_CONSUMPTION = "CONSUMPTION_FULFILLED"
EV_SHORTAGE = "RESOURCE_SHORTAGE"
EV_TRANSFER = "RESOURCE_TRANSFERRED"

SUSTAINED_SHORTAGE_LOW_THRESHOLD = 5
STRESS_NONE, STRESS_LOW, STRESS_HIGH = "NONE", "LOW", "HIGH"


class EconomyProfileUnconfigured(WorldRuntimeError):
    code = "ECONOMY_UNCONFIGURED"


class EconomyStateInconsistent(WorldRuntimeError):
    code = "ECONOMY_STATE_INCONSISTENT"


@dataclass(frozen=True)
class EconomyProfile:
    """种族经济消费 profile（M2b 仅 synthetic TEST；正式种族 UNCONFIGURED）。

    per_capita_demand：resource_id → Fraction（canonical units / 人 / 福地年）。
    """
    profile_id: str
    per_capita_demand: dict[str, Fraction] = field(default_factory=dict)
    semantic_version: str = "test-economy-1"


# TEST_FIXTURE_ONLY：synthetic economy profile（不得作为正式种族 Canon）
TEST_ECONOMY_PROFILE = EconomyProfile(
    profile_id="TEST-ECONOMY-PROFILE-001",
    per_capita_demand={"TEST-RESOURCE-002": Fraction(7, 6)},
    semantic_version="test-economy-1")

SPECIES_ECONOMY_PROFILES: dict[str, EconomyProfile] = {
    "TEST-SPECIES-001": TEST_ECONOMY_PROFILE,
}

# stock 行 ledger 字段（增量累加；每行每字段恰 1 条 StateChange）
_CUM_FIELDS = ("cum_extracted_minor", "cum_produced_minor", "cum_input_minor",
               "cum_imported_minor", "cum_exported_minor", "cum_consumed_minor",
               "cum_lost_minor")


def _empty_delta() -> dict:
    return {"quantity": 0, **{f: 0 for f in _CUM_FIELDS}}


class EconomyEngine:
    """Aggregate Physical Economy Engine（Engine Protocol 实现）。"""

    engine_id: str = ENGINE_ID
    engine_version: str = ENGINE_VERSION

    def __init__(self, *, profiles: dict[str, EconomyProfile] | None = None,
                 extra_draws: int = 0):
        """extra_draws：测试专用 —— 额外消耗 RNG 证明 substream 独立性
        （RB35）；引擎算法本身零 RNG。"""
        self._profiles = profiles if profiles is not None \
            else SPECIES_ECONOMY_PROFILES
        self._extra_draws = extra_draws

    def _profile_of(self, species: str) -> EconomyProfile:
        profile = self._profiles.get(species)
        if profile is None:
            raise EconomyProfileUnconfigured(
                f"种族 {species!r} 无经济消费 profile（正式种族保持 UNCONFIGURED）",
                detail=species)
        return profile

    # ------------------------------------------------------------ simulate
    def simulate(self, ctx: SimulationContext) -> EngineResult:
        staged = ctx.staged
        settlements = sorted(
            [s for s in staged.rows("settlements")
             if s.get("working_name")],
            key=lambda s: s["working_name"])
        if ctx.crash_after == "mid:ECONOMY":
            raise RuntimeError("crash: mid:ECONOMY")
        # 测试专用：额外 RNG 消耗（RB35 substream 独立性证明；算法本身零 RNG）
        for _ in range(self._extra_draws):
            ctx.rng.randint(0, 1_000_000)

        species_profiles: dict[str, EconomyProfile] = {}
        for g in staged.rows("population_groups"):
            species_profiles.setdefault(g["species"],
                                        self._profile_of(g["species"]))

        population = {s["working_name"]: sum(
            int(g["count"]) for g in staged.rows("population_groups")
            if g.get("settlement_ref") == s["working_name"])
            for s in settlements}

        resource_profiles = {p["resource_id"]: p for p in staged.rows(
            "resource_profiles")}
        stocks = {(r["settlement_ref"], r["resource_profile_ref"]): r
                  for r in staged.rows("resource_stocks")}
        recipes = sorted(staged.rows("production_recipes"),
                         key=lambda r: r["recipe_id"])
        prod_state = {(p["settlement_ref"], p["recipe_ref"]): p
                      for p in staged.rows("production_state")}
        pressure = {(p["settlement_ref"], p["resource_profile_ref"]): p
                    for p in staged.rows("economic_pressure_state")}

        proposed: list[StateChange] = []
        events: list[DomainEventDraft] = []
        metrics = {"production_input_minor": 0, "production_output_minor": 0,
                   "loss_minor": 0, "demand_minor": 0,
                   "fulfilled_minor": 0, "unmet_minor": 0,
                   "imported_minor": 0, "exported_minor": 0,
                   "transfer_quantity_minor": 0, "transfers": 0,
                   "production_batches": 0, "shortage_pairs": 0}
        deltas: dict[tuple[str, str], dict] = {k: _empty_delta()
                                               for k in stocks}
        demand_carry_sets: dict[tuple[str, str], int] = {}

        def stock_of(settlement: str, ref: str) -> dict | None:
            return stocks.get((settlement, ref))

        def require_stock(settlement: str, ref: str) -> dict:
            row = stock_of(settlement, ref)
            if row is None:
                raise EconomyStateInconsistent(
                    f"聚落 {settlement} 缺资源库存行 {ref}",
                    detail=(settlement, ref))
            return row

        # ---- Phase A：开采入账 + 生产（每聚落）
        for srow in settlements:
            sref = srow["working_name"]
            # 开采入账（RESOURCE 本步 staged 结果）
            for node in staged.rows("resource_nodes"):
                if node.get("settlement_relation") != sref:
                    continue
                ref = node.get("resource_profile_ref")
                amount = int(node.get("last_extracted_minor", 0))
                if not ref or amount <= 0:
                    continue
                require_stock(sref, ref)
                deltas[(sref, ref)]["quantity"] += amount
                deltas[(sref, ref)]["cum_extracted_minor"] += amount

            # 生产
            for recipe in recipes:
                ps_row = prod_state.get((sref, recipe["recipe_id"]))
                if ps_row is None:
                    continue  # 未登记生产的聚落×recipe
                limits: list[int] = []
                capacity = recipe.get("capacity_batches_per_year")
                new_carry = 0
                if capacity is not None and int(capacity) > 0:
                    carry = int(ps_row["production_carry"]) \
                        + int(capacity) * (ctx.blessed_end_tick
                                           - ctx.blessed_start_tick)
                    limits.append(carry // TICKS_PER_BLESSED_YEAR)
                    new_carry = carry % TICKS_PER_BLESSED_YEAR
                if recipe.get("input_resource_ref") \
                        and recipe.get("input_qty_minor"):
                    avail = int(stocks[(sref, recipe["input_resource_ref"])][
                        "quantity"]) \
                        + deltas[(sref, recipe["input_resource_ref"])][
                            "quantity"]
                    limits.append(avail // int(recipe["input_qty_minor"]))
                labor_per_batch = int(recipe.get("labor_per_batch") or 0)
                if labor_per_batch > 0:
                    limits.append(population.get(sref, 0) // labor_per_batch)
                batches = min(limits) if limits else 0

                input_qty = int(recipe.get("input_qty_minor") or 0)
                output_qty = int(recipe.get("output_qty_minor") or 0)
                input_used = batches * input_qty
                output_gross = batches * output_qty
                loss_num = int(recipe.get("loss_num") or 0)
                loss_den = int(recipe.get("loss_den") or 1)
                loss = output_gross * loss_num // loss_den \
                    if loss_den > 0 else 0
                output_net = output_gross - loss

                if recipe.get("input_resource_ref") and input_used > 0:
                    in_ref = recipe["input_resource_ref"]
                    require_stock(sref, in_ref)
                    deltas[(sref, in_ref)]["quantity"] -= input_used
                    deltas[(sref, in_ref)]["cum_input_minor"] += input_used
                if recipe.get("output_resource_ref") and output_gross > 0:
                    out_ref = recipe["output_resource_ref"]
                    require_stock(sref, out_ref)
                    deltas[(sref, out_ref)]["quantity"] += output_net
                    # ledger 语义（§18）：cum_produced = 配方总产出（gross），
                    # loss 单独计 —— ending = starting + produced − loss − …
                    deltas[(sref, out_ref)]["cum_produced_minor"] \
                        += output_gross
                    if loss > 0:
                        deltas[(sref, out_ref)]["cum_lost_minor"] += loss

                proposed.append(StateChange(
                    table="production_state", entity_id=ps_row["id"],
                    field="production_carry", old_value=None,
                    new_value=new_carry))
                proposed.append(StateChange(
                    table="production_state", entity_id=ps_row["id"],
                    field="engine_version", old_value=None,
                    new_value=ENGINE_VERSION))
                proposed.append(StateChange(
                    table="production_state", entity_id=ps_row["id"],
                    field="updated_blessed_tick", old_value=None,
                    new_value=ctx.blessed_end_tick))

                metrics["production_input_minor"] += input_used
                metrics["production_output_minor"] += output_net
                metrics["loss_minor"] += loss
                metrics["production_batches"] += batches
                if batches > 0:
                    events.append(DomainEventDraft(
                        engine_id=ENGINE_ID, event_type=EV_PRODUCTION,
                        cause={"recipe_id": recipe["recipe_id"],
                               "settlement": sref},
                        effect={"batches": batches,
                                "input_minor": input_used,
                                "output_minor": output_net,
                                "loss_minor": loss}))

        # ---- Phase B：需求（每聚落 × 消费类资源；整数有理 + 持久 carry）
        demands: dict[tuple[str, str], int] = {}
        for srow in settlements:
            sref = srow["working_name"]
            pop_by_species: dict[str, int] = {}
            for g in staged.rows("population_groups"):
                if g.get("settlement_ref") == sref:
                    pop_by_species[g["species"]] = \
                        pop_by_species.get(g["species"], 0) + int(g["count"])
            for ref, profile in resource_profiles.items():
                if not profile.get("consumption_category"):
                    continue
                row = require_stock(sref, ref)
                rate = Fraction(0)
                for species, pop in pop_by_species.items():
                    econ = species_profiles.get(species)
                    if econ is None:
                        econ = self._profile_of(species)
                    rate += econ.per_capita_demand.get(ref, Fraction(0)) \
                        * Fraction(pop)
                scale = int(profile["quantity_scale"])
                num = rate.numerator * scale
                den = rate.denominator
                delta = ctx.blessed_end_tick - ctx.blessed_start_tick
                carry = int(row["consumption_carry"]) + num * delta
                demands[(sref, ref)] = carry // (
                    den * TICKS_PER_BLESSED_YEAR)
                demand_carry_sets[(sref, ref)] = carry % (
                    den * TICKS_PER_BLESSED_YEAR)

        # ---- Phase C：聚落间转移（每资源单趟贪心；净变化 0；无双花）
        for ref in sorted({r["resource_profile_ref"]
                           for r in stocks.values()}):
            balances = []
            for srow in settlements:
                sref = srow["working_name"]
                stock_now = int(stocks[(sref, ref)]["quantity"]) \
                    + deltas[(sref, ref)]["quantity"]
                demand_now = demands.get((sref, ref), 0)
                balances.append((sref, stock_now - demand_now))
            receivers = [(s, -b) for s, b in balances if b < 0]
            donor_surplus = {s: b for s, b in balances if b > 0}
            for recv_s, need in receivers:
                for donor_s in list(donor_surplus):
                    surplus = donor_surplus[donor_s]
                    if need <= 0 or surplus <= 0:
                        continue
                    x = min(need, surplus)
                    donor_surplus[donor_s] = surplus - x
                    need -= x
                    require_stock(donor_s, ref)
                    require_stock(recv_s, ref)
                    deltas[(donor_s, ref)]["quantity"] -= x
                    deltas[(donor_s, ref)]["cum_exported_minor"] += x
                    deltas[(recv_s, ref)]["quantity"] += x
                    deltas[(recv_s, ref)]["cum_imported_minor"] += x
                    events.append(DomainEventDraft(
                        engine_id=ENGINE_ID, event_type=EV_TRANSFER,
                        cause={"from_settlement": donor_s,
                               "policy_version": TRANSFER_POLICY_VERSION},
                        effect={"to_settlement": recv_s,
                                "resource_profile_ref": ref,
                                "quantity_minor": x}))
                    metrics["imported_minor"] += x
                    metrics["exported_minor"] += x
                    metrics["transfer_quantity_minor"] += x
                    metrics["transfers"] += 1

        # ---- Phase D：消费满足 + 压力状态
        for srow in settlements:
            sref = srow["working_name"]
            for (pset, pref), demand_now in sorted(demands.items()):
                if pset != sref:
                    continue
                row = require_stock(sref, pref)
                available = int(row["quantity"]) + deltas[(sref, pref)][
                    "quantity"]
                fulfilled = min(demand_now, available)
                unmet = demand_now - fulfilled
                deltas[(sref, pref)]["quantity"] -= fulfilled
                deltas[(sref, pref)]["cum_consumed_minor"] += fulfilled

                events.append(DomainEventDraft(
                    engine_id=ENGINE_ID, event_type=EV_CONSUMPTION,
                    cause={"settlement": sref,
                           "resource_profile_ref": pref},
                    effect={"demand_minor": demand_now,
                            "fulfilled_minor": fulfilled,
                            "unmet_minor": unmet}))
                metrics["demand_minor"] += demand_now
                metrics["fulfilled_minor"] += fulfilled
                metrics["unmet_minor"] += unmet

                p_row = pressure.get((sref, pref))
                if p_row is None:
                    raise EconomyStateInconsistent(
                        f"聚落 {sref} 缺压力行 {pref}", detail=(sref, pref))
                g = math.gcd(unmet, demand_now) if demand_now > 0 else 1
                ratio_num = unmet // g if g else 0
                ratio_den = demand_now // g if g else 1
                sustained = int(p_row["sustained_shortage_steps"]) + 1 \
                    if unmet > 0 else 0
                stress = STRESS_NONE if unmet == 0 else (
                    STRESS_HIGH
                    if sustained >= SUSTAINED_SHORTAGE_LOW_THRESHOLD
                    else STRESS_LOW)
                for field_name, value in (
                        ("demand_minor", demand_now),
                        ("fulfilled_minor", fulfilled),
                        ("unmet_minor", unmet),
                        ("shortage_ratio_num", ratio_num),
                        ("shortage_ratio_den", ratio_den),
                        ("sustained_shortage_steps", sustained),
                        ("stress_level", stress),
                        ("engine_version", ENGINE_VERSION),
                        ("updated_blessed_tick", ctx.blessed_end_tick)):
                    proposed.append(StateChange(
                        table="economic_pressure_state",
                        entity_id=p_row["id"], field=field_name,
                        old_value=None, new_value=value))
                if unmet > 0:
                    metrics["shortage_pairs"] += 1
                    events.append(DomainEventDraft(
                        engine_id=ENGINE_ID, event_type=EV_SHORTAGE,
                        cause={"settlement": sref,
                               "resource_profile_ref": pref},
                        effect={"unmet_minor": unmet,
                                "demand_minor": demand_now,
                                "shortage_ratio_num": ratio_num,
                                "shortage_ratio_den": ratio_den,
                                "sustained_steps": sustained}))

        # ---- 每库存行恰 1 组 StateChange（quantity + cum 计数器 + carry）
        for k, row in stocks.items():
            d = deltas[k]
            if d["quantity"] != 0:
                proposed.append(StateChange(
                    table="resource_stocks", entity_id=row["id"],
                    field="quantity", old_value=None,
                    new_value=int(row["quantity"]) + d["quantity"]))
            for f in _CUM_FIELDS:
                if d[f] != 0:
                    proposed.append(StateChange(
                        table="resource_stocks", entity_id=row["id"],
                        field=f, old_value=None,
                        new_value=int(row[f]) + d[f]))
            if k in demand_carry_sets:
                proposed.append(StateChange(
                    table="resource_stocks", entity_id=row["id"],
                    field="consumption_carry", old_value=None,
                    new_value=demand_carry_sets[k]))
            if d["quantity"] != 0 or k in demand_carry_sets:
                proposed.append(StateChange(
                    table="resource_stocks", entity_id=row["id"],
                    field="engine_version", old_value=None,
                    new_value=ENGINE_VERSION))
                proposed.append(StateChange(
                    table="resource_stocks", entity_id=row["id"],
                    field="updated_blessed_tick", old_value=None,
                    new_value=ctx.blessed_end_tick))

        return EngineResult(
            engine_id=ENGINE_ID, engine_version=ENGINE_VERSION,
            proposed_changes=proposed, domain_events=events,
            draw_count=self._extra_draws, metrics=metrics)
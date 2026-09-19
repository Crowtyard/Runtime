"""M6C.1 — SNAPSHOT_V1_CANDIDATE 的 BOOTSTRAP CONFIGURATION 层（确定性分配规则）。

本模块**不是** materializer（owner §26）：
  * 不连接/读/写任何数据库，不 import `database.*`、不 import 任何冻结引擎；
  * 不读 World Seed、不读正式库、不构造引擎、不产生任何持久化行；
  * 只做一件事：把**主人已批准**的输入（群体人数、聚落槽位容量）按版本化规则
    确定性地展开为 (群体 × 聚落) 名额矩阵，使候选文档中的每一个派生数字都能被
    **独立重算**（owner §7/§23 可独立复算；§24 版本化）。

规则 RA-ALLOC-001 v1.0（owner §21：确定性最大余额、固定顺序、固定 tie-break、
无 RNG、无 hash(seed)、逐字节相同）：

  输入：GROUP_POPULATIONS（有序，Σ == N）、SETTLEMENT_SLOTS（有序，Σ 容量 == N）
  阶段 A（列内最大余额，锁定"每聚落人口"）：
      逐列 j（固定顺序 MAIN-01..SAT-08）计算精确有理数 ideal[r][j] = P_r * T_j / N，
      先取 floor；列余额 R_j = T_j - Σ floor 分配给"小数余额最大"的行；
      余额相同 → 行下标小者优先。→ Σ_r alloc[r][j] == T_j 严格成立。
  阶段 B（行边际修复，锁定"群体人数"）：
      若某行和 != P_r：取行下标最小的"超出"行为 donor、行下标最小的"不足"行为
      receiver；在 donor 拥有正数的列中，选"偏离代价最小"的列搬运 1 人
      （代价 = |alloc-ideal| 的增量之和；相同 → 列下标小者优先）。
      列内搬运不改变任何列和。→ Σ_j alloc[r][j] == P_r 严格成立。
  性质：全整数 + `fractions.Fraction`，无浮点、无随机、无迭代上限依赖；
        双边际（行 = 群体人数、列 = 聚落人口）同时严格精确；
        输入相同 → 输出逐字节相同（`allocation_digest` 稳定）。

规则 RA-COHORT-001 v1.1（初始 cohort 权重；owner M6C.2 正式批准
`APPROVED_PRODUCTION_BOOTSTRAP_RULE`，"derive, don't invent"）：
  仅由**冻结引擎已定义的**人口学结构参数（`SpeciesDemographyProfile.mortality_by_bucket`
  与 `cohort_buckets`）推出初始年龄分布形状：
      weight[b]   = Π_{k<b} (1 - mortality[k])                （存活曲线，精确有理数）
      weight[N-1] = weight[N-1] * (1 / mortality[N-1])        （**open-ended 末桶累计**：
                     age ≥ N-1 的 survivor 全部累计到最后 bucket，与引擎
                     `bucket_of(age) = min(age, N-1)` + `mortality_of` clamp 语义一致）
      count[b]    = 最大余额整数分配(Σ count == 该 (聚落×物种) 人口，固定 tie-break)
  说明：这是**初始条件规则**，不声称任何平衡态/增长率结论；它不使用 `birth_rate`，
  不做迭代求解，不引入 RNG。
  v1.0（截断末桶、无尾部累计）**已被 owner 批准取代**，其实现以
  `cohort_counts_v1_0` + `RULE_COHORT_VERSION_SUPERSEDED` 显式保留（provenance），
  禁止再用于正式 bootstrap；**不得原地改语义**（版本纪律见文末）。

版本纪律：任何语义变更必须升 `RULE_VERSION` 并重算 digest；禁止原地改语义。
"""
from __future__ import annotations

import hashlib
import json
from fractions import Fraction
from typing import Iterable, Mapping, Sequence

# --------------------------------------------------------------------------
# 规则标识
# --------------------------------------------------------------------------
RULE_ALLOC_ID = "RA-ALLOC-001"
RULE_ALLOC_VERSION = "1.0"
RULE_COHORT_ID = "RA-COHORT-001"
#: M6C.2：owner 正式批准 `RA-COHORT-001 v1.1 = APPROVED_PRODUCTION_BOOTSTRAP_RULE`
#: （open-ended final bucket = 年龄 ≥ N-1 的 survivor 全部累计到最后 bucket）。
#: v1.0 的截断语义**未**被静默改写：它以 `cohort_counts_v1_0` 显式保留为
#: SUPERSEDED_PRODUCTION_RULE_PROVENANCE，仅用于历史复算/对照。
RULE_COHORT_VERSION = "1.1"
RULE_COHORT_VERSION_SUPERSEDED = "1.0"

# --------------------------------------------------------------------------
# 主人已批准输入（M6C.1 owner directive；SOURCE_CLASS = OWNER_APPROVED）
# 这些常量本身**不**构成 SNAPSHOT_V1：它们是候选构造的输入记录。
# --------------------------------------------------------------------------
OWNER_APPROVED_INITIAL_TOTAL_POPULATION = 12_000
OWNER_APPROVED_MAIN_SETTLEMENT_COUNT = 4
OWNER_APPROVED_SATELLITE_SETTLEMENT_COUNT = 8
OWNER_APPROVED_MAIN_SETTLEMENT_POPULATION = 2_000
OWNER_APPROVED_SATELLITE_SETTLEMENT_POPULATION = 500

#: 群体槽位（有序；identity 沿用既有 group 槽位，不重命名）
GROUP_POPULATIONS: tuple[tuple[str, int], ...] = (
    ("GROUP_1", 4_000),
    ("GROUP_2", 3_000),
    ("GROUP_3", 2_500),
    ("GROUP_4", 2_500),
)

#: 聚落槽位（有序；`WORKING_NAME_ONLY` —— 非最终世界内名称）
SETTLEMENT_SLOTS: tuple[tuple[str, str, int], ...] = (
    ("MAIN-01", "MAIN", 2_000),
    ("MAIN-02", "MAIN", 2_000),
    ("MAIN-03", "MAIN", 2_000),
    ("MAIN-04", "MAIN", 2_000),
    ("SAT-01", "SATELLITE", 500),
    ("SAT-02", "SATELLITE", 500),
    ("SAT-03", "SATELLITE", 500),
    ("SAT-04", "SATELLITE", 500),
    ("SAT-05", "SATELLITE", 500),
    ("SAT-06", "SATELLITE", 500),
    ("SAT-07", "SATELLITE", 500),
    ("SAT-08", "SATELLITE", 500),
)

#: 灾劫周期（主人已批准 · 福地年）。仅是排期输入，不是"已启动倒计时"。
OWNER_APPROVED_TRIBULATION_PERIODS: tuple[tuple[str, int], ...] = (
    ("REGULAR", 10),
    ("MAJOR", 50),
    ("CENTENNIAL", 100),
)


class AllocationError(AssertionError):
    """分配输入/输出不满足本模块声明的双边际不变式。"""


def _frac_matrix(group_pops: Sequence[int],
                 slot_caps: Sequence[int]) -> list[list[Fraction]]:
    total = sum(group_pops)
    if total != sum(slot_caps):
        raise AllocationError(
            f"population mismatch: groups={total} slots={sum(slot_caps)}")
    if total <= 0:
        raise AllocationError("total population must be positive")
    return [[Fraction(p * c, total) for c in slot_caps] for p in group_pops]


def allocate(group_pops: Sequence[int],
             slot_caps: Sequence[int]) -> tuple[tuple[int, ...], ...]:
    """RA-ALLOC-001 v1.0：返回 (群体 × 聚落) 整数名额矩阵，双边际严格精确。"""
    ideal = _frac_matrix(group_pops, slot_caps)
    rows = len(group_pops)
    cols = len(slot_caps)

    # ---- 阶段 A：列内最大余额（锁定列和 = 聚落人口）----
    matrix = [[0] * cols for _ in range(rows)]
    for j in range(cols):
        floors = [int(ideal[r][j]) for r in range(rows)]     # Fraction -> floor
        for r in range(rows):
            matrix[r][j] = floors[r]
        residual = slot_caps[j] - sum(floors)
        # 固定 tie-break：余额降序、行下标升序
        order = sorted(range(rows),
                       key=lambda r: (-(ideal[r][j] - floors[r]), r))
        for r in order[:residual]:
            matrix[r][j] += 1

    # ---- 阶段 B：行边际修复（锁定行和 = 群体人数；列内搬运不改列和）----
    guard = 0
    guard_limit = total_moves = sum(group_pops) * rows + cols
    while True:
        guard += 1
        if guard > guard_limit:
            raise AllocationError("row-marginal repair did not converge")
        row_sums = [sum(matrix[r]) for r in range(rows)]
        donors = [r for r in range(rows) if row_sums[r] > group_pops[r]]
        receivers = [r for r in range(rows) if row_sums[r] < group_pops[r]]
        if not donors:
            break
        donor = donors[0]
        receiver = receivers[0]
        best_j = None
        best_cost = None
        for j in range(cols):
            if matrix[donor][j] <= 0:
                continue
            cost = ((ideal[donor][j] - (matrix[donor][j] - 1))
                    + ((matrix[receiver][j] + 1) - ideal[receiver][j]))
            if best_cost is None or cost < best_cost:
                best_cost = cost
                best_j = j
        if best_j is None:  # pragma: no cover - 不可达（donor 行和 > 0）
            raise AllocationError("no movable cell for donor row")
        matrix[donor][best_j] -= 1
        matrix[receiver][best_j] += 1
        total_moves += 1

    out = tuple(tuple(r) for r in matrix)
    verify_allocation(out, group_pops, slot_caps)
    return out


def verify_allocation(matrix: Sequence[Sequence[int]],
                      group_pops: Sequence[int],
                      slot_caps: Sequence[int]) -> None:
    """双边际不变式 + 非负 + 整数性。任何违反 raise AllocationError。"""
    rows = len(group_pops)
    cols = len(slot_caps)
    if len(matrix) != rows or any(len(r) != cols for r in matrix):
        raise AllocationError("matrix shape mismatch")
    for r in range(rows):
        for j in range(cols):
            cell = matrix[r][j]
            if not isinstance(cell, int) or cell < 0:
                raise AllocationError(f"invalid cell at ({r},{j}): {cell!r}")
    for r in range(rows):
        if sum(matrix[r]) != group_pops[r]:
            raise AllocationError(
                f"row {r} total {sum(matrix[r])} != {group_pops[r]}")
    for j in range(cols):
        col = sum(matrix[r][j] for r in range(rows))
        if col != slot_caps[j]:
            raise AllocationError(f"column {j} total {col} != {slot_caps[j]}")


def allocation_of(record: Mapping[str, object]) -> tuple[tuple[int, ...], ...]:
    """对 (group_populations, settlement_slots) 记录重算矩阵（供独立复算用）。"""
    group_pops = [int(rec["value"]) for rec in record["group_populations"]]  # type: ignore[index]
    slot_caps = [int(rec["value"]) for rec in record["settlement_slots"]]    # type: ignore[index]
    return allocate(group_pops, slot_caps)


def render_matrix(matrix: Sequence[Sequence[int]],
                  groups: Sequence[str] = tuple(g for g, _ in GROUP_POPULATIONS),
                  slots: Sequence[str] = tuple(s for s, _, _ in SETTLEMENT_SLOTS)
                  ) -> str:
    """规范文本渲染（digest 与文档共用的唯一文本形式）。"""
    head = "group," + ",".join(slots)
    lines = [head]
    for name, row in zip(groups, matrix):
        lines.append(name + "," + ",".join(str(c) for c in row))
    return "\n".join(lines) + "\n"


def allocation_digest(matrix: Sequence[Sequence[int]]) -> str:
    """矩阵规范文本的 SHA256（逐字节稳定；无时间戳、无环境依赖）。"""
    return hashlib.sha256(render_matrix(matrix).encode("utf-8")).hexdigest()


def column_totals(matrix: Sequence[Sequence[int]]) -> tuple[int, ...]:
    return tuple(sum(row[j] for row in matrix)
                 for j in range(len(matrix[0])))


def row_totals(matrix: Sequence[Sequence[int]]) -> tuple[int, ...]:
    return tuple(sum(row) for row in matrix)


# --------------------------------------------------------------------------
# RA-COHORT-001 v1.0：初始 cohort 权重（规则实现；正式数值 = BLOCKED）
# --------------------------------------------------------------------------
def cohort_survivor_weights(mortality_by_bucket: Iterable[Fraction]
                            ) -> tuple[Fraction, ...]:
    """存活曲线权重 Π(1 - mortality[k])（精确有理数；无 float、无 RNG）。"""
    weights: list[Fraction] = []
    acc = Fraction(1)
    for m in mortality_by_bucket:
        weights.append(acc)
        acc = acc * (Fraction(1) - Fraction(m))
    if not weights:
        raise AllocationError("mortality_by_bucket must be non-empty")
    return tuple(weights)


def apportion_largest_remainder(weights: Sequence[Fraction], total: int
                                ) -> tuple[int, ...]:
    """按权重把整数 total 分配到各槽位（最大余额；tie-break = 下标升序）。

    与 `allocate` 阶段 A 同一舍入政策：先 floor，再把余额给小数余额最大者，
    余额相同 → 下标小者优先。输出和严格 == total（total >= 0）。
    """
    if total < 0:
        raise AllocationError("total must be non-negative")
    denom = sum(weights)
    if denom <= 0:
        raise AllocationError("weights must sum to a positive value")
    ideals = [Fraction(w * total, denom) for w in weights]
    floors = [int(i) for i in ideals]
    residual = total - sum(floors)
    order = sorted(range(len(weights)), key=lambda k: (-(ideals[k] - floors[k]), k))
    out = list(floors)
    for k in order[:residual]:
        out[k] += 1
    if sum(out) != total:  # pragma: no cover - 不可达
        raise AllocationError("apportionment lost population")
    return tuple(out)


def cohort_counts_v1_0(mortality_by_bucket: Sequence[Fraction], total: int
                       ) -> tuple[int, ...]:
    """RA-COHORT-001 **v1.0**（SUPERSEDED_PRODUCTION_RULE_PROVENANCE）。

    历史语义：存活曲线在**全部 bucket** 上分配，末桶**不**聚合开区间尾部
    （age ≥ N-1 的 survivor 被截断）。owner 已批准 v1.1 取代之；本函数仅为
    历史复算/对照保留，**不得**再用于正式 bootstrap。
    """
    return apportion_largest_remainder(
        cohort_survivor_weights(mortality_by_bucket), total)


def cohort_open_ended_tail_multiplier(
        mortality_by_bucket: Sequence[Fraction]) -> Fraction:
    """末桶（open-ended）尾部乘数 = 1 / m_{N-1}（精确有理数）。

    引擎把 age ≥ N-1 一律 clamp 到最后一个 bucket，并使用**该桶**的死亡率
    （`SpeciesDemographyProfile.mortality_of` → `bucket_of(age) = min(age, N-1)`），
    因此"年龄 ≥ N-1 仍存活"的总质量 = w_{N-1} · Σ_{k≥0} (1-m_{N-1})^k
    = w_{N-1} / m_{N-1}。

    若末桶死亡率 ≤ 0（尾部级数不收敛）→ `AllocationError`（fail-closed，
    绝不静默截断）。
    """
    if not mortality_by_bucket:
        raise AllocationError("mortality_by_bucket must be non-empty")
    m_last = Fraction(mortality_by_bucket[-1])
    if m_last < 0 or m_last >= 1:
        raise AllocationError("末桶死亡率必须在 (0, 1) 内才能形成开区间尾部")
    if m_last == 0:
        raise AllocationError(
            "末桶死亡率 = 0 ⇒ 开区间尾部不收敛（无法定义 v1.1 初始分布）")
    return Fraction(1) / m_last


def cohort_counts(mortality_by_bucket: Sequence[Fraction], total: int
                  ) -> tuple[int, ...]:
    """RA-COHORT-001 **v1.1**（owner: APPROVED_PRODUCTION_BOOTSTRAP_RULE）。

    open-ended final bucket：年龄 ≥ N-1 的 survivor **全部累计到最后 bucket**：
        weight[b]   = Π_{k<b} (1 - mortality[k])            for b < N-1
        weight[N-1] = weight[N-1] * (1 / mortality[N-1])    （尾部累计）
    随后按既有最大余额政策整数分配（tie-break = 下标升序），
    输出和严格 == total；无浮点、无 RNG、逐字节可复现。
    """
    weights = list(cohort_survivor_weights(mortality_by_bucket))
    weights[-1] = weights[-1] * cohort_open_ended_tail_multiplier(
        mortality_by_bucket)
    return apportion_largest_remainder(tuple(weights), total)


def cohort_rule_record() -> dict[str, object]:
    """RA-COHORT-001 的可序列化规则声明（inputs 未批准 → 输出 BLOCKED）。"""
    return {
        "rule_id": RULE_COHORT_ID,
        "rule_version": RULE_COHORT_VERSION,
        "inputs": [
            "SpeciesDemographyProfile.cohort_buckets",
            "SpeciesDemographyProfile.mortality_by_bucket",
            "population_groups.settlement_ref × species 人口总数",
        ],
        "output": "population_groups(age_cohort) 每个 bucket 的整数 count",
        "rounding_policy": "FLOOR_THEN_LARGEST_REMAINDER",
        "tie_break_policy": "REMAINDER_DESC_THEN_BUCKET_INDEX_ASC",
        "uses_birth_rate": False,
        "uses_rng": False,
        "uses_float": False,
        "uses_hash_of_seed": False,
        "canonical_form": "weight[b] = PROD_{k<b}(1 - mortality[k]); share[b] = weight[b]/SUM",
    }


def allocation_rule_record() -> dict[str, object]:
    """RA-ALLOC-001 的可序列化规则声明。"""
    return {
        "rule_id": RULE_ALLOC_ID,
        "rule_version": RULE_ALLOC_VERSION,
        "inputs": [
            "GROUP_POPULATIONS（有序群体人数）",
            "SETTLEMENT_SLOTS（有序聚落容量）",
        ],
        "output": "(group × settlement) 整数名额矩阵 + 行/列合计",
        "rounding_policy": "FLOOR_THEN_LARGEST_REMAINDER_STAGE_A_"
                           "MIN_DISTORTION_REPAIR_STAGE_B",
        "tie_break_policy": "REMAINDER_DESC_THEN_ROW_INDEX_ASC_"
                            "THEN_MIN_COST_THEN_COLUMN_INDEX_ASC",
        "uses_rng": False,
        "uses_float": False,
        "uses_hash_of_seed": False,
        "marginals": "BOTH_ROWS_AND_COLUMNS_EXACT",
    }


def allocation_section() -> dict[str, object]:
    """候选 JSON 的 allocation 段（含矩阵与 digest；数值全部由规则产出）。

    整段带 `source_class = DETERMINISTIC_DERIVATION`：段内所有数字（矩阵、行和、
    列和）均由同一规则产出，可按 derivation 块**独立复算**。
    """
    if sum(p for _, p in GROUP_POPULATIONS) != sum(
            c for _, _, c in SETTLEMENT_SLOTS):
        raise AllocationError("group/settlement population totals differ")
    matrix = allocate([p for _, p in GROUP_POPULATIONS],
                      [c for _, _, c in SETTLEMENT_SLOTS])
    return {
        "source_class": "DETERMINISTIC_DERIVATION",
        "attribution_scope": "SECTION",
        "state": "DERIVED",
        "derivation": {
            "rule_id": RULE_ALLOC_ID,
            "rule_version": RULE_ALLOC_VERSION,
            "inputs": ["GROUP_POPULATIONS（owner 已批准群体人数）",
                       "SETTLEMENT_SLOTS（owner 已批准聚落目标人口）"],
            "output": "(group × settlement) 整数名额矩阵",
            "rounding_policy": "FLOOR_THEN_LARGEST_REMAINDER_STAGE_A_"
                               "MIN_DISTORTION_REPAIR_STAGE_B",
            "tie_break_policy": "REMAINDER_DESC_THEN_ROW_INDEX_ASC_"
                                "THEN_MIN_COST_THEN_COLUMN_INDEX_ASC",
        },
        "rule": allocation_rule_record(),
        "group_order": [g for g, _ in GROUP_POPULATIONS],
        "settlement_order": [s for s, _, _ in SETTLEMENT_SLOTS],
        "matrix": [list(row) for row in matrix],
        "row_totals": list(row_totals(matrix)),
        "column_totals": list(column_totals(matrix)),
        "canonical_text": render_matrix(matrix),
        "matrix_sha256": allocation_digest(matrix),
    }


def dumps_canonical(obj: object) -> str:
    """规范 JSON 文本（排序键、ASCII、无空白抖动）——供 digest 与落盘共用。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n"

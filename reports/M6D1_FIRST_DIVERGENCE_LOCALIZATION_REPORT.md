# M6D.1 — FIRST DIVERGENCE LOCALIZATION（首处分歧定位 + 最小确定性排序修复）

**状态：ROOT_CAUSE_PROVEN / MINIMAL_FIX_APPLIED / DETERMINISM_GATES_PASS（待 owner 复核）**
**本轮红线不变**：`SNAPSHOT_V1 = NOT_APPROVED`、`MATERIALIZER_ALLOWED = FALSE`、
`FORMAL_ACTIVATION_ALLOWED = FALSE`、`FORMAL_WORLD_RUNTIME_ROWS = 0`、
`CURRENT_BLESSED_TICK = NULL`、`FORMAL_WORLD_STATUS = NOT_ACTIVATED`、
`FORMAL_WORLD_SEED_CONSUMED = FALSE`；正式 DB SHA256 未变更
`7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837`；
legacy stale DB 仍为 `NON_AUTHORITATIVE`。本轮未触碰 materializer / 正式激活 /
正式 Seed 读取 / live deploy。

---

## 0. 结论摘要（一句话）

`PYTHON_HASH_ORDER_DEPENDENCY` 的**唯一已证明根因**是
`services/simulation/population.py` 中 `group_keys` 的
**集合字面量 + 非全序排序键**：`DEMOGRAPHY@<tick>` 单一 RNG 流的消耗顺序
= 群体处理顺序，顺序随 `PYTHONHASHSEED` 变化 → **同一条随机序列被分配给不同
实体（case B）** → 第 1 年（T1）即分叉。只对**这一处**加全序键后，
hash-seed 0/1/42/default 四种取值（含重复运行）逐字节一致，全管线
（八相）在 T1/T4/T10/T50/T100 亦逐字节一致。

---

## 1. 定位结果（M6D.1 必需产出）

| 产出 | 值 | 证据 |
|---|---|---|
| `PYTHON_HASH_ORDER_DEPENDENCY` | **CONFIRMED** | 见 §2 前置矩阵 |
| `FIRST_DIVERGENT_YEAR` | **1** | 逐年（Y1..Y10）state/event hash 对比：`H0_VS_H1_SAME_YEARS = []`（无一年相同） |
| `FIRST_DIVERGENT_PHASE` | **DEMOGRAPHY（pipeline 第 2 相）** | 隔离测试台只注册 `PopulationGroupEngine`；分叉发生在该引擎 `simulate()` 的**第 1 个实体位置**（position 0），晚于 TIME、早于其余所有相 |
| `FIRST_DIVERGENT_RNG_CALL_INDEX` | **0**（流 `DEMOGRAPHY@0`，两进程同流同序） | trace 探针：H0 首抽 `p=0.18333333333333332` vs H1 首抽 `p=0.05`，均 `result=False` |
| `FIRST_DIFFERENT_ENTITY_POSITION` | **0** | H0 首个群体 `(MAIN-03, Hairy Men)`；H1 首个群体 `(SAT-05, Hairy Men)` |
| 实体集合是否相同 | **相同**（48/48） | `SAME_ENTITY_SET = True`，但 48 个位置中 **40 个位置不同** |
| **case 判定** | **CASE B**（同一条 RNG 序列被分配给不同实体 → 处理顺序问题，**非** RngService 问题） | 两进程 RNG 流标签、每流调用序号、抽样次数（2928）一致；`p`/`result` 序列不同 |
| `RngService` 是否可疑 | **排除** | `derive_seed` = SHA-256(world_id\|version\|tick\|subsystem\|scope)，入参全为常量字符串/整数；`subsystem="DEMOGRAPHY"`、`blessed_period_tick=0` 两进程一致 |

相位分辨率说明（避免过度声称）：首处分歧已在**第 1 步的第 1 个引擎的第 1 个实体**
出现，因此"年内相位检查点 A–I"无更细可分之物——`PHASE_RESOLUTION =
(FIRST_STEP, FIRST_ENGINE, ENTITY_POSITION_0, RNG_CALL_0)`。全管线相位一致性改由
§5.2 的集成 gate 逐检查点证明。

---

## 2. 根因（代码级）

`services/simulation/population.py:191-193`（修复前）：

```python
group_keys = sorted({(r["settlement_ref"], r["species"]) for r in rows},
                    key=lambda k: (_settlement_order(k[0]), k[1]))
```

* `{... for r in rows}` 是**集合字面量**：迭代顺序由元素 `hash()` 决定，
  元组内含字符串 → 随 `PYTHONHASHSEED` 变化（CPython str hash randomization）。
* `_settlement_order(ref)` 只对 `"TEST-MAIN-A"` 返回 0，**其余一律返回 1**
  （`population.py:149-150`）→ 12 个正式聚落全为 1 → 排序键 `(1, species)`
  **对同一 species 的 12 个聚落构成并列**；`sorted` 是稳定排序 → **并列项的相对
  顺序 = 集合的哈希迭代顺序** → 非确定性。
* 处理顺序即 `ctx.rng` 的消耗顺序：`_step_group()` 内按 bucket 抽
  `ctx.rng.chance(frac)`（死亡余数）与出生余数，`_allocate_migration()` 再按
  `outcomes` 顺序抽迁出余数 → 顺序一变，**抽样结果错配到不同群体**（case B）。

**未参与**：任何人口方程、死亡率、生育率、`birth_rate`、RNG 算法、seed 派生、
世界规则。

`_settlement_order` 同时被用作 `migration_weights` 的下标
（`population.py:370-371`；`scripts/build_snapshot_candidate.py:707-712` 的 `EC-3`
已记录该"二值下标"事实）——因此本轮**刻意不修改 `_settlement_order` 语义**，
只补全排序键。

### 2.1 因果证明（test-only，不改 production）

用 `scripts/_m6d_trace_probe.py --normalize-order` 在**测试进程内**拦截
`population` 模块的 `sorted()`，仅当入参是 `(settlement_ref, species)` 二元组集合时
改用全序键 `(_settlement_order(ref), ref, species)`（`_settlement_order` 本身不动）：

| 配置 | Y1 state_hash | Y1 event_hash | Y1 人口 | 实体位置不一致数 | 首个不同 RNG 调用 |
|---|---|---|---|---|---|
| 原样 H0 | `45828221c4c1…` | `4989d2928381…` | 12032 | 40 / 48 | index 0 |
| 原样 H1 | `bcd1d42f3af8…` | `d2fd3cbea217…` | 12032 | — | — |
| 规范化 H0N | `d4fc73f4421c…` | `0e8e7ed2ec68…` | 12013 | **0 / 48** | **无（None）** |
| 规范化 H1N | `d4fc73f4421c…` | `0e8e7ed2ec68…` | 12013 | **0 / 48** | **无（None）** |

`H0N == H1N` 逐字节相同（state/event/人口/逐年），且 `RNG_PROBABILITY_SEQUENCE_IDENTICAL = True`
→ 该调用点是**唯一**分叉源，因果闭环。

### 2.2 其余候选点的静态排查（AST + 人工，全部排除）

| 位置 | 构造 | 结论 |
|---|---|---|
| `coordinator.py:475` | `tuple({...} for i in range(s,e))` | **AST 实测为 `GeneratorExp`（生成器），不是 `tuple(set(...))`**；元素为 dict，若真为集合会 `TypeError: unhashable`。→ **不是**哈希顺序源。（修正 M6D 诊断笔记中的表述） |
| `coordinator.py:482` | `tuple((eid, tuple(staged.changes[s:e])) ...)` | 生成器 + 切片，有序 |
| `coordinator.py:530` | `snap_residual_ids = {r["id"] …}` | 仅成员判定 `r.id not in …`，顺序无影响 |
| `coordinator.py:492/550` | `eps_touched: set` | 出口 `tuple(sorted(eps_touched))`，已规范化 |
| `feedback.py:78,94` | `zone_ids = {…}` | 仅成员判定 |
| `social.py:157` | `sorted({g["species"] …})` | 已排序 |
| `population.py:176-180` | `sorted(rows, key=(order, species, bucket, id))` | `id` 收尾 → 全序（无需改动，保持最小修复面） |

结论：population 执行路径上**无其它**无序集合参与"顺序敏感"计算。

---

## 3. 最小修复（MINIMAL DETERMINISTIC ORDERING FIX）

按 owner 要求逐项声明（修复后代码见 `services/simulation/population.py:191-204`）：

* **WHY_ORDER_MATTERS**：`group_keys` 的顺序就是 `ctx.rng`
  （`DEMOGRAPHY@<tick>` 单一流）的消耗顺序；顺序变化会把同一条伯努利序列分配给
  不同 `(settlement, species)`，使死亡/出生余数抽样错配（实测 case B）。
* **SOURCE_COLLECTION**：`{(r["settlement_ref"], r["species"]) for r in rows}`
  集合字面量（迭代顺序 = 哈希顺序，随 `PYTHONHASHSEED` 变化）。
* **CURRENT_NONDETERMINISTIC_BEHAVIOR**：H0 vs H1 → 48 个实体中 40 个处理位置
  不同、首个位置即不同（MAIN-03 vs SAT-05）、`STATE_HASH_EQUAL = False`；
  同一进程内重复运行一致（`repeat_identical = True`），跨进程不一致
  → 典型跨进程哈希序依赖特征。
* **CANONICAL_SORT_KEY**：`(_settlement_order(ref), ref or "", species)`
  —— 在原有 `_settlement_order` 语义之上补全**全序**并列键（`settlement_ref` 为
  `None` 时退化为 `""`，保持与旧键同样不抛错）。

改动仅为**排序键 + 说明注释**；不新增/删除任何计算、不调整任何阈值。

**基线影响预判（并已实测）**：既有 golden 基线（`mini_world.py`）只有
`TEST-MAIN-A`（order 0）与 `TEST-SATELLITE-B`（order 1），两者 order 不同、从不并列
→ 该修复对既有基线**结构上不可能生效**，故预期
`GOLDEN_BASELINE_MUTATIONS = 0`。

---

## 4. 前置证据（修复前，M6D）

* hash-seed 矩阵（单进程 × 各 300y）：`H0-A`(pid 60248) 与 `H0-B`(pid 52380)
  **逐字节相同**（state `d68e166d352bbec7…`、events `ad822119df66…`、
  T10 12043 / T100 12246 / T300 12583）；`H1-A`(pid 49604) 不同
  （state `f529cab9993642ab…`、events `252637d3223e…`、
  T10 12062 / T100 11953 / T300 12219）→ 跨进程依赖确认。
* 独立佐证（**与本轮探针无关的驱动**）：同一 5-seed 稳健性套件修复前跑过两次，
  T300 逐种子差异最大 **±533**（`[12444,12266,11998,11752,12571]` vs
  `[11911,12526,12193,11660,12255]`），而每次运行**进程内**重复完全一致
  （`DETERMINISTIC_RNG_REPRODUCIBILITY = PASS`）——正是"进程内稳定 / 跨进程发散"
  的签名。归档：`reports/M6C1D_SEED_ROBUSTNESS_PREFIX.json`、
  `reports/M6C1D_SEED_ROBUSTNESS_PREFIX_REPEAT.json`。

---

## 5. 修复后 gate

### 5.0 trace 级验证（**production 路径，无任何测试钩子**）

同一 trace 探针在修复后原样重跑（`--years 1`，`PYTHONHASHSEED = 0` vs `1`）：

* 首个群体 = `(MAIN-01, Hairy Men)`，其后 `(MAIN-01, Mermen/Mushroommen/Rockmen)`、
  `(MAIN-02, …)` → 规范字典序；
* `FIRST_DIFFERENT_ENTITY_POSITION = None`、`ENTITY_POSITION_MISMATCH_COUNT = 0`、
  `FIRST_DIVERGENT_RNG_CALL_INDEX = None`、`RNG_PROBABILITY_SEQUENCE_IDENTICAL = True`、
  `STATE_HASH_EQUAL = True`；
* Y1 `state = d4fc73f4421c017c…`、`event = 0e8e7ed2ec68f91a…`、人口 12013
  —— **与修复前 §2.1 的"规范化"实验（H0N/H1N）逐字节相同**，即生产代码现已在
  无钩子的情况下复现规范顺序。

### 5.1 Hash-seed gate（隔离人口学，Y1..Y10 逐年 + T50/T100）

`HASH_SEED_GATE = PASS`：5 个标签（`H0`、`H0` 重复、`H1`、`H42`、`default`）
**state / events / 人口 / 逐年 hash 全部逐字节一致**：

```
final_state_hash        = ea4094a1105c47052c9e9edd4487afe1583d0dc2568c8f26490a634c9541c233
final_event_stream_hash = 178e53cab6bd745aedb46f6be88bafebede60d6a6d952664acfc37e8a98aff85
population_by_checkpoint = {T0: 12000, T50: 12009, T100: 12160}
identity_ok = True
```

### 5.2 集成 gate（真实八相引擎，T1/T4/T10/T50/T100）

`INTEGRATED_HASH_SEED_GATE = PASS`（`PYTHONHASHSEED = 0` vs `1`，各一个全新进程）：
每个检查点的 `state_hash`、完整 per-(聚落×资源) 台账、生态压力/质量载荷
**全部相同**：

```
T100 final_state_hash = f5bf7322926038b77cbc67de66700dad078b5d8599113fd6d9d67e481a458038
```

### 5.3 5-seed 稳健性（`birth_rate` 不变 = 53/1000）

`P2_B_MULTI_SEED_ROBUSTNESS = PASS`（5/5 落在 `[11400, 12600]`）、
`POPULATION_ACCOUNTING_IDENTITY = PASS`、`DETERMINISTIC_RNG_REPRODUCIBILITY = PASS`
（每种子进程内重复运行一致）：

| seed | T100 | T300 |
|---|---|---|
| SYNTH-DEMO-001 | 12160 | 12360 |
| SYNTH-DEMO-002 | 11997 | 12490 |
| SYNTH-DEMO-003 | 11821 | 12058 |
| SYNTH-DEMO-004 | 11999 | 12223 |
| SYNTH-DEMO-005 | 12086 | 12564 |

`MIN 12058 / MAX 12564 / MEAN 12339 / MEDIAN 12360`；上界余量 36
（`12600 - 12564`，需 owner 知悉）。归档：
`reports/M6D1_SEED_ROBUSTNESS_POSTFIX.json`。

> 注：修复会使数值轨迹发生**一次性**位移（修复前数值本身依赖哈希种子，不具权威性）。
> 修复前 T300 = `[12444,12266,11998,11752,12571]`（run-1）/ `[11911,12526,12193,11660,12255]`
> （run-2）；修复后为 `[12360,12490,12058,12223,12564]`。`birth_rate` 未改，
> 中标结论（P2-B = 53/1000）不变，但 `P2_B_FINAL_RATIFICATION` 仍需 owner 以
> **修复后确定性数值**重新确认。

### 5.4 回归

#### 5.4.1 `GOLDEN_BASELINE_MUTATIONS = 0`（静态下界证明）

所有 committed golden 基线均由 `services/simulation/mini_world.py` 生成，其聚落集合
**恰好两个**：`TEST-MAIN-A`（`_settlement_order` → 0）与 `TEST-SATELLITE-B`
（→ 1）——**两值互不相同、永不并列**，故本次新增的并列键
（`settlement_ref`）在这些基线上**结构上不可能生效**。覆盖：
M2a/M2b/M2c/M2d 120y（`mini_world_v1`）、M2 integrated 1000y ×5 seeds、
M3a 灾劫 300y、M3b 因果历史 300y、M3 integrated 1000y/5000y
（`fixture_version = mini_world_v1` 见各基线 `summary.json`）。

#### 5.4.2 实测（targeted，已完成）

`pytest tests/test_m2a_population.py tests/test_m2b_resource_economy.py
tests/test_m2c_ecology.py tests/test_m2d_social.py tests/test_m2_review.py -q`
→ **exit 0**，230 tests（223 passed / 7 skipped / 0 failed / 0 errors），
其中含 4 处 `final_world_state_hash == golden[...]` 逐字节比对；
`git status tests/baselines` **无任何变更**（golden 字节守护亦未触发）。

#### 5.4.3 canonical fast regression（运行中，结果以追加提交记录）

`pytest tests -q --ignore=tests/test_m3_integrated_long.py` 已启动
（后台 job `pwsh-70`，独立进程）。该套件含已知重测：
`test_budget_equivalence_1000y_long`（1000/500/250/100/10/7/1 七档）、
`test_scheduler_1000y_reproduces_frozen_seed001`、
`test_scheduler_5000y_endurance_reproduces_frozen`、
`test_m2_review_long` 的 `test_lt1_1000y_five_seeds` 与 `test_lt7_5000y_endurance`
——预计数小时；本轮**不以未完成的套件冒充 PASS**，完成后以追加报告/提交记录
`FAST_REGRESSION = PASS/FAIL` 与 `GOLDEN_BASELINE_MUTATIONS` 终值。

> 本轮结论不依赖该套件：§5.4.1 的静态下界 + §5.4.2 的 targeted 实测已覆盖
> 全部 4 处 M2 家族 golden 比对，确定性 gate（§5.0–§5.3）全部 PASS。

---

## 6. 本轮未做（明确边界）

* 未改 `_settlement_order` 语义、未改 `migration_weights` 下标语义（`EC-3` 仍是
  独立待议项：12 个正式聚落的迁移权重无法按聚落区分）。
* 未做全局 `sorted()` 清扫；未改其它任何引擎的排序/取值顺序。
* `coordinator.py:475` 已证明**不是**哈希顺序源（生成器），无需修复；
  "事件顺序" 议题的另一半（M3b history bundle 顺序）在 §2.2 中逐点判定为有序，
  如后续 M3b 实测发现新证据再单独立项。
* 未跑修复后 300y 集成长跑 / 300y×2 集成确定性 / restart equivalence /
  真实 `history_builder` 历史完整性 / S-B 事件级 / T-B 伤亡与效果收集
  —— 这些仍按 owner 排序在确定性通过后执行（M6D.2 起）。
* 未重跑 TIER-1 资源/生态 300y 冒烟（`reports/M6C1D_RESOURCE_SMOKE_PREFIX.json`
  为**修复前**数值，其 T300 台账/生态轨迹为哈希种子相关，**不具权威性**；
  修复后 300y 数值应在 M6D.2 重新采集）。
* canonical fast regression 仍在运行（见 §5.4.3），本轮不代其宣告 PASS。
* 未做 materializer / 正式激活 / 正式 Seed 读取 / live deploy。

---

## 7. 产出文件

* 修复：`services/simulation/population.py`（仅排序键 + 注释）
* 探针（test-only）：`scripts/_m6d_hashseed_probe.py`、
  `scripts/_m6d_peryear_compare.py`、`scripts/_m6d_trace_probe.py`、
  `scripts/_m6d_trace_compare.py`、`scripts/_m6d_hashseed_gate.py`、
  `scripts/_m6d_integrated_hashseed_gate.py`
* 证据归档：`reports/M6D1_SEED_ROBUSTNESS_POSTFIX.json`、
  `reports/M6C1D_SEED_ROBUSTNESS_PREFIX.json`、
  `reports/M6C1D_SEED_ROBUSTNESS_PREFIX_REPEAT.json`、
  `reports/M6C1D_DEMOGRAPHY_FINALISTS_PREFIX.json`、
  `reports/M6C1D_DEMOGRAPHY_SCAN300_PREFIX.json`

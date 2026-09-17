# M6D.2 — FINAL POST-DETERMINISM INTEGRATED WORLD VERIFICATION

**状态：INTEGRATED RUN COMPLETE（RUN1/RUN2/RUN3）× BLOCKER FOUND（T-B 效果未落地）**
**`SNAPSHOT_V1_ENGINE_VERIFIED_CANDIDATE = FALSE`**
**`NEXT_ACTION = AWAIT_OWNER_ON_FINAL_INTEGRATED_BLOCKER`**

红线（复核，未变）：

```
FORMAL_DB_AUTHORITY = PASS
FORMAL_DB_SHA256   = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837
FORMAL_WORLD_RUNTIME_ROWS = 0     CURRENT_BLESSED_TICK = NULL
FORMAL_WORLD_STATUS = NOT_ACTIVATED   FORMAL_WORLD_SEED_CONSUMED = FALSE
SNAPSHOT_V1 = NOT_APPROVED        MATERIALIZER_ALLOWED = FALSE（本轮未实现、未激活）
```

---

## 0. 一句话结论

确定性修复后的**最终集成世界 300y 跑通**（RUN1/RUN2 连续、RUN3 分两进程重启），
确定性/重启等价 **PASS**；但 §13 人口会计恒等式与 §17 T-B 事件级验证**暴露出一个真实
生产缺陷**：**灾劫（T-B）域适配器的状态效果被同一步内所属引擎的 staged 变更覆盖
（last-write-wins），事件与历史账本记录了效果，世界状态却没有落地**。
因此 `SNAPSHOT_V1_ENGINE_VERIFIED_CANDIDATE = FALSE`，交回 Owner 裁决。

---

## 1. 最终候选配置（owner §9，未做任何重新标定）

| 域 | 配置 |
|---|---|
| DEMOGRAPHY | `birth_rate = 53/1000`、lifespan 60、mortality 1/60、fertility 15–45、`capacity = NULL`、四族共享 profile |
| RESOURCE | RE-LEAN-v2：8 formal profiles（7 消费类 + `RESOURCE_SLOT_08` registry-only）、7 production nodes、1 local blessed-year initial stock、capacity = 1.10 × actual served annual demand |
| ECOLOGY | E-B-v2：sensitivity 1/279、recovery 1/25、ppp 1、initial habitat_quality = FULL（1,000,000） |
| SOCIAL | S-B |
| TRIBULATION | T-B：periods 10/50/100、first omen tick 10,000,000 |

管线（owner §10，**history builder 已真实接线**）：
`TIME → DEMOGRAPHY → RESOURCE → ECONOMY → ECOLOGY → SOCIAL → TRIBULATION → HISTORY`
（`coordinator.history_builder = HistoryLinkBuilder()`；无 harness 遗漏）

激活路径（owner §11）：正式 zero-row 契约 → `activate_formal_world()` →
`WORLD_SEED_ACTIVATED` genesis → test-only bootstrap rows → 集成管线。
`TEST_BOOTSTRAP_ATOMICITY_WITH_ACTIVATION = NOT_PROVEN`（production Materializer 未实现，维持原判定）。

---

## 2. 集成检查点（owner §12）— RUN1（连续 300y，`PYTHONHASHSEED` 未固定）

| checkpoint | T0 | T10 | T50 | T100 | T300 |
|---|---|---|---|---|---|
| population total | 12000 | 11704 | 10464 | 8547 | **2852** |
| Hairy Men | 4000 | 3938 | 3548 | 2910 | **1020** |
| Rockmen | 3000 | 2902 | 2630 | 2159 | **624** |
| Mermen | 2500 | 2428 | 2097 | 1633 | **484** |
| Mushroommen | 2500 | 2436 | 2189 | 1845 | **724** |
| births（累计） | 0 | 1675 | 7803 | 13791 | **25897** |
| deaths（累计） | 0 | 1971 | 9339 | 17244 | **35043** |
| immigration / emigration | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | **0 / 0** |
| tribulation casualties（记录） | 0 | 0 | 0 | 5 | **12** |
| tribulation casualties（实际落地） | 0 | 0 | 0 | 0 | **2** |

* 集成 T300 = 2852（**不是** 12000；owner §13 明确允许真实历史导致的人口变化）。
  与 demography-only 标定（T300 ≈ 12360）差异来自**集成反馈**（生态压力死亡修正 +
  社会生育修正），**未重新 calibration `birth_rate`**。
* 资源：`unmet_cells = 0`（T10/T50/T100/T300 全部）、`unmet_minor = 0`、
  `stress_levels = ['NONE']`、`max_sustained_shortage_steps = 0`、84 个 pressure 行 /
  84 个 stock cell 全在；`SHORTAGE_YEARS_300 = 0`；`PERMANENT_ZERO_SUPPLY_CELLS = 0`。
* 经济：`demand_minor` T300 = 4,991,000,000 → `fulfilled_minor` 同值（100% 履约）；
  `PRODUCTION_COMPLETED = 2177`、`RESOURCE_EXTRACTED = 2100`、`RESOURCE_TRANSFERRED = 23100`。
* 生态：`habitat_quality` T10 **19447** → T50 20227 → T100 21326 → T300 **24074**
  （满值 1,000,000；即 **1.94% → 2.41%**）；`ecological_stress` 513823 → 494303 → 466831 →
  398150；四压力分量 T300：population 325 / extraction **1000000（clamp 满）** /
  production 92219 / depletion 113；`quality_min_seen` 未触零、无负值、无 runaway。
* 社会：households 1220（行数；`HOUSEHOLD_FORMED = 1220`、`HOUSEHOLD_DISSOLVED = 85`）、
  institutions 12（`INSTITUTION_FOUNDED = 12`、`INSTITUTION_DISSOLVED = 1`）、**lineages 0**。
  `SOCIAL_DOMAIN_ACTIVE = TRUE`；无无限分裂环（形成 1220 次、解散 85 次，T10 后不再增长）、
  无重复 institution（12 行 / 12 次 founded）。
* 灾劫：episodes **30**、first episode tick **10,000,000 ✔**、schedule **10/50/100 ✔**
  （`TRIBULATION_SCHEDULED = 30`、`PRECURSOR_STARTED = 30`、`COMPLETED = 28`、
  `RECOVERY_PROGRESS = 115`、`RESIDUAL_CHANGE_CREATED = 29`、
  `SUCCESSION_CANDIDATE_CREATED = 28`）→ 无 drift。
* 历史：`world_events = 77876`、`causal_history_links = 1161583`、
  `entity_history_index_rows = 1160656`、`indexed_through_tick = 300000000`、
  `WORLD_SEED_ACTIVATED = 1`、`TEST_PROFILE_USAGE_COUNT = 0`。
* 历史完整性：`orphan_links = 0`、`cycle_count = 0`、`invalid_relations = 0`、
  `duplicate_links = 0`、`tick_paradox_links = 0`、`clean = True`。
* `causal_history_hash = 921324e2b779e130e273172fbbfa1f3d5b1f2d67b3c7f827398482e82a2ea2cf`（links 1161583）。

事件类型普查（T300，节选）：`POPULATION_BIRTHS 11556`、`POPULATION_DEATHS 11571`、
`TIME_ADVANCE 300`、`HOUSEHOLD_FORMED 1220`、`HOUSEHOLD_DISSOLVED 85`、
`INSTITUTION_FOUNDED 12`、`INSTITUTION_DISSOLVED 1`、`CONSUMPTION_FULFILLED 25200`、
`RESOURCE_EXTRACTED 2100`、`RESOURCE_TRANSFERRED 23100`、`PRODUCTION_COMPLETED 2177`、
`ECOLOGY_THRESHOLD_CROSSED 1`、`TRIBULATION_*`（PRECURSOR 30 / SCHEDULED 30 /
PREPARATION 29 / IMPACT_STARTED 29 / IMPACT_APPLIED 29 / DECISION 系 AUTONOMOUS_RESPONSE_SELECTED 29 +
MITIGATION_COMMITTED 29 / COMPLETED 28 / NEW_NORMAL_REACHED 28 / STABILIZED 29 /
RECOVERY_PROGRESS 115 / RESIDUAL_CHANGE_CREATED 29）、
`*_IMPACT_APPLIED`（DEMOGRAPHY 3 / RESOURCE 29 / ECONOMY 29 / ECOLOGY 29 / SOCIAL 0）、
`WORLD_SEED_ACTIVATED 1`。

---

## 3. BLOCKER：灾劫效果未落地（本轮最重要发现）

### 3.1 现象（§13 会计恒等式不闭合）

| checkpoint | 实际人口 | `start + births + imm − deaths − emig − casualties(记录)` | 残差 |
|---|---|---|---|
| T0 | 12000 | 12000 | 0 |
| T10 | 11704 | 11704 | 0 |
| T50 | 10464 | 10464 | 0 |
| T100 | 8547 | 8542 | **+5** |
| T300 | 2852 | 2842 | **+10** |

若改用**实际落地**的灾劫损失（= 实测 2）：
`12000 + 25897 − 35043 − 2 = 2852` → **恒等式精确闭合**。

### 3.2 证据链（READ-ONLY，全部来自 RUN1 世界库）

1. **实体级账本链**（population_groups.count，entity 61）：

   ```
   y52 engine 246 -> 245
   y53 engine 245 -> 244
   y53 ADAPTER 245 -> 243        <- 记录 old=245（步前值）
   y55 engine 244 -> 243         <- 下一步起点 = 244 → 适配器写入被覆盖
   ```

   entity 61 / 122 / 244 同型（适配器行 `old` 均为步前值，持久化链证明引擎值胜出）；
   entity 183 适配器与引擎 delta 相同（−1/−1）→ 被**重复记账**。

2. **资源域同型**（resource_nodes.remaining_reserve，entity 1）：

   ```
   y13 engine  29962050000000 -> 29959080000000
   y13 ADAPTER 29962050000000 -> 29957555692500
   y14 engine  29959080000000 -> 29956275000000   <- 起点 = 引擎值，适配器 damage 丢失
   ```

3. **全量统计**（300y，474 条适配器状态变更行）：

   | 表 | 与同一步引擎变更**重叠**的 key | 仅适配器独有（真正落地） | 适配器 delta（重叠组） | 适配器 delta（独有组） |
   |---|---|---|---|---|
   | resource_nodes | 203 | **0** | −5,630,091,327,675 | 0 |
   | resource_stocks | 203 | **0** | −37,873,380,427 | 0 |
   | settlement_social_state | 29 | **0** | +2,043,000 | 0 |
   | ecology_state | 27 | 2 | −78,817 | −7,080 |
   | population_groups | 8 | 2 | −10 | −2 |
   | **合计** | **470 / 474 = 99.2%** | **4** | | |

   即：**99.2% 的灾劫状态效果与所属引擎在同步的 staged 变更冲突**，仅 0.8%
   （4 个 key，population −2 / ecology −7080）真正写入世界状态。

4. **受影响的事件计数**：`DEMOGRAPHY_IMPACT_APPLIED 3`（记录损失 12，实际 −2）、
   `RESOURCE_IMPACT_APPLIED 29`、`ECONOMY_IMPACT_APPLIED 29`、`ECOLOGY_IMPACT_APPLIED 29`、
   `SOCIAL_IMPACT_APPLIED 0`。

### 3.3 判定与影响面

* **性质**：确定性缺陷（非哈希序问题；RUN1/RUN2 一致，见 §4）。根因指向
  **同一步内「引擎 staged 变更」与「灾劫适配器直接变更」的写入冲突（last-write-wins）**，
  以及适配器变更记录使用**步前 old 值**导致账本区间重叠。
* **影响**：T-B 的伤害在事件/历史层"看起来发生了"，但世界状态未减损 →
  资源损毁、生态打击、社会打击、人口伤亡**实质未生效**（人口仅 12 记录 / 2 落地）。
* **不影响**：确定性、重启等价、历史完整性（orphans/cycles/invalid = 0）、
  §18 的 `TEST_PROFILE_USAGE_COUNT = 0`、genesis 唯一性。
* **本轮未修**（超出 M6D.1 预授权范围，按 owner §6/§15 精神交回 Owner）：
  未改 production、未改 baseline、未调参、未改 harness 结论口径。

### 3.4 建议的最小修复方向（**待 Owner 批准后才实施**）

1. 令引擎 staged 变更与适配器变更**在同一权威顺序**中合成（适配器变更以引擎结果为新基线，
   或统一进入同一变更队列按显式顺序 apply），保证"最后写入者"唯一且语义明确；
2. 适配器 HistoryStateChange 的 `old_value` 改为**步内合成后的真实前值**，消除账本区间重叠；
3. 增加 gate：对每个 `*_IMPACT_APPLIED` 事件，断言其 `effect` 与实际状态差分一致
   （记录值 == 落地值），即 `TRIBULATION_EFFECT_APPLIED_IDENTITY`。

---

## 4. 确定性 / 重启等价（owner §19–§21）

| 项 | 值 |
|---|---|
| RUN1（连续 300y，hashseed 未固定）state / events | `032aa1973f343da71d58ec6cd60ab32c24f5052f37aa1449a283e49285bfc4bf` / `25b93c40e6f15fdb1d04fc46c406a2d455acfa559c50bdaf353193cab896fcef` |
| RUN2（连续 300y，独立进程，hashseed 未固定） state / events | `032aa1973f343da71d58ec6cd60ab32c24f5052f37aa1449a283e49285bfc4bf` / `25b93c40e6f15fdb1d04fc46c406a2d455acfa559c50bdaf353193cab896fcef` |
| `DETERMINISM` | **PASS**（RUN1 == RUN2 逐字节；两个独立进程；`PYTHONHASHSEED` 均未固定；T300 pop 2852、habitat 24074、事件/历史一致） |
| RUN3（0→100y @ `PYTHONHASHSEED=0`，销毁进程后新进程 100→300y @ `PYTHONHASHSEED=42`） state / events | `032aa1973f343da71d58ec6cd60ab32c24f5052f37aa1449a283e49285bfc4bf` / `25b93c40e6f15fdb1d04fc46c406a2d455acfa559c50bdaf353193cab896fcef` |
| `RESTART_STATE_HASH` / `RESTART_HISTORY_HASH` | `032aa197…` / `921324e2b779e130e273172fbbfa1f3d5b1f2d67b3c7f827398482e82a2ea2cf`（links 1,161,583） |
| `RESTART_EQUIVALENCE` | **PASS**（RUN3 == RUN1 的 state / event / causal-history 三哈希逐字节） |
| `PYTHONHASHSEED_INDEPENDENT_RESTART` | **PASS**（跨重启边界使用了**不同**哈希种子 0 → 42，仍与连续参考完全相等） |

运行规模：RUN1 2790 s / RUN2 2783 s / RUN3a 885 s / RUN3b 1867 s；
RUN1 与 RUN2 的世界库字节数一致（1,045.4 MB），RUN3 亦收敛到同一终态。

已完成的**前置**重启等价证据（M6D.2 harness 自检，2y 规模）：连续 2y 与
「1y @ seed 0 + 1y @ seed 42（两进程）」state/event hash 逐字节相同。

---

## 5. 文件与命令

* harness：`scripts/_m6d2_integrated.py`（八相集成 runner，`continuous`/`part1`/`part2`）、
  `scripts/_m6d2_driver.py`（RUN1/RUN2/RUN3 编排与比较）
* 诊断（READ-ONLY）：`scripts/_m6d2_accounting_diag.py`（逐 tick 账本对账）、
  `scripts/_m6d2_ledger_cum.py`（checkpoint 累计账本）、
  `scripts/_m6d2_entity_chain.py`（实体写入链）、
  `scripts/_m6d2_adapter_overlap.py`（适配器/引擎重叠统计）、
  `scripts/_m6d2_tick_probe.py`（单 tick 变更明细）
* 归档：`reports/M6D2_ACCOUNTING_DIAGNOSIS.json`、
  `reports/M6D2_ADAPTER_OVERWRITE_DIAGNOSIS.txt`、
  `reports/M6D2_FINAL_INTEGRATED_VERIFICATION.json`（driver 输出）
* pre-fix 产物（owner §8）：`reports/M6C1D_*_PREFIX.json` 状态
  `DIAGNOSTIC_NON_AUTHORITATIVE`，保留但不作为最终 Snapshot 依据。

---

## 6. Gate 汇总（owner §22）

| Gate | 结果 |
|---|---|
| `P2_B_FINAL_STATUS` | `OWNER_RATIFIED_FOR_SNAPSHOT_V1`（M6D.1 closeout） |
| `RE_LEAN_V2` | PASS（0 shortage / 0 unmet / 0 permanent-zero，7-node topology 正常） |
| `E_B_V2` | PASS_WITH_OBSERVATION：无负值/无 runaway/无零化；**早期大幅下降**（T10 仅 1.94% 满值）为既有集成行为，**未自动重标定**，按 §15 报告 |
| `S_B` | PASS（域活跃、无无限分裂、无重复 institution；**lineages = 0** 已如实记录） |
| `T_B` | **FAIL_ATTRIBUTION**：first omen tick / schedule 无 drift，但 §3 的"记录未落地"使事件级验证不成立 |
| `POPULATION_ACCOUNTING_IDENTITY` | **FAIL（记录口径，残差 +10 @T300）** / PASS（落地口径，见 §3.1） |
| `INTEGRATED_WORLD_VIABILITY` | PASS_WITH_BLOCKER（300y 跑通；资源/经济无短缺；人口衰减由集成反馈解释；灾劫效果未落地见 §3） |
| `DETERMINISM` / `RESTART_EQUIVALENCE` | **PASS / PASS**（§4；含 `PYTHONHASHSEED_INDEPENDENT_RESTART = PASS`） |
| `HISTORY_INTEGRITY` | PASS（orphan 0 / cycle 0 / invalid 0 / duplicate 0 / tick paradox 0 / clean） |
| `TEST_PROFILE_USAGE_COUNT` | **0** |
| `FORMAL_WORLD_UNTOUCHED` | TRUE（§0 红线） |
| **`SNAPSHOT_V1_ENGINE_VERIFIED_CANDIDATE`** | **FALSE（T_B 未通过）** |
| `SNAPSHOT_V1` | `NOT_APPROVED` |
| `MATERIALIZER_ALLOWED` | `FALSE` |
| **`NEXT_ACTION`** | **`AWAIT_OWNER_ON_FINAL_INTEGRATED_BLOCKER`** |

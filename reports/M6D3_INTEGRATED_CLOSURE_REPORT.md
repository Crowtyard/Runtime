# M6D.3 — INTEGRATED STATE-APPLICATION & EQUIVALENCE CLOSURE

**状态：三 lane 全部定位并处理；A lane 已修复（最小复现 + 授权修复 + 复现通过），
B lane 为 harness 配置缺陷（已修），C lane 为哈希口径误报（已证伪）。**
**但 §28 STOP 条件触发：Golden baseline 变化（12 项），未自动更新，交回 Owner。**

红线（复核，未变）：

```
FORMAL_DB_AUTHORITY = PASS
FORMAL_DB_SHA256 = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837
FORMAL_WORLD_RUNTIME_ROWS = 0    CURRENT_BLESSED_TICK = NULL
FORMAL_WORLD_STATUS = NOT_ACTIVATED   FORMAL_WORLD_SEED_CONSUMED = FALSE
SNAPSHOT_V1 = NOT_APPROVED       MATERIALIZER_ALLOWED = FALSE（未实现、未激活、未消费 Seed、未部署）
```

---

## 0. 三 lane 结论

| lane | blocker | 结论 |
|---|---|---|
| A | Tribulation effects 被 owning engine 覆盖 | **ROOT_CAUSE_PROVEN（最小复现）→ 已按 owner §8 授权做 MINIMAL FIX → 复现 3/3 转为 PASS** |
| B | Ecology calibration ≈96% vs integrated ≈2% | **HARNESS CONFIG DEFECT**：integrated run 未使用 owner-ratified E-B-v2 sensitivity（用了 audited packet 的标定**前**候选值 3998/525 ≈ 7.615，而 ratified = 1/279）。修 harness 后 T1 立即回到 999,088（= 标定值）。**未重新标定 sensitivity。** |
| C | Restart history hash 不等 | **FALSE BLOCKER（口径误报）**：`25b93c40…` 是 **event stream hash**（另一函数/另一投影），`921324e2…` 才是 causal history hash。用同一 production 函数重算 RUN1/RUN2/RUN3 → 三者**完全相同**；四个账本摘要逐字节一致。`RESTART_EQUIVALENCE = PASS`。 |

---

## 1. lane A — Tribulation effect application

### 1.1 TRIBULATION_EFFECT_SEMANTICS（只读核实，未自行假设）

```
TRIBULATION_EFFECT_SEMANTICS = DELTA（相对增量）作用于「所属域引擎本步产出后的权威状态」
CANON_SOURCE =
  runtime_design/M3A_TRIBULATION_ENGINE.md §14-§20（冻结 M3a 设计）
   §15 Domain Impact Adapters（方案 B）：Coordinator 依 sorted(DOMAIN_ADAPTERS)
        调用各 Adapter.apply(session, plan)；Adapter 返回
        (domain_events, state_changes, affected_entity_ids)，state_changes
        **供 Coordinator 记入 world_state_changes 账本**（即权威变更）；
   §16 population_risk × intensity 比例损失 → population_groups.count（clamp ≥0）
   §17 resource_damage 比例削减 resource_nodes.remaining_reserve（clamp ≥0）
   §18 inventory_damage 扣减 resource_stocks.quantity（clamp ≥0）
   §19 habitat_quality -= ecology_pressure（clamp 0..1_000_000）
   §20 social_displacement / social_stress 有界抬升
   ＋ frozen pipeline：TIME→DEMOGRAPHY→RESOURCE→ECONOMY→ECOLOGY→SOCIAL→
        TRIBULATION→HISTORY ⇒ TRIBULATION 在各域引擎**之后** ⇒
        final = post_engine_value + delta（不是基于 pre-step 值的 absolute 替换）
```

### 1.2 最小因果复现（test-only，owner §2）

`tests/test_m6d3_tribulation_effect_application.py`（一步、真实 coordinator、真实 adapter）：

| 字段 | population（修复前） | population（修复后） | resource（修复前） | resource（修复后） |
|---|---|---|---|---|
| `PRE_STEP_VALUE` | 11 | 11 | 30,000,000,000,000 | 30,000,000,000,000 |
| `OWNING_ENGINE_MUTATION` | 10 | 10 | 29,999,999,999,993 | 29,999,999,999,993 |
| `TRIBULATION_EFFECT` | −2 | −2 | −30,000,000,000 | −30,000,000,000 |
| `FINAL_STAGED_VALUE` | 10 | 10 | 29,999,999,999,993 | 29,999,999,999,993 |
| `PERSISTED_VALUE` | **10（effect 丢失）** | **8 ✓** | **29,999,999,999,993（丢失）** | **29,969,999,999,993 ✓** |

第三例（无 owning engine 变更）修复前后均 PASS（pre 3 → effect −3 → 0），证明**恰好一次**
（既有 M6D.2 证据中 4/474 落地行即属此类）。

### 1.3 Root cause（production）

* `coordinator.py` 只应用 **engines 的 staged 变更**：`_apply_changes(session, staged.changes)`
  → 对每个 staged 变更 `setattr(row, field, change.new_value)`（绝对写）。
* 适配器（旧实现）在 `adapter.apply()` 内**直接 mutate ORM 行**，其 `state_changes`
  **从未进入 staged 容器**，因此：(a) 与 owning engine 同 (row, field) 时被随后的
  `setattr` 覆盖（last-write-wins 意外）；(b) 无 owning engine 变更时才侥幸落地。
* 实测：474 条适配器变更行中 **470 条（99.2%）** 与同步引擎变更冲突；仅 4 条落地
  （population −2 / ecology −7,080）。

### 1.4 授权修复（owner §8：MINIMAL TRIBULATION EFFECT APPLICATION FIX）

* `services/simulation/tribulation_adapters.py`：五个适配器**不再直接 mutate ORM 行**，
  只计算并返回 `state_changes`（保持 clamp 语义，`new` 有界）；新增
  `ADAPTER_FIELD_BOUNDS`（population≥0 / reserve≥0 / quantity≥0 /
  habitat_quality∈[0,1e6] / represented_population≥0 / social_stress∈[0,1e6]）。
* `services/simulation/coordinator.py`：新增 `_apply_adapter_effects(session, results)`，
  在 `_apply_changes(...)` **之后**执行，把每条记录效果作为 delta 应用于
  **post-engine 值**，按 bounds 裁剪；并把**实际生效**的 (old,new) 写回 adapter_results，
  使 M3b 历史账本记录真实转移（消除 M6D.2 发现的区间重叠/链不一致）。
* **未改**：灾劫概率、T-B profile 数值、period 10/50/100、人口方程、资源/生态/社会定律。
* 应用点唯一 ⇒ 0 dropped / 0 double-apply。

### 1.5 Identity gate（§6/§9/§10/§11）— 修正后真实世界（T50，`m6d3_short50`）

`scripts/_m6d3_effect_identity.py`（READ-ONLY：链一致性 + 同步合成 + 幅度对账 + exactly-once）：

```
TRIBULATION_EFFECTS_RECORDED_ROWS = 64
TRIBULATION_EFFECTS_APPLIED_ROWS  = 64
TRIBULATION_EFFECTS_DROPPED       = 0
SAME_STEP_COMPOSITION_OK / BAD    = 64 / 0
EXACTLY_ONCE_VIOLATIONS           = 0
TRIBULATION_EFFECT_APPLIED_IDENTITY = PASS

逐域幅度对账（recorded == applied）:
  RESOURCE  recorded 159,112,116,459 == applied 159,112,116,459
  ECONOMY   recorded      25,562,006 == applied      25,562,006
  ECOLOGY   recorded           3,040 == applied           3,040
  DEMOGRAPHY/SOCIAL 本 T50 窗口尚无该类 impact（null），social_stress 侧
    应用 228,000（该字段无对应 event payload 字段，故不参与对账）
```

POPULATION_ACCOUNTING_IDENTITY（同一 DB，逐 tick 账本对账）：
`mismatch_tick_count = 0`、`residual(births − deaths) = 0`、`residual(incl. casualties) = 0`
（**M6D.2 的 residual +10 已消失**）。

`T300` 版本（§6 的完整 300y 修正跑）完成后按同一脚本复算并入 §6。

---

## 2. lane B — Ecology discrepancy

### 2.1 §13 Configuration Equivalence Audit

`scripts/_m6d3_config_equivalence.py`（逐字段覆盖 owner 列表：initial HQ / sensitivity /
recovery_rate / ppp / profile / zone 数 / node topology / capacities / initial stocks /
minor-unit scaling / recipes / population profile / social / tribulation / activation-runtime /
pipeline order / steps-per-year / pressure weights / normalization / persisted fields）：

```
CALIBRATION_CONFIG_HASH       = e0989a9e331d940a4ab5ee375bf1ec4e3c752094c61f244c68f06fd66526ef20
INTEGRATED_CONFIG_HASH（as run）= 923a31dcabb4b182ede9feac59d5511869fe9517ec122a4f83f702f9cf58b564
M6D3_CORRECTED_CONFIG_HASH    = 852f924bb9f4143395131941d3ef7e45bc3111eaa4ab56d7d181c1f45c767dac
CONFIG_DIFFERENCES = 仅 1 项实质差异：
    ecology.sensitivity : calibration 1/279  vs  integrated(as run) 3998/525
```

### 2.2 FIRST_ECOLOGY_DIVERGENT_INPUT（§14，T1 级）

```
FIRST_ECOLOGY_DIVERGENT_INPUT = ecology.profile.sensitivity
                                （calibration 1/279 ≈ 0.003584 vs integrated 3998/525 ≈ 7.615）
```

T1 实测（同一 harness、同一 bootstrap、同一 owner-final profiles）：

| 量 | calibration（1/279） | integrated as run（3998/525） | 修正后（ratified 默认） |
|---|---|---|---|
| habitat_quality | **999,088** | **19,244** | **999,088** ✔ |
| ecological_stress | 518,883 | ~513,823 | 518,884 |
| population_pressure | 1,990 | 1,924 | 1,996 |
| extraction_pressure | 1,000,000 | 1,000,000 | 1,000,000 |
| production_pressure | 573,487 | 553,314 | 573,487 |
| depletion_pressure | 110 | 110 | 110 |

**输入侧（各压力分量）几乎相同，输出侧差 50×** ⇒ 分歧在 sensitivity 一项，而非 pressure
重复计算 / 单位缩放 / step 数（owner §15 case 2）。

### 2.3 判定

* 这是 **M6D.2 harness 的配置缺陷**（未固定/未传入 owner-ratified E-B-v2 sensitivity），
  **不是 production bug**，也**不是** calibration harness 漏接 pressure。
* 修复（test-only harness）：`tests/m6c1d_support.py` 新增
  `E_B_V2_RATIFIED_SENSITIVITY = Fraction(1, 279)` 并作为 `ecology_profile()` **默认**；
  env `M6C1D_ECOLOGY_SENSITIVITY` 仅保留给 re-calibration 扫描。
  `scripts/_m6d2_integrated.py` 现把生效 ecology 配置写入每个产物
  （profile/sensitivity/recovery/ppp/env），防止再次静默错配。
* 旧 E-B-v2 calibration evidence **未被推翻**（其配置即 ratified 1/279）；
  M6D.2 的 ~2% 数值降级为 `DIAGNOSTIC_NON_AUTHORITATIVE`（harness 配置错误所致）。
* **未重新标定 sensitivity**（owner §12）。`E_B_V2_OWNER_SELECTION = RETAINED`。
  `E_B_V2_FINAL_STATUS` 待修正后完整 integrated path 确认（owner §16/§26）。

---

## 3. lane C — Restart / history hash

### 3.1 §18 Hash definition audit

```
CONTINUOUS_HISTORY_HASH_DEFINITION =
  function  : services/history/service.py::canonical_causal_history_hash
  tables    : causal_history_links
  projection: [schema_version, world_id, count] + per link
              (relation_type, source_kind, source_id, target_kind, target_id,
               episode_id, status, committed_tick, semantic_version)
  ordering  : ORDER BY link_id（行序无关）
  genesis   : world_id 参与前缀；genesis 仅经其链接进入

RESTART_HISTORY_HASH_DEFINITION = 与上**完全相同**（同一函数/表/排序/投影/genesis 策略）

HASH_DEFINITION_EQUIVALENT = TRUE

另：M6D.2 报告中的 25b93c40e6f1… 是 **EVENT_STREAM_HASH**
  （services/simulation/event_stream.py::step_event_stream_hash；增量链、发射顺序、
   与 history 完全不同的投影）→ 与 history hash 比较属口径混用，不是不一致。
```

### 3.2 同函数重算（§19/§21）

```
recomputed_canonical_causal_history_hash:
  RUN1 (continuous) = 921324e2b779e130e273172fbbfa1f3d5b1f2d67b3c7f827398482e82a2ea2cf
  RUN2 (replica)    = 921324e2b779e130e273172fbbfa1f3d5b1f2d67b3c7f827398482e82a2ea2cf
  RUN3 (restart)    = 921324e2b779e130e273172fbbfa1f3d5b1f2d67b3c7f827398482e82a2ea2cf
CONTINUOUS_STATE_HASH = RESTART_STATE_HASH = 032aa1973f343da71d58ec6cd60ab32c24f5052f37aa1449a283e49285bfc4bf
streaming digests（RUN1/RUN2/RUN3 全同；diff missing/extra/different 全 0）:
  world_events_by_uid     9c495b15f9b8a10c…   (77,876 rows)
  causal_links            ac838ff5ba583963…   (1,161,583)
  entity_history_index    cc80f404e1144729…   (1,160,656)
  history_state_changes   1fbac6361d66e02e…   (604,610)
RESTART_EQUIVALENCE = PASS（state + history + causal hash 三项）
```

---

## 4. §28 回归与 STOP 条件

targeted domain suite（`test_m3a_tribulation + test_m3b_history + test_m3b_metric_audit +
test_m3_preflight + test_m6d3_*`）：

```
TOTAL=177   FAILED=12   ERRORS=0   SKIPPED=4
```

12 项失败**全部**是 frozen golden baseline / 冻结指标不匹配（无功能性/边界性失败）：

| 失败测试 | 证据 |
|---|---|
| `test_m3a_baseline_300y_artifact` | 300y state hash `c5ef2564…` ≠ golden `0fc6ece0…` |
| `test_hb34_m3a_baseline_unchanged` | 同上 |
| `test_hb43_300y_baseline_artifacts` | `m3b_causal_history_300y_v1/summary.json` 不一致 |
| `test_ma5_entity_history_index_rows_correct` | 66,005 ≠ 64,858 |
| `test_ma6_distinct_entities_with_history_correct` | 145 ≠ 134 |
| `test_ma7_domain_entities_separated_from_index_references` | index reference types 变化 |
| `test_ma9_causal_link_density_metrics_correct` | 2,224 ≠ 2,184 |
| `test_ma12_growth_projection_reproducible` | 4,535 ≠ 4,479 |
| `test_ma20_causal_history_hash_stable` | `d3b8a499…` ≠ `c1293e59…` |
| `test_ma22_world_state_hash_unchanged` | 同上 state hash |
| `test_ma23_event_stream_hash_unchanged` | `83bdc08f…` ≠ `8b117097…` |
| `test_ma28_metric_audit_baseline_artifacts` | `metric_audit.json` 不一致 |

**归因**：这些基线/指标是在**effect 被丢弃**的旧行为下冻结的。修复后灾劫效果真正落地
→ 更多权威 state change 被索引（66,005 > 64,858；145 > 134 实体）→ 三哈希改变。
即：**基线编码了 bug**，不是修复引入回归。

```
GOLDEN_BASELINE_MUTATIONS = 12（全部为含 tribulation 的 M3a/M3b 基线）
M2 家族 golden 基线（mini_world，无 tribulation）实测：230 tests / FAILED 0 /
  ERRORS 0 / SKIPPED 8 / exit 0 → GOLDEN_BASELINE_MUTATIONS(M2) = 0
```

按 owner §28：**Golden baseline 变化 ⇒ STOP，不自动更新**。
因此 **canonical fast regression 本轮未启动**（其必然因上述 4 组基线失败），
`FAST_REGRESSION = NOT_RUN_PENDING_OWNER_BASELINE_DECISION`。

需 Owner 裁决：是否授权**重新冻结** M3a/M3b 300y 基线（because 旧基线编码了
effect-dropped 行为）——本 agent 不自行更新任何 baseline。

---

## 5. 交付文件

* 修复：`services/simulation/tribulation_adapters.py`、`services/simulation/coordinator.py`
* 复现/门禁测试：`tests/test_m6d3_tribulation_effect_application.py`
* harness 配置修复：`tests/m6c1d_support.py`（`E_B_V2_RATIFIED_SENSITIVITY`）、
  `scripts/_m6d2_integrated.py`（产物记录生效 ecology 配置）
* 审计脚本：`scripts/_m6d3_evidence_manifest.py`、
  `scripts/_m6d3_history_equivalence.py`、`scripts/_m6d3_config_equivalence.py`、
  `scripts/_m6d3_effect_identity.py`、`scripts/_m6d3_eb_profile.py`、
  `scripts/_m6d3_ebv2_probe.py`
* 证据产物：`reports/M6D3_M6D2_EVIDENCE_MANIFEST.json`、
  `reports/M6D3_HISTORY_EQUIVALENCE.json`、
  `reports/M6D3_CONFIG_EQUIVALENCE.json`

M6D.2 现场 DB 保留（owner §1/§30）：
`%TEMP%\m6d2_5ohuj6y7\`（run1/run2/run3 各 1,096,151,040 bytes；
sha256 见 manifest；`M6D2_FORENSIC_EVIDENCE_READ_ONLY = TRUE`，未修改）。

---

## 6. 修正后 integrated 300y（§23/§24）

`IN_FLIGHT`：RUN1/RUN2 连续 300y + RUN3（0→100y seed 0 / 100→300y seed 42）正以修正后配置
（P2-B + RE-LEAN-v2 + **ratified E-B-v2 1/279** + S-B + T-B + effect fix）运行
（job `pwsh-81`，产物 `reports/M6D3_CORRECTED_INTEGRATED_VERIFICATION.json`）。

**已完成的修正后短程验证（T50，同一 harness / 同一配置）**：

```
FINAL_STATE_HASH (T50)  = a47b4d96bae6acddbc661f9e31a9f43da5eca64723370735fe7b5898f1daa077
FINAL_EVENT_STREAM_HASH = 3134785a7c00c8ea14038d5147910d53f320909b9a4b5982b47329957032f4dc
POP_T50 = 10464        RESOURCE_UNMET_DEMAND_CELLS = 0（逐年 unmet 全 0）
HABITAT_T25 = 979,960  HABITAT_T50 = 968,847   ← 回到 owner 93–97% 政策区间（修复前 2%）
TRIBULATION_EFFECT_APPLIED_IDENTITY = PASS（dropped 0 / exactly-once 0）
POPULATION_ACCOUNTING_IDENTITY = PASS（residual 0，含 casualty 口径）
ecology_effective_config 记录于产物: sensitivity = 1/279, recovery = 1/25, ppp = 1
```

300y 完成后填入：T10/T50/T100/T300 人口与四族、habitat 四点、逐域 identity、
DETERMINISM、RESTART_EQUIVALENCE、history integrity、300y 版
`TRIBULATION_EFFECTS_RECORDED/APPLIED/DROPPED`。

旧 M6D.2 数值继续保留为诊断 evidence，不作为最终 Snapshot truth（owner §23）；
M6D.2 的 habitat ≈2% 轨迹归因于 harness 配置错误（§2），标记
`DIAGNOSTIC_NON_AUTHORITATIVE_HARNESS_CONFIG_ERROR`。

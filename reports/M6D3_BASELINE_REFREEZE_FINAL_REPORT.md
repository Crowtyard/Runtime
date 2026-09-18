# M6D.3 — BASELINE REFREEZE FINAL REPORT（OPT-1 执行 + 新阻塞点）

**UPDATE_ENTRYPOINT_REPAIR = PASS**
**BASELINE_REFREEZE = PASS（12 个授权文件已按 canonical 路径重冻结）**
**TARGETED_REGRESSION = FAIL（6 项内联冻结字面量，超出本轮授权写入面）**
**NEXT_ACTION = AWAIT_OWNER_ON_BASELINE_REFREEZE_FAILURE**

---

## 1. owner §21 字段

```
UPDATE_ENTRYPOINT_REPAIR              = PASS
NORMAL_MODE_STRICT                    = PASS
UPDATE_MODE_FUNCTIONAL                = PASS

FILES_MODIFIED_TEST_INFRA             =
  tests/test_m3a_tribulation.py      （update mode：dump-then-return）
  tests/test_m3b_history.py          （同上）
  tests/test_m3b_metric_audit.py     （同上）
  tests/test_golden_update_mode.py   （新增：9 条 test-infra 回归）
  scripts/_m6d3_fast_regression_chunked.py（新增：chunked/JUnit 计数跑法）
  scripts/_m6d3_refreeze_crosscheck.py    （新增：生成物 vs 采集候选交叉校验）

BASELINE_REFREEZE                     = PASS
AUTHORIZED_BASELINE_REFREEZE_COUNT    = 12（文件级；见 §3）
UNAUTHORIZED_BASELINE_MUTATIONS       = 0
M2_BASELINE_MUTATIONS                 = 0
GENERATED_MATCHES_CAPTURED_CANDIDATE  = PASS（12/12，确定性字段口径）
BASELINE_PROVENANCE_COMPLETE          = TRUE

TARGETED_REGRESSION                   = FAIL
TARGETED_COLLECTED                    = 146
TARGETED_PASSED                       = 137
TARGETED_FAILED                       = 6
TARGETED_ERRORS                       = 0
TARGETED_SKIPS                        = 3

FAST_REGRESSION                       = NOT_RUN（§12 要求 targeted 先 0 failed）

FORMAL_DB_AUTHORITY                   = PASS
FORMAL_DB_SHA256                      = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837
FORMAL_WORLD_RUNTIME_ROWS             = 0
FORMAL_WORLD_STATUS                   = NOT_ACTIVATED
FORMAL_WORLD_SEED_CONSUMED            = FALSE

E_B_V2_FINAL_STATUS                   = OWNER_RATIFIED_FOR_SNAPSHOT_V1
OWNER_ACCEPTS_LONG_TERM_POPULATION_TRAJECTORY = TRUE

SNAPSHOT_V1_ENGINE_VERIFIED_CANDIDATE = FALSE（targeted/fast 未全绿）
SNAPSHOT_V1                           = NOT_APPROVED
MATERIALIZER_ALLOWED                  = FALSE
FORMAL_ACTIVATION_ALLOWED             = FALSE
```

---

## 2. OPT-1 修复（TEST-INFRA-ONLY，未动 production / 未动 frozen 语义）

Owner 判断成立：`UPDATE_ENTRYPOINT = EXISTS_BUT_FUNCTIONALLY_BROKEN_FOR_SEMANTIC_REFREEZE`。

修复方式采用 owner §1 指定的**最窄方案**（只改 3 个授权 artifact test 的流程）：

```python
artifact = compute_current_artifact(...)
if update_mode_enabled():
    dump_artifact(...)      # 写入当前 artifact 即完成
    return
assert_deterministic_equal(expected_baseline, artifact)   # normal mode：严格比较
```

* **未修改** `assert_deterministic_equal()` 本体（owner §1 首选）；
* **未**把全局断言改成"update mode 永不 raise"；
* normal mode（`BLR_UPDATE_GOLDEN_BASELINES` 未开）行为逐字保持；
* 未新增第二套 writer；仍只用 `scripts/update_baselines.py` + `dump_artifact`。

`tests/test_golden_update_mode.py`（9 tests，全绿）覆盖 owner §5 的 A–D：

| 用例 | 内容 | 结果 |
|---|---|---|
| A | normal mode，old != new → 比较必须 FAIL | PASS |
| B | update mode，old != new → canonical writer 真正写入 | PASS |
| C | update mode，仅 telemetry 差异 → 按既有 GB3 规则 | PASS |
| D | 未授权路径无隐式写权限；updater 仅显式节点清单（无全仓扫描）；不存在第二套 writer | PASS |
| E | 结构守卫：3 个授权 artifact test 必须"先 dump 后比较"且保留严格比较（防回归） | PASS |

---

## 3. 正式重冻结（§7/§8/§9）

命令（owner §3：显式传入现有 3 个授权 artifact 节点，未全仓扫描）：

```
python scripts/update_baselines.py \
  tests/test_m3a_tribulation.py::test_m3a_baseline_300y_artifact \
  tests/test_m3b_history.py::test_hb43_300y_baseline_artifacts \
  tests/test_m3b_metric_audit.py::test_ma28_metric_audit_baseline_artifacts
→ "..." (3 passed in update mode) → 从当前 clean HEAD 真实重算写入
```

**未**把 `reports/_m6d3_candidates_keep/` 直接拷入 baselines（owner §7）。

交叉校验（`scripts/_m6d3_refreeze_crosscheck.py`，确定性字段、忽略 GB3 telemetry）：

```
GENERATED_MATCHES_CAPTURED_CANDIDATE = PASS   (12/12 文件)
RUN1 == RUN2 == 官方写入                            （§8 两轮确定性）
```

**范围硬检查（§9）**：`git status --short tests/baselines` = **恰好 12 个文件**，
`M2_BASELINE_MUTATIONS = 0`，其它 M3 / scheduler / M6 baseline = **0 变更**。
最终 commit `4b9a713` 只含这 12 个文件。

### 3.1 第 13 个文件的发现与处理（§9 硬检查，如实记录）

canonical updater 在本次运行中**额外**改写了
`tests/baselines/m3b_causal_history_300y_v1/query_performance.json`——该文件由**已授权**的
metric-audit 节点 dump，但它属**纯机器计时 telemetry**（normal mode 只比较键集合），
且本次被写成 **四个条目全 `null`**（信息被破坏）。

处理：**已 `git checkout` 回滚该文件**（telemetry 数值恢复：114.594 / 2.148 / 13.8 / 0.849），
未纳入 commit。即：未静默接受第 13 个变更（owner §9）。
待 Owner 决定是否另行授权该 telemetry 文件按其正常语义刷新。

---

## 4. 新的阻塞点：6 项**内联冻结字面量**（owner §9/§10 边界之外）

重冻结后，先前 12 项失败中的 **6 项已转绿**
（`test_m3a_baseline_300y_artifact`、`hb34`、`hb43`、`ma22`、`ma23`、`ma28`），
但仍有 **6 项失败于 `tests/test_m3b_metric_audit.py` 的测试体字面量**：

| 位置 | 断言 | OLD（字面量，effect-dropped 真值） | NEW（修正后引擎真值） |
|---|---|---|---|
| `:148` `test_ma5_entity_history_index_rows_correct` | `entity_history_index_rows` | 64,858 | **66,005** |
| `:154` `test_ma6_distinct_entities_with_history_correct` | `distinct_entities_with_history` | 134 | **145** |
| `:168` `test_ma7_domain_entities_separated_from_index_references` | `distinct_event_ids_indexed` | 2,184 | **2,224** |
| `:188` `test_ma9_causal_link_density_metrics_correct` | 链接密度指标 | 4,479 | **4,535** |
| `:219` `test_ma12_growth_projection_reproducible` | growth projection | 21,914 | **22,296** |
| `:365` `test_ma20_causal_history_hash_stable` | `causal_history_hash` | `c1293e59d967…44c8727046a44` | **`d3b8a499257f…6cbdc4fd2ae130ba`** |

**性质**：与已重冻结的 baseline 属**同一类**冻结期望（`BUG_FIX_BASELINE_INVALIDATION`：
旧值忠实记录了 effect 被丢弃时的行为），但它们**不在 `tests/baselines/` 内**，
而是硬编码在测试体里，因此：

* canonical updater（本轮修复后）**无法**刷新它们；
* owner §9 的硬检查口径只覆盖 `tests/baselines`；
* owner §10 明确"不得弱化测试期望"，我**不自行**改动这些数字。

⇒ 依 owner §9/§12（targeted 必须 0 failed 才能进 fast regression）**STOP 并交回裁决**。

### 4.1 两个可选 remediation（我未实施任何一个）

| 选项 | 做法 | 说明 |
|---|---|---|
| **OPT-A** | 授权把这 6 个字面量按上表 OLD→NEW 更新为修正后真值 | 与 baseline 重冻结同类（`BUG_FIX_BASELINE_INVALIDATION`），严格性不变，仅数值体检 |
| **OPT-B**（建议） | 把这 6 处断言改为**从已重冻结的 `metric_audit.json` baseline 读取期望值**（单一真值源），断言仍为严格相等 | 消除"数值双写"；今后任何经授权的重冻结自动传播，不再出现本轮这种漂移；属 test-infra 改进，不改世界语义 |

任一授权后我会：更新 → 重跑 targeted（受影响 → 广域，0 failed/0 errors）→
canonical fast regression（chunked/JUnit 计数，报告**实测** collected/passed/expected skips）→
最终 baseline 统计 → 才判定 `SNAPSHOT_V1_ENGINE_VERIFIED_CANDIDATE`。

---

## 5. Provenance 补充（owner §10）

* 原 canonical update entrypoint 在 semantic baseline change 场景下，因
  **compare-before-write** 事实上不可用（test infrastructure bug）。
* 本轮 `TEST_INFRA_UPDATE_MODE_REPAIR` 只**恢复 updater 本来宣称拥有的功能**：
  update mode 下写出当前 artifact。
* 它**不是**：world-law change、baseline 数值手工改写、test expectation weakening。
  （normal mode 的 GB guards / 严格比较 / telemetry 剥离 / artifact 规范化全部保持不变，
  并由 `tests/test_golden_update_mode.py` A–E 守卫。）

## 6. 提交纪律（§11）

```
67b7c55  test: make golden baseline update mode functional          (Commit A：test infra + 回归)
4b9a713  test: re-freeze M3 tribulation baselines after effect-…     (Commit B：仅 12 个授权 baseline)
（Commit C：本报告 + provenance 补充 + crosscheck 证据）
```

无 amend / rebase / force push；未创建 M6 freeze tag；未实现 Materializer；
未激活正式世界；未消费正式 Seed；未部署 live。

## 7. 正式世界与取证（§17/§18）

```
AUTHORITATIVE_DB_RESOLUTION = PASS   NON_AUTHORITATIVE_DB_DETECTED = False
FORMAL_DB_SHA256 = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837
FORMAL_WORLD_RUNTIME_ROWS = 0   CURRENT_BLESSED_TICK = NULL
FORMAL_WORLD_STATUS = NOT_ACTIVATED   FORMAL_WORLD_SEED_CONSUMED = FALSE
```

M6D.2 forensic DB 保留未删：`%TEMP%\m6d2_5ohuj6y7\`（owner §18）。
Ecology / Population owner 状态按 §15/§16 记录，sensitivity 1/279 与 birth_rate 53/1000
均未重新 calibration。

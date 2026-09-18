# M6D.3 — OPT-B FINAL CLOSEOUT REPORT

**OPT_B_IMPLEMENTATION = PASS**
**METRIC_AUDIT_SINGLE_SOURCE_OF_TRUTH = PASS**
**INLINE_GOLDEN_DUPLICATION = 0**
**AFFECTED_SIX_ASSERTIONS = PASS（6/6，0 skips，精确相等）**
**TARGETED_AFFECTED = PASS　TARGETED_WIDER = FAIL（1 项，非授权范围内）**
**FAST_REGRESSION = NOT_RUN（按 owner §13 顺序，targeted 未全绿前不启动；已在启动后停止并保留 chunk 供 `--resume`）**
**NEXT_ACTION = AWAIT_OWNER_ON_M6D3_OPT_B_FAILURE**

---

## 1. owner §20 字段

```
OPT_B_IMPLEMENTATION                  = PASS
METRIC_AUDIT_SINGLE_SOURCE_OF_TRUTH   = PASS
INLINE_GOLDEN_DUPLICATION             = 0

QUERY_PERFORMANCE_REFREEZE            = NOT_AUTHORIZED
QUERY_PERFORMANCE_BASELINE_MUTATION   = 0

AUTHORIZED_BASELINE_REFREEZE_COUNT    = 12
UNAUTHORIZED_BASELINE_MUTATIONS       = 0
M2_BASELINE_MUTATIONS                 = 0

AFFECTED_SIX_ASSERTIONS               = PASS（6/6）

TARGETED_REGRESSION                   = FAIL（affected PASS / wider 1 failure）
TARGETED_COLLECTED                    = 707（wider）／148（affected）
TARGETED_PASSED                       = 693（wider）／145（affected）
TARGETED_EXPECTED_SKIPS               = 13（wider）／3（affected）
TARGETED_FAILED                       = 1（wider）／0（affected）
TARGETED_ERRORS                       = 0

FAST_REGRESSION                       = NOT_RUN（STOPPED；见 §4）
FAST_COLLECTED / FAST_PASSED / FAST_EXPECTED_SKIPS / FAST_FAILED / FAST_ERRORS /
FAST_UNEXPECTED_SKIPS                 = NOT_RUN（未产生 chunk JUnit；workdir 保留供 resume）

FORMAL_DB_AUTHORITY                   = PASS
FORMAL_DB_SHA256                      = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837
FORMAL_WORLD_RUNTIME_ROWS             = 0
FORMAL_WORLD_STATUS                   = NOT_ACTIVATED
FORMAL_WORLD_SEED_CONSUMED            = FALSE

TRIBULATION_EFFECT_APPLICATION        = PASS
T_B_ENGINE_VERIFICATION               = PASS
E_B_V2_ENGINE_VALIDATION              = PASS
DETERMINISM                           = PASS
RESTART_EQUIVALENCE                   = PASS
HISTORY_INTEGRITY                     = PASS
INTEGRATED_WORLD_VIABILITY            = PASS

SNAPSHOT_V1_ENGINE_VERIFIED_CANDIDATE = FALSE（wider targeted 未全绿）
SNAPSHOT_V1                           = NOT_APPROVED
MATERIALIZER_ALLOWED                  = FALSE
FORMAL_ACTIVATION_ALLOWED             = FALSE
```

---

## 2. OPT-B 实现（owner §1/§2/§3/§5/§6）

窄 helper（未新建 magic-number 模块，复用既有 `load_artifact`）：

```python
def _expected(name: str) -> dict:
    """EXPECTED 来自 committed（已 refrozen）baseline artifact —— single source of
    golden truth；ACTUAL 仍由本次 production 计算独立得到。"""
    return load_artifact(BASELINE_DIR / name)
```

六个 duplicated frozen expectations 全部改为 baseline 读取：

| 测试 | EXPECTED 来源 | 原内联字面量 → baseline 值 |
|---|---|---|
| `ma5` | `entity_cardinality_audit.json["entity_history_index_rows"]` | 64,858 → **66,005** |
| `ma6` | `…["distinct_entities_with_history" / "distinct_domain_entities" / "distinct_entity_ids"]` | 134 → **145** |
| `ma7` | `…["graph_node_cardinality"][三个 distinct_*_indexed]` | 2,184 / 37,759 / 30 → **2,224 / 37,826 / 30** |
| `ma9` | `relation_density_audit.json[五个指标]` | 4,479 / 37,818 / 65,742 / ±0.01 → **4,535 / 37,885 / 66,889（精确相等）** |
| `ma12` | `growth_projection.json["growth_projection"][六个指标]` | 21,914 / 21,619 / 12,606 / 10 / 219,140 / 1,095,700 → baseline 值（22,296 / 22,002 / 12,628 / 10 / 222,963 / 1,114,817） |
| `ma20` | `metric_audit.json["hash"]["causal_history_hash"]` | `c1293e59…` → **`d3b8a499…`** |

* **严格性不降反升**：全部精确相等；原 `ma9` 两处 `<0.01` 容差改为对 baseline 的精确相等。
* **保留**全部独立语义/结构/边界断言（`metric_source_table`、`classification`、
  `index_reference_only_types == []`、`distinct < rows`、关系分布完备性与求和、
  `projection_mode` 等）。
* **非 tautological**：`_expected()` 只 `load_artifact(BASELINE_DIR / …)`；
  ACTUAL 来自 `entity_cardinality_audit` / `relation_density_audit` /
  `growth_projection` / `HistoryService.causal_history_hash`（由 §6 的 G 测试以 AST 强制）。
* **Anti-drift**（AST，非文本 grep）：F 六个测试必须经 `_expected(...)` 取期望且函数体内
  不得再出现被 baseline 覆盖的冻结数字/哈希（`INLINE_GOLDEN_DUPLICATION = 0`）；
  G `_expected` 只允许读 committed baseline，禁止审计计算与 `dump_artifact`。

§9 结果：`tests/test_m3b_metric_audit.py -k "ma5 or ma6 or ma7 or ma9 or ma12 or ma20"`
→ **6 collected / 6 passed / 0 skipped**（非 skip、非弱化，均为精确相等通过）。

---

## 3. Targeted 回归（owner §10/§11）

`affected`（此前 146 collected 的同一集合，现含 2 条新 anti-drift 测试）：

```
collected = 148   passed = 145   failed = 0   errors = 0   skipped = 3   rc = 0   (940 s)
```

`wider`（M2 family + M3 engine set + M3a/M3b + metric audit + history integrity +
determinism + restart + M6 targeted + M6D3 effect identity，共 23 个文件）：

```
collected = 707   passed = 693   failed = 1   errors = 0   skipped = 13   rc = 1   (4822 s)
FAILED tests/test_scheduler_determinism.py::test_scheduler_1000y_reproduces_frozen_seed001
```

13 个 skip 全部是既有条件门禁（12 × `BLR_FORMAL_DB_PATH` + 1 ×
`BLR_TEST_PG_DSN`），与预期一致。

证据：`reports/M6D3_TARGETED_REGRESSION.json`（含每集合 JUnit 路径与失败 node id）。

---

## 4. 新阻塞点：M6D.3 effect fix 的 baseline 影响面**大于**已授权的 12 个文件

### (B1) M3 integrated 冻结基线（1000y / 5000y）同样编码了 effect-dropped 行为

* 读取方 1：`tests/test_scheduler_determinism.py::test_scheduler_1000y_reproduces_frozen_seed001`
  → 对比 `tests/baselines/m3_integrated_1000y_v1/seed_001.json` → **本次实测 FAIL**。
* 读取方 2：`tests/test_scheduler_endurance.py`
  → 对比 `tests/baselines/m3_integrated_5000y_seed001_v1.json` → 同类，预计 FAIL
  （该 5000y 用例属 fast chunk01，本轮未单独跑）。
* 生成方：`tests/test_m3_integrated_long.py::test_lt1_1000y_five_seeds` /
  `::test_lt7_5000y_endurance` / `::test_lt13_summary_artifact` —— **已被列在
  `scripts/update_baselines.py::ARTIFACT_TESTS` 中**，因此 canonical updater **可以**
  刷新它们；但 canonical fast suite 明确 ignore 该文件，且重算成本高
  （1000y × 5 seeds + 5000y，约数小时）。

### (B2) `tests/test_query_service.py` 内联 M3 哈希字面量

`test_m5q46_m3_baselines_unchanged` 断言
`final_world_state_hash.startswith("0fc6ece0")`（= **重冻结前**的 M3a 300y hash；
现为 `c5ef2564…`）与 `startswith("7cd769e0")`（M2d 120y，未受影响）。
实测：`tests/test_query_service.py` → **25 collected / 24 passed / 1 failed**
（`FAILED tests.test_query_service::test_m5q46_m3_baselines_unchanged`）。

该测试**设计上**就是"M3 基线未变"守护；owner 授权的重冻结使其需要同步更新——
与本轮 6 个 metric-audit 字面量**属同一类**（`BUG_FIX_BASELINE_INVALIDATION`），
但**不在** 12 个授权文件内，OPT-B 授权文本也只点名了 6 个 metric-audit literals。

### 4.1 请求 Owner 裁决（我未改动任何相关文件）

| 选项 | 内容 | 成本 |
|---|---|---|
| **B1-OPT-A** | 授权把 M3 integrated 基线（`m3_integrated_1000y_v1/` 5 seeds + `summary.json`、`m3_integrated_5000y_seed001_v1.json`）纳入重冻结，走同一 canonical updater + 同一 provenance 纪律 | 需重跑 1000y×5 + 5000y（数小时） |
| **B1-OPT-B** | 仅授权其中**被测试读取**的部分（`seed_001.json`、5000y seed001），或把这两个读取方改为 M3c 范围内的"自洽确定性"检查（不依赖冻结历史值） | 中等 |
| **B2-OPT-A** | 对本轮 OPT-B 的同款做法：把 `test_query_service.py` 的两处哈希前缀改为**从已 refrozen 的 M3a summary 读取**（single source），M2d 前缀保持不变 | 极小 |
| **B2-OPT-B** | 或授权把 `0fc6ece0…` 字面量替换为重冻结后的 `c5ef2564…` | 极小 |

---

## 5. Fast regression（owner §13/§14）

按 owner §13 顺序（targeted 全绿后才启动），本轮**未**完成 fast regression：
其在 wider 结果出来前已启动 chunk01（scheduler 重档），确认 (B1) 后**已停止**，
未产生任何 chunk JUnit；`--workdir %TEMP%\m6d3_fast_chunks` 已保留，
脚本 `scripts/_m6d3_fast_regression_chunked.py` 支持 `--resume`（复用已完成 chunk，
只补 interrupted / not-started，符合 owner §14）。

`FAST_*` 一律记为 NOT_RUN，**不预填**任何历史数字（1025/983/42 等均未使用）。

---

## 6. query_performance.json（owner §7/§8）

`QUERY_PERFORMANCE_REFREEZE = NOT_AUTHORIZED` → 文件保持 refreeze 前状态
（telemetry 114.594 / 2.148 / 13.8 / 0.849 完整），
`QUERY_PERFORMANCE_BASELINE_MUTATION = 0`，**不计入** 12 个授权文件；
本轮**未**扩大 updater 修复（未来 telemetry 刷新另立 workflow）。

## 7. 提交（owner §19）

```
809316c  test: deduplicate M3 metric-audit golden expectations   (OPT-B 实现)
67b7c55  test: make golden baseline update mode functional        (OPT-1 修复)
4b9a713  test: re-freeze M3 tribulation baselines after effect-…  (12 个授权 baseline)
（本报告 + targeted 证据：docs commit）
```
无 amend / rebase / force push；无 freeze tag；未实现 Materializer；
未激活正式世界；未消费正式 Seed；未部署。正式世界开始/结束各查一次，均 PASS
（sha256 未变、`world_runtime = 0`、`NOT_ACTIVATED`、`CURRENT_BLESSED_TICK = NULL`、
Seed 未消费）。Owner canon 未变（§16）；M6D.2 forensic DB 保留未删（§18）。

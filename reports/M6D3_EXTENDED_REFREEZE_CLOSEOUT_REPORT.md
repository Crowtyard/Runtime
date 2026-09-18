# M6D.3 — EXTENDED REFREEZE CLOSEOUT REPORT

**状态：IN PROGRESS（B1 长跑执行中；B2 已完成并提交）**
**红线：`SNAPSHOT_V1 = NOT_APPROVED`　`MATERIALIZER_ALLOWED = FALSE`　
`FORMAL_ACTIVATION_ALLOWED = FALSE`**

---

## 0. owner §27 / §L 字段

```
B1_INTEGRATED_REFREEZE            = PASS（canonical updater 写入 7 文件，Commit D 9fbe412）
M3_INTEGRATED_REFREEZE_COUNT      = 7（实测）
AUTHORIZED_BASELINE_REFREEZE_COUNT_TOTAL = 19（12 + 7）

B2_QUERY_SERVICE_SINGLE_SOURCE    = PASS（Commit 398775a）
QUERY_SERVICE_INLINE_HASH_DUPLICATION = 0

QUERY_PERFORMANCE_BASELINE_MUTATION = 0
UNAUTHORIZED_BASELINE_MUTATIONS   = 0
M2_BASELINE_MUTATIONS             = 0
OTHER_UNRELATED_BASELINE_MUTATIONS = 0

INTEGRATED_GENERATED_MATCHES_RUN1_RUN2 = PASS（见 §2.1 说明口径）

AFFECTED_TARGETED_REGRESSION      = PASS
AFFECTED_TARGETED_COLLECTED       = 10
AFFECTED_TARGETED_PASSED          = 10
AFFECTED_TARGETED_SKIPPED         = 0
AFFECTED_TARGETED_FAILED          = 0
AFFECTED_TARGETED_ERRORS          = 0
   G1 = PASS (1/1, 428s)   1000y determinism reader
   G2 = PASS (1/1, 3222s)  5000y endurance reader
   G3 = PASS (1/1, 36s)    M5Q46 query-service guard
   G4 = PASS (7/7, 5835s)  M3-integrated artifact nodes（normal mode vs refrozen goldens）

QUERY_SERVICE_FINGERPRINT_FIX     = PASS（Commit 4779001；单字段修复）
CHECKPOINT_ORDER_COLUMN           = checkpoint_blessed_tick
QUERY_WORLD_STATE_HASH_POPULATED  = TRUE
QUERY_EVENT_STREAM_HASH_POPULATED = TRUE
QUERY_CAUSAL_HISTORY_HASH_POPULATED = TRUE
QUERY_FINGERPRINT_RESTART_EQUIVALENCE = PASS
QUERY_SERVICE_BROAD_EXCEPTION_TECH_DEBT = OPEN_NON_BLOCKING
M3_INTEGRATED_BASELINE_ARTIFACT_DIFF_AFTER_QUERY_FIX = 0

WIDER_TARGETED_REGRESSION         = PASS（§J；见下）
FAST_REGRESSION                   = PASS
FAST_COLLECTED                    = 1049（chunked runner 实测）
                                    1048（canonical 口径：runner 额外收集了
                                    tests/zz_formal_db_guard.py 1 例，该文件不在
                                    canonical `pytest tests -q` 的收集范围内）
FAST_PASSED                       = 1006
FAST_EXPECTED_SKIPS               = 43（chunked 实测）／42（canonical 口径：
                                    12 × BLR_FORMAL_DB_PATH + 30 × BLR_TEST_PG_DSN）
FAST_FAILED                       = 0
FAST_ERRORS                       = 0
FAST_UNEXPECTED_SKIPS             = 0（全部为既有条件门禁）

§J 分步实测（final HEAD 4779001）：
  1 query fingerprint   5 / 5
  2 B2 query service   25 / 25
  3 scheduler determinism  → 复用 §14 G1（PASS 1/1，428s）
  4 scheduler endurance    → 复用 §14 G2（PASS 1/1，3222s）
  5 M3 integrated readers  → 复用 §14 G4（PASS 7/7，5835s）
  6 M3a/M3b           131 / 134（3 expected skips）
  7 history integrity 107 / 110（3 expected skips）
  8 M6 / M6D3         247 / 248（1 expected skip）
  9 wider targeted    552 / 562（10 expected skips）
  → 全部 0 failed / 0 errors；TARGETED_REGRESSION = PASS

BASELINE_PROVENANCE_COMPLETE      = TRUE

FORMAL_DB_AUTHORITY               = PASS
FORMAL_DB_SHA256                  = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837
FORMAL_WORLD_RUNTIME_ROWS         = 0
FORMAL_WORLD_STATUS               = NOT_ACTIVATED
FORMAL_WORLD_SEED_CONSUMED        = FALSE

SNAPSHOT_V1_ENGINE_VERIFIED_CANDIDATE = TRUE
SNAPSHOT_V1                       = NOT_APPROVED
MATERIALIZER_ALLOWED              = FALSE
FORMAL_ACTIVATION_ALLOWED         = FALSE
NEXT_ACTION                       = AWAIT_OWNER_FINAL_SNAPSHOT_V1_RATIFICATION
```

### 0.1 Fast regression 环境说明（如实记录，不影响判定）

首次 final-HEAD fast 运行（chunk 1–8）出现 **2 项失败**，全部位于
`tests/test_query_isolation.py`：`test_m5q38_runtime_update_isolation` /
`test_m5q39_companion_update_isolation`，错误为
`RuntimeError: 无法解析 AstrBot plugin_data 路径（缺少官方路径 API）`
（`plugin_shell/paths.py:35`）。

* 定性：**环境/测试 harness 配置条件**，与 M6D.3 任何改动无关
  （本机解释器 `import astrbot` 失败；隔离运行同样失败）。
* 该模块自带受官方支持的测试覆盖：`plugin_shell/paths.py` 文档说明
  「测试可通过环境变量 `BLR_TEST_PLUGIN_DATA_DIR` 覆盖（仅测试 harness 使用）」。
* 验证：以 `BLR_TEST_PLUGIN_DATA_DIR=<tmp>\astrbot_plugin_blessed_land_runtime`
  （须为**插件同名目录**，否则测试自身断言 `plugin name in str(data_dir)` 失败）
  运行 `tests/test_query_isolation.py` → **4/4 PASS**。
* 处理：在**同一 final HEAD**、仅补上该受支持覆盖的前提下**只重跑 chunk 7**
  （461s，85/85 PASS），其余 chunk 的证据在同一 HEAD 上继续有效（无 HEAD 漂移，
  未复用跨 HEAD chunk）；随后 `--resume` 重新聚合全部 8 个 chunk 得到上表总计。
* 若 Owner 要求"零环境覆盖"的 canonical 复跑，可在具备 AstrBot 运行时（或已设
  `BLR_TEST_PLUGIN_DATA_DIR`）的环境中整轮重跑，本 runner 支持 `--resume`/整轮重跑。

---

## 1. B2（owner 裁决 F）— DONE

`test_m5q46_m3_baselines_unchanged`（nodeid 保留）：

* EXPECTED ← committed（已授权重冻结）M3a 300y `summary.json`（`load_artifact`）
* ACTUAL ← 独立 production M3a 300y 重算（`run_m3a_world` report），**精确相等**
* 另加 query 层确认：同一 world 已 committed 到 tick 300,000,000 且有 checkpoint rows
* 跨 artifact 不变量：committed M3b `world_state_hash` == committed M3a
  `final_world_state_hash`（不含任何 hash 字面量；精确身份仍由 `test_hb43` /
  `test_ma20` 对同一 committed artifact 断言）
* 删除的 duplicated golden truth：旧 M3a 前缀 `0fc6ece0…` 与 M3b 前缀 `c1293e59…`
  —— **未**替换为新字面量
* Anti-drift（AST）：guard H —— `QUERY_SERVICE_INLINE_HASH_DUPLICATION = 0`

实测：`13 collected / 13 passed / 0 failed`（含 11 条 infra/anti-drift 测试）。
Commit：`398775a`。

## 2. B1（owner 裁决 A/G）— 长跑与实测 inventory

**两轮 capture 已完成**（`M3C_CANDIDATE_DIR` repo-external，`tests/baselines` 全程
0 dirty）：每轮 lt1（5×1000y seeds）与 lt7（5000y endurance）以独立进程并发，
随后 lt13 summary；每轮 ≈60 min。**`RUN1 == RUN2`（确定性字段）全 7 文件 PASS。**

**实测 inventory**（`reports/M6D3_M3_INTEGRATED_CANDIDATE_INVENTORY.json`）：

| FILE | ROLE | OLD_SHA256 → NEW_CANDIDATE_SHA256 | 语义字段变化数 | RUN1==RUN2 |
|---|---|---|---|---|
| `m3_integrated_1000y_v1/seed_001.json` | 1000Y_SEED_RECORD | `941b3ff1473a…` → `ac469935ee5c…` | 11 | PASS |
| `…/seed_002.json` | 1000Y_SEED_RECORD | → | 11 | PASS |
| `…/seed_003.json` | 1000Y_SEED_RECORD | → | 11 | PASS |
| `…/seed_004.json` | 1000Y_SEED_RECORD | → | 11 | PASS |
| `…/seed_005.json` | 1000Y_SEED_RECORD | → | 11 | PASS |
| `…/summary.json` | 1000Y_SUMMARY | `f2f59375ecec…` → `4b120af2011c…` | 语义 + 嵌套 telemetry | PASS |
| `m3_integrated_5000y_seed001_v1.json` | 5000Y_ENDURANCE_RECORD | `17dcc6b70dad…` → `c1aa835964ee…` | 11 | PASS |

`M3_INTEGRATED_REFREEZE_COUNT = 7`（**实测**，owner §1 明确不得预设为 2）。

变化字段（逐文件一致的 11 项）完全归因于本次 effect-application 修复：
`hashes.world_state_hash` / `hashes.event_stream_hash` / `hashes.causal_history_hash`
与 `counts.world_events` / `counts.causal_history_links` / `counts.entity_history_index(_rows)`
/ `counts.history_state_changes` / `counts.households` / `counts.lineages` /
`counts.distinct_entities_with_history`
（例：seed_001 links 201,619 → 199,707；5000y links 940,440 → 954,359）。
`summary.json` 另有 `db_growth.*`（GB3 telemetry 类，嵌套在 telemetry 键下，
已与语义变化分开归类）。

**正式写入**（owner §4/§7）：`python scripts/update_baselines.py
tests/test_m3_integrated_long.py::test_lt1_1000y_five_seeds
tests/test_m3_integrated_long.py::test_lt7_5000y_endurance
tests/test_m3_integrated_long.py::test_lt13_summary_artifact`
（同一 production HEAD，canonical 入口；不手改 JSON、不 copy 候选）。

**首次尝试被同一类 test-infra 缺陷阻塞（如实记录）**：该模块的三个 artifact 节点与
M3a/M3b 一样是"先比较、后 dump"，因此在语义变更下 update-mode dump 不可达 →
`update_baselines.py` 报 `FFF`、`nothing committed`（`tests/baselines` 仍 0 dirty）。
处理：把 owner 已选定的 **OPT-1 窄修复形态**（update mode 下写入当前 artifact 并
return；normal mode 逐字不变；`assert_deterministic_equal` 本体不动）应用到该模块三个
节点，并把**结构守卫**扩展到该模块（`tests/test_golden_update_mode.py` 现 15 tests，
新增 3 条 integrated-node shape 检查）。
Commit：`6c3e2a7 test: apply OPT-1 update-mode repair to M3-integrated artifact tests`
（test-infra only，无 production 改动、无 baseline 字节改动；属 owner 已定义的
`TEST_INFRA_UPDATE_MODE_REPAIR` 同类修复，为使 B1 的 canonical refreeze 可执行）。

修复后重新执行 canonical 写入 → 运行中。完成后：`GENERATED == RUN1 == RUN2` 逐文件核对 →
`scripts/_m6d3_baseline_scope_audit.py`（§17）→ 独立 Commit D
`test: re-freeze M3 integrated baselines after tribulation fix`。

## 3. Query Service fingerprint bug（owner 裁决 B–E）— APPROVED, NOT YET APPLIED

* 事实：`_fingerprint` 用 `SimulationCheckpoint.blessed_tick`（不存在），真实列为
  `checkpoint_blessed_tick`；异常被 broad `except Exception` 吞掉 →
  三个 hash 恒为 `None`（实测：20 行 checkpoint、fingerprint hash 全 None）。
* Owner 授权最小修复（B1 完成后单独 commit `fix: restore query checkpoint fingerprint hashes`）；
  本轮**不重构** query service、不动 broad exception policy、不动 schema、
  不动 simulation/history semantics、不动 baseline generation。
* `QUERY_SERVICE_BROAD_EXCEPTION_TECH_DEBT = OPEN_NON_BLOCKING`（正式记录，不在本轮 scope）。
* 回归测试已写就（`tests/test_query_fingerprint.py`，owner §E 五项：非 None、
  按 `checkpoint_blessed_tick` 排序、插入顺序无关、restart/session 等价、
  actual 路径独立读真实 DB），将与修复同一 commit 落地并运行。
* §I 保护性检查：query fix 后必须证明
  `M3_INTEGRATED_BASELINE_ARTIFACT_DIFF_AFTER_QUERY_FIX = 0`
  （query 层不参与 baseline 生成；若出现任何 artifact 差异则 STOP）。

## 4. 正式世界 / 红线（本轮已复核）

```
AUTHORITATIVE_DB_RESOLUTION = PASS   NON_AUTHORITATIVE_DB_DETECTED = False
FORMAL_DB_SHA256 = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837
FORMAL_WORLD_RUNTIME_ROWS = 0   CURRENT_BLESSED_TICK = NULL
FORMAL_WORLD_STATUS = NOT_ACTIVATED   FORMAL_WORLD_SEED_CONSUMED = FALSE
tests/baselines dirty files = 0
```

Owner canon 固定不变（§21）：`birth_rate 53/1000`、`INITIAL_POPULATION 12000`、
corrected integrated `11704 / 10464 / 8619 / 2936`（`VALID_EMERGENT_WORLD_HISTORY`）、
`RE-LEAN-v2`、`MINIMUM_RESOURCE_NODE_COUNT = 7`、ecology sensitivity `1/279`、
S-B accepted、T-B PASS —— 未重新调参。
M6D.2 forensic DB 保留（§23），未删除。

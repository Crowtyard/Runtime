# M6D.3 — BASELINE REFREEZE PROVENANCE（STOP：缺可用更新入口）

**`BASELINE_REFREEZE = BLOCKED_NO_FUNCTIONAL_UPDATE_ENTRYPOINT`**
**`NEXT_ACTION = AWAIT_OWNER_ON_BASELINE_REFREEZE_FAILURE`**
（NEW 侧候选**已采集并证明确定性**，只差一个被授权的写入口）

Machine-readable 版本：`reports/M6D3_BASELINE_REFREEZE_PROVENANCE.json`
（含 18 个基线文件逐项 OLD sha256 + 确定性字段、**12 个 NEW 候选逐文件
sha256/确定性字段与 OLD→NEW 差异**、12 个受影响测试、修复 commits、语义契约声明、
阻塞证据、三个 remediation 选项）；候选原样证据：
`reports/M6D3_BASELINE_REFREEZE_CANDIDATES.json` 与
`reports/_m6d3_candidates_keep/`。

---

## 0. 本轮做了什么 / 没做什么

* Owner 已授权 `APPROVE_M3A_M3B_BASELINE_REFREEZE = TRUE`
  （`BASELINE_REFREEZE_CLASS = BUG_FIX_BASELINE_INVALIDATION`、
  `WORLD_LAW_CHANGE = FALSE`、`FROZEN_SEMANTICS_CHANGE = FALSE`）。
* 已先生成 provenance（owner §4），OLD 侧完整。
* 随后按 owner §5 尝试使用**仓库既有 canonical 入口**
  `python scripts/update_baselines.py <节点...>`（该脚本内部设置
  `BLR_UPDATE_GOLDEN_BASELINES=1`，是 `tests/GOLDEN_BASELINES.md` 规定的**唯一**
  合法写 golden 路径）。
* **入口不可用** → 依 owner §5 明确规则 **STOP**：
  **未自行写覆盖脚本、未修改任何 baseline 字节**（`git status tests/baselines` 为空）。

---

## 1. 阻塞证据（可复现）

命令：

```
python scripts/update_baselines.py \
  tests/test_m3a_tribulation.py::test_m3a_baseline_300y_artifact \
  tests/test_m3b_history.py::test_hb43_300y_baseline_artifacts \
  tests/test_m3b_metric_audit.py::test_ma28_metric_audit_baseline_artifacts
```

结果：`[update_baselines] BLR_UPDATE_GOLDEN_BASELINES=1 pytest -q …` →
**`FFF`**（3 个 artifact 测试全部 FAILED）→
`[update_baselines] artifact tests failed; nothing committed.`
`git status --short tests/baselines` = **空**（零字节被写）。

首次差异（每个 baseline 目录各一例）：

| baseline 文件 | 首次差异 |
|---|---|
| `m3a_tribulation_synthetic_300y_v1/summary.json` | `$.domain_event_count: 4779(golden) != 4835(candidate)` |
| `m3b_causal_history_300y_v1/summary.json` | `$.average_chain_depth: 112.82(golden) != 113.918(candidate)` |
| `m3b_causal_history_300y_v1/metric_audit.json` | `$.hash.causal_history_hash: c1293e59…(golden) != d3b8a499…(candidate)` |

### 代码层原因（只读核实）

1. `tests/golden_baseline.py:123-139` — `assert_deterministic_equal()` 在**任何**
   确定性差异上 `raise AssertionError`，**没有** update-mode 短路。
2. `tests/test_m3a_tribulation.py:961-976` — 先比较、后
   `if update_mode_enabled(): dump_artifact(...)` ⇒ 差异存在时 **dump 永不执行**。
   `tests/test_m3b_history.py`（~975-984）、`tests/test_m3b_metric_audit.py`
   （~518-526）同一写法。
3. `tests/test_m3a_tribulation.py:979 _write_baseline`、
   `tests/test_m2a_population.py:589 _write_baseline` 是**无调用者的非测试 helper**
   （死代码）；M3 各模块**没有**独立的 update-entrypoint 测试节点。
4. `tests/conftest.py:195-207` — update mode 只**豁免 GB1 字节守卫**，
   不绕过确定性比较。

→ 结论：`scripts/update_baselines.py` 的**实际适用范围是 telemetry 刷新**
（确定性内容不变时才可写），**不适用于
`BUG_FIX_BASELINE_INVALIDATION` 这类语义变更后的重冻结**。
即：形式上存在入口，功能上**不覆盖本授权场景**——按 owner §5 属于
"没有可用 baseline update entrypoint" → STOP 并报告。

---

## 2. Provenance 已记录内容（OLD 侧，完整）

* `AUTHORIZED_BASELINE_REFREEZE_COUNT = 12`（受影响测试节点清单，含
  `role` = ARTIFACT_WRITER / ASSERTION_VS_M3A_BASELINE / FROZEN_METRIC /
  FROZEN_HASH）。
* 受影响 baseline 目录（2 个、共 **18 个文件**）：
  `tests/baselines/m3a_tribulation_synthetic_300y_v1/`（6 文件）、
  `tests/baselines/m3b_causal_history_300y_v1/`（12 文件）——
  逐文件 `OLD_BASELINE_SHA256` + 确定性字段（`final_world_state_hash` /
  `final_event_stream_hash` / counts / metrics / index 数）已写入 JSON 与
  `reports/_m6d3_baseline_OLD.json`。
* `OLD_BASELINE_STATUS = SUPERSEDED_BY_CONFIRMED_IMPLEMENTATION_BUG`
  （并明确注明：**不是 invalid canon**，而是"忠实记录了与已冻结的
  Tribulation effect application contract 相矛盾的 buggy implementation 行为"）。
* `PRODUCTION_FIX_COMMITS = 40a7e79 / 160e845 / 2a79a82`。
* `WHAT_CHANGED`（owner §7 口径）：`M2_BASELINE_MUTATIONS = 0`、
  `OTHER_M3` / `SCHEDULER` / `M6` baseline 一律 0、只允许上述 2 个目录。
* `NEW_BASELINE_INVENTORY = null`、`NEW_BASELINE_STATUS = NOT_GENERATED_BLOCKED`、
  `NEW_BASELINE_DETERMINISM_RUN1_EQ_RUN2 = NOT_RUN`（§6 双跑门槛未开始）。

---

## 3. NEW 侧候选已采集（**只差授权写入口**）

用**只读观察插件** `scripts/_m6d3_candidate_observer.py`（`-p` 注入；仅在被比较
拒绝时把 test **已经算出**的 candidate 落到 `%TEMP%`，**绝不写 `tests/baselines/`**，
不改 GB10 行为：普通 pytest/`update_baselines.py` 仍然照旧 FAIL）采集两轮独立候选：

```
NEW_BASELINE_CANDIDATE_FILE_COUNT = 12      （受权重冻结范围内、artifact 测试真正生成的文件）
NEW_BASELINE_CHANGED_FILE_COUNT   = 12      （相对 OLD 全部变化，符合授权范围）
NEW_BASELINE_RUN1_EQ_RUN2 (deterministic) = PASS
NEW_BASELINE_RUN1_EQ_RUN2 (byte)          = FAIL_TELEMETRY_ONLY
```

| 候选文件（`tests/baselines/…`） | RUN1==RUN2 | 相对 OLD |
|---|---|---|
| `m3a_tribulation_synthetic_300y_v1/final_state.json` | BYTE_EQ | CHANGED |
| `m3a_tribulation_synthetic_300y_v1/summary.json` | TELEM_DIFF（仅 `wall_seconds`） | CHANGED |
| `m3b_causal_history_300y_v1/causal_graph_digest.json` | BYTE_EQ | CHANGED |
| `m3b_causal_history_300y_v1/entity_cardinality_audit.json` | BYTE_EQ | CHANGED |
| `m3b_causal_history_300y_v1/entity_history_samples.json` | BYTE_EQ | CHANGED |
| `m3b_causal_history_300y_v1/episode_history_samples.json` | BYTE_EQ | CHANGED |
| `m3b_causal_history_300y_v1/growth_projection.json` | BYTE_EQ | CHANGED |
| `m3b_causal_history_300y_v1/metric_audit.json` | BYTE_EQ | CHANGED |
| `m3b_causal_history_300y_v1/relation_density_audit.json` | BYTE_EQ | CHANGED |
| `m3b_causal_history_300y_v1/summary.json` | TELEM_DIFF（仅 `wall_seconds_queries` + `query_latency_ms.*`） | CHANGED |
| `m3b_causal_history_300y_v1/timeline_samples.json` | BYTE_EQ | CHANGED |
| `m3b_causal_history_300y_v1/why_query_samples.json` | BYTE_EQ | CHANGED |

字节差异**全部**属于项目自身在确定性比较前深剥离的 telemetry 键
（`wall_seconds` / `wall_seconds_queries` / `query_latency_ms`，GB3）；
剥离后 RUN1 == RUN2 **逐字节相同** ⇒ owner §6 门槛在**确定性字段口径**上满足。
另外 6 个基线文件（`m3a/decisions.json`、`episode_index.json`、`profiles.json`、
`schedule.json`、`m3b/episode_state_audit.json`、`query_performance.json`）
不由这些 artifact 测试生成 ⇒ **不在本次重冻结范围**（保持原样）。

### 3.1 需要 Owner 授权的 remediation（三选一；我未实施任何一个）

| 选项 | 范围 | 做法 | 风险 |
|---|---|---|---|
| **OPT-1** | TEST_INFRA_ONLY | 在 update mode 下把 M3 artifact 测试的 dump 移到比较**之前**（或让 `assert_deterministic_equal` 在 `BLR_UPDATE_GOLDEN_BASELINES=1` 时**记录**差异而非 raise）；普通 pytest（GB10）行为不变 | 触碰 golden-baseline 政策代码，需 owner 明确签署 |
| **OPT-2** | TEST_INFRA_ONLY | 为 M3 各模块新增**专用 update-entrypoint 测试节点**（仅在 update env 下写），artifact 测试本身不改 | 给 canonical 套件增加测试节点 |
| **OPT-3** | ONE_OFF_OWNER_SANCTIONED | owner 明确授权对这 3 个 artifact 节点做**一次性 sanctioned 生成运行**（仍不手改任何 hash，仍执行 §6 双跑一致性门槛） | 一次性绕过既有流程，须记入 provenance |

授权后我将严格按 owner §5/§6/§7/§9–§12/§18 执行：
以授权入口重新生成（我已有 12 个候选与双跑确定性证据，可直接交叉校验生成结果
是否与候选逐字节一致）→ 独立 commit
`test: re-freeze M3 tribulation baselines after effect-application fix` →
本次 provenance commit `docs: record M6D3 baseline refreeze provenance` →
targeted（M3 → 广域）→ canonical fast regression（chunked，报告实测
collected/passed/expected skips）→ 最终 baseline 检查 →
`AUTHORIZED_BASELINE_REFREEZE_COUNT = 12 / UNAUTHORIZED_BASELINE_MUTATIONS = 0`。

---

## 4. 本轮未受影响、仍然成立的既有结论（owner §0–§3 已接受）

```
TRIBULATION_EFFECT_APPLICATION = PASS
T_B_EFFECT_APPLICATION_BLOCKER = RESOLVED
T_B_ENGINE_VERIFICATION        = PASS_PENDING_FINAL_REGRESSION
E_B_V2_ENGINE_VALIDATION       = PASS
E_B_V2_FINAL_STATUS            = OWNER_RATIFIED_FOR_SNAPSHOT_V1
E_B_V2_SENSITIVITY = 1/279   RECOVERY_RATE = 1/25   PPP = 1   INITIAL_HQ = FULL_QUALITY
corrected habitat T10/T50/T100/T300 = 991691 / 968847 / 956569 / 958683
RESTART_EQUIVALENCE = PASS（canonical history hash 口径）
DETERMINISM = PASS
HISTORY_ORPHAN_LINKS / CAUSAL_CYCLES / INVALID_REFS = 0 / 0 / 0
INTEGRATED_WORLD_VIABILITY = PASS（POP T0/T10/T50/T100/T300 = 12000/11704/10464/8619/2936；
  DEMOGRAPHY_BIRTH_RATE = 53/1000 不再 calibration）
```

正式世界（本轮开始与结束各查一次）：

```
FORMAL_DB_AUTHORITY = PASS
FORMAL_DB_SHA256 = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837
FORMAL_WORLD_RUNTIME_ROWS = 0   CURRENT_BLESSED_TICK = NULL
FORMAL_WORLD_STATUS = NOT_ACTIVATED   FORMAL_WORLD_SEED_CONSUMED = FALSE
```

`SNAPSHOT_V1_ENGINE_VERIFIED_CANDIDATE = FALSE`（blocked on baseline refreeze →
targeted → fast regression；§16 条件未满足）
`SNAPSHOT_V1 = NOT_APPROVED`　`MATERIALIZER_ALLOWED = FALSE`
`FORMAL_ACTIVATION_ALLOWED = FALSE`

M6D.2 forensic DB 继续保留（owner §14）：
`%TEMP%\m6d2_5ohuj6y7\`（read-only，未修改）。

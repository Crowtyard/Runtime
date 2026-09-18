# M6D.3 — BASELINE REFREEZE CLOSEOUT REPORT

**BASELINE_REFREEZE = BLOCKED_NO_FUNCTIONAL_UPDATE_ENTRYPOINT**
**NEXT_ACTION = AWAIT_OWNER_ON_BASELINE_REFREEZE_FAILURE**

（Owner 已批准 `APPROVE_M3A_M3B_BASELINE_REFREEZE = TRUE`；本条不是要推翻裁决，
而是报告：**仓库现有"唯一合法写入口"在功能上无法完成这次重冻结**，按 owner §5
的明确规则 STOP 并交回裁决。NEW 侧候选已采集且证明确定性，只差一个被授权的写入口。）

---

## 1. 结论一览（owner §19 字段）

```
BASELINE_REFREEZE                    = BLOCKED_NO_FUNCTIONAL_UPDATE_ENTRYPOINT
AUTHORIZED_BASELINE_REFREEZE_COUNT   = 12        （授权范围，未执行写入）
UNAUTHORIZED_BASELINE_MUTATIONS      = 0
M2_BASELINE_MUTATIONS                = 0
BASELINE_PROVENANCE_COMPLETE         = TRUE（OLD 完整 + NEW 候选完整；写入未发生）

TARGETED_REGRESSION                  = NOT_RUN_PENDING_WRITE_PATH（阻塞前状态见 §3）
TARGETED_COLLECTED / PASSED / FAILED / ERRORS = N/A

FAST_REGRESSION                      = NOT_RUN_PENDING_BASELINE_REFREEZE
FAST_COLLECTED / PASSED / EXPECTED_SKIPS / FAILED / ERRORS / UNEXPECTED_SKIPS = N/A

FORMAL_DB_AUTHORITY                  = PASS
FORMAL_DB_SHA256                     = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837
FORMAL_WORLD_RUNTIME_ROWS            = 0
FORMAL_WORLD_STATUS                  = NOT_ACTIVATED
FORMAL_WORLD_SEED_CONSUMED           = FALSE

TRIBULATION_EFFECT_APPLICATION       = PASS
T_B_ENGINE_VERIFICATION              = PASS_PENDING_FINAL_REGRESSION
E_B_V2_ENGINE_VALIDATION             = PASS
E_B_V2_FINAL_STATUS                  = OWNER_RATIFIED_FOR_SNAPSHOT_V1
DETERMINISM                          = PASS
RESTART_EQUIVALENCE                  = PASS
HISTORY_INTEGRITY                    = PASS（orphan 0 / cycle 0 / invalid 0）
INTEGRATED_WORLD_VIABILITY           = PASS

SNAPSHOT_V1_ENGINE_VERIFIED_CANDIDATE = FALSE（§16 条件未满足：refreeze/targeted/fast 未完成）
SNAPSHOT_V1                          = NOT_APPROVED
MATERIALIZER_ALLOWED                 = FALSE
FORMAL_ACTIVATION_ALLOWED            = FALSE
```

---

## 2. 为什么 STOP（owner §5）

`tests/GOLDEN_BASELINES.md` 规定唯一合法写入口 = `python scripts/update_baselines.py`
（内部置 `BLR_UPDATE_GOLDEN_BASELINES=1`）。实际运行该入口（3 个受权 artifact 节点）：

* 结果 `FFF`：三个 artifact 测试全部 **先**在
  `assert_deterministic_equal(...)` 上失败；
* `tests/golden_baseline.py:123-139` 在任何确定性差异上直接 `raise`，**没有**
  update-mode 短路；
* `tests/test_m3a_tribulation.py:961-976`（以及 `test_m3b_history.py` ~975-984、
  `test_m3b_metric_audit.py` ~518-526）的
  `if update_mode_enabled(): dump_artifact(...)` 位于比较**之后** ⇒ 语义变更时
  **永不可达**；
* `_write_baseline`（`test_m3a_tribulation.py:979`、`test_m2a_population.py:589`）
  是无调用者的死代码；M3 各模块没有独立 update-entrypoint 测试节点；
* `tests/conftest.py:195-207` 的 update-mode 豁免只覆盖 GB1 字节守卫，不覆盖比较。

⇒ `UPDATE_ENTRYPOINT_SCOPE = TELEMETRY_REFRESH_ONLY`（确定性内容不变时可用），
**`NOT_FUNCTIONAL_FOR_BUG_FIX_BASELINE_INVALIDATION`**。

**未做的事**（严格遵守 §5）：没有自行写覆盖脚本；没有修改任何 baseline 字节
（`git status tests/baselines` 全程为空）；没有手工改 hash；没有 amend/rebase/force push；
没有创建 M6 freeze tag；未实现 Materializer、未激活正式世界、未消费正式 Seed、未部署。

---

## 3. 阻塞前已完成的工作（provenance 完整）

Owner §4 要求的 provenance 已生成（`reports/M6D3_BASELINE_REFREEZE_PROVENANCE.{md,json}`）：

* `AUTHORIZED_BASELINE_REFREEZE_COUNT = 12`（受影响测试节点 + role：
  ARTIFACT_WRITER / ASSERTION / FROZEN_METRIC / FROZEN_HASH）；
* 受影响目录 2 个、文件 18 个 → 其中 artifact 测试真正生成的 **12 个文件**；
  逐文件 `OLD_BASELINE_SHA256` + 确定性字段（`final_world_state_hash` /
  `event_stream_hash` / metrics / index 计数）；
* `WHY_CHANGED` = confirmed tribulation effect application bug；
* `PRODUCTION_FIX_COMMITS = 40a7e79 / 160e845 / 2a79a82`；
* `SEMANTIC_CONTRACT` = 既有 frozen M3A/M3B 语义不变（只让 baseline 与已冻结的
  effect application contract 一致）；
* `OLD_BASELINE_STATUS = SUPERSEDED_BY_CONFIRMED_IMPLEMENTATION_BUG`，并明确
  **不是** "invalid canon"，而是"忠实记录了与冻结契约相矛盾的 buggy 实现行为"。

**NEW 侧（只读采集，未写入）**：`scripts/_m6d3_candidate_observer.py`（pytest 插件，
仅在被拒时把 test 已算出的 candidate 落到 `%TEMP%`；不改 GB10 行为）：

```
NEW_BASELINE_CANDIDATE_FILE_COUNT = 12   （12/12 相对 OLD 全部 CHANGED，与授权范围一致）
NEW_BASELINE_RUN1_EQ_RUN2（确定性字段） = PASS
NEW_BASELINE_RUN1_EQ_RUN2（字节）      = FAIL_TELEMETRY_ONLY
   字节差异全部是 wall_seconds / wall_seconds_queries / query_latency_ms
   ——项目自己在比较前深剥离的 telemetry 键（GB3）；剥离后逐字节相同 ⇒ owner §6 满足
另 6 个文件（m3a decisions/episode_index/profiles/schedule、
m3b episode_state_audit/query_performance）不由这些 artifact 测试生成 ⇒ 不在范围内
```

证据：`reports/M6D3_BASELINE_REFREEZE_CANDIDATES.json`、
`reports/_m6d3_candidates_keep/`（24 个原始候选文件）。

### 3.1 一次作废的沙盒试跑（如实记录，不作依据）

曾在一次性 git worktree 里试跑"重冻结后是否全绿"：结果无效——(a) 我的复制脚本
把文件名多加了一次 `.json`（`summary.json.json`），worktree 的 golden 实际未被替换；
(b) worktree 父目录缺兄弟仓库 `XIAOGUANG_CROW_KB`，3 个 world-seed 测试
`FileNotFoundError`。worktree 已删除，canonical 仓库 `tests/baselines` 仍零改动；
该结果不作为任何结论依据。

---

## 4. 请求 Owner 在三个 remediation 中择一（我未实施任何一个）

| 选项 | 范围 | 做法 | 风险 |
|---|---|---|---|
| **OPT-1** | TEST_INFRA_ONLY | update mode 下把 M3 artifact 测试的 dump 移到比较之前（或让 `assert_deterministic_equal` 在 `BLR_UPDATE_GOLDEN_BASELINES=1` 时记录差异而非 raise）；普通 pytest（GB10）不变 | 触碰 golden 政策代码，需 owner 签署 |
| **OPT-2** | TEST_INFRA_ONLY | 为 M3 模块新增专用 update-entrypoint 测试节点（仅 update env 下写），artifact 测试不改 | canonical 套件增节点 |
| **OPT-3** | ONE_OFF_OWNER_SANCTIONED | owner 明确授权对 3 个 artifact 节点做一次性 sanctioned 生成（仍不手改 hash、仍跑 §6 双跑门槛；可用已采集候选做交叉校验） | 一次性绕过既有流程，须记入 provenance |

授权后我会按 §5/§6/§7/§9–§12/§18 直接执行：生成（并与已采集候选交叉校验）→
`test: re-freeze M3 tribulation baselines after effect-application fix` →
`docs: record M6D3 baseline refreeze provenance` → targeted（M3 → 广域，0 failed/0 errors，
`M2_BASELINE_MUTATIONS = 0`）→ canonical fast regression（chunked runner；
报告**实测** collected/passed/expected skips，不假定 1025）→ 最终 baseline 检查 →
`AUTHORIZED_BASELINE_REFREEZE_COUNT = 12 / UNAUTHORIZED_BASELINE_MUTATIONS = 0 /
BASELINE_PROVENANCE_COMPLETE = TRUE` → 届时才可判定
`SNAPSHOT_V1_ENGINE_VERIFIED_CANDIDATE`。

---

## 5. 正式世界（本轮开始与结束各查一次）

```
AUTHORITATIVE_DB_RESOLUTION = PASS     NON_AUTHORITATIVE_DB_DETECTED = False
FORMAL_DB_SHA256           = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837
FORMAL_WORLD_RUNTIME_ROWS  = 0         CURRENT_BLESSED_TICK = NULL
FORMAL_WORLD_STATUS        = NOT_ACTIVATED   FORMAL_WORLD_SEED_CONSUMED = FALSE
```

M6D.2 forensic DB 继续保留（owner §14）：`%TEMP%\m6d2_5ohuj6y7\`（read-only）。
长期人口轨迹按 owner §15 记录待最终提醒：
`POP_T0/T10/T50/T100/T300 = 12000 / 11704 / 10464 / 8619 / 2936`，
`DEMOGRAPHY_BIRTH_RATE = 53/1000` 不再 calibration。

Git（独立 commit，无 amend/rebase/force）：
`728a628`（provenance + STOP）、`e348e4e`（NEW 候选 + 只读采集工具与证据）。

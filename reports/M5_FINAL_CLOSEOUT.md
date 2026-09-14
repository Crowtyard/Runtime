# M5 FINAL CLOSEOUT（M5 阶段收尾与冻结）

- 报告生成时间：2026-09-14T01:07（本地）
- 报告性质：M5 阶段**收尾冻结报告**（历史记录型，不改写、不回填）
- 权威修订：`M5_FINAL_HEAD = ac8d422aab6c49f67852b90c3bcc60686058c4dc`
- 本报告自身为**新增未跟踪文件**（`reports/M5_FINAL_CLOSEOUT.md`）；本阶段**未创建任何 commit**、**未改写历史**、**未 force push**、**未新增/移动 tag**

---

## 1. 冻结声明与最终判定

```
M5_COMPLETE                            = TRUE_WITH_KNOWN_LIMITATIONS
M5_FROZEN                              = TRUE_WITH_KNOWN_LIMITATIONS
M5_RUNTIME_INTEGRATION                 = PASS
M5_RUNTIME_SAFETY                      = PASS
M5_1_LIVE_PATCH                        = PASS
M5_1_LOGGING_INCIDENT                  = RESOLVED
M5_WORLD_TIME_ROUTING                  = PASS
M5_CHAT_SEMANTICS                      = ACCEPTED_WITH_KNOWN_LIMITATIONS
M5_CHAT_SEMANTICS_BUGFIX_IMPLEMENTED   = TRUE（代码已修复并提交 ac8d422；部署已就位）
M5_2_POST_PATCH_LIVE_AB_ACCEPTANCE     = NOT_PERFORMED（OWNER_DECISION = DEFER）
M5_3_AUTHORITATIVE_CONTEXT_PRIORITY_BUGFIX = STOPPED_BY_OWNER
OWNER_DECISION                         = DEFER_NO_FURTHER_FIX
```

**禁止表述**：不得将 `M5_CHAT_SEMANTICS` 标注为 `PASS`（本报告、任何后续报告、任何 manifest 均不得使用该组合）。原因见第 4 节：本阶段的人类自然语言验收存在 3 项 FAIL，语义冲突已由 owner 明确决定不再继续修复。

知识局限登记（**不得记为 RESOLVED**）：

```
KL-M5-001 = OPEN（DEFERRED）
  persona / 世界观叙述仍可能把「神社 / 居民 / 灵田 / 世界内活动」
  作为当前事实叙述（NOT_ACTIVATED 世界本无这些事实）。
KL-M5-002 = OPEN（DEFERRED）
  Q2 / Q5 类问句仍可能把 UNKNOWN 表达为「记录不完整 / 档案缺失 / 未统计」，
  与 NOT_ACTIVATED 契约（UNKNOWN ≠ 未统计/未记录）措辞冲突。
```

已实现但**未被 live 复验**的部分（如实登记，不得当作已验证）：

- M5.2 修复（NOT_ACTIVATED 契约 + `WORLD_TIME` 路由）已在代码层实现、已提交、已部署到 live 实例；
- **修复后的 Q1–Q6 live A/B 复验没有执行**（owner 在复验前终止该线并转入 M5 收尾）；
- 因此 `M5_CHAT_SEMANTICS` 只能记为 `ACCEPTED_WITH_KNOWN_LIMITATIONS`，不能记为通过。

---

## 2. 阶段记录（formal records）

| 阶段 | 内容 | 记录 |
| --- | --- | --- |
| M5 | Query + Companion 集成（查询服务挂载到 AstrBot `@on_llm_request`） | `M5_RUNTIME_INTEGRATION = PASS` / `M5_RUNTIME_SAFETY = PASS` |
| M5.1 | live 部署启动事故定位与最小补丁（含 Launcher readiness 语义） | `M5_1_LIVE_PATCH = PASS` / `M5_1_LOGGING_INCIDENT = RESOLVED` |
| M5.2 | chat 语义缺陷修复（NOT_ACTIVATED 契约 + 世界时间路由） | 代码已交付；live 复验未执行 |
| M5.3 | AUTHORITATIVE CONTEXT PRIORITY BUGFIX | `STOPPED_BY_OWNER`（不再继续修复 Q1/Q2/Q5 的语义冲突） |

M5.1 因果定性（保留，不得改写）：

```
RUNTIME_PLUGIN_CAUSAL            = TRUE   （插件内嵌 alembic fileConfig 关闭宿主 logger）
VENV_CAUSAL                      = FALSE
PORT_COLLISION_CAUSAL            = FALSE  （历史上为自伤性配置，非本次事故主因）
LAUNCHER_READY_HANDSHAKE_CAUSAL  = TRUE   （Launcher 仅以 stdout 字面量 "AstrBot started." 判就绪）
PORT_0                           = 仅影响 UI 访问可达性，非启动失败主因
```

---

## 3. 人类验收历史（逐字保留，不得删改）

```
Q1 = FAIL
Q2 = FAIL
Q3 = PASS
Q4 = PASS_WITH_WARN
Q5 = FAIL
Q6 = PASS
```

- 该矩阵为 **M5.2 补丁前**的 live 人工样本（`M5_2_PRE_PATCH_LIVE_CONTROL_SAMPLE`），**必须保留为对照样本**，不得删除或覆盖。
- 该矩阵是人类对 M5 自然语言表现的最终判定；M5.2/M5.3 的后续工作**不改变**该历史记录，也不得据此重述为通过。
- 明细见 `D:\MY SELF\IKUN\小光\M5_Q1_Q6_LIVE_CHAT_ACCEPTANCE_REPORT.md`。

---

## 4. Known Limitations（冻结内容）

### 4.1 KL-M5-001 persona / 世界观事实化

- 现象：在 `WORLD_RUNTIME_STATUS = NOT_ACTIVATED`、`CURRENT_BLESSED_TICK = NULL`、`OFFICIAL_WORLD_EVENTS = 0` 的世界中，伴侣侧叙述仍可能把「神社 / 居民 / 灵田 / 世界内活动」讲成当前事实。
- 成因定性：**不来自 Runtime 权威数据的伪造**，而来自 Private Companion 自身的 persona/世界观文本；该文本中的意象在 Private Companion 配置中大量存在（神社 ×22 / 灵田 ×4 / 居民 ×26 / 福地 ×93）。
- 处置边界（owner 已认可的唯一修复方向，本阶段不执行）：
  - 只在 **Runtime 侧**强化 NOT_ACTIVATED 契约（优先级 + 预算），**绝不修改 Private Companion 源码或配置**；
  - **绝不**为特定问题硬编码答案。

### 4.2 KL-M5-002 UNKNOWN 表达冲突

- 现象：Q2/Q5 类问句仍可能把 UNKNOWN 表述为「记录不完整 / 档案缺失 / 未统计」。
- 契约要求（M5.2 已写入实现与文档）：`UNKNOWN ≠ 未统计/未记录/档案缺失`；`NONE_OFFICIAL ≠ 发生了没记`；`blessed tick = NULL = NOT_STARTED ≠ 第0年/元年`。
- 现状：契约本身已实现（`services/query/context_builder.py` + `docs/m5_astrbot_companion_integration.md` §4.1/§4.2），但**自然语言层仍可绕过**；该残留为已登记局限，不是未完成项。

---

## 5. 世界不变式与运行态证据（live，只读采集）

```
WORLD_RUNTIME_STATUS    = NOT_ACTIVATED
CURRENT_BLESSED_TICK    = NULL
OFFICIAL_WORLD_EVENTS   = 0
OFFICIAL_WORLD_MUTATIONS = 0
WORLD_SEED_CONSUMED     = FALSE
SCHEDULER_STATE         = DORMANT
```

live 实例：`C:\Users\Crowtyard\.astrbot_launcher\instances\f76fe2fd-8c03-4ba2-b4d6-467d1645ed0d`

| 项 | 实测 | 说明 |
| --- | --- | --- |
| 实例进程 | RUNNING（PID 1744 / 56560，均始于 2026-09-14T00:46:00） | owner 通过 Launcher UI 启动 |
| Web 端口 | 6185 LISTEN（owner PID 1744） | 就绪握手已满足（未出现 300s 超时） |
| `runtime_state/scheduler_state.json` | `world_id=FORMAL-UNSEEDED`，`scheduler_state=DORMANT`，`pause_state=false`，counters 全 0（cycle / batches_total / recovery / lease_takeover / stale_writer_rejection / commit_ambiguity / last_successful_commit / last_batch_ticks），`last_error=null` | 运行中零 mutation、零接管、零歧义 |
| `runtime_state/authoritative_db.json` | `checksum_sha256 = 1d84ee370167b047265bd2200c69c7373372fb0b594bf7ac073b33097de52cf2`，`written_at = 2026-09-13T16:46:08Z`（当地 2026-09-14T00:46:08，即本次运行期写出） | 与 M5 冻结记录的正式库校验和**逐字一致** → 部署与运行未改变正式库 |
| 正式库文件 sha256 | 运行中**无法重新哈希**（文件被运行进程独占） | 上述不变性由插件自身运行期写出的校验和 + DORMANT 零 mutation 计数共同佐证；严格停机复核登记为 `NOT_PERFORMED_THIS_PHASE` |
| 插件源码 vs `M5_FINAL_HEAD` | 源文件 99（排除 `__pycache__`；另有 81 个 `.pyc`）：`MISMATCH = 0`、`MISSING_IN_REPO = 0` | `LIVE_PLUGIN_SOURCE_MATCH_HEAD = TRUE`（live 源码与 ac8d422 逐文件同哈希） |
| Private Companion 源 | 基线 529 文件，`changed = 0`、`missing = 0`，整体 sha256 `cf259085…a1a77c` | `COMPANION_SOURCE_UNCHANGED = TRUE`（从未修改） |

启动回归结论：M5.1 修复的启动缺陷在 **M5.2 包下仍然成立**（无 300s 超时，实例持续 RUNNING）。

---

## 6. 交付物与哈希

| 交付物 | 位置 | sha256 / 指纹 |
| --- | --- | --- |
| M5.2 chat 语义补丁包 | `D:\MY SELF\IKUN\小光\astrbot_plugin_blessed_land_runtime_chat_semantics_fix.zip` | `953BDD1013B860BD293E1F29D50794492D3D309DC0D4DB567F6B0EF65A7ABB29`（99 文件，`NESTED_ROOT = FALSE`） |
| M5.1 logging 修复包（最终） | `...\astrbot_plugin_blessed_land_runtime_loggingfix_final.zip` | `0D111A94…3322` |
| 回滚备份（M5.1 前） | `...\incident_quarantine\live_runtime_pre_m5_1_loggingfix_20260913_173255` | 137 文件，tree hash `9387fe3d…f9e0` |
| 回滚备份（M5.2 前） | `...\incident_quarantine\live_runtime_pre_m5_2_chat_semantics_20260914_004408` | 99 源文件，tree hash `fd5f329765e97379a134e35b7c08810c0bca02968b1c49ebddac3e15e267cfb8` |
| Private Companion 源码基线 | `D:\MY SELF\IKUN\小光\m5_companion_source_baseline.txt` | 529 文件，整体 `cf259085…a1a77c` |
| 阶段报告（仓库外） | `D:\MY SELF\IKUN\小光\` | `M5_1_LIVE_ASTRBOT_STARTUP_INCIDENT_RECOVERY.md`、`M5_1_ROUND2_LAUNCHER_READY_DIAGNOSIS.md`、`M5_1_ROUND3_READY_HANDSHAKE_DIAGNOSIS.md`、`M5_1_LOGGING_FIX_REPORT.md`、`M5_1_MINIMAL_LIVE_PATCH_REPORT.md`、`M5_Q1_Q6_LIVE_CHAT_ACCEPTANCE_REPORT.md`、`M5_CHAT_SEMANTICS_BUGFIX_DEV_REPORT.md` |
| 阶段报告（仓库内） | `reports\` | `m5_query_companion_acceptance.md`、`m4_scheduler_acceptance.md`、本报告 |

备份目录**不含**正式库与 `plugin_data` 内容（仅插件源码），故备份不构成世界状态回滚能力；世界状态回滚能力由 `services/backup_service.py` 单独提供。

---

## 7. Git 状态与 M5_FINAL_HEAD

```
M5_FINAL_HEAD  = ac8d422aab6c49f67852b90c3bcc60686058c4dc
HEAD 提交标题   = "fix: enforce not-activated semantics and world-time routing"
本地分支        = m5-query-companion
工作区(采集时)  = DIRTY = 0（干净）
远端镜像引用    = refs/remotes/github-runtime/m5-1-runtime-integration-fix = ac8d422…
标签            = 本地 16（含 m5-query-companion-frozen 等历史冻结标签）；远端 0；本阶段未新增/移动
提交链          = c706e8f(PRE_FIX_HEAD) → 7637fa4(VALIDATED_FIX_HEAD) → 3bd2230(REPOSITORY_HYGIENE_HEAD) → ac8d422(M5_CHAT_BUGFIX_HEAD / M5_FINAL_HEAD)
```

关键判定：**当前实际 HEAD 已包含最新已验证的 M5.2 修复**，因此本阶段**无需**退化为「仅审计、不记录」模式；同时本阶段**没有**创建任何提交、没有改写历史、没有 force push。

`7637fa4` 的提交标题首字符含 U+FEFF（早期 PowerShell `Set-Content -Encoding UTF8` 写入 BOM 所致）。该瑕疵**已如实保留、未 amend**（amend/force push 属禁止操作）。

本报告与 `docs/pre_m6_pg_gate_audit.md` 为该 HEAD 之上的**新增未跟踪文件**；写入后工作区不再是 `DIRTY = 0`，但**未修改任何被跟踪文件**。

---

## 8. 回归与证据链

```
BLOCK_H                              = PASS（17/17，exit 0，2h28m35s）
BLOCK_R（第 1 次）                   = FAIL_PRECONDITION_MISMATCH（被取代，不入账）
BLOCK_R（第 2 次，Decision A 规范模式）= PASS（726：714 passed / 0 failed / 0 errors / 12 expected skips，4h54m36s）
FAST_M0_M5_2_M0_M4_FULL_FAST         = PASS（733 collected → 721 passed / 0 failed / 0 errors / 12 skips，exit 0，5h09m30s，JUnit %TEMP%\m5_2_full_fast_junit.xml）
M5_QUERY_CONTEXT_HOOK_ISOLATION_SET  = PASS（59 passed）
GOLDEN_BASELINE_MUTATIONS            = 0（36 个基线文件与 HEAD 逐字节一致）
```

说明：BLOCK_R 第 1 次失败原因为测试前置条件误设（注入了 `BLR_FORMAL_DB_PATH`，导致正式库守卫测试在 0 行 `world_runtime` 上取 `None` 下标）；owner 裁定 Decision A 后以**规范未设置模式**重跑并 PASS，测试代码未因此修改。12 个 skip 为既有 `EXPECTED_FORMAL_DB_SKIP`。

---

## 9. 未执行项与偏差登记（不掩盖）

1. `M5_2_POST_PATCH_LIVE_AB_ACCEPTANCE = NOT_PERFORMED`：M5.2 包已部署并运行，但修复后的 Q1–Q6 人工复验未进行（owner 决定不再继续）。
2. 正式库 sha256 停机复核未执行（运行中文件被独占）。
3. M5.3「AUTHORITATIVE CONTEXT PRIORITY」修复按 owner 指令**停止**，未实施、未部分实施。
4. PG 双门禁在本阶段**未触碰、未降级**（保持 `REQUIRED`）；详见 `docs/pre_m6_pg_gate_audit.md`。

---

## 10. 过程事故记录（保留原始事实）

| 事故 | 事实 | 处置 |
| --- | --- | --- |
| 控制台信号 `0xC000013A` | 环境周期性杀前台 harness 任务（pytest 前台运行与 3 个等待作业被杀） | 改为 detached 进程 + 文件日志 + `--junitxml`，结果不受影响（已记入 M5.2 开发报告） |
| 过宽进程清理（22:30） | 曾误杀 owner 正在运行的实例 | 新增 `scripts/process_scope.py`：禁止按进程名杀，仅显式 PID + 已验证进程树；新增 `assert_no_foreign_python()` 与回归测试 `tests/test_process_kill_scope.py` |
| `_PRIORITY` 断言误报 | 合同文本内含被否定示例，导致「禁止措辞」断言误命中 | 断言前剥离合同行后再检查 |
| venv 缺 `alembic`/`mako` | live venv 缺包（既存问题） | 离线复制补入，无 dist-info；作为残余风险登记（未 `pip install`） |

---

## 11. 剩余门禁与下一步

```
PRE_ACTIVATION_PG_GATE                  = REQUIRED（RUNNING 前必须 PASS）
PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_GATE = REQUIRED（同上）
M6_ACTIVATION                           = PROHIBITED
```

M5 阶段到此**冻结**。下一阶段动作：**PRE-M6 ACTIVATION GATE CLOSURE**（只读审计已完成，见 `docs/pre_m6_pg_gate_audit.md`），在 owner 明确授权前**不得**进入 M6、不得激活世界、不得消费 World Seed、不得修改 Private Companion、不得改动 Scheduler 与 M0–M4 冻结面。

---

## 12. 冻结确认

```
M5_STATUS                = FROZEN
M5_FINAL_HEAD            = ac8d422aab6c49f67852b90c3bcc60686058c4dc
HISTORY_REWRITTEN        = FALSE
COMMITS_CREATED_THIS_PHASE = 0
FORMAL_DB_MODIFIED       = FALSE
WORLD_ACTIVATED          = FALSE
WORLD_SEED_CONSUMED      = FALSE
COMPANION_MODIFIED       = FALSE
CODE_MODIFIED_THIS_PHASE = FALSE
```

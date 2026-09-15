# FINAL PRE-M6 ACTIVATION REVIEW

- 报告时间：2026-09-14（本地）
- 阶段：`FINAL PRE-M6 ACTIVATION REVIEW`（**非开发阶段**；不新增世界规律、不改 M0–M4 语义、
  不继续 M5 persona 修复、不新增 PG 功能、不改 commit protocol、不部署 live、不迁移正式库、
  不消费 World Seed、不进入 M6）
- 权威基线：`CURRENT_HEAD = b6a0340`（前置 `dd1f7cf`；本阶段唯一代码改动为**测试侧** formal-db 口径修正）
- 结论：`PRE_M6_CODE_READY = TRUE`（详见 §9）；`M6_ACTIVATION = PROHIBITED`
  —— live 仍落后于当前 HEAD，需先完成独立的 `FINAL PRE-M6 LIVE STAGING` 阶段。

---

## 1. Formal DB representation 技术债关闭（§2 / §3）

`PRE_M6_TECH_DEBT = FORMAL_DB_NOT_ACTIVATED_REPRESENTATION_CONSISTENCY` → **CLOSED**
（仅修改 test / test helper / test documentation，**未触碰** production persistence
semantics、activation code、正式库文件）。

**Canonical contract（固定，不得更改）**：

```
world_runtime 0 行  ==  官方世界从未激活（NOT_ACTIVATED 的唯一 canonical 表示）
```

**原缺陷**：6 处 explicit formal-db guard 假设「正式库存在一行 `runtime_status='NOT_ACTIVATED'`」，
在 canonical 0 行下 `fetchone()` 返回 `None` → `TypeError`/断言失败。后果：
一旦真的设置 `BLR_FORMAL_DB_PATH`，guard 反而失败，**无法充当篡改证据**（规范模式下恒 skip）。

**修正**（commit `b6a0340`，9 files，+186/−44）：

- 新增 `tests/formal_db.py`：formal-db **只读**连接（`file:...?mode=ro`, `uri=True`）、
  SHA256、canonical 断言（`world_runtime` 行数 == 0）、表空断言、`integrity_ok`、
  `snapshot()` 快照；在 docstring 中固化 canonical contract 与口径修正历史；
- 全部 guard 连接改为**显式只读**（10 处 `sqlite3.connect(path)` → 只读 URI），
  使「前后 SHA256 一致」成为有效证据（只读 ⇒ 不产生 `-journal`/`-wal` 副产物）；
- 6 处行存在断言改为**行数断言**（`SELECT COUNT(*) FROM world_runtime) == 0`）；
- `tests/zz_formal_db_guard.py` 重写为 helper 驱动：字节不变 → canonical 0 行 →
  官方实体表全空 → M2_PREFLIGHT checkpoint 0 → 结构完整性。

**正式验证（BLR_FORMAL_DB_PATH 指向 live 正式库，只读）**：

```
FORMAL_DB_SHA256_BEFORE = 1d84ee370167b047265bd2200c69c7373372fb0b594bf7ac073b33097de52cf2
FORMAL_DB_SHA256_AFTER  = 1d84ee370167b047265bd2200c69c7373372fb0b594bf7ac073b33097de52cf2
FORMAL_DB_UNCHANGED     = TRUE
WORLD_RUNTIME_ROWS      = 0
FORMAL_DB_EXPLICIT_GUARDS = PASS
   - 注入 BLR_FORMAL_DB_PATH（只读连接）：15 项**全部真实执行**、0 skip、exit 0
     （不再出现 fetchone() == None 导致的 TypeError/断言失败）
   - canonical 模式（不注入）：13 项按设计 skip、其余 3 项照常 PASS，exit 0
     —— 即 guard 在两种模式下都「要么真实执行并通过、要么明确 skip」，不再静默失效
```

## 2. Live Runtime 版本漂移审计（§5）

```
LIVE_RUNTIME_FILES          = 99
LIVE_RUNTIME_TREE_HASH      = e2d0bf6b08d61af25b4e11d7945f1b2290a288be35bdd032fc878206a2735fc9
CURRENT_RUNTIME_FILES       = 99
CURRENT_RUNTIME_TREE_HASH   = 67869c5330ac533d9c2a5dbc1e101400cd4832b7bf15b837edbcaa0007574d4e
LIVE_RUNTIME_MATCHES_PRE_M6_HEAD = FALSE
DRIFT_COUNT                 = 7（全部为 Pre-M6 合法改动，无 live 私有改动）
LIVE_STAGING_REQUIRED       = TRUE
```

漂移文件（逐字节比较，均为「live 为旧版、HEAD 为新版」）：`database/invariants.py`、
`database/models_world.py`、`plugin_shell/runtime_host.py`、`services/scheduler/core.py`、
`services/simulation/recovery.py`、`database/alembic/versions/5aef35f022b4_*.py`、
`database/alembic/versions/a1c9f3d77e21_*.py` —— 与 M5.2 之后全部 Pre-M6 修复一致。
**本阶段未部署**（禁止）。

## 3. Live schema 与代码 migration head（§4）

```
CURRENT_CODE_ALEMBIC_HEAD    = a9d4f2b7c1e8
LIVE_FORMAL_DB_ALEMBIC_HEAD  = d7f9b1c3e5a7
LIVE_SCHEMA_SYNC_REQUIRED    = TRUE
```

版本漂移属 live staging 前**允许**存在；**本阶段未执行任何迁移**（未 `alembic upgrade`、
未改 live schema、未改正式库 head）。

## 4. 正式世界最终 Pre-M6 快照（§12，只读）

```
WORLD_RUNTIME_ROWS        = 0
WORLD_EVENTS              = 0
SIMULATION_RUN_ROWS       = 0
RUNTIME_LOCK_ROWS         = 0
TIME_RATIO_HISTORY_ROWS   = 0
SIMULATION_CHECKPOINTS    = 0
PERSONS / POPULATION_GROUPS / SETTLEMENTS / RESOURCE_NODES / TRIBULATIONS /
TIMELINE_ENTRIES / WORLD_STATE_CHANGES = 0
CURRENT_BLESSED_TICK      = NULL
WORLD_SEED_CONSUMED       = FALSE
SCHEDULER_STATUS          = DORMANT（runtime_state/scheduler_state.json；
                            counters 全 0、last_error = null）
FORMAL_DB_INTEGRITY       = ok
```

## 5. PG Gates 证据一致性（§9）

```
PG012_PRESENT_IN_HEAD = TRUE（services/scheduler/core.py：
                        `except sa_exc.DBAPIError` 分支 + `_read_durable_tick_resilient()`）
```

| Gate | 证据报告（均在 HEAD） | 关键提交（均存在于历史） |
| --- | --- | --- |
| PRE_M6_PG_PORTABILITY | `reports/PRE_M6_PG_PORTABILITY_FIX_REPORT.md` | `6c3d24b`（fix）、`14492f2`/`4268e45`（记录） |
| PRE_M6_PG_ENVIRONMENT | `reports/PRE_M6_PG_ENVIRONMENT_BRINGUP_REPORT.md`、`reports/PRE_M6_PG_DRIVER_AND_ENV_CONTINUATION_REPORT.md` | `2890852`（fix）、`86843c3`（记录） |
| PRE_M6_PG_FUNCTIONAL_GATE | `reports/PRE_M6_PG_FUNCTIONAL_GATE_REPORT.md` | `42d13af`（harness）、`3146d25`（记录） |
| PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_GATE | `reports/PRE_M6_PG_COMMIT_AMBIGUITY_GATE_REPORT.md`、`docs/pre_m6_pg_commit_ambiguity_audit.md` | `c12ba2c`（harness）、`005db4f`（PG-012 fix）、`89af5ad`/`cbcfbcc`/`dd1f7cf`（记录） |

对应 harness 亦全部在 HEAD：`tests/pg_portability_scan.py`、
`tests/test_pg_functional_gate.py`、`tests/test_pg_commit_ambiguity_gate.py`。

## 6. Golden Baselines 最终检查（§11）

```
M2_BASELINES_UNCHANGED              = TRUE
M3A_BASELINE_UNCHANGED              = TRUE
M3B_BASELINE_UNCHANGED              = TRUE
M3_INTEGRATED_BASELINES_UNCHANGED   = TRUE
GOLDEN_BASELINE_MUTATIONS           = 0
```

依据：`git diff --exit-code -- tests/baselines` 退出码 0、`git status --porcelain --
tests/baselines` 为空（36 个基线文件与 HEAD 逐字节一致）；会话级 baseline 守卫
（GB1/GB2）在本次 fast regression 全程零触发。

## 7. Canonical Fast Regression（§6 / §7 / §8）

范围与模式：`pytest tests` **排除** `tests/test_m3_integrated_long.py`（owner §8：
M3 长测无需重跑）；canonical test mode（**不注入** `BLR_FORMAL_DB_PATH`）；
分块 + detached + 独立 process group + 逐块 JUnit + info JSON。

**范围/覆盖核验**（防止排除项造成漏测）：

```
TOTAL_TEST_FILES      = 53
IN_SCOPE              = 52（分组 11 / 11 / 10 / 10 / 10）
EXCLUDED_DECLARED     = tests/test_m3_integrated_long.py
MISSING_FROM_SCOPE    = []（无漏测）
UNEXPECTED_IN_SCOPE   = []
DUPLICATES            = []
```

（结果回填见本节末尾表格。）

**首轮运行（run #1，HEAD `b6a0340`）结果与处置（如实记录，未重新定义为 harness 问题）**：

```
run #1: 795 collected / 753 passed / 1 FAILED / 0 errors / 41 skipped；296.3 min；verdict=FAIL
FAILED: tests/test_process_kill_scope.py::test_no_unscoped_process_kill_in_repo
  违例: tests/pg_ambiguity_support.py:455 未使用显式 PID: os.kill(p, signal.SIGTERM)
```

这是**仓库既有的进程安全门禁**（`PROCESS_KILL_SCOPE`，源自 owner 曾经被过宽
kill 误伤事件）对新 ambiguity harness 的真实告警：`kill_worker()` 使用了
`os.kill(pid, SIGTERM)`，未被该门禁的「显式 PID 形式」识别。**未修改门禁**，
而是修正 harness：只保留 `taskkill /F /PID`（显式 PID，语义等价且合规）。
后续独立复验：

```
tests/test_process_kill_scope.py            = PASS（5 项，exit 0）
POSTGRES COMMIT AMBIGUITY GATE（重跑）        = PASS（9/9，0 failed/0 errors；attempt 3）
   —— 证明修改后的终止方式仍执行**真实 OS 进程终止**（依赖真实 kill 的
      CA-01/CA-02/CA-05/CA-07 全部通过）
```

修复提交：`03d21f3` test: use explicit-pid kills in the ambiguity harness
（仅测试侧，不含 production 改动）。随后在 `03d21f3` 上重跑全量（run #2）。

**run #2（HEAD `03d21f3`，01:58 启动）与 Windows 重启恢复（如实记录，未把重启当代码失败）**：

```
run #2 分块状态（机器于 2026-09-15 05:32:46 重启；被关机码 0x40010004 = 1073807364 终止）：
  Group 1 = PASS（151 collected / 146 passed / 0 failed / 0 errors / 5 skipped；exit 0；JUnit 完整）
  Group 2 = PASS（164 / 153 / 0 / 0 / 11；exit 0；JUnit 完整）
  Group 3 = INTERRUPTED（运行中遇关机；exit 1073807364；无 JUnit）
  Group 4 = NOT_STARTED
  Group 5 = NOT_STARTED

恢复动作（**未从头重跑**）：Group 1/2 复用既有 JUnit；只补跑 Group 3/4/5。
  Group 3 补跑 = PASS（159 / 156 / 0 / 0 / 3；exit 0）
  Group 4 补跑 = 首次出现 **1 项真实失败**（见下），修正后补跑 PASS（153 / 134 / 0 / 0 / 19）
  Group 5 补跑 = PASS（168 / 165 / 0 / 0 / 3；exit 0）
```

Group 4 的失败与处置（**真实失败，非环境借口**）：

```
tests/test_process_kill_scope.py::test_guard_aborts_on_foreign_astrbot_instance
  → finally: scoped.kill_tree(fake.pid) → scripts/process_scope.py::_run_ps
  → RuntimeError: PowerShell 查询失败(rc=1)
```

根因（已直接实测取证）：该用例伪造一个 AstrBot 形态进程 → 断言守卫 ABORT（断言全部通过）
→ cleanup 调 `kill_tree`；当目标进程**已自行退出**时，PowerShell 的
`Stop-Process -Id <不存在 PID> -Force -ErrorAction SilentlyContinue` **仍以退出码 1 结束**，
而 `process_scope` 的查询封装把非 0 退出码统一抛为 `RuntimeError`。
本环境周期性终止进程，故该竞态可达；该用例单独重跑 **6/6 PASS** —— 属环境相关 flake。

处置（最小测试侧修正，提交 `5d2a8c8`）：cleanup 容忍该特定错误，
**紧随其后的 `assert not _alive(fake.pid)` 仍强制进程确实消失**（安全性不变）；
`scripts/process_scope.py`（安全脚本本体）**未修改**。

**最终聚合（5/5 分块 exit 0，无 incomplete / 无 failed group）**：

```
FULL_FAST_REGRESSION = PASS
  collected 795 / passed 754 / failed 0 / errors 0 / skipped 41
  G1 151/146/0/0/5   G2 164/153/0/0/11   G3 159/156/0/0/3
  G4 153/134/0/0/19（补跑）   G5 168/165/0/0/3
```

**Skip 审计**：本模式下 skip 全部来自两类**契约允许**项：
(1) explicit formal-db guards（需 `BLR_FORMAL_DB_PATH`）——其真实执行已由 §1 的
只读 guard 运行独立覆盖并通过；
(2) PG gated integration 入口（需 `BLR_TEST_PG_DSN` + `BLR_TEST_PG_ALLOW`）——
真实 PG 门禁已在 §5 独立完成并通过，**不得**据此误写为「PG 未验证」。
`UNEXPECTED_SKIPS = 0`（41 = 13 formal-db guards + 27 PG gate entries + 1 PG recovery entry）。

```
M3_5000Y_RERUN = NOT_REQUIRED_FOR_FINAL_PRE_M6_REVIEW
  （Pre-M6 production changes 仅涉及 PostgreSQL portability 与 scheduler DB error
    recovery，未修改 frozen simulation semantics；M3 长测历史 PASS + PG determinism /
    chunk / restart equivalence + PG functional gate / ambiguity gate 均已独立 PASS）
```

## 8. CA03 口径（§10）

```
CA03_ITERATIONS                = 20
CA03_AMBIGUOUS_NOT_COMMITTED   = 10
CA03_AMBIGUOUS_COMMITTED       = 0
CA03_COMMITTED_BRANCH_COVERAGE = SATISFIED_BY_CA02_CA07_CA07B
```

「commit durable / application ack lost」已由 CA-02、CA-07、CA-07b 以**真实进程级**
路径确定性覆盖；CA-03 的 connected-kill 窗口在本机时序下产生 not-committed 分支属
**合法时序结果**，非 blocker。**未为制造该分支修改 DB 或测试协议。**

## 9. Final Gate 计算（§16 / §17）

```
FORMAL_DB_EXPLICIT_GUARDS               = PASS
FULL_FAST_REGRESSION                    = PASS（795 / 754 / 0 failed / 0 errors / 41 expected skips）
GOLDEN_BASELINE_MUTATIONS               = 0
PRE_M6_PG_PORTABILITY                   = PASS
PRE_M6_PG_ENVIRONMENT                   = PASS
PRE_M6_PG_FUNCTIONAL_GATE               = PASS
PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_GATE = PASS
BLIND_RETRY_COUNT                       = 0
DUPLICATE_TICKS                         = 0
DUPLICATE_HISTORY_EVENTS                = 0
LOST_TICKS                              = 0
FORKED_HISTORY                          = 0
STALE_WRITER_MUTATIONS                  = 0
HISTORY_INTEGRITY                       = PASS（orphan 0 / cycles 0 / invalid 0）
WORLD_RUNTIME_ROWS                      = 0
CURRENT_BLESSED_TICK                    = NULL
WORLD_SEED_CONSUMED                     = FALSE
```

`PRE_M6_CODE_READY = TRUE`（§16 全部条件满足：formal-db guards PASS、full fast regression
PASS（0 failed / 0 errors / 0 unexpected skips）、golden baseline mutations 0、
四个 PG gate 全 PASS、BLIND_RETRY_COUNT 0、无重复/丢失/fork、history integrity clean、
world_runtime 0 行、tick NULL、World Seed 未消费）。

## 10. M5 Known Limitations（§13）

```
KL-M5-001 = OPEN（DEFERRED）
KL-M5-002 = OPEN（DEFERRED）
OWNER_DECISION = DEFER_NO_FURTHER_FIX
```

自 M5 收尾（`14492f2`）以来未再改动，**本阶段未重新打开** M5 persona / context
priority 开发；二者不构成 authoritative state blocker。

## 11. PG Test Environment（§14）

```
blr-pre-m6-postgres = PostgreSQL 16.15，healthy，127.0.0.1:55432（TEST ONLY）
                      重启后曾为 Exited(255)；经授权重新启动 Docker Desktop + 该容器后
                      恢复 healthy，31 个合成测试库随卷保留
dev/test venv       = %TEMP%\blr-pre-m6-pg-venv（psycopg 3.3.5）
stayops-postgres    = 未触碰（独立容器，healthy）
```

环境在 Final Pre-M6 Live Staging 完成前**不得删除**。

## 12. Git（§15）

```
b6a0340 test: align formal-db guard with unactivated zero-row state（formal-db 口径修正）
03d21f3 test: use explicit-pid kills in the ambiguity harness（PROCESS_KILL_SCOPE 告警修正）
5d2a8c8 test: tolerate an already-exited target in kill-tree cleanup（清理竞态修正）
（本报告单独 commit；normal fast-forward push；无 amend / rebase / force / 未创建 M6 tag）
```

全部为**测试侧**改动；本阶段（Final Review）未修改任何 production 代码。

## 13. 结论与下一步

`PRE_M6_CODE_READY = TRUE`（§16 全绿），但**仍不得**消费 World Seed 或激活世界：
live Runtime 为 M5.2 lineage（tree hash `e2d0bf6b…`，7 个文件落后于当前 HEAD），
live 正式库 alembic head 为 `d7f9b1c3e5a7`（落后代码 head `a9d4f2b7c1e8` 一个修订）。
必须先完成独立阶段 **FINAL PRE-M6 LIVE STAGING**（部署最终 Runtime code → live plugin →
正式 SQLite schema migration → Scheduler 仍 DORMANT → 世界仍 0 rows → 重启验证；
**仍不消费 World Seed**）。

```
LIVE_RUNTIME_MATCHES_PRE_M6_HEAD = FALSE
LIVE_SCHEMA_SYNC_REQUIRED        = TRUE
M6_ACTIVATION = PROHIBITED
NEXT_ACTION   = AWAIT_OWNER_AUTHORIZATION_FOR_FINAL_PRE_M6_LIVE_STAGING
```

---

## 14. 返回字段（FINAL_PRE_M6_ACTIVATION_REVIEW）

```
FINAL_PRE_M6_ACTIVATION_REVIEW

CURRENT_HEAD = 5d2a8c8d27f4e9d065d4dfd86bd289f26a2eaa65

FORMAL_DB_TECH_DEBT      = CLOSED（测试侧对齐 canonical 0 行口径；未改 production 语义）
FORMAL_DB_EXPLICIT_GUARDS = PASS

FULL_FAST_REGRESSION   = PASS
FAST_TOTAL             = 795
FAST_PASSED            = 754
FAST_FAILED            = 0
FAST_ERRORS            = 0
FAST_SKIPPED           = 41
FAST_UNEXPECTED_SKIPS  = 0

GOLDEN_BASELINE_MUTATIONS = 0

PRE_M6_PG_PORTABILITY                   = PASS
PRE_M6_PG_ENVIRONMENT                   = PASS
PRE_M6_PG_FUNCTIONAL_GATE               = PASS
PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_GATE = PASS

PG012_PRESENT_IN_HEAD = TRUE

CA03_COMMITTED_BRANCH_COVERAGE = SATISFIED_BY_CA02_CA07_CA07B

BLIND_RETRY_COUNT        = 0
DUPLICATE_TICKS          = 0
DUPLICATE_HISTORY_EVENTS = 0
LOST_TICKS               = 0
FORKED_HISTORY           = 0
STALE_WRITER_MUTATIONS   = 0

HISTORY_ORPHAN_LINKS  = 0
HISTORY_CAUSAL_CYCLES = 0
HISTORY_INVALID_REFS  = 0

LIVE_RUNTIME_MATCHES_PRE_M6_HEAD = FALSE（7 文件漂移，均为 Pre-M6 合法修复）
LIVE_SCHEMA_SYNC_REQUIRED        = TRUE

LIVE_FORMAL_DB_ALEMBIC_HEAD = d7f9b1c3e5a7
CURRENT_CODE_ALEMBIC_HEAD   = a9d4f2b7c1e8

WORLD_RUNTIME_ROWS    = 0
CURRENT_BLESSED_TICK  = NULL
OFFICIAL_WORLD_EVENTS = 0
WORLD_SEED_CONSUMED   = FALSE
SCHEDULER_STATUS      = DORMANT

M5_KNOWN_LIMITATIONS_STATUS = OWNER_DEFERRED

PRE_ACTIVATION_PG_GATE                  = PASS（待最终 Pre-M6 Live Staging 后复验 live 侧）
PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_GATE = PASS

PRE_M6_CODE_READY = TRUE

M6_ACTIVATION = PROHIBITED

NEXT_ACTION = AWAIT_OWNER_AUTHORIZATION_FOR_FINAL_PRE_M6_LIVE_STAGING
```

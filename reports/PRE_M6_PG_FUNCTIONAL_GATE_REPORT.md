# PRE-M6 POSTGRESQL FUNCTIONAL GATE — 报告

- 报告时间：2026-09-14（本地）
- 阶段：`PRE-M6 POSTGRESQL FUNCTIONAL GATE`（A–G；**不含** commit ambiguity）
- 前置提交：
  - `PG_ENV_FIX_HEAD = 28908526f112b032184a34cf7eac564525a194ab`
    （fix: validate migrations and invariants on real postgres）
  - `PG_ENV_REPORT_HEAD = 86843c33301af57ae9756793619597e410dc8363`
    （docs: record postgres environment validation）
- 本阶段提交（详见 §9）：
  - `a44e004` fix: widen tribulation decision policy for postgres（**PG-011**）
  - `42d13af` test: add real postgres functional gate
- 结论：**`PRE_M6_PG_FUNCTIONAL_GATE = PASS`**（18/18，0 failed / 0 errors / 0 skipped；
  5504.9s）。`PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_GATE` 仍为 `REQUIRED`。
- `M6_ACTIVATION = PROHIBITED`（未进入 M6）

---

## 1. 环境（沿用上一阶段，未重建）

```
容器            = blr-pre-m6-postgres（TEST ONLY，healthy）
PostgreSQL      = 16.15（x86_64-pc-linux-musl）
端点            = 127.0.0.1:55432（仅回环）
驱动            = psycopg 3.3.5（DEV_TEST_ONLY，%TEMP%\blr-pre-m6-pg-venv）
PG 成本标定      = 迁移+播种 2.4s；仿真 ≈ 2.1 s/福地年（SQLite 侧更快）
```

所有 gate 测试均在**每用例独立**的合成库上运行（`blr_pg_functional_test_<N>`，
库名含 `test`，可 DROP/CREATE 重建）。**未触碰**正式库 / live `plugin_data` /
World Seed / 正式 world_id；未使用 `BLR_FORMAL_DB_PATH`（runner 显式剔除该变量）。

---

## 2. 关键发现：PG-011（真实缺陷，已修）

**gate 首次真实仿真即中止**（这是本轮最有价值的产出）：

```
sqlalchemy.exc.DataError: (psycopg.errors.StringDataRightTruncation)
value too long for type character varying(24)
[SQL: UPDATE tribulation_episodes SET current_stage=..., decision_policy=..., ...]
[parameters: {'decision_policy': 'DEFAULT_AUTONOMOUS_RESPONSE_POLICY', ...}]
```

- 根因：`tribulation_episodes.decision_policy` 声明 `VARCHAR(24)`，而冻结常量
  `DEFAULT_AUTONOMOUS_RESPONSE_POLICY` 长 **33** 字符。
- 为什么一直没被发现：**SQLite 不强制 `VARCHAR(N)` 长度**（亲和类型只有 TEXT），
  因此该写入在 SQLite 上"一直成功"；PostgreSQL 严格强制 → 仿真在 IMPACT 阶段
  写 decision_policy 时直接中止。
- 修复：migration `a9d4f2b7c1e8` 加宽为 `VARCHAR(64)`（模型同步 `String(64)`）；
  SQLite 数据与语义不变（本就不强制长度），`ALEMBIC_HEAD = a9d4f2b7c1e8`。
- 契约新增 **§11 列宽契约**：声明列宽必须覆盖全部冻结常量/enum 取值；
  确定性 id 必须精确等于列宽；并把"实跑 + information_schema 逐列 max(length)"
  定为审计手段。
- 附带列宽审计（真实合成世界跑完后实测，仍在界内的 near-limit 观察项）：
  `tribulation_profiles.status` 17/24、`lineages.semantic_version` 13/16、
  `households.state` 9/12、`tribulation_episodes.status` 9/12；
  多数确定性 id 列恰好 32/32（`causal-link-id-v1` 设计如此）。

---

## 3. A. Single Writer（真实 PG）

```
POSTGRES_SINGLE_WRITER     = PASS
MAX_AUTHORITATIVE_WRITERS  = 1
```

- A 获取成功 → B（独立 engine/连接）在其租约有效期内申请 → **拒绝**
  （`WriterLockConflict`："另一 Runtime 正在推进该世界"）；
- A 续约（`renew`）成功 → B 仍被拒；
- A 释放后 B 可获取（世界不会永久锁死）；
- 任意时刻 DB 侧**未过期租约行数 = 1**（`SELECT count(*) FROM runtime_lock
  WHERE expires_at > now()` 断言）；
- 两连接**真并发**竞态（`ThreadPoolExecutor` + 两个独立 engine）→ 恰好一个胜出。

## 4. B/C. Fencing、Lease Expiry、Takeover

```
POSTGRES_FENCING         = PASS
POSTGRES_LEASE_TAKEOVER  = PASS
FENCING_TAKEOVERS        = 2（同进程过期接管 + 真实进程死亡后接管）
STALE_WRITER_MUTATIONS   = 0
```

- **接管走 production coordination path**：A 以 `lease_seconds=2` 获取后停止心跳，
  租约自然过期（`live_lease_rows == 0`），B 经 `WriterLease.acquire()` 的
  **CAS 接管**（`UPDATE ... WHERE expires_at <= now`，rowcount 判定）取得新 token；
  **未手工 UPDATE `runtime_lock` 造 takeover**。
- 接管后 DB 行内 `lease_token` 已更替（旧 token 失效），新租约 `expires_at > now`。
- 旧 writer 的续约被拒，且三类 mutation **全部被拒**（`FencingViolation`，零写入）：
  1. world mutation（`EventRepository.append` + `WorldMutationContext`）
  2. checkpoint / authoritative commit（写 `simulation_checkpoints`）
  3. history mutation（写 `causal_history_links`）
  → 前后计数逐一相等（`world_events` / `simulation_checkpoints` / `simulation_run` /
  `world_runtime` / `runtime_lock` 全不变）→ `STALE_WRITER_MUTATIONS = 0`。

## 5. 进程级隔离（owner §10）

```
PROCESS_LEVEL_WRITER_TEST = PASS
```

- **两个真实 OS 进程**（`python -m tests.pg_functional_worker`，各自独立 engine /
  连接 / 进程状态，文件回传结果，父进程只以显式 PID 控制）在同一毫秒窗口竞态
  （`start_at_ms` 屏障）→ `sorted(outcomes) == ["ACQUIRED", "REJECTED"]`，
  且两进程 PID 互异、DB 侧活租约 = 1。
- 进程 A 死亡（`lease_seconds=3`、不释放即退出）→ 租约过期 → 进程 B 接管 →
  再起进程 C 持 **A 的旧 token** 尝试三类 mutation → 全部 `REJECTED`、
  `mutations_applied == 0`、计数与攻击前完全相同。
- 未使用 `taskkill python.exe` / 按名字批量 kill；仅操作明确 PID。

## 6. D/E/F. 等价性（determinism / chunk / restart）

```
POSTGRES_DETERMINISM          = PASS
POSTGRES_CHUNK_EQUIVALENCE    = PASS
POSTGRES_RESTART_EQUIVALENCE  = PASS
SEEDS_TESTED                  = 5（world id 复用 M3LONG-001..005 约定）
```

- **Determinism**：5 seeds × 100 福地年，每 seed 在**两个独立合成库**各跑一次 →
  三哈希（world_state_hash / event_stream_hash / causal_history_hash）逐字相同；
  其中 **3 seeds 另与 SQLite 参照实现（同一 mini world、同一 seed、同一 world_id）
  逐字相同** → 跨方言语义一致（不是只有 PG 内部可重复）。
- **Chunk equivalence**：direct 250y 与 scheduler budget 分块
  **250y / 100y / 10y** 三种切分最终三哈希一致（batch 边界不进入世界语义）。
- **Restart equivalence**：
  - 同进程分段落盘（`restart_every_years=25`，120y）== direct 120y；
  - **真实进程重启**：进程 1 跑 0→60y 退出，进程 2（新 engine）从 durable 状态
    续跑 60→120y，最终 tick = 120,000,000 且三哈希 == 单进程 direct 120y。
- 全部使用 synthetic seeds / synthetic world id；未消费 World Seed。

**福地年统计（PG）**：determinism 1000（5×2×100）+ chunk 1000（250×4）
+ restart 240 + process-restart 240 + history 60 = **2,540 PG 福地年**；
另有 SQLite 参照 300 年（跨方言对照）。

## 7. G. History Integrity 与事件不可变（仿真后）

```
HISTORY_ORPHAN_LINKS   = 0
HISTORY_CAUSAL_CYCLES  = 0
HISTORY_INVALID_REFS   = 0
PG_EVENT_IMMUTABILITY  = PASS
PG_EVENT_UPDATE_PROTECTION   = ENFORCED
PG_EVENT_DELETE_PROTECTION   = ENFORCED
PG_EVENT_TRUNCATE_PROTECTION = ENFORCED
```

- 真实 PG 世界完成 60 福地年仿真后运行 `HistoryService.history_integrity_audit`：
  `orphan_links = 0`、`cycle_count = 0`、`invalid_relations = []`、
  `tick_paradox_links = 0`、`duplicate_links = 0`、`clean = True`。
- 事件层：`verify_event_immutability` 在位；对仿真产生的真实事件执行
  UPDATE / DELETE / TRUNCATE → 三者全部被 DB 层拒绝（PL/pgSQL `RAISE EXCEPTION`，
  SQLSTATE `P0001`，消息含 `append-only` 与算子名），攻击后
  `world_events` 计数不变、触发器仍在位。
  其中 TRUNCATE 由**语句级** `blr_world_events_no_truncate`（migration
  `f2a7c4e9b1d6`）拦截 —— 即 PG-006 的缺口确已在真实 PG 上补上。

## 8. 逐用例结果（真实耗时）

| # | 用例 | 结果 | 耗时 |
| --- | --- | --- | --- |
| 1 | test_pg_single_writer_exclusive_and_renew | PASS | 2.6s |
| 2 | test_pg_single_writer_concurrent_two_connections | PASS | 2.3s |
| 3 | test_pg_lease_expiry_takeover_production_path | PASS | 6.0s |
| 4 | test_pg_stale_writer_all_mutations_rejected | PASS | 5.9s |
| 5 | test_pg_process_level_writer_race | PASS | 10.5s |
| 6 | test_pg_process_level_stale_worker_mutations_rejected | PASS | 7.1s |
| 7 | test_pg_determinism_repeat_and_cross_dialect[M3LONG-001] | PASS | 446.7s |
| 8 | test_pg_determinism_repeat_and_cross_dialect[M3LONG-002] | PASS | 458.8s |
| 9 | test_pg_determinism_repeat_and_cross_dialect[M3LONG-003] | PASS | 453.1s |
| 10 | test_pg_determinism_repeat_and_cross_dialect[M3LONG-004] | PASS | 418.8s |
| 11 | test_pg_determinism_repeat_and_cross_dialect[M3LONG-005] | PASS | 425.0s |
| 12 | test_pg_chunk_equivalence_direct_reference | PASS | 536.9s |
| 13 | test_pg_chunk_equivalence[250] | PASS | 524.0s |
| 14 | test_pg_chunk_equivalence[100] | PASS | 541.6s |
| 15 | test_pg_chunk_equivalence[10] | PASS | 519.5s |
| 16 | test_pg_restart_equivalence_same_process | PASS | 471.7s |
| 17 | test_pg_process_restart_equivalence | PASS | 541.3s |
| 18 | test_pg_history_integrity_and_event_immutability | PASS | 131.0s |

合计 **5502.7s**（runner 记录 5504.9s = 1h31m45s），`exit_code = 0`。

## 9. SQLite 侧回归（本轮范围）

```
SQLITE_TARGETED_REGRESSION = PASS（exit 0；85 collected → 65 passed / 20 expected skips）
FULL_FAST_REGRESSION       = NOT_RERUN_ON_CURRENT_HEAD /
                             DEFERRED_TO_FINAL_PRE_M6_REVIEW（按 owner §0）
```

- 定向模块：`test_database`、本阶段 3 个 PG 文件、`test_pg_event_truncate_protection`、
  `test_pg_recovery_checkpoint_portability`、`test_pg_portability_static_audit`、
  `test_backup_events`、`test_guards`。
- 20 个 skip 全部为**预期**：18 × functional gate（缺 DSN/ALLOW）+ 2 × PG 集成入口。
  即门禁在无 PG 环境下**按设计 skip**（非静默通过）。
- 全量 fast 回归（约 7.3h 分块）**未在当前 HEAD 上重跑**，属 `DEFER_TO_FINAL_PRE_M6_REVIEW`；
  最终 M6 前必须补做（不得写成 `PASS_ON_CURRENT_HEAD`）。

## 10. 正式世界 / live 红线复核

```
FORMAL_WORLD_TOUCHED     = FALSE
WORLD_RUNTIME_STATUS     = NOT_ACTIVATED（world_id = FORMAL-UNSEEDED）
CURRENT_BLESSED_TICK     = NULL
OFFICIAL_WORLD_EVENTS    = 0
OFFICIAL_WORLD_MUTATIONS = 0
WORLD_SEED_CONSUMED      = FALSE
SCHEDULER_STATUS         = DORMANT（counters 全 0；last_error = null）
```

- 正式库 `blessed_land.sqlite` 536576 B、mtime `09-12 09:53:41`（未变）、`-wal` = 0 B；
  `authoritative_db.json` 校验和 `1d84ee37…52cf2`（与冻结值一致）。
- live 实例 PID 56560 / 1744 持续运行、未重启；**未**触碰 live venv / Runtime plugin /
  plugin_data / Private Companion / AstrBot Core / Launcher。
- 未迁移正式世界、未创建正式 `world_runtime`、未消费 World Seed、未进入 M6。
- **保留登记的技术债（本轮未修）**：`PRE_M6_TECH_DEBT =
  FORMAL_DB_NOT_ACTIVATED_REPRESENTATION_CONSISTENCY`
  （canonical 持久化 = `world_runtime` 0 行；部分显式 formal-db 测试曾假设存在
  一行 `NOT_ACTIVATED`）。本阶段未插行、未改测试口径，留待 Pre-M6 Final Review。

## 11. 过程事故（如实记录）

| 事项 | 现象 | 处置 |
| --- | --- | --- |
| runner 静默死亡 | 首次 detached runner 立即退出且无日志：凭据 JSON 由 PowerShell 写出**带 BOM**，`json.loads` 抛错，而日志文件在读取凭据之后才创建 | runner 改为**先建日志**再读凭据，并用 `utf-8-sig` 读取；启动异常显式写 info JSON |
| 守卫 fail-closed 生效 | runner 传入的 DSN 库名 `blr_pre_m6` **不含 `test`** → 全部 18 项 setup 阶段 `Failed: 拒绝在非测试库上执行 PG 集成测试` | 修正 DSN 库名为 `blr_pre_m6_test`；该次失败本身证明门禁守卫有效（非绕过） |
| 测试设计缺陷（非产品缺陷） | takeover 用例最初断言 `owner` 字符串不同；但 A/B 在同一进程内，`owner = host:pid:process_run_id` 相同 | 改为断言 **DB 行内 `lease_token` 已更替且新租约未过期**（更贴近语义） |
| 并发路径缺行级锁说明 | `SELECT … FOR UPDATE` 全仓未使用，PG 侧依赖 CAS UPDATE 行锁 + 唯一索引 | 已由本阶段并发/竞态/接管用例实证（含真实进程），并在契约中保留说明 |

## 12. 新增/修改文件（本阶段）

| 文件 | 变更 |
| --- | --- |
| `database/alembic/versions/a9d4f2b7c1e8_pg_widen_tribulation_decision_policy.py` | **新增 migration**（PG-011：decision_policy 24 → 64） |
| `database/models_world.py` | `decision_policy` → `String(64)` |
| `tests/conftest.py` / `plugin_shell/runtime_host.py` / `scripts/migrate_db_to_plugin_data.py` | head → `a9d4f2b7c1e8` |
| `tests/test_pg_event_truncate_protection.py` | head 常量同步（NEW_HEAD/PREV_HEAD） |
| `tests/pg_functional_support.py` | **新增**：PG 合成库/世界构建、哈希、worker 进程编排 |
| `tests/pg_functional_worker.py` | **新增**：独立 OS 进程 worker（acquire/renew/stale_mutation/run_years/scheduler_budget） |
| `tests/test_pg_functional_gate.py` | **新增**：A–G 门禁 18 项 |
| `POSTGRESQL_COMPATIBILITY_CONTRACT.md` | §9 增 PG-011；新增 §11 列宽契约、§12 PG functional gate 实跑记录 |

## 13. Git

```
PG_ENV_FIX_HEAD        = 28908526f112b032184a34cf7eac564525a194ab
PG_ENV_REPORT_HEAD     = 86843c33301af57ae9756793619597e410dc8363
PG_FUNCTIONAL_FIX_HEAD = a44e004（fix: widen tribulation decision policy for postgres）
PG_FUNCTIONAL_GATE_HEAD = 42d13af（test: add real postgres functional gate）
GITHUB_SYNC            = PASS（fast-forward：86843c3..42d13af → refs/heads/m5-1-runtime-integration-fix）
HISTORY_REWRITTEN      = FALSE（未 amend / rebase / force push；未新增或移动 tag）
```

## 14. 返回字段（PRE_M6_PG_FUNCTIONAL_GATE_REPORT）

```
PRE_M6_PG_FUNCTIONAL_GATE_REPORT

PG_ENV_FIX_HEAD        = 28908526f112b032184a34cf7eac564525a194ab
PG_ENV_REPORT_HEAD     = 86843c33301af57ae9756793619597e410dc8363
GITHUB_SYNC            = PASS

POSTGRES_SINGLE_WRITER = PASS
MAX_AUTHORITATIVE_WRITERS = 1

POSTGRES_FENCING       = PASS
POSTGRES_LEASE_TAKEOVER = PASS
FENCING_TAKEOVERS      = 2
STALE_WRITER_MUTATIONS = 0

PROCESS_LEVEL_WRITER_TEST = PASS（两个真实 OS 进程竞态 + 进程死亡后接管）

POSTGRES_DETERMINISM        = PASS
POSTGRES_CHUNK_EQUIVALENCE  = PASS
POSTGRES_RESTART_EQUIVALENCE = PASS

SEEDS_TESTED        = 5（M3LONG-001..005）
BLESSED_YEARS_TESTED = 2540 PG 福地年（determinism 1000 / chunk 1000 / restart 240 /
                       process-restart 240 / history 60）+ SQLite 参照 300 年

HISTORY_ORPHAN_LINKS  = 0
HISTORY_CAUSAL_CYCLES = 0
HISTORY_INVALID_REFS  = 0

PG_EVENT_UPDATE_PROTECTION   = PASS（ENFORCED，P0001）
PG_EVENT_DELETE_PROTECTION   = PASS（ENFORCED，P0001）
PG_EVENT_TRUNCATE_PROTECTION = PASS（ENFORCED，P0001，语句级触发器）

PG_GATE_DEFECTS_FOUND_AND_FIXED = PG-011（列宽不足，SQLite 不强制 / PG 强制）

FORMAL_WORLD_TOUCHED = FALSE
WORLD_RUNTIME_STATUS = NOT_ACTIVATED
WORLD_SEED_CONSUMED  = FALSE

PRE_M6_PG_FUNCTIONAL_GATE = PASS
PRE_ACTIVATION_PG_GATE    = PARTIAL（commit ambiguity 仍未执行，不得 FINAL PASS）
PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_GATE = REQUIRED
M6_ACTIVATION             = PROHIBITED

FULL_FAST_REGRESSION = NOT_RERUN_ON_CURRENT_HEAD / DEFERRED_TO_FINAL_PRE_M6_REVIEW
PRE_M6_TECH_DEBT     = FORMAL_DB_NOT_ACTIVATED_REPRESENTATION_CONSISTENCY（未修）

NEXT_ACTION = AWAIT_OWNER_REVIEW_FOR_REAL_COMMIT_AMBIGUITY_GATE
```

**STOP** — 未实现/未测试任何 commit ambiguity（连接在 COMMIT 中断开、ACK lost、
unknown outcome、blind-retry reconciliation 全部留给下一独立阶段）；
未做 worker/server kill；未做 5000y PG endurance；未进入 M6；未对 live 与正式世界做任何改动。

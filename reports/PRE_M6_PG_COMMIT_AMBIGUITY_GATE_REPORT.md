# PRE-M6 POSTGRESQL COMMIT AMBIGUITY GATE — 报告

- 报告时间：2026-09-14（本地）
- 阶段：`PRE-M6 POSTGRESQL COMMIT AMBIGUITY GATE`（M6 激活前最后一个独立数据库安全门禁）
- 前置基线：`HEAD = 3146d25`（`PRE_M6_PG_FUNCTIONAL_GATE = PASS`，工作区 clean）
- 审计产物：`docs/pre_m6_pg_commit_ambiguity_audit.md`
- 本阶段提交：
  - `c12ba2c` test: add real postgres commit ambiguity harness
  - `005db4f` fix: reconcile ambiguous postgres commits safely（**PG-012**）
- 结论：**`PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_GATE = PASS`**
  （9/9 用例，两轮独立运行均 PASS）；`PRE_ACTIVATION_PG_GATE = READY_FOR_FINAL_REVIEW`。
- `M6_ACTIVATION = PROHIBITED`（未进入 M6）

---

## 1. Commit Boundary Audit（§2，只读）

审计定位（完整见 `docs/pre_m6_pg_commit_ambiguity_audit.md`）：

```
AUTHORITATIVE_COMMIT_ENTRYPOINT = services.catchup.catch_up 阶段 2（ctx2.commit）
                                  与 services.atomic_tick.run_atomic_tick（ctx.commit）
TRANSACTION_BEGIN               = WorldMutationContext.__enter__（fencing.py:44，含心跳刷新）
TRANSACTION_COMMIT              = WorldMutationContext.commit()（fencing.py:78：
                                  先 assert_current_fence() 再 session.commit()）
DURABLE_OPERATION_IDENTITY      = simulation_run.run_id（run-id-v1 确定性 128-bit；
                                  输入 world/version/区间或目标 tick/attempt_seq，无 UUID4/墙钟）
DURABLE_BATCH_IDENTITY          = (world_id, simulation_version,
                                   real_interval_start_us, real_interval_end_us)
                                  （部分唯一索引 uq_simulation_run_committed_interval 强制）
RECOVERY_LOOKUP_KEY             = SimulationRunRepository.committed_for_interval(...) /
                                  committed_until_tick >= target /
                                  world_runtime.current_blessed_tick /
                                  最新 complete WORLD_COMMITTED checkpoint
POST_COMMIT_IN_MEMORY_STATE     = RuntimeScheduler 内存字段 + scheduler_state.json
                                  （代码明示「非世界真值」，恢复不得信任）
```

**既有机制复用判定**：M3c/M4 的确定性 run_id、区间幂等、stale RUNNING 清理、
fencing token、租约 CAS 接管、`_recover_truth` 全部为 ORM/SQL（无 SQLite 私有 SQL）
→ **在 PG 上可复用**；本阶段**未**新设计任何第二套 commit protocol。

**审计发现的三个要点**（AMB-AUDIT-01/02/03）：
1. `_execute_batch` 的歧义分支只 `except RuntimeError`，而真实连接故障是
   `sqlalchemy.exc.OperationalError`（MRO 实测不含 `RuntimeError`）→ 疑点，需实证；
2. 幂等键是「区间键」，而区间由 durable 游标派生 → 判定"是否已提交"必须**双真值**
   （world tick + 操作区间）；
3. 进程死于阶段 1 与阶段 2 之间会留下 RUNNING run（设计内，可安全重做），
   必须与 `COMMITTED` 区分，否则会把设计行为误判为重复。

---

## 2. Harness 结构（§4 / §5 / §23）

```
Controller（pytest 进程）
  ├── Writer Process A（独立 engine / 连接 / 进程状态；文件 IPC sentinel）
  ├── Recovery Process B（独立 engine / 连接 / 进程状态）
  └── PostgreSQL 16.15（隔离容器 blr-pre-m6-postgres，TEST ONLY）
```

- 每个 worker 均为**真实 OS 进程**（`python -m tests.pg_ambiguity_worker`），
  结果与阶段通报经文件回传（不使用管道）；终止只按**显式 PID**（Windows venv
  启动器下 `Popen.pid` 只是 stub，故以 sentinel 中真实 PID 为准）；
- sentinel 阶段：`started` / `inside_tx`（事务内）/ `pre_commit`（即将 COMMIT）/
  `committed`（durable commit 后、应用确认前）；
- **未在生产代码中加入任何测试 failpoint**：`AFTER_DATABASE_COMMIT_BEFORE_APPLICATION_ACK`
  窗口由 harness 在应用确认写出前真实杀死进程实现（应用确认 = 调度器 checkpoint /
  worker 完成记录，worker 从不写它）；事务内延时经生产公开扩展点 `simulate_fn` /
  `coordinator` 注入，不改事务顺序与语义；
- 隔离：专用合成库 `blr_pg_commit_ambiguity_test`（+ `..._ref_test` 参照库）、
  world id `PGAMB-*`、synthetic seed；**未**触碰正式库 / live plugin_data /
  StayOps DB / functional gate 的库；
- 恢复语义：一律**先查 durable truth** 再决定是否提交；租约按生产语义
  **自然过期**后由生产 CAS 接管（绝不手工 UPDATE `runtime_lock`）。

---

## 3. 用例结果（§6–§14）

| 用例 | 结果 | 耗时 | 关键证据 |
| --- | --- | --- | --- |
| CA-01 明确未提交（事务中被真实杀进程） | PASS | 128.5s | durable 未推进；PG 回滚；允许重做；无重复 |
| CA-02 已提交但应用确认前进程死亡 | PASS | 131.0s | durable tick=1,000,000、run_id 存在 → `ALREADY_COMMITTED`；**不重试** |
| CA-03 COMMIT 期连接丢失（20 轮扫掠） | PASS | 100.7s | 每轮 reconcile；world 只推进一次；无重复/丢失 |
| CA-04 COMMIT 窗口内服务器重启 | PASS | 131.3s | 客户端 ERROR；恢复 reconcile；`PG_HEALTH = healthy` |
| CA-05 歧义后接管 + CA-06 陈旧 token 重提 | PASS | 12.0s | 过期租约 → 生产 CAS 接管（新 token = epoch N+1）；旧 token 重提**未提交**年份 → `FencingViolation`、零写入 |
| CA-07 ACK-lost 等价用例 ×5 | PASS | 39.6s | 5/5 全部 `ALREADY_COMMITTED`；应用完成记录不存在 |
| CA-07b 调度器路径 ACK-lost | PASS | 11.7s | `ADVANCED=True ACK_RETAINED=False`（真实 ACK 丢失）后恢复正确 |
| CA-08 调度器连接故障必须 fail-closed | PASS | 4.5s | 修复后：异常不再逃出；状态 `FAILED`；`recovery_count=1`、`commit_ambiguity_count=1` |
| CA-99 PG-011 回归 + 历史完整性 + 事件不可变 | PASS | 24.8s | `decision_policy VARCHAR(64)`、>24 字符策略真实写入；历史 audit clean；UPDATE/DELETE/TRUNCATE 全被拒 |

两轮独立运行（修复后）：

```
run #1（无 -s）: 9 collected / 9 passed / 0 failed / 0 errors / 0 skipped；585.4s；exit 0
run #2（-s）  : 9 collected / 9 passed / 0 failed / 0 errors / 0 skipped；612.5s；exit 0
```

### CA-03 分支观测（如实报告，未强行制造）

```
CA03_ITERATIONS              = 20
AMBIGUOUS_NOT_COMMITTED      = 10（客户端 outcome 未知 + durable 未提交）
CLIENT_ERROR                 = 10
CLIENT_OK / KILL_MISSED_OR_POST_ACK = 10（kill 落在 ack 之后或未命中，属合法时序）
AMBIGUOUS_COMMITTED          = 0
```

即：**在本机时序下，`pg_terminate_backend` 与 COMMIT 竞速产生的歧义分支是
「未提交」**（kill 落在 COMMIT 之前，PG 回滚在途事务）；「服务器已提交、客户端未收到确认」
这一分支在 CA-03 中未观测到（本机 COMMIT+ACK 往返快于外部连接的 terminate 往返）。
该分支由 **CA-02 与 CA-07/CA-07b 确定性覆盖**（真实进程在 durable commit 后、
应用确认前被杀死）——两者均已 PASS。**未通过 UPDATE DB 强行制造另一分支。**

---

## 4. 硬指标（§15–§19）

```
BLIND_RETRY_COUNT              = 0（所有恢复路径先查 durable truth 再决定提交；
                                  CA-06 另有 1 次**受控**盲重试探针，单独计数
                                  BLIND_RETRY_PROBES=1 → 生产幂等使其成为 no-op，
                                  未产生重复）
DUPLICATE_TICKS                = 0
DUPLICATE_HISTORY_EVENTS       = 0
LOST_TICKS                     = 0
FORKED_HISTORY                 = 0
STALE_WRITER_MUTATIONS         = 0（以 durable 接管时刻界定，接管后无旧 token 写入）
HISTORY_ORPHAN_LINKS           = 0
HISTORY_CAUSAL_CYCLES          = 0
HISTORY_INVALID_REFS           = 0
FINAL_HASH_EQUIVALENCE         = PASS（每个用例与无故障 direct 参照三哈希一致）
POSTGRES_ACK_LOST_EQUIVALENT_CASES = 5（CA-07；另有 CA-07b 调度器路径 1 例）
```

**事件不可变性未被用作"清理重复"的手段**（§19）：CA-99 明确验证
`UPDATE` / `DELETE` / `TRUNCATE world_events` 三者全部被 DB 层拒绝，
且 harness 从不需要也不允许以改写历史来"修复"重复。

**事务原子性（§18）**：world 时钟 + 事件 + history + run(→COMMITTED) + checkpoint
同属一次 `ctx.commit()`；阶段 1 的 RUNNING run 属**设计内**中间态（AMB-AUDIT-03），
`fail_stale_running` 处理，不产生「world 已提交但 operation identity 未提交」的不一致。
**未发现 activation blocker 级别的原子性缺陷。**

---

## 5. Production Defect：PG-012（§28）

**发现（真实证据，CA-08 初版即失败）**：

```
error.type = OperationalError
error.msg  = (psycopg.errors.AdminShutdown) terminating connection ...
status_after_error = {scheduler_state: CATCHING_UP, writer_owned: True, ...}
assert 'CATCHING_UP' in ('RECOVERING', 'FAILED')  → FAIL
```

真实 PG 连接在 COMMIT 期间断开时抛 `sqlalchemy.exc.OperationalError`；
`RuntimeScheduler._execute_batch` 的歧义分支只 catch `RuntimeError`，异常逃出
`run_cycle`（其只 catch `FencingViolation`），调度器停在 `CATCHING_UP` **且仍持租约**，
既无 durable-truth 核对也无 fail-closed —— 正是 owner §1 所禁止的"未知状态静默继续"风险面。

**最小修复**（`services/scheduler/core.py`，+38/−3）：
1. `_execute_batch` 增加 `except sa_exc.DBAPIError` 分支，走**同一** durable-truth
   核对路径（`_recover_truth`）——与 `RuntimeError` 分支共用语义：已提交则继续，
   未推进则 `FAILED`（fail-closed），**绝不盲重试**；
2. `_recover_truth` 改经 `_read_durable_tick_resilient()` 读取（连接失效重试一次，
   失效连接由连接池回收）；若 durable truth **完全不可读** → `FAILED` fail-closed。

**复验**：CA-08 PASS（`ERROR_TYPE=None`、`STATE_AFTER=FAILED`、计数各 +1）；
SQLite 定向回归（scheduler / ack-lost / commit-ambiguity / fencing / writer-recovery /
catchup 等）**exit 0**，正常路径语义未变。

---

## 6. 回归（§20 / §25）

```
PG FUNCTIONAL GATE REGRESSION  = PASS（PG-012 修复后重跑：18 collected / 18 passed /
                                 0 failed / 0 errors / 0 skipped；5520.1s；exit 0）
PG PORTABILITY TESTS           = PASS（scanner 90 文件 0 违规；PG 入口在缺 DSN 时按设计 skip）
SQLITE TARGETED REGRESSION     = PASS
   - scheduler/ambiguity 组（ack-lost / commit-ambiguity / crash-recovery / fencing /
     single-writer / lifecycle / observability / dormant-gate / m2b-ambiguity）: 50 项 exit 0
   - portability + recovery 组（pg_portability_scan / pg_event_truncate / pg_recovery /
     database / backup_events / catchup / fencing / writer_recovery）: 90 项 exit 0（2 expected skip）
   - history/audit 组（m3b_metric_audit / hardening_hp）: exit 0
   - 门禁非空过：无 BLR_TEST_PG_DSN/ALLOW 时 ambiguity 9 项与 functional 18 项
     全部按设计 skip（exit 0），非静默通过
FULL_FAST_REGRESSION           = NOT_RERUN_ON_CURRENT_HEAD /
                                 DEFERRED_TO_FINAL_PRE_M6_REVIEW（按 owner §25，未声称 PASS）
PG 5000y ENDURANCE             = NOT_RUN（按 owner §24，属最终 Review 决策项）
PG-011 COLUMN-WIDTH REGRESSION = PASS（CA-99：列宽 64、>24 字符策略可写入）
```

---

## 7. 环境与正式世界（§21 / §22）

```
PG_CONTAINER   = blr-pre-m6-postgres（PostgreSQL 16.15，127.0.0.1:55432，TEST ONLY）
PG_HEALTH      = healthy（CA-04 真实重启后恢复；他容器 stayops-postgres 未受影响）
测试库隔离      = blr_pg_commit_ambiguity_test / blr_pg_commit_ambiguity_ref_test（可 DROP/CREATE）
FORMAL_WORLD_TOUCHED = FALSE
WORLD_RUNTIME_STATUS = NOT_ACTIVATED（world_id = FORMAL-UNSEEDED）
CURRENT_BLESSED_TICK = NULL
OFFICIAL_WORLD_EVENTS = 0
OFFICIAL_WORLD_MUTATIONS = 0
WORLD_SEED_CONSUMED  = FALSE
SCHEDULER_STATUS     = DORMANT（counters 全 0；last_error = null）
```

- 正式库 `blessed_land.sqlite` 536576 B、mtime `09-12 09:53`（未变）、`-wal` = 0 B；
  `authoritative_db.json` 校验和 `1d84ee37…52cf2`（与冻结值一致）；
- live 实例 PID 56560 / 1744 持续运行、未重启；未部署 Runtime、未改 live venv、
  未连接 live SQLite 做 mutation、未修改 Private Companion；
- 保留登记技术债（未修）：`PRE_M6_TECH_DEBT =
  FORMAL_DB_NOT_ACTIVATED_REPRESENTATION_CONSISTENCY`。

---

## 8. 返回字段（PRE_M6_PG_COMMIT_AMBIGUITY_GATE_REPORT）

```
PRE_M6_PG_COMMIT_AMBIGUITY_GATE_REPORT

COMMIT_BOUNDARY_AUDIT        = COMPLETE
DURABLE_OPERATION_IDENTITY   = simulation_run.run_id（run-id-v1 确定性 128-bit）
RECOVERY_LOOKUP_KEY          = committed_for_interval(world, version, interval) /
                               committed_until_tick >= target /
                               world_runtime.current_blessed_tick /
                               latest complete WORLD_COMMITTED checkpoint

CA01_DEFINITE_ROLLBACK            = PASS
CA02_COMMITTED_WORKER_DIES        = PASS
CA03_CONNECTION_LOST_DURING_COMMIT = PASS
CA03_ITERATIONS                   = 20
CA03_COMMITTED_OUTCOMES           = 0（本机时序下未观测到；该分支由 CA-02/CA-07 覆盖）
CA03_NOT_COMMITTED_OUTCOMES       = 10（客户端 outcome 未知 + durable 未提交）
CA04_SERVER_RESTART_DURING_COMMIT = PASS
CA05_TAKEOVER_AFTER_AMBIGUITY     = PASS
CA06_STALE_RETRY                  = PASS
CA07_ACK_LOST_EQUIVALENT          = PASS
CA08_SCHEDULER_CONNECTION_LOSS_FAIL_CLOSED = PASS

POSTGRES_ACK_LOST_EQUIVALENT_CASES = 5（CA-07）+ 1（CA-07b 调度器路径）

BLIND_RETRY_COUNT        = 0
DUPLICATE_TICKS          = 0
DUPLICATE_HISTORY_EVENTS = 0
LOST_TICKS               = 0
FORKED_HISTORY           = 0
STALE_WRITER_MUTATIONS   = 0

HISTORY_ORPHAN_LINKS     = 0
HISTORY_CAUSAL_CYCLES    = 0
HISTORY_INVALID_REFS     = 0

FINAL_HASH_EQUIVALENCE   = PASS

PRODUCTION_DEFECTS_FOUND = PG-012（真实连接故障未被 commit 歧义恢复覆盖）
PRODUCTION_DEFECTS_FIXED = PG-012（最小修复 + CA-08 复验 PASS + SQLite 定向回归 exit 0）

FORMAL_WORLD_TOUCHED = FALSE
WORLD_SEED_CONSUMED  = FALSE
WORLD_RUNTIME_STATUS = NOT_ACTIVATED

PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_GATE = PASS
PRE_ACTIVATION_PG_GATE                  = READY_FOR_FINAL_REVIEW
M6_ACTIVATION                           = PROHIBITED

NEXT_ACTION = AWAIT_OWNER_REVIEW_FOR_FINAL_PRE_M6_ACTIVATION_REVIEW
```

**STOP** — 未进入 M6。

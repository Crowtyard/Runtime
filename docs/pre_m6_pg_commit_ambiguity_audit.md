# PRE-M6 PG COMMIT AMBIGUITY — COMMIT BOUNDARY AUDIT（只读）

- 审计时间：2026-09-14（本地）
- 审计基准修订：`3146d25f40b46e46655245b163df29b317cbbba7`（`PRE_M6_PG_FUNCTIONAL_GATE = PASS`）
- 审计性质：**只读**（未改代码、未改配置、未写 DB；本文件为审计产物）
- 目标：定位生产代码中的权威提交边界与既有事务身份/幂等/ACK-loss 机制，
  判定其**在真实 PostgreSQL 上可复用性**，并据此设计 commit ambiguity harness。
- 硬约束：**禁止未经审计重新设计第二套 commit protocol**（本轮只复用既有机制）。

---

## 1. 权威提交入口（AUTHORITATIVE_COMMIT_ENTRYPOINT）

| 入口 | 位置 | 用途 | 事务特征 |
| --- | --- | --- | --- |
| `run_atomic_tick(...)` | `services/atomic_tick.py:38` | 单 tick 原子操作（M1 语义）；`simulate_fn` 写世界状态/事件 | **单事务**：run 行 + simulate_fn 全部写入 + commit |
| `catch_up(...)` → 阶段 2 `_advance_and_commit(...)` | `services/catchup.py:57` / `:131` | 真实世界推进（M3/M4 均经此） | **两段 fenced 事务**：阶段 1 建 RUNNING run；阶段 2 写时钟 + TIME_ADVANCE 事件 + simulate_fn（全 pipeline + history）+ `commit_run` + checkpoint |
| `run_blessed_year(...)` | `services/scheduler/adapter.py:23` | 调度器年粒度编排（= catch_up 的子区间序列） | 每个子区间一次 `catch_up` |

```
AUTHORITATIVE_COMMIT_ENTRYPOINT = services.catchup.catch_up（阶段 2 ctx2.commit）
                                  与 services.atomic_tick.run_atomic_tick（ctx.commit）
                                  —— 二者是全部世界状态 + history + checkpoint 的唯一
                                  权威提交点；两者均要求 fencing 凭据。
TRANSACTION_BEGIN               = WorldMutationContext.__enter__（services/fencing.py:44）
                                  —— 打开 Session 并以 UPDATE runtime_lock（token/owner/
                                  未过期）续约，该写操作即取得数据库写锁。
TRANSACTION_COMMIT              = WorldMutationContext.commit()（services/fencing.py:78）
                                  —— **先** assert_current_fence()（COMMIT 前最终校验
                                  token/owner/expiry），**再** session.commit()。
```

## 2. 持久化身份与恢复查找键（§5 / §15）

```
DURABLE_OPERATION_IDENTITY = simulation_run.run_id
                             = deterministic_hex_id([world_id, simulation_version,
                               target_blessed_tick | (interval_start_us, interval_end_us),
                               attempt_seq], schema="run-id-v1")
                             —— 128-bit 确定性 id，attempt_seq 由 DB 状态派生
                               （services/identity.py + run_lifecycle.py:49-61 /
                                atomic_tick.py:82-92），**不含 UUID4/墙钟/随机熵**。
DURABLE_BATCH_IDENTITY     = (world_id, simulation_version,
                              real_interval_start_us, real_interval_end_us)
                             —— 由部分唯一索引 uq_simulation_run_committed_interval
                               （status='COMMITTED'，migration e6c0f4a1b3d9）在 DB 层强制
                               「同一现实区间只允许一个 COMMITTED run」。
RECOVERY_LOOKUP_KEY        = 生产查找路径（两套，均已存在）：
                              (a) 区间键：SimulationRunRepository.committed_for_interval(
                                  world_id, simulation_version, start_us, end_us)
                                  —— catch_up 阶段 1 的幂等命中
                              (b) 刻度键：simulation_run(world_id, version, status=COMMITTED)
                                  → max(committed_until_tick) >= target
                                  —— run_atomic_tick 的幂等 skip
                              (c) 世界真值：world_runtime.current_blessed_tick /
                                  last_committed_real_us + 最新
                                  complete=True 且 checkpoint_kind='WORLD_COMMITTED'
                                  的 simulation_checkpoints（services/simulation/recovery.py）
                              (d) 调度器恢复：RuntimeScheduler._recover_truth(year_index, exc)
                                  （services/scheduler/core.py:298）——读 durable tick 与
                                  year_end_tick 比较
POST_COMMIT_IN_MEMORY_STATE = **非真值**：RuntimeScheduler 的 _state / _cycle /
                              _last_successful_commit / _commit_ambiguity_count /
                              _recovery_count / _batches_total 等内存字段，
                              以及 scheduler_state.json 检查点
                              （core.py:243-244 明确注释「非世界真值」）。
                              恢复**不得**信任它们（§15）。
```

**事务原子性事实**：`world_runtime` 时钟、`world_events`、`history`（
`causal_history_links` / `history_state_changes` / `history_episode_index`，由
`coordinator.run_step` 在 `simulate_fn` 内写入）、`simulation_run`（→COMMITTED）、
以及 `simulation_checkpoints`（catch_up 的 TIME_COMMITTED）**同属一次 `ctx.commit()`**
（同一事务）。因此不存在「world committed 但 operation identity 未 committed」的
窗口——**除非**进程在阶段 1（RUNNING run 已提交）与阶段 2 之间死亡，此时
durable 状态留下 RUNNING run 而未推进世界；这正是 `fail_stale_running` 的处理对象。

## 3. 既有幂等 / ACK-loss / 接管机制（M3c/M4）——可复用性判定

| 机制 | 位置 | SQLite 专属？ | PG 可复用性 |
| --- | --- | --- | --- |
| 确定性 run_id（run-id-v1） | `services/identity.py`, `run_lifecycle.py:49` | 否（Python 侧 sha256 + ORM） | **可复用（已验证：functional gate 在 PG 上跑通同一路径）** |
| 幂等命中 `committed_for_interval` | `services/run_lifecycle.py:96` | 否（ORM select） | 可复用 |
| 幂等命中 `committed_until_tick >= target` | `services/atomic_tick.py:67` | 否 | 可复用 |
| COMMITTED 区间唯一索引（DB 层幂等防线） | migration `e6c0f4a1b3d9`（含 `postgresql_where`） | 否（partial unique index 双方言） | **PG 上已实测存在**（fresh/existing 迁移 PASS） |
| stale RUNNING 清理 `fail_stale_running` | `services/run_lifecycle.py:111` | 否 | 可复用 |
| fencing commit-前重验 | `services/fencing.py:62-81` | 否 | 已在 PG 上实测（FENCING/TAKEOVER PASS） |
| 租约过期 CAS 接管 | `services/writer_lock.py:66-117` | 否 | 已在 PG 上实测（lease takeover PASS） |
| ACK-lost 恢复（世界/history/checkpoint 三类） | `tests/test_scheduler_ack_lost.py`（**测试注入**）+ `_recover_truth`（生产） | 否 | 生产路径可复用；**PG 真实故障证据缺失**（本轮补齐） |
| commit 歧义恢复 `_recover_truth` | `services/scheduler/core.py:298-312` | 否 | 可复用，但见 §4 覆盖缺口 |

**结论**：无需、也不得新设计第二套 commit protocol。本轮 harness 必须
（a）复用上述生产入口与查找键，（b）用**真实 PG 连接/进程/服务器故障**产生
UNKNOWN outcome，（c）以 durable truth 判定结果。

## 4. 审计发现（**开工前必须验证的结构性疑点**）

### AMB-AUDIT-01 — 真实连接故障异常未被歧义恢复分支覆盖（候选 PG-012）

`RuntimeScheduler._execute_batch`（core.py:278-287）的歧义分支是：

```python
except RuntimeError as exc:
    self._commit_ambiguity_count += 1
    ... self._recover_truth(year_index, exc) ...
```

而真实数据库连接故障的异常类型**不是** `RuntimeError`（实测 MRO）：

```
sqlalchemy.exc.OperationalError → DatabaseError → DBAPIError → StatementError
                                 → SQLAlchemyError → Exception
issubclass(OperationalError, RuntimeError) = False
psycopg.OperationalError → DatabaseError → Error → Exception（同样不是 RuntimeError）
```

后果（**推断，待 CA-03/CA-04 实证**）：连接在 COMMIT 期间断开（或服务器重启）时，
异常不会被该分支捕获，`_recover_truth` 不会被调用，`commit_ambiguity_count` 不增加；
异常将穿过 `run_cycle`（其只 catch `FencingViolation`）向上抛出，调度器停留在
`CATCHING_UP` 且仍持有租约 —— 既没有 durable-truth 核对，也没有 fail-closed 状态置位。

**判定规则（owner §28）**：只有 CA-03/CA-04 的真实 PG 证据才能确认这是生产缺陷；
确认后记为 `PG-012`，最小修复（把 `sqlalchemy.exc.DBAPIError` 纳入同一 durable-truth
核对与 fail-closed 分支），再加 targeted 复验。**不得**把真实失败改写为 harness 问题。

### AMB-AUDIT-02 — 幂等命中依赖「区间键」，而区间键由 durable 游标派生

`catch_up` 的幂等键是「本次调用计算出的 [cursor, now_real_us]」，其中 cursor 来自
**durable** `world_runtime.last_committed_real_us`。因此：
- 若上一笔已 durable 提交 → 下一次调用的 cursor 已前移 → 生成**不同**区间 →
  不会重复应用（安全），但也不会命中 `committed_for_interval` 的"已提交"分支；
- 「同一操作被重复提交」的精确防线是**区间唯一索引**与 year→interval 的确定性映射。

harness 判定"该操作是否已提交"因此必须同时用：
`current_blessed_tick >= year_end_tick`（世界真值）**与**
`committed_for_interval(...)`（操作真值），二者任一为真即 `ALREADY_COMMITTED`。

### AMB-AUDIT-03 — 阶段 1 与阶段 2 之间存在"已提交的运行行"

进程在阶段 1 之后死亡会留下 `RUNNING` run（durable，但非世界真值）。
恢复路径 `fail_stale_running` 会将其置 `FAILED` 并重做该区间 —— 这是**设计内**行为，
且不产生 duplicate（世界从未推进）。harness 必须区分
`RUNNING_STALE`（重做安全）与 `COMMITTED`（禁止重做），否则会把设计行为误判为重复。

## 5. Harness 设计要求（据本审计）

1. **真实故障模型**：真实 PG 连接（`pg_terminate_backend`）、真实 OS 进程终止、
   真实服务器重启（仅 `blr-pre-m6-postgres` 测试容器）。
2. **不修改生产事务顺序**：worker 通过 `simulate_fn`（生产公开扩展点）注入
   可控延时以扩大故障窗口；**不需要**在生产代码里加 failpoint
   （owner §8 允许的 `AFTER_DATABASE_COMMIT_BEFORE_APPLICATION_ACK` 由 harness
   在**应用确认之前**杀死进程实现——"应用确认"在本架构中即调度器 checkpoint/内存态，
   worker 从不写它）。
3. **BLIND_RETRY_COUNT 可断言**：恢复驱动必须先查 durable truth 再决定是否提交；
   计数器在"未经查询即提交同一操作"时自增（§16）。
4. **不变量检查器**：DUPLICATE_TICKS / DUPLICATE_HISTORY_EVENTS / LOST_TICKS /
   FORKED_HISTORY / STALE_WRITER_MUTATIONS / HISTORY_{ORPHAN_LINKS,CAUSAL_CYCLES,
   INVALID_REFS} + FINAL_HASH_EQUIVALENCE（与无故障 direct 参照比较）。
5. **隔离**：专用合成库（`blr_pg_commit_ambiguity_test`）、world id `PGAMB-*`、
   synthetic fixed seeds；禁止正式 world / 正式 DB / StayOps DB / live。

## 6. 审计结论

```
COMMIT_BOUNDARY_AUDIT      = COMPLETE（唯一权威提交点 = catch_up 阶段 2 / run_atomic_tick；
                             事务边界 = WorldMutationContext.__enter__ / commit；
                             身份与查找键见 §2；M3c/M4 机制在 PG 上可复用，无需第二套协议）
DURABLE_OPERATION_IDENTITY = simulation_run.run_id（确定性 run-id-v1）
DURABLE_BATCH_IDENTITY     = (world_id, simulation_version, interval_start_us, interval_end_us)
RECOVERY_LOOKUP_KEY        = committed_for_interval(...) / committed_until_tick>=target /
                             world_runtime.current_blessed_tick /
                             latest WORLD_COMMITTED checkpoint
POST_COMMIT_IN_MEMORY_STATE = RuntimeScheduler 内存字段 + scheduler_state.json（非真值，不得信任）
AUDIT_FINDINGS             = AMB-AUDIT-01（候选 PG-012：OperationalError 不在歧义分支内）、
                             AMB-AUDIT-02（幂等键 = 区间键，判定需双真值）、
                             AMB-AUDIT-03（阶段 1 RUNNING 残留属设计内，需与 COMMITTED 区分）
NEXT                       = 按 §5 实现真实 PG commit ambiguity harness（CA-01..CA-07）
```

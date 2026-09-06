# DSH_M1_TIME_ENGINE_OFFLINE_CATCHUP_FINAL_REPORT

> 执行方：DSH（Runtime 唯一实现与维护方）。日期：2026-09-06。
> 前置：WORLD_BIBLE v1.0 FROZEN；M0 ACCEPTED；TIME_MODEL_UNIT_BLOCKER RESOLVED；
> WORLD_RUNTIME_STATUS=NOT_ACTIVATED；World Seed=NULL；正式世界业务数据=EMPTY。

---

## 1. Architecture（分层：TIME ENGINE / FENCING / CATCH-UP 互不知道业务）

```
domain/blessed_time.py     tick=µy、TimeRate(整数 tick/µs)、epoch µs 转换（纯数学）
services/time_engine.py    Integrator（同速率进位/跨速率重置）+ rate_at + segment_interval
services/fencing.py        WorldMutationContext —— 统一 Mutation Guard（commit 前重验）
services/writer_lock.py    runtime_lock 租约（acquire 即时提交/CAS 接管/token fencing/renew）
services/run_lifecycle.py  SimulationRunRepository（PENDING→RUNNING→COMMITTED / FAILED）
services/catchup.py        catch_up() 编排：守卫→fence→分段积分→时钟提交→run→checkpoint
services/atomic_tick.py    M0 原子 tick 改造为 fencing 统一入口
database/                  models + 9 migrations + invariants
```

TIME ENGINE 不知道人口系统；CATCH-UP 不知道 NPC；FENCING 不知道灾劫。

## 2. Fencing 实现（services/fencing.py）
- **WorldMutationContext**：进入时 verify+refresh 心跳
  （UPDATE runtime_lock WHERE lease_token=本事务 token AND owner=本 writer
  AND expires_at>now → 延长 expires_at；rowcount≠1 → FENCING_VIOLATION）。
  该写操作立即取得 DB 写锁 → 同一世界同一时刻只有一个 mutation 事务在途。
- **commit() 前 assert_current_fence()**：重读 runtime_lock，token/owner/未过期
  三者必须仍匹配 —— 最终写入授权，不是开始的一次性检查。
- 未显式 commit 或异常 → 回滚（绝不裸提交）。

## 3. Mutation Transaction commit guard
- 覆盖：blessed time advancement / world clock update / simulation run /
  checkpoint / catch-up cursor / 事件写入（run_atomic_tick 与 catch_up 全部经同一 ctx）。
- 跨方言一致性：SQLite 单写者（心跳写锁串行化接管）+ PG 行级 UPDATE 锁等价。
- 被接管的旧 Writer：__enter__ 或 commit() 任一环节失败，零世界状态写入。

## 4. Time Engine（services/time_engine.py）
- 公式（与 M0 量纲一致）：`ticks=(real_us×num+remainder)//den`、
  `remainder=(real_us×num+remainder)%den`；全整数，无 float。
- 同一速率区间保持 remainder（1s×86400 == 1day；24×1h == 1×24h）；
  速率改变 remainder 归零（不跨速率泄漏）。
- 支持任意长 Offline Catch-up（O(n) 整数运算）；空/反向区间为 0；
  无速率 Canon 的时间区间拒绝积分（IntegrityError，不发明历史速率）。

## 5. Rate History segmentation
- time_ratio_history 增加整数真实时间边界 `real_effective_from_us`（epoch µs，
  migration c4a8d2f9b1e7 从 real_effective_from 精确回填）。
- `segment_interval(windows, start, end)`：按窗口边界切分（A→B→C→D 多区间），
  `rate_at()` 解析每段生效速率。catch-up 实测 4 速率历史 = 分段之和，
  禁止用当前速率倒推历史（测试验证整段倒推结果 ≠ 分段结果）。

## 6. Remainder persistence
- `world_runtime.time_rate_remainder`（BigInteger，NOT NULL）+ `current_time_ratio_id`
  绑定速率。catch-up 恢复时：当前生效速率 ≠ 持久化 remainder 所属速率 → 余数作废。
- 实测：1 秒 chunk 后 remainder=49,600,000,000 持久化；"重启"（新 session）后续推
  完整一天，总 delta 与一次整体推进完全一致（1,000,000）。

## 7. Offline Catch-up（services/catchup.py）
- `catch_up(session_factory, *, world_id, now_real_us, writer_id, fencing_token,
  last_real_cursor_us=None, simulation_version=..., simulate_fn=None)`。
- 权威游标 = DB `world_runtime.last_committed_real_us`；调用方游标仅校验/日志
  （陈旧游标不得重复累计，实测第二次只补增量区间）。
- 流程：只读守卫+快照 → fenced 阶段1（清理 stale RUNNING、幂等检查、创建 RUNNING
  run）→ fenced 阶段2（分段积分→时钟提交→TIME_ADVANCE→run COMMITTED→checkpoint）
  → commit 前 fence 重验。
- M1 不生成世界内容：仅 TIME_ADVANCE / CHECKPOINT / SIMULATION_RUN_METADATA。

## 8. Simulation Run lifecycle
- PENDING → RUNNING → COMMITTED；异常 RUNNING → FAILED（仍持有 fence 时 best-effort
  标记；fence 已失则留给接管者 `fail_stale_running` 清理）。
- 幂等身份 = world_id + simulation_version + real_interval_start_us +
  real_interval_end_us；COMMITTED 行受部分唯一索引 DB 层强制
  （migration e6c0f4a1b3d9，sqlite_where/postgresql_where 双实现）。

## 9. Checkpoint schema（migration e6c0f4a1b3d9）
world_id / checkpoint_blessed_tick / last_committed_real_us / rate_id /
rate_remainder / simulation_version / last_committed_run_id / writer_id /
fencing_token / world_state_hash（M1=时钟状态哈希，M2 起换真实世界状态哈希）/
complete / meta / created_at。Crash 后仅依赖 DB 即可恢复。

## 10. Crash Recovery（用例 A–G 全实测）
A 计算前 crash→无变化 ✅｜B 计算后 commit 前 crash→时钟/事件/checkpoint 全回滚、
run FAILED ✅｜C commit 完成客户端误判→retry +0 ✅｜D checkpoint 写入中 crash→
无半 checkpoint ✅｜E 旧 Writer 恢复→fencing 拒绝 ✅｜F 新 Writer 接管→唯一时间线 ✅｜
G stale RUNNING→接管者明确 FAIL 后重试、不重复时间 ✅

## 11. Idempotency
- 双层防线：DB 游标 skip（now<=cursor）+ COMMITTED 区间部分唯一索引
  （同区间第二个 COMMITTED run → IntegrityError；NULL 区间 legacy 行不受影响）。
- 实测：相同区间第一次 +1,000,000，第二次 retry +0，最终世界时间不是 +2,000,000。

## 12. Migration（9 个，全部 Alembic）
0001 建表 / 0002 blessed 整数 / 0003 canonical tick / 0004 显式 UTC / 0005 事件不可变
触发器 / 0006 有理速率 / **0007 c4a8d2f9b1e7**（速率 µs 边界 + 时钟游标/remainder）/
**0008 d5b9e3f0a2c8**（run 区间身份列）/ **0009 e6c0f4a1b3d9**（checkpoint 扩展 +
COMMITTED 区间唯一索引）。downgrade base → upgrade head 全链路实测可逆
（触发器随 upgrade 重建）；正式库迁移前 pre-migration 备份（integrity=ok）；
SQLite 可运行；领域层零 SQLite 私有依赖（PG 兼容契约 §8 已更新 fencing 等价语义）。

## 13. 测试矩阵
**103 tests / 103 PASS**（0 失败、warnings-as-errors 通过）。
- M0 回归全保留：tick 模型（1d=1,000,000 / 3d / 12h / 1h=41,666+rem / 24×1h==1×24h /
  2×1h=83,333 / Rate A+B 分段 / 跨速率不泄漏）✅
- 新增必测：30 天→30,000,000 ✅｜365 天→365,000,000 ✅｜1s×86,400==1day ✅｜
  随机 500 分块==整体 ✅｜4-rate == Fraction oracle（3,750,000）✅｜
  同区间重试 delta=0 ✅｜重启 remainder 等价 ✅
- FENCING F1–F8 全通过（见 §14）；crash A–G；NOT_ACTIVATED 拒绝（正式世界 + 未初始化
  时钟双态）；迁移升降级；run 生命周期；唯一索引；空区间/速率缺口拒绝。

## 14. Fencing 并发实测
F1 有效 token commit PASS ✅｜F2 B 接管后 A commit FAIL（零写入）✅｜F3 租约存活时
第二 writer FAIL ✅｜F4 过期 CAS 接管 PASS ✅｜F5 事务内 token 被替换→commit 前重验
FAIL（整事务回滚）✅｜F6 stale 写 checkpoint FAIL ✅｜F7 stale 写 run 终态 FAIL、
B 清理 stale RUNNING ✅｜F8 双 writer：A stale 重试被拒、B 推进一次、B 重试 skip、
最终 blessed time 只增加一次 ✅

## 15. Restart / offline 实测
- 24×1h 分块（每次全新 session 模拟重启）== 一次整体推进 1,000,000 ✅
- remainder 跨重启从 DB 恢复（49,600,000,000）且终值一致 ✅
- 关闭 30 天/365 天自然态恢复推进精确 ✅
- 陈旧调用方游标不得重复累计（增量区间实测）✅

## 16. 正式 DB 空状态审计（迁移后实测）
integrity=ok｜WAL｜head=e6c0f4a1b3d9｜不可变触发器在位｜
persons=0、population=0、settlements=0、resources=0、world_events=0（业务事件）、
tribulations=0、simulation_run=0、simulation_checkpoints=0、runtime_lock=0、
timeline=0、其余业务表全 0｜schema_version=e6c0f4a1b3d9｜
rate history 仅 1 行自然态（1,000,000/86,400,000,000，blessed_effective_from_tick=NULL）。

## 17. World Seed 状态
**NOT_ACTIVATED**（world_seed_version=NULL、current_blessed_tick=NULL、
last_committed_real_us=NULL）。M1 全程未推进、未激活正式世界；测试全部使用
tmp 临时库 + ACTIVE_FOR_TEST 测试世界。

## 18. Canon 修改情况
**无。** World Bible 零改动；「现实约 1 天 ≈ 福地约 1 年」未修改；
无 float rate truth；无当前速率倒推历史；未生成任何人口/NPC/聚落/资源/生态/
社会事件/灾劫/正式历史；未接 AstrBot/LLM。

## 19. 已知风险
1. PG 从未实跑：fencing 等价性、partial unique index、migrations from 0 需按契约
   §6 实跑验证（Activation 前）。
2. SQLite 下 mutation 事务期间接管方会阻塞至 busy_timeout（30s）：mutation 事务必须
   保持短小（M1 catch-up 满足）；超长事务需显式 renew。
3. `world_state_hash` 目前是时钟状态哈希；M2 引入真实世界状态哈希时需迁移语义。
4. 强 fencing 的跨方言等价（SQLite 写锁 vs PG 行锁）依赖契约 §8 语义，未在多机实跑。
5. 部分唯一索引覆盖 COMMITTED 行；RUNNING 行的并发清理依赖接管流程（已测）。

## 20. Git commit SHA
```
<M1 commit>  DSH M1 time engine & offline catch-up: fencing mutation guard, …
717fd76      DSH M0 TIME_MODEL_UNIT_BLOCKER fix: dimensional rational time rate
0e49a94      docs: finalize QA report commit references
a135942      DSH M0 independent QA: canonical blessed tick, aware UTC, …
127523f      M0 Foundation: prior-agent delivery baseline for DSH independent QA
```

## 21. 工作区 clean 状态
`git status` = clean（world.db/backups/*.db/pycache 由 .gitignore 排除）。

## 验收标准逐项
[PASS] Fencing commit-time enforcement｜[PASS] Single Writer｜[PASS] Integer Rational
Time｜[PASS] Same-rate remainder continuity｜[PASS] Cross-rate remainder reset｜
[PASS] Historical segmented integration｜[PASS] Offline Catch-up｜[PASS] Idempotent
Retry｜[PASS] Crash Recovery｜[PASS] Persistent Checkpoint｜[PASS] Restart equivalence｜
[PASS] Formal DB untouched｜[PASS] World Seed NOT_ACTIVATED｜[PASS] No dynamic world
content generated｜[PASS] M0 regression suite｜[PASS] Full test suite（103/103）

---

```
M1_TIME_ENGINE_READY
```

（完成后停止，不进入 M2。）

# M6A.1 ZERO-ROW ENTRY ADDENDUM

> 独立 addendum 文件（原报告 `reports/M6_ACTIVATION_IMPLEMENTATION_REPORT.md` **未改写**；
> 待新的执行预算时按 §23 以 in-place 追加方式并入主报告，内容与本文件一致）。

## 1. 覆盖缺口（COVERAGE_GAP_DISCOVERED = TRUE）

- 原 M6A **77 项** activation 测试全部经 `tests/conftest.py::m6_world` →
  `tests/m6_activation_support.py::seed_m6_world` 运行，该 fixture **预先**执行
  `RuntimeRepository.create_not_activated(...)`（`m6_activation_support.py:55,77`）与
  `TimeRatioRepository.add(...)`（`:58,80`）。
- 因此原套件**从未**覆盖 canonical zero-row 入口
  （`tests/formal_db.py:4-13` 的 canonical 契约：`world_runtime` **0 行** == 世界从未激活，
  且明文禁止为了测试方便插入 NOT_ACTIVATED 行）。

## 2. 缺口如何被发现

`M6C.1D` real activation rehearsal（临时 file-backed SQLite + synthetic seed + 无 scheduler
+ 无第二写者 → 直接调用 `activate_formal_world()`）首次暴露 blocker：
`WriterLease.acquire()` → `WriterLockConflict("租约竞争：锁定行在竞争期间消失")` →
`ActivationRefused`。RED 由 `tests/test_m6a1_zero_row_activation.py` 固化。

## 3. 根因

1. `WriterLease` 使用**独立 session / 独立事务**（`services/activation/service.py:308-312`），
   在零行状态下 `RuntimeLock` 的 `world_id` 外键无父行 → INSERT 失败 →
   `writer_lock.py:100-107` 一律报成"竞争期间消失"（错误分类缺失）。
2. activation 事务体（`service.py:339-347`）假定 `world_runtime` 行已存在
   （`RuntimeRepository.activate()` 是 UPDATE 语义）。
3. `service.py:249-251` 硬性要求 `time_ratio_history` 已由外部预播种 →
   initial rate binding **实现缺口**（与 M6A 报告宣称的 atomic fields 不符）。

## 4. 修复（commit `aebc9dc`）

- `services/activation/service.py`：新增 canonical zero-row 分支 —— 同一 authoritative
  事务内先建立 **transient** `world_runtime` 父行（未提交 → 其它连接不可见 →
  `TRANSIENT_RUNTIME_ROW_DURABLE_PRE_COMMIT = FALSE`）→ 同一 session
  `WriterLease.acquire(commit=False)` → 事务内 `_seed_canonical_initial_rate()`
  建立 canonical initial rate binding（M1 自然态倍率 `1_000_000/86_400_000_000`，未 invent）。
  legacy 已存在世界行的路径逐字未改。
- `services/writer_lock.py`：`acquire(*, commit: bool = True)`（默认 True 保持既有调用方；
  `commit=False` 把提交权交给调用方事务）＋ IntegrityError 分类
  `LOCK_PARENT_WORLD_ABSENT` / `TRUE_CONCURRENT_LOCK_RACE`。
- `tests/test_m6_activation_contract.py::test_m6ac06…`（原 `test_m6ac09_refuses_without_metadata`）
  编码的正是 CONTRACT_IMPLEMENTATION_DRIFT，已按新契约改写为
  "zero-row → 原子 bootstrap → ACTIVE"。

## 5. Transactional Activation Claim + transaction-scoped Fence（owner protocol C）

- **CLAIM** = activation 事务内**未提交**的 `world_runtime(world_id)` 唯一插入。
- **FENCE** = 仅 claim 持有者可达 `WriterLease.acquire(commit=False)`。
- 后续 rate binding / seed truth / ACTIVE+tick0+anchor / genesis / commit 全部在同一事务。

## 6. SQLite 并发证据（`tests/test_m6a1f_claim_fencing.py`）

```
SQLITE_CONCURRENCY_ITERATIONS = 20（每轮两个独立 engine/连接，同一 file-backed DB，真 zero-row）
SQLITE_CLAIM_WINNERS_MAX = 1     SQLITE_FENCE_WINNERS_MAX = 1     SQLITE_COMMIT_WINNERS_MAX = 1
CAN_TWO_ACTIVATORS_BOTH_PASS_ACTIVATION_CLAIM = FALSE（20/20）
CAN_TWO_ACTIVATORS_BOTH_ACQUIRE_VALID_ACTIVATION_FENCE = FALSE（20/20）
CLAIM_ROLLBACK_TAKEOVER = PASS   FENCE_REQUIRED_AFTER_CLAIM = PASS
ACTIVATION_FENCING_CORRECTNESS = PASS
```

## 7. Crash matrix / 资源泄漏（`tests/test_m6a1c_zero_row_crash_matrix.py`）

C0/C1/C2/C3/C5/C6/C7 每个注入点：durable state 全 0（无 partial），且**新连接可立即写入**
（证明 session 已 rollback+close、SQLite 写锁已释放），随后同一 DB 仍可正常激活。

**本轮发现并修复的真实缺陷**：零行 bootstrap 块（`service.py` step 3）最初没有 fault-path
cleanup —— claim 后、commit 前发生 fault 时 SQLite 写锁被持有到进程结束；同一进程内第二个
activator 会得到 `OperationalError` 而非 canonical 结果。按 owner §11 授权作最小修复
（`_close_quietly()` + `except BaseException: rollback+close; raise`），未改变正常路径语义。

C8/ACK-lost：`read_activation_truth` 判 `COMMITTED`，重复调用得 `ALREADY_COMMITTED`，
状态零变更（`ACK_LOST_RECONCILIATION = PASS`，`BLIND_ACTIVATION_RETRY_COUNT = 0`）。
Restart equivalence 与 scheduler 三态（DORMANT / DORMANT / VALID）亦在本模块内实测。

## 8. PostgreSQL 证据 = PASS（既有 test venv，未安装任何包）

环境：`%TEMP%\blr-pre-m6-pg-venv`（Python 3.11.9，**psycopg 3.3.5** + psycopg_binary 3.3.5，
SQLAlchemy 2.0.52，pytest 9.1.1）；容器 `blr-pre-m6-postgres`（PostgreSQL 16.15 @127.0.0.1:55432）。
未安装任何包、未改 live venv、未借用其它项目 psycopg2、**未触碰 stayops-postgres**。

```
PG_SINGLE_WRITER_REGRESSION   = PASS   PG_FENCING_REGRESSION        = PASS
PG_LEASE_TAKEOVER_REGRESSION  = PASS   PG_STALE_WRITER_REGRESSION   = PASS
PG_SHARED_WRITER_LOCK_GATES   = PASS（4/4：single writer exclusive+renew /
                              single writer concurrent two connections /
                              lease expiry takeover / stale writer mutations rejected）
   → writer_lock.py 的 commit=False 新增未改变默认 commit=True 语义。

PG_AMBIGUITY_REGRESSION = PASS（tests/test_pg_commit_ambiguity_gate.py 9/9，exit code 0）
PG012_PRESENT = TRUE        PG_BLIND_RETRY_COUNT = 0

M6_FORMAL_ACTIVATION_POSTGRES_SUPPORTED = TRUE
   evidence：services/activation/service.py 与 services/writer_lock.py 无任何 dialect/PostgreSQL
   分支（`postgres|dialect` 命中 0）→ activation 为 SQLAlchemy 层方言无关实现，必须真跑 PG 并发。
PG_ZERO_ROW_CONCURRENCY = PASS（tests/test_m6a1pg_zero_row_concurrency.py：fresh PG test DB、
   真 canonical zero-row、**两个真实 OS 进程**同时激活）
   PG_CLAIM_WINNERS_MAX = 1   PG_FENCE_WINNERS_MAX = 1   PG_COMMIT_WINNERS_MAX = 1
   最终 world_runtime = 1 / time_ratio_history = 1 / genesis = 1 / runtime_lock <= 1
   PG_LOSER_FENCES = 0（落败方从未取得 fence）
   PG_LOSER_OUTCOME = IntegrityError（psycopg.errors.UniqueViolation: duplicate key world_runtime）
     ⚠ 记录用事实（未改设计）：PG 在 **claim 阶段**以 unique violation 阻断落败方，
       不会出现双方同时持有 fence；但落败方拿到的是**未分类的原始 IntegrityError**，
       而非 SQLite 侧的 canonical 拒绝 / ALREADY_COMMITTED。属待 Owner 裁决的分类差距。
```

> 早期本 addendum 曾记录 "PostgreSQL 证据 = 缺失（环境阻塞，psycopg3 不可得 / PyPI 403）"；
> 该结论基于主解释器。随后按 owner 指引找到既有 test-only venv 并完成上述真实 PG gate，
> 本节为**更新后的权威记录**（旧描述在此更正，历史不改写）。

## 9. Fast regression

post-fix canonical fast regression 已启动（`pytest tests -q --ignore=tests/test_m3_integrated_long.py`，
后台 job）；本会话结束前未完成 → 结果待补，不声称 PASS。

## 10. Formal DB

PRE 与 POST 均实测 `AUTHORITATIVE_DB_RESOLUTION = PASS`，
`FORMAL_DB_SHA256 = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837`（PRE == POST），
`world_runtime = 0`，`NOT_ACTIVATED`，seed 未消费；legacy stale DB 继续 NON_AUTHORITATIVE。

## 11. 相关 commit

```
aebc9dc  fix (含 test): canonical zero-row activation entry —— 见 §24 的 git 偏差记录
aeef082  test: prove zero-row activation claim-before-fence (M6A.1F)
（本轮）test/fix: zero-row crash matrix + fault-path session cleanup
```

## 12. FAST REGRESSION CLOSEOUT（M6A.1F 收口，append-only）

命令（后台 job `pwsh-20`，post-fix HEAD）：

```
pytest tests -q -p no:randomly --ignore=tests/test_m3_integrated_long.py
log: %TEMP%\m6a1f_fast_regression_postfix.txt
```

```
EXIT_CODE              = 0
FAST_COLLECTED         = 1024
FAST_PASSED            = 983
FAST_EXPECTED_SKIPS    = 41（按设计：12 × BLR_FORMAL_DB_PATH 正式库守护 + 29 × BLR_TEST_PG_DSN
                          PG gated 套件；与既有 canonical 基线口径一致）
FAST_FAILED            = 0
FAST_ERRORS            = 0
FAST_UNEXPECTED_SKIPS  = 0
进步曲线               = 7% → … → 91% → 98% → 100%（进度标记逐字节统计，无 F/E/x 标记）
重型用例（本轮实测耗时，供后续排程参考）：
  test_scheduler_budget_equivalence 1000y 系列（_0…_6，各约 10–15 分钟）
  test_scheduler_5000y_endurance（约 50 分钟以上）
  m3b_audit3000
```

collected 由历史 906 增至 **1024**（+118）：M6A.1 zero-row 4 + M6A.1F claim/fencing 22 +
M6A.1b concurrency 2 + M6A.1c crash matrix 10 + M6A.1PG zero-row concurrency 1 +
既有调整后的总数变化。**未更新任何 Golden Baseline**
（`git diff --numstat HEAD -- tests/baselines` = 0 行）。

### 最终 formal DB 复核（收口时实测）

```
FORMAL_DB_AUTHORITY_FINAL  = PASS
FORMAL_DB_SHA256_FINAL     = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837
FORMAL_WORLD_RUNTIME_ROWS  = 0
CURRENT_BLESSED_TICK       = NULL
FORMAL_WORLD_STATUS        = NOT_ACTIVATED
FORMAL_WORLD_SEED_CONSUMED = FALSE
GOLDEN_BASELINE_MUTATIONS  = 0
FORMAL_WORLD_UNTOUCHED     = TRUE
```

### 判定

```
M6A_ZERO_ROW_ENTRY_REPAIRED = TRUE
  （ZERO_ROW_ACTIVATION / ROLLBACK / ACTIVATION_CLAIM_PROTOCOL / FENCING_CORRECTNESS /
    CLAIM_ROLLBACK_TAKEOVER / CRASH_MATRIX_ZERO_ROW / SESSION_CLEANUP_ON_ALL_FAULT_PATHS /
    ACK_LOST_RECONCILIATION / BLIND_RETRY=0 / RATE_BINDING_ATOMIC + RESTART_EQUIVALENCE /
    SECOND_ACTIVATION_IDEMPOTENT / SCHEDULER_REGRESSION / PG_SHARED_WRITER_LOCK_GATES /
    PG_AMBIGUITY_REGRESSION(PG012_PRESENT) / PG_ZERO_ROW_CONCURRENCY / FAST_REGRESSION /
    GOLDEN_BASELINE_MUTATIONS=0 / FORMAL_WORLD_UNTOUCHED —— 全部 PASS）
PG_LOSER_ERROR_NORMALIZATION = DEFERRED_NON_SAFETY_TECH_DEBT（Owner 裁决；不阻塞本 Gate）
```

NEXT_ACTION = RESUME_M6C1D_RESOURCE_ECOLOGY_VERIFICATION
（FORMAL_ACTIVATION_ALLOWED = FALSE；MATERIALIZER_ALLOWED = FALSE）

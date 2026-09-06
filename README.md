# XiaoguangBlessedLandRuntime

Blessed Land Runtime —— 小光福地世界运行内核（M0 Foundation + M1 Time Engine & Offline Catch-up）。
架构：Knowledge/World Bible → **Runtime** → World Database → AstrBot Adapter（ASTRBOT != WORLD）。

## 状态（DSH M1 完成后）

```
WORLD_BIBLE = v1.0 FROZEN（18 文件 MANIFEST SHA256 复算一致）
RUNTIME_PROJECT = CREATED        （本目录，git 由 DSH 接管）
DATABASE_SCHEMA = CREATED        （20 表, alembic 9 个 migration）
WORLD_DATABASE = EMPTY           （业务表 0 行）
WORLD_SEED = NOT_ACTIVATED
CURRENT_BLESSED_TICK = NULL
OFFICIAL_POPULATION / HISTORY_EVENTS / NPCS / TRIBULATIONS = 0
```

## 快速开始

```bash
pip install sqlalchemy alembic pytest   # 依赖见 pyproject.toml
python scripts/init_db.py               # migrate to head + seed 版本元数据（NOT_ACTIVATED）
python -m pytest tests/                 # 103 tests
python scripts/backup_now.py            # 手动备份（--pre-migration 为迁移前备份）
```

## 目录

- `database/`：SQLAlchemy 2.x 模型（20 表）+ Alembic migrations（0001 建表 / 0002 blessed 整数 /
  0003 canonical blessed tick / 0004 显式 ISO-8601 UTC / 0005 事件不可变触发器 /
  0006 有理时间速率 / 0007 M1 时钟+速率整数边界 / 0008 run 区间身份 /
  0009 checkpoint 扩展+COMMITTED 区间唯一索引）+ `invariants.py`（DB 不变量校验）
- `domain/`：常量、错误分类（10 类 code）、版本锁与 Bible 指纹校验、`blessed_time.py`
  （CANONICAL_BLESSED_TICK + TimeRate + epoch µs 转换）
- `services/`：guard（WORLD_NOT_ACTIVATED + 受保护事件入口）、writer_lock（单写者租约 +
  STALE_WRITER_RECOVERY）、**fencing（WorldMutationContext 统一 Mutation Guard）**、
  **time_engine（Integrator + 速率分段）**、**catchup（Offline Catch-up 编排）**、
  **run_lifecycle（Simulation Run 生命周期）**、atomic_tick（fencing 统一入口）、
  time_service（aware UTC/时钟异常/分段积分）、rng_service（确定性独立流）、
  backup_service（在线备份 + 安全恢复）、repositories（只追加事件库 + correction）、
  bible_integrity
- `scripts/`：init_db（migrate+seed 幂等 + schema_version 校正 + 不变量校验）、backup_now
- `tests/`：103 项（迁移/事务/原子tick/单写者/stale recovery/FENCING F1-F8/RNG/备份恢复/
  守卫/纠错/tick/UTC/catch-up/crash A-G/幂等/生命周期）
- `POSTGRESQL_COMPATIBILITY_CONTRACT.md`：跨方言约束契约

## 设计要点（DSH M0 独立 QA 修正后）

- **时间坐标（CANONICAL_BLESSED_TICK）**：世界时间 = 整数 canonical tick，
  1 tick = 1 micro-blessed-year（µy，1e-6 福地年）。年/月/日只是 projection；
  禁止浮点累计世界时间（纯整数运算）。历法 Canon 未定义前不发明月/日/纪年制度。
- **时间速率（有量纲有理速率）**：自然态 = `1,000,000 ticks / 86,400,000,000 µs`
  （现实 1 天 → 福地 1 年，Bible WS-0201；"约 365 倍"仅是派生展示语）。
  DB 存 INTEGER rate_numerator/rate_denominator，禁止 float 倍率真值；
  换算公式 `ticks = (µ_real × num) // den`（floor）；同一速率连续分段共享余数进位
  （24×1h == 1×24h，无累计 drift）。
- **现实时间**：应用层 aware UTC；DB 层显式 ISO-8601 UTC（SQLite 带 +00:00 后缀，
  PG 原生 TIMESTAMPTZ）；不依赖机器本地时区、不受 DST 影响。
- **速率历史**：来自 time_ratio_history（effective-dated）；离线补算必须按 effective
  interval 分段积分，禁止拿当前速率倒推历史。
- **事件**：world_events 只追加，DB 触发器禁 UPDATE/DELETE（非代码约定）；
  纠错=新事件（supersedes/reverses + correction_reason）。
- **世界推进**：必须先激活（runtime_status=ACTIVE 且 world_seed 生效），
  否则 WORLD_NOT_ACTIVATED 拒绝 advance/simulate/catchup/create_event；
  创建 metadata / time rule ≠ 激活。
- **单写者 + FENCING（M1 硬门槛已实现）**：runtime_lock 租约（acquire 即时提交、owner
  identity、token fencing、renew）；所有 World State Mutation Transaction 必须经
  `WorldMutationContext`——进入时 verify+refresh 心跳（即取写锁），COMMIT 前再次
  assert_current_fence()（DB 中 token 必须仍等于本事务 token）。被接管的旧 Writer
  即使恢复执行也不得提交任何世界状态。崩溃/重启后过期租约自动接管
  （STALE_WRITER_RECOVERY），世界不会永久锁死。
- **时间推进（M1 Time Engine + Offline Catch-up）**：`catch_up()` 按
  time_ratio_history 的真实时间整数边界分段积分（A→B→C→D 多区间），remainder 持久化
  于 world_runtime（重启后从 DB 恢复，结果与不重启一致）；权威现实游标在 DB
  （陈旧调用方游标不会重复累计区间）；tick 与游标单调；Simulation Run 生命周期
  PENDING→RUNNING→COMMITTED（异常 FAILED），同区间幂等（游标 skip + COMMITTED 区间
  唯一索引双防线）；每次提交写持久化 checkpoint（crash 后仅依赖 DB 恢复）。
  M1 不生成任何世界内容（仅 TIME_ADVANCE/CHECKPOINT/RUN_METADATA 基础设施记录）。
- **幂等**：TICK_IDENTITY = world_id + simulation_version + status=COMMITTED +
  committed_until_tick；旧 simulation_version 不阻止新版推进；失败事务不推进 committed。
- **RNG**：每子系统独立流（seed=sha256(world, sim_version, period_tick, subsystem, scope)）；
  子系统/实体/simulation version/world 四重隔离。

## 约束

- M0 之后未经批准不得推进世界（M1+ 待 RUNTIME_ARCHITECTURE_REVIEW 后逐里程碑进行）。
- 禁止把 DB 当第二套 Bible：Bible 内容由 knowledge 层管理，DB 只存版本+manifest hash。

## M1 之后的硬性门禁（World Seed Activation 前必须 PASS）

1. **FENCING_TOKEN**：已实现（M1）；Activation 前复审跨方言语义（PG for_update 等价性）。
2. PG 实跑清单（POSTGRESQL_COMPATIBILITY_CONTRACT.md §6）。
3. SQLite batch 重建 world_events 后必须重新应用不可变触发器（invariants 校验兜底）。
4. M1 不得生成任何世界内容；正式世界推进必须等 World Seed Activation（M2+）。

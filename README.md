# XiaoguangBlessedLandRuntime

Blessed Land Runtime —— 小光福地世界运行内核（M0 Foundation, PHASE_1_9_1 + DSH M0 独立 QA）。
架构：Knowledge/World Bible → **Runtime** → World Database → AstrBot Adapter（ASTRBOT != WORLD）。

## 状态（DSH M0 独立 QA 完成后）

```
WORLD_BIBLE = v1.0 FROZEN（18 文件 MANIFEST SHA256 复算一致）
RUNTIME_PROJECT = CREATED        （本目录，git 由 DSH 接管）
DATABASE_SCHEMA = CREATED        （20 表, alembic 6 个 migration）
WORLD_DATABASE = EMPTY           （业务表 0 行）
WORLD_SEED = NOT_ACTIVATED
CURRENT_BLESSED_TICK = NULL
OFFICIAL_POPULATION / HISTORY_EVENTS / NPCS / TRIBULATIONS = 0
```

## 快速开始

```bash
pip install sqlalchemy alembic pytest   # 依赖见 pyproject.toml
python scripts/init_db.py               # migrate to head + seed 版本元数据（NOT_ACTIVATED）
python -m pytest tests/                 # 65 tests
python scripts/backup_now.py            # 手动备份（--pre-migration 为迁移前备份）
```

## 目录

- `database/`：SQLAlchemy 2.x 模型（20 表）+ Alembic migrations（0001 建表 / 0002 blessed 整数 /
  0003 canonical blessed tick / 0004 显式 ISO-8601 UTC / 0005 事件不可变触发器 /
  0006 有理时间速率）+ `invariants.py`（DB 不变量校验）
- `domain/`：常量、错误分类（9 类 code）、版本锁与 Bible 指纹校验、`blessed_time.py`
  （CANONICAL_BLESSED_TICK 定义与换算）
- `services/`：guard（WORLD_NOT_ACTIVATED + 受保护事件入口）、writer_lock（单写者租约 +
  STALE_WRITER_RECOVERY）、atomic_tick（版本化幂等 + 事务 + 激活校验）、
  time_service（aware UTC/时钟异常/ratio 分段积分）、rng_service（确定性独立流）、
  backup_service（在线备份 + 安全恢复）、repositories（只追加事件库 + correction）、
  bible_integrity
- `scripts/`：init_db（migrate+seed 幂等 + schema_version 校正 + 不变量校验）、backup_now
- `tests/`：65 项（迁移/事务/原子tick/单写者/stale recovery/RNG/备份恢复/守卫/纠错/tick/UTC）
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
- **单写者**：runtime_lock 租约（acquire 即时提交、owner identity、token fencing、
  renew）；崩溃/重启后过期租约自动接管（STALE_WRITER_RECOVERY），世界不会永久锁死。
- **幂等**：TICK_IDENTITY = world_id + simulation_version + status=COMMITTED +
  committed_until_tick；旧 simulation_version 不阻止新版推进；失败事务不推进 committed。
- **RNG**：每子系统独立流（seed=sha256(world, sim_version, period_tick, subsystem, scope)）；
  子系统/实体/simulation version/world 四重隔离。

## 约束

- M0 之后未经批准不得推进世界（M1+ 待 RUNTIME_ARCHITECTURE_REVIEW 后逐里程碑进行）。
- 禁止把 DB 当第二套 Bible：Bible 内容由 knowledge 层管理，DB 只存版本+manifest hash。

## M1 硬性门禁（World Seed Activation 前必须 PASS）

1. **FENCING_TOKEN（强 fencing）**：M1 所有世界 Mutation Transaction 在提交前必须
   校验当前 fencing token（租约持有者身份）；旧 Writer 在 lease 失效并被新 Writer
   接管以后，即使恢复执行也**不得提交任何世界状态**。
2. PG 实跑清单（POSTGRESQL_COMPATIBILITY_CONTRACT.md §6）。
3. SQLite batch 重建 world_events 后必须重新应用不可变触发器（invariants 校验兜底）。

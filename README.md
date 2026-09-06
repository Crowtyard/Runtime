# XiaoguangBlessedLandRuntime

Blessed Land Runtime —— 小光福地世界运行内核（M0 Foundation, PHASE_1_9_1）。
架构：Knowledge/World Bible → **Runtime** → World Database → AstrBot Adapter（ASTRBOT != WORLD）。

## 状态（M0 完成时）

```
WORLD_BIBLE = v1.0 FROZEN
RUNTIME_PROJECT = CREATED        （本目录）
DATABASE_SCHEMA = CREATED        （20 表, alembic 2 个 migration）
WORLD_DATABASE = EMPTY           （业务表 0 行）
WORLD_SEED = NOT_ACTIVATED
CURRENT_BLESSED_TIME = NULL
OFFICIAL_POPULATION / HISTORY_EVENTS / NPCS / TRIBULATIONS = 0
```

## 快速开始

```bash
pip install -r requirements.txt      # 或 pip install sqlalchemy alembic pytest
python scripts/init_db.py            # migrate to head + seed 版本元数据（NOT_ACTIVATED）
python -m pytest tests/              # 23 tests（迁移/事务/原子tick/单写者/RNG/备份/守卫/纠错）
python scripts/backup_now.py         # 手动备份（可选；测试已覆盖）
```

## 目录

- `database/`：SQLAlchemy 2.x 模型（20 表）+ Alembic migrations（0001 建表 / 0002 blessed 整数刻度）
- `domain/`：常量、错误分类（9 类 code）、版本锁与 Bible 指纹校验
- `services/`：guard（WORLD_NOT_ACTIVATED）、writer_lock（单写者租约）、atomic_tick（幂等+事务）、
  time_service（UTC/时钟异常/ratio 分段）、rng_service（确定性独立流）、backup_service（在线备份）、
  repositories（只追加事件库 + correction）、bible_integrity
- `scripts/`：init_db（migrate+seed 幂等）、backup_now
- `tests/`：23 项（覆盖 PHASE_1_9 §三十 全部 13 类要求）
- `POSTGRESQL_COMPATIBILITY_CONTRACT.md`：跨方言约束契约

## 设计要点（详见各模块 docstring 与 runtime_design/ 文档）

- 时间：DB 层统一 naive UTC；blessed 时间=整数福地年；ratio 来自 time_ratio_history（effective-dated，禁硬编码）
- 事件：world_events 只追加；纠错=新事件（supersedes/reverses/correction_reason）
- 世界推进：必须先激活（runtime_status=ACTIVE 且 world_seed 生效），否则 WorldNotActivated 拒绝
- RNG：每子系统独立流（seed=sha256(world, sim_version, period, subsystem, scope)）

## 约束

- M0 之后未经批准不得推进世界（M1+ 待 RUNTIME_ARCHITECTURE_REVIEW 后逐里程碑进行）。
- 禁止把 DB 当第二套 Bible：Bible 内容由 knowledge 层管理，DB 只存版本+manifest hash。

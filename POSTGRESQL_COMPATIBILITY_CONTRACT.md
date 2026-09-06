# POSTGRESQL_COMPATIBILITY_CONTRACT（M0 · 2026-09-06 · DSH QA 修订）

> 目的：确保未来 SQLite → PostgreSQL 迁移不需要重写 Domain Layer（PHASE_1_9 §五 修正口径：
> 正式定义为 POSTGRESQL_MIGRATION_READY，不是"换一行配置"）。

## 1. 允许使用（跨方言安全）
- SQLAlchemy 2.x ORM 标准能力：Mapped 声明、session/query、relationship（少用）、
  类型：Integer/String/Text/Boolean/DateTime(timezone)/JSON/BigInteger（canonical blessed tick）。
- Alembic migrations（batch_alter 仅用于 SQLite 回迁路径；PG 上 batch 直通原生 ALTER）。
- Repository 模式：业务只经 services/repositories.py 访问。
- 通用 SQL：SELECT/INSERT/UPDATE/DELETE、WHERE、ORDER BY、LIMIT、JOIN、递归 CTE（M3 因果链）
  ——均为跨方言标准。

## 2. 禁止进入 Domain Logic（SQLite 私有）
- PRAGMA（journal_mode/foreign_keys/busy_timeout）→ 只允许出现在 database/db.py 的引擎工厂
  （URL 前缀分流），业务层禁止。
- sqlite3 直连 API（除 services/backup_service.py 的在线备份/恢复路径，且该路径按 URL 分支，
  PG 下换 pg 备份实现；integrity_check 同样只服务 SQLite）。
- 字符串拼接 SQL / f-string SQL（一律 text()/参数绑定或 ORM）。
- 依赖 SQLite 隐式行为的类型（如 BOOLEAN→INTEGER 隐转、无 CHECK 依赖）。
- SQLite 专用函数（date()/julianday()/FTS5 等）禁止进入 ORM 查询表达式；
  时间换算在应用层 time_service / domain.blessed_time 完成。

## 3. 时间列（M0 DSH QA 修正后 + M1）
- blessed 时间坐标：CANONICAL_BLESSED_TICK，一律 BigInteger（SQLite 64-bit INTEGER /
  PostgreSQL BIGINT）；不用 Integer（32-bit 会在 ~2147 福地年溢出）。年/月/日为投影。
- 时间速率：time_ratio_history 的有量纲有理速率，rate_numerator/rate_denominator
  一律 BigInteger（tick / real µs）；禁止 float 倍率；换算在应用层
  domain/blessed_time.py（纯整数）。
- M1 现实时间游标/边界：last_committed_real_us / real_effective_from_us /
  real_interval_*_us 一律 BigInteger（epoch µs）；跨方言整数语义一致。
- 现实时间：database/base.py 的 UtcDateTime TypeDecorator（impl=DateTime(timezone=True)）：
  应用层 aware UTC；SQLite 落显式 ISO-8601（+00:00）文本；PG 落 TIMESTAMPTZ。
  naive 输入按 UTC 解释（与旧数据兼容）。

## 4. 事件不可变（DB 触发器）
- world_events 禁 UPDATE/DELETE 由 DB 触发器强制（migration b2d4e8f9a6c3）：
  SQLite BEFORE UPDATE/DELETE → RAISE(ABORT)；PG BEFORE UPDATE OR DELETE → RAISE EXCEPTION。
- database/invariants.py::verify_event_immutability 校验触发器在位（init_db 启动校验）。
- SQLite 注意：Alembic batch_alter_table 重建 world_events 会丢失触发器 ——
  未来任何对 world_events 的 batch 结构变更后必须重新应用触发器。

## 5. JSON 列
- ORM 统一用 sqlalchemy.JSON()；PG 落 jsonb 时可经类型注解切换，业务不感知。
- 禁止在 SQL 内对 JSON 做方言专用查询（如 PG jsonb_path）；JSON 读取在应用层过滤。

## 6. 未来 PG 实跑需验证清单
1. migrations 在 PG 上从 0 upgrade head（同一 migration 文件集；0003 的 rename+BigInteger、
   0004 的触发器分支必须在 PG 生效；0004 的 SQLite 数据修正对 PG 为 no-op）。
2. 全测试套件在 PG 上运行（需 PG compatibility tests；M0 不部署）。
3. 时间列语义（aware UTC / TIMESTAMPTZ）一致；backup_service 切换为 PG 备份实现并过
   integrity/restore 测试。
4. SINGLE_WORLD_WRITER：PG 下租约表行级语义相同（PK 冲突 + 过期 CAS UPDATE 同语义）。
5. 布尔/JSON 往返、递归 CTE 因果链查询结果一致。

## 7. 已落实的隔离点
- database/db.py：URL 前缀（sqlite）驱动 PRAGMA；PG 分支仅调整 connect 参数。
- config/settings：database_url 单一入口；BLR_DATABASE_URL 覆盖。
- services/repositories.py：全部 ORM 访问；EventRepository 无 update/delete。
- services/time_service.py + domain/blessed_time.py：时间换算在应用层（不依赖 DB 时间函数）。
- database/invariants.py：跨方言触发器在位校验。

## 8. Fencing 与 M1 硬性门禁
1. FENCING_TOKEN（M1 已实现）：所有世界 Mutation Transaction 经
   services/fencing.py::WorldMutationContext —— 进入时 verify+refresh 心跳
   （UPDATE runtime_lock WHERE token/owner/未过期 → 延长 expires_at；该写操作即取
   写锁）；COMMIT 前 assert_current_fence() 重验。SQLite：写锁使接管 UPDATE 串行化
   （不依赖 PG 行锁）；PG：同一行 UPDATE 行锁语义等价。被接管的旧 Writer 不得提交
   任何世界状态。
2. COMMITTED 区间唯一索引（migration e6c0f4a1b3d9）：partial unique index 同时提供
   sqlite_where 与 postgresql_where（status='COMMITTED'）；NULL 区间行不受影响。
3. PG 实跑清单 §6 全部通过（World Seed Activation 前）。
4. 未来对 world_events 的任何 batch 结构变更后必须重新应用不可变触发器。

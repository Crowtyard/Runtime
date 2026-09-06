# POSTGRESQL_COMPATIBILITY_CONTRACT（M0 · 2026-09-06）

> 目的：确保未来 SQLite → PostgreSQL 迁移不需要重写 Domain Layer（PHASE_1_9 §五 修正口径：
> 正式定义为 POSTGRESQL_MIGRATION_READY，不是"换一行配置"）。

## 1. 允许使用（跨方言安全）
- SQLAlchemy 2.x ORM 标准能力：Mapped 声明、session/query、relationship（少用）、类型：Integer/String/Text/Boolean/DateTime(timezone)/JSON/Enum。
- Alembic migrations（batch_alter 仅用于 SQLite 回迁路径）。
- Repository 模式：业务只经 services/repositories.py 访问。
- 通用 SQL：SELECT/INSERT/UPDATE/DELETE、WHERE、ORDER BY、LIMIT、JOIN、递归 CTE（M3 因果链）——均为跨方言标准。

## 2. 禁止进入 Domain Logic（SQLite 私有）
- PRAGMA（journal_mode/foreign_keys/busy_timeout）→ 只允许出现在 database/db.py 的引擎工厂（URL 前缀分流），业务层禁止。
- sqlite3 直连 API（除 backup_service 的在线备份路径，且该路径按 URL 分支，PG 下换 pg 备份实现）。
- 字符串拼接 SQL / f-string SQL（一律 text()/参数绑定或 ORM）。
- 依赖 SQLite 隐式行为的类型（如 BOOLEAN→INTEGER 隐转、无 CHECK 依赖）。
- SQLite 专用函数（date()/julianday()/FTS5 等）禁止进入 ORM 查询表达式；时间换算在应用层 time_service 完成。

## 3. JSON 列
- ORM 统一用 sqlalchemy.JSON()；PG 落 jsonb 时可经类型注解切换，业务不感知。
- 禁止在 SQL 内对 JSON 做方言专用查询（如 PG jsonb_path）；JSON 读取在应用层过滤。

## 4. 未来 PG 实跑需验证清单
1. migrations 在 PG 上从 0 upgrade head（同一 migration 文件集，无 SQLite batch 特判失败）。
2. 全测试套件在 PG 上运行（需 PG compatibility tests；M0 不部署）。
3. 时间列语义（UTC naive 约定）一致；backup_service 切换为 PG 备份实现并过 integrity/restore 测试。
4. SINGLE_WORLD_WRITER：PG 下锁表行级语义相同（租约表通用）。
5. 布尔/JSON 往返、递归 CTE 因果链查询结果一致。

## 5. 已落实的隔离点
- database/db.py：URL 前缀（sqlite）驱动 PRAGMA；PG 分支仅调整 connect 参数。
- config/settings：database_url 单一入口；BLR_DATABASE_URL 覆盖。
- services/repositories.py：全部 ORM 访问；EventRepository 无 update/delete。
- services/time_service.py：时间换算在应用层（不依赖 DB 时间函数）。

# PRE-M6 PostgreSQL 门禁只读审计（PRE-M6 ACTIVATION GATE CLOSURE）

- 审计时间：2026-09-14T01:07（本地）
- 审计修订：`ac8d422aab6c49f67852b90c3bcc60686058c4dc`（`M5_FINAL_HEAD`）
- 审计模式：**只读**（未改代码、未改配置、未装依赖、未建实例、未动正式库、未改 Private Companion）
- 审计对象门禁：`PRE_ACTIVATION_PG_GATE`、`PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_GATE`
- 审计依据文档：`POSTGRESQL_COMPATIBILITY_CONTRACT.md`（§2/§5/§6/§7/§8）、`runtime_design/M2B_RESOURCE_ECONOMY_ENGINE.md` §28、`reports/m4_scheduler_acceptance.md`

---

## 0. 结论摘要（先读）

> **更新（2026-09-14 · PRE-M6 POSTGRESQL GATE IMPLEMENTATION 第一阶段）**：
> 本审计的 4 个代码/审计面 blocker 已在本阶段修复，环境面 blocker 未变：
> `PG-001 = FIXED`（recovery 改可移植 JSON 表达式，SQLite 行为等价已验证）、
> `PG-002 = FIXED`（全生产路径静态扫描门禁）、`PG-006 = FIXED`（新增语句级
> BEFORE TRUNCATE 保护 migration）、`PG-008 = CORRECTED`（契约勘误：
> `PG_RECURSIVE_CTE_REQUIREMENT = N/A`）；
> `PG-003/PG-004 = OPEN`（PG 驱动/PG 实例仍缺失，Docker daemon 未运行）；
> `PG-005/PG-007/PG-009 = OPEN`（属后续 PG 环境与 harness 阶段）。
> 配套变更：`ALEMBIC_HEAD` 由 `d7f9b1c3e5a7` → `f2a7c4e9b1d6`（本文件下方
> 表格中的 head 值属**审计当时快照**，保持原样不改写）。
> 详见 `reports/PRE_M6_PG_PORTABILITY_FIX_REPORT.md`。

```
PRE_ACTIVATION_PG_GATE                  = NOT_READY_FOR_EXECUTION
PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_GATE = NOT_READY_FOR_EXECUTION
M6_ACTIVATION                           = PROHIBITED
```

**本机当前无法执行 PG 门禁**，原因有两层，任何一层单独成立即足以阻塞：

1. **环境层（外部阻塞）**：本机没有 PostgreSQL 软件、没有监听中的 PG 服务、没有可用的容器运行时（Docker Desktop 已安装但 daemon 未运行）；项目依赖中**没有 PG 驱动**，`create_engine("postgresql://…")` 会直接 `ModuleNotFoundError`。要闭合门禁必须先改变环境（安装 PG 或启动容器 + 安装驱动），这属于**环境变更，需 owner 授权**。
2. **代码层（已确认缺陷）**：生产代码存在 **SQLite 私有函数 `json_extract()`**（`services/simulation/recovery.py`，被执行权威恢复路径的生产模块 `services/simulation/coordinator.py` 导入）。即使 PG 环境就绪，该缺陷也会使恢复路径在 PG 上报 `function json_extract(...) does not exist`。该缺陷同时说明现有静态兼容性审计（`test_ta59`）**覆盖面不足、当前为空过**。

**既有 SQLite 结果不构成 PG 证据**：`reports/m4_scheduler_acceptance.md` 中的 `FENCING = PASS`、`STALE_WRITER_MUTATIONS = 0`、`ACK_LOST_EQUIVALENCE = PASS`、`HISTORY_ORPHAN_LINKS/CYCLES/INVALID_REFS = 0` 全部产生于 SQLite + 进程内注入，按 `runtime_design/M2B_RESOURCE_ECONOMY_ENGINE.md` §28 的规定，**不得声称 PostgreSQL 已验证**。

---

## 1. 审计方法与证据索引

| 项 | 方法 | 结果 |
| --- | --- | --- |
| 依赖面 | 读 `requirements.txt`、`pyproject` 依赖、全仓 grep `psycopg`/`asyncpg`/`postgresql+` | 仅 `SQLAlchemy>=2.0`、`alembic>=1.13`；**无任何 PG 驱动引用** |
| 环境面 | `Get-Command psql/pg_ctl/postgres/pg_isready`、`Get-Service *postgres*`、`Get-NetTCPConnection -LocalPort 5432`、`C:\Program Files\PostgreSQL` | 全部 `NOT_FOUND` / 0 服务 / 无监听 / 目录不存在 |
| 容器面 | `docker version` / `docker images` / `docker ps -a` | CLI 存在于 `C:\Program Files\Docker\Docker\resources\bin\docker.exe`；**daemon 未运行**（`npipe:////./pipe/dockerDesktopLinuxEngine` 连接失败）→ 无可用 PG 容器 |
| 方言隔离点 | 读 `database/db.py`、`database/invariants.py`、`database/base.py`、`services/backup_service.py`、`services/writer_lock.py`、`services/fencing.py`、`services/simulation/recovery.py`、`services/history/service.py` | 见 PG-001 / PG-005 / PG-006 / PG-007 / PG-010 |
| Migration 可移植性 | 读 `database/alembic/versions/*`（grep `sqlite`/`PRAGMA`/`batch_alter_table`/`postgresql`/`dialect`）、`alembic/env.py` | 见 PG-006 / PG-008 / PG-010 |
| SQLite 私有构造扫描 | 全仓 grep `json_extract`/`rowid`/`INSERT OR REPLACE`/`PRAGMA`/`sqlite_master`/`strftime` | 生产面命中 2 个模块（`services/simulation/recovery.py`、`services/backup_service.py`），其余全在 tests/scripts |
| Harness 能力 | 读 `tests/test_scheduler_crash_recovery.py`、`test_scheduler_ack_lost.py`、`test_scheduler_commit_ambiguity.py`、`test_m2b_commit_ambiguity.py`、`services/scheduler/core.py` | 见 PG-009 |
| 静态合同门禁 | 读 `tests/test_m3a_tribulation.py::test_ta59_postgresql_contract_audit` | 见 PG-002 |
| Git / live 面 | `git rev-parse HEAD`、`git status --porcelain`、live 插件目录逐文件哈希比对 | HEAD = ac8d422，采集时 DIRTY = 0；live 源码与 HEAD 同哈希 |

---

## 2. 发现清单（Findings）

### PG-001 — 【BLOCKER / 代码】生产代码使用 SQLite 私有 JSON 函数

- 证据：`services/simulation/recovery.py:33`、`:44`、`:49`
  - `text("json_extract(meta, '$.checkpoint_kind') = 'WORLD_COMMITTED'")`（选权威恢复 checkpoint）
  - `"… json_extract(meta, '$.kind') = 'CATCHUP' …"`、`"… json_extract(meta, '$.checkpoint_kind') = 'WORLD_COMMITTED' …"`（审计计数）
- 生产可达性：`services/simulation/coordinator.py:46` 导入该模块的 `WORLD_COMMITTED_KIND` 等 → 崩溃恢复/断点续跑的**权威判定**路径。
- PG 影响：PostgreSQL 无 `json_extract()`（对应 `->`/`->>` 或 `jsonb_extract_path_text`）→ `UndefinedFunction` 报错，恢复路径直接失败。
- 契约违背：违反 `POSTGRESQL_COMPATIBILITY_CONTRACT.md` §2（SQLite 专用函数禁止进入 ORM 查询表达式）与 §5（禁止在 SQL 内对 JSON 做方言专用查询；JSON 读取应在应用层过滤）；亦与 `runtime_design/M2B_RESOURCE_ECONOMY_ENGINE.md` §28「生产代码不执行 SQLite-only 语法」的**现存表述冲突**（该表述当前为不成立状态，须修正或修码）。
- 建议修法（**本阶段不执行**）：改用 ORM 层 JSON 比较（如 `SimulationCheckpoint.meta["checkpoint_kind"].as_string() == WORLD_COMMITTED_KIND`），或把 `checkpoint_kind` 提升为独立索引列；二者均需在 SQLite 与 PG 两侧回归等价性。
- 阻塞级别：**PG 门禁必须先修此项**，否则 D1/D2/D3 全部无法进行。

### PG-002 — 【BLOCKER / 审计盲区】静态兼容性审计覆盖面不足，当前为空过

- 证据：`tests/test_m3a_tribulation.py:918-923` 只扫描 3 个文件：`tribulation.py`、`tribulation_adapters.py`、`m3a_runner.py`，检查 `json_extract` / `rowid` / `INSERT OR REPLACE`。
- 后果：PG-001 位于 `services/simulation/recovery.py`，**不在扫描集合内**，因此该门禁在存在 PG 阻塞缺陷的情况下仍然 PASS。
- 建议修法（**本阶段不执行**）：把该静态审计改为对全部生产包（`main.py`、`services/`、`database/`、`plugin_shell/`、`config/`、`domain/`）做白名单外零容忍扫描，并显式排除 `tests/`、`scripts/`；同时把 `services/backup_service.py` 列为**唯一**允许 `sqlite3`/PRAGMA 的适配点（与契约 §2 一致）。

### PG-003 — 【BLOCKER / 环境与依赖】无 PostgreSQL 驱动

- 证据：`requirements.txt` 仅 2 行（`SQLAlchemy>=2.0`、`alembic>=1.13`）；全仓 grep `psycopg` / `asyncpg` / `postgresql+` **零命中**。
- 后果：`database/db.py::create_db_engine` 走 `create_engine(url)`，PG URL 需要 DBAPI 驱动；未安装时在建立引擎阶段即抛 `ModuleNotFoundError`。`POSTGRES_CONNECTIVITY` 不可能 PASS。
- 附加约束：本阶段**禁止 `pip install`**；若采用离线 wheel 方式补齐（与 M5.1 补 `alembic`/`mako` 同法），需 owner 授权并记录版本与 wheel 哈希，且需注意 live venv 无 dist-info 的既存残余风险会叠加。
- 备注：`database/alembic/env.py:48` 已是 `create_engine(_url(), poolclass=pool.NullPool)`，与 PG 兼容；连接参数/池化策略仍待定义（`pool_size`、`isolation_level`、`synchronous_commit` 全仓零命中 → 尚无显式策略）。

### PG-004 — 【BLOCKER / 环境】本机无可用 PostgreSQL 实例

- 证据：`psql` / `pg_ctl` / `postgres` / `pg_isready` 全部 `NOT_FOUND`；`Get-Service *postgres*` = 0；TCP 5432 无监听；`C:\Program Files\PostgreSQL` 不存在；`C:\` 下无 `PostgreSQL|pgsql` 目录。
- 容器替代路径当前不可用：`docker.exe` 存在但 daemon 未运行（named pipe 不存在）→ 无法 `docker run postgres`；即便启动 Docker Desktop，拉取镜像涉及网络与镜像来源策略，需 owner 决定。
- 结论：**PG 环境必须由 owner 决定如何提供**（三选一：启动 Docker Desktop 用 postgres 容器 / 原生安装 PostgreSQL / 提供独立测试 PG 主机）。测试 DSN 必须指向**全新合成库**，正式库绝不可作为 PG 测试目标。

### PG-005 — 【GAP / 代码】backup_service 为 SQLite-only，PG 路径未实现

- 证据：`services/backup_service.py:8`（注释自认「全部 PRAGMA/sqlite3 只存在于本 adapter 模块……PG 下换实现」）、`:38-41`（`_require_sqlite` 对非 sqlite URL **fail-closed 抛 `BackupError`**）、`:48-70`（`sqlite3` 在线 backup API + `PRAGMA integrity_check`）、`:100-121`（恢复时清 `-wal`/`-shm` 副产物 + 完整性校验）。
- 契约要求：`POSTGRESQL_COMPATIBILITY_CONTRACT.md` §6.3「backup_service 切换为 PG 备份实现并过 integrity/restore 测试」。
- 现状评价：**fail-closed 是正确行为**（不会静默产生错误备份），但 PG 备份/恢复/完整性校验能力缺失；若 PG 成为生产目标，则「迁移前备份」「恢复」两个门禁动作在 PG 上不可用。
- 建议：在 PG 门禁范围内明确处置——要么实现 PG 路径（`pg_dump`/`pg_basebackup` + 校验），要么在 activation 前书面声明「PG 部署不支持 backup_service，须以外部备份机制替代」并登记为已知限制。

### PG-006 — 【GAP / 未验证】事件不可变触发器与 invariants 的 PG 分支从未执行

- 证据：`database/alembic/versions/b2d4e8f9a6c3_m0_event_immutability_triggers.py:30-70` 具备 `sqlite` / `postgresql` 双分支（PG 侧 `CREATE TRIGGER blr_world_events_no_modify` + 函数；未知方言抛 `NotImplementedError`，正确 fail-closed）；`database/invariants.py:23-29` 具备 PG 分支（`pg_trigger WHERE tgname='blr_world_events_no_modify' AND NOT tgisinternal`）。
- 现状：两条 PG 分支**从未在 PG 上执行过**（含 `init_db` 启动校验路径）→ 触发器名、函数体、`RAISE EXCEPTION` 行为、以及 `verify_event_immutability` 的实际通过性均为未验证。
- **PG 专属漏洞（需在 activation 前决策）**：SQLite 无 `TRUNCATE`，而 PG 的 `BEFORE UPDATE OR DELETE` 行级触发器**不拦截 `TRUNCATE TABLE world_events`**。因此在 PG 上「DB 层事件不可变」比 SQLite 弱：需要补 `BEFORE TRUNCATE` 语句级触发器，或对应用角色 `REVOKE TRUNCATE`，否则不可变契约在 PG 上存在绕过口。

### PG-007 — 【GAP / 并发语义】single-writer 与 fencing 的 PG 语义未证

- 证据：
  - `services/writer_lock.py:67-117`：租约通过 `UPDATE runtime_lock … WHERE expires_at <= now` 的 **CAS + rowcount** 判定接管（rowcount = 0 视为被抢先），先 SELECT 后 UPDATE；
  - `services/fencing.py:44-71`：进入写事务时以 `lease_token + owner + expires_at > now` 延长租约（该 UPDATE 即取写锁），`assert_current_fence()` 在 COMMIT 前重验 token/owner/expiry；
  - 全仓 grep `with_for_update` / `FOR UPDATE` **零命中** → 未使用行级显式锁。
- SQLite 侧的隐性保护：`PRAGMA journal_mode=WAL` + 单写者写锁把所有写**串行化**（契约 §8.1 已明示「SQLite：写锁使接管 UPDATE 串行化（不依赖 PG 行锁）」）。PG 的 READ COMMITTED 下，前置 SELECT 是**非锁定读**，并发正确性完全落在 CAS UPDATE 的行锁语义上。
- 需在 PG 上实测的点：两进程/多连接同时接管同一世界；心跳续约与接管竞争；stale writer 提交被拒（`STALE_WRITER_MUTATIONS` 必须为 0）；`now` 的来源（代码侧 `utcnow()` vs 数据库时钟）与 `TIMESTAMPTZ` 比较在跨进程时钟偏移下的行为；`expires_at` 的 `UtcDateTime` 归一化在 PG 往返后是否保持 aware UTC。
- 风险定级：中高。SQLite 的写串行化**会掩盖**这类缺陷，属于「换库后才暴露」的典型类别。

### PG-008 — 【DRIFT / 文档与代码不一致】契约 §6.5 引用的递归 CTE 在当前代码中不存在

- 证据：`POSTGRESQL_COMPATIBILITY_CONTRACT.md` §1 允许「递归 CTE（M3 因果链）」、§6.5 要求验证「布尔/JSON 往返、递归 CTE 因果链查询结果一致」；但全仓 grep `WITH RECURSIVE` / `recursive` **零命中**（生产与测试均无）。
- 实际实现：因果环检测为**应用层迭代式 3-color DFS**（`services/history/service.py:660-697`，`_find_cycles`），supersede 环同为 Python 递归（`:699-717`），均不依赖 DB 方言 → 这部分**天然无 PG 风险**。
- 处置：§6.5 的 CTE 项当前为**空项（无代码面）**，应在门禁报告中如实标注为 `N/A（当前无递归 CTE；若未来引入需回归）`，避免把无代码面的条目记为 PASS 造成虚假通过。

### PG-009 — 【GAP / 验证手段】现有崩溃/歧义 harness 无法表达 PG 层 commit 歧义

- 证据：
  - 崩溃注入是**进程内**模拟：`services/scheduler/core.py:45-63`（`SchedulerCrash(RuntimeError)` + 16 个 `CRASH_POINTS` + `set_crash_point` 单次触发，`:514-527`）；
  - commit 歧义注入是 **monkeypatch 应用层**：`tests/test_scheduler_commit_ambiguity.py:41-49`（替换 `WorldMutationContext.commit` 使其在「durable 之前」抛 `RuntimeError` 模拟假失败）；
  - ACK lost 用例以「durable 已提交」为前提构造，崩溃/接管通过 `UPDATE runtime_lock SET expires_at='2000-01-01'` 强制 stale（如 `tests/test_m2b_commit_ambiguity.py:342-345`）；
  - 全部 harness 基于 SQLite 临时库（`tmp_path`），无真实进程被杀、无真实连接中断。
- 缺口：PG 门禁要求的是**数据库事务层**的 commit-ack 歧义（COMMIT 已发送但回执丢失、连接被 `pg_terminate_backend` 掐断、进程在 COMMIT 往返窗口内死亡、接管者读取 durable truth 判定结果）。当前手段无法覆盖，且 SQLite 的本地快速提交路径短、写串行化强，**恰好掩盖了这些窗口**。
- 结论：`PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_GATE` 需要**新增 PG 专属 harness**（真实连接断开 + 真实进程终止 + durable truth 复核），而非复用现有 SQLite 用例。

### PG-010 — 【INFO / 已具备的有利条件】

以下隔离点当前看是 PG-sound 的，可作为门禁执行的基础（仍需实测确认）：

- `database/db.py:22-35`：以 URL 前缀分流——SQLite 才注入 `connect_args` 与 `PRAGMA`（WAL / foreign_keys / busy_timeout），PG 路径不施 PRAGMA；
- `database/base.py`：`UtcDateTime(TypeDecorator)`（impl = `DateTime(timezone=True)`）在边界把 naive 输入按 UTC 解释、aware 输入转 UTC；
- `database/models_core.py` / `models_world.py`：时间坐标一律 `BigInteger`、数值量一律 minor units 整数（无浮点权威数量）、JSON 列统一 `sa.JSON()`、布尔用 `sa.Boolean`；
- `database/alembic/versions/e6c0f4a1b3d9_…py:46-52`：COMMITTED 区间唯一索引**同时**提供 `sqlite_where` 与 `postgresql_where`（`status='COMMITTED'`），partial unique index 在 PG 语义正确；
- `database/alembic/versions/d8e1b3a5c7f9_…py:42-59`：UTC ISO8601 数据修正对非 sqlite **显式 no-op**（PG 原生 TIMESTAMPTZ），且初始 schema 已用 `sa.DateTime(timezone=True)`；
- `database/alembic/versions/b2d4e8f9a6c3_…py:60`：未知方言抛 `NotImplementedError`（fail-closed，不静默降级）；
- `database/alembic/env.py:48`：`poolclass=NullPool`（迁移期无连接池残留）；
- 业务访问基本经 ORM/repositories（契约 §7），PG 私有 SQL 不进入业务层；
- `services/history/service.py::history_integrity_audit`（`:580-658`）已能一次性产出 orphan / duplicate / invalid relation / tick paradox / cycle / supersede loop / 索引水印全套指标，**与方言无关**，可直接在 PG 上复测 owner 要求的 `HISTORY_ORPHAN_LINKS / CAUSAL_CYCLES / INVALID_REFS`。

---

## 3. 门禁逐项就绪矩阵

| 门禁项（owner 通过标准） | 当前状态 | 阻塞原因 |
| --- | --- | --- |
| `POSTGRES_CONNECTIVITY` | **BLOCKED** | PG-003（无驱动）、PG-004（无 PG 实例） |
| `SCHEMA_MIGRATION`（0 → head） | **NOT_VERIFIED** | PG-004；另需在 PG 上确认 head 与 SQLite `d7f9b1c3e5a7`、46 张表一致 |
| `FRESH_DB`（新建库全量迁移） | **NOT_VERIFIED** | PG-004 |
| `EXISTING_DB`（既有库前进） | **NOT_VERIFIED** | PG-004 |
| `SINGLE_WRITER` | **NOT_VERIFIED** | PG-007（PG 无 SQLite 写串行化保护） |
| `FENCING` | **NOT_VERIFIED** | PG-007 |
| `STALE_WRITER_MUTATIONS = 0` | **NOT_MEASURED_ON_PG**（SQLite 侧为 0） | PG-007、PG-009 |
| `DETERMINISM` | **NOT_VERIFIED** | PG-001 阻断恢复路径；PG-004 |
| `CHUNK_EQUIVALENCE` | **NOT_VERIFIED** | 同上（SQLite 侧 PASS） |
| `RESTART_EQUIVALENCE` | **NOT_VERIFIED** | 同上 |
| `HISTORY_ORPHAN_LINKS = 0` | **NOT_MEASURED_ON_PG**（SQLite 侧 0） | PG-004；审计入口已就绪（PG-010） |
| `HISTORY_CAUSAL_CYCLES = 0` | **NOT_MEASURED_ON_PG**（SQLite 侧 0） | 同上（检测为应用层 DFS，PG-008） |
| `HISTORY_INVALID_REFS = 0` | **NOT_MEASURED_ON_PG**（SQLite 侧 0） | 同上 |
| `DUPLICATE_TICKS = 0` | **NOT_MEASURED_ON_PG**（SQLite 侧 0） | PG-009（需 PG 专属歧义 harness） |
| `DUPLICATE_HISTORY_EVENTS = 0` | **NOT_MEASURED_ON_PG**（SQLite 侧 0） | PG-009 |
| `LOST_TICKS = 0` | **NOT_MEASURED_ON_PG**（SQLite 侧 0） | PG-009 |
| `FORKED_HISTORY = 0` | **NOT_MEASURED_ON_PG**（SQLite 侧 0） | PG-009 |
| `NO_BLIND_RETRY` | **NOT_VERIFIED_ON_PG** | PG-009（现有语义为 RECOVERING → 读 durable truth → 不重试，需在 PG 复现） |
| `SQLITE_ONLY_PRODUCTION_SQL = 0` | **FAIL** | **PG-001**（`recovery.py` `json_extract` ×3）；静态门禁空过（PG-002） |
| `PG_DRIVER_AVAILABLE` | **FALSE** | PG-003 |
| `PG_SERVER_AVAILABLE` | **FALSE** | PG-004 |
| `SQLITE_RESULTS_DO_NOT_IMPLY_PG_VERIFIED` | **遵守** | 本报告与 M5 报告均未据此声称 PG 通过 |

---

## 4. 建议的闭合路径（分阶段，**需 owner 授权，本阶段不执行**）

> 以下仅为方案，**未经授权不得启动**；每一步都不得触碰正式库、不得消费 World Seed、不得修改 Private Companion。

- **PG-D0 环境与依赖（需 owner 决策）**
  1. 选定 PG 提供方式：启动 Docker Desktop 后用 `postgres` 容器 / 原生安装 PostgreSQL / 独立测试主机；
  2. 选定驱动（如 `psycopg[binary]`）并**离线**提供 wheel（记录版本 + 文件哈希，不执行 `pip install` 之外的隐式联网动作）；若 owner 仍禁止安装，则本门禁**无法闭合**，须如实登记为环境受限；
  3. 建立**专用合成测试库** DSN（与正式库完全分离），并确认网络策略允许本地/容器连接。
- **PG-D1 代码修复（需授权）**：PG-001 去 `json_extract`（ORM JSON 比较或显式列）；PG-002 把静态审计扩到全生产目录；决定 PG-005（实现 PG 备份路径或书面声明不支持）与 PG-006（`TRUNCATE` 不可变补强）。
- **PG-D2 迁移与基线**：空库 `alembic upgrade head`，比对 `alembic current/heads` 与 SQLite head `d7f9b1c3e5a7`、表数 46、partial unique index / 触发器 / JSON / boolean 往返。
- **PG-D3 功能等价**：在 PG 上跑全套测试（仅合成世界 / 临时库），比对 determinism / chunk / restart 三哈希与 SQLite golden。
- **PG-D4 并发与 fencing**：真实多进程/多连接验证 single-writer、租约过期 CAS 接管、心跳续约、stale 拒绝（`STALE_WRITER_MUTATIONS` 必须 0）。
- **PG-D5 commit 歧义**：构造真实 COMMIT 期连接中断（含 `pg_terminate_backend`）与进程死亡，验证 durable truth 判定、不盲重试、`DUPLICATE_* / LOST_TICKS / FORKED_HISTORY = 0`。
- **PG-D6 报告与冻结**：产出 `PRE_ACTIVATION_PG_GATE_REPORT` 与 `PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_REPORT`；两项全 PASS 后方可解除 `M6_ACTIVATION = PROHIBITED`。

---

## 5. 本阶段禁令遵守声明

```
CODE_CHANGES                = 0（未新增/修改任何 `.py`）
CONFIG_CHANGES              = 0
DEPENDENCY_INSTALLED        = 0（未执行 pip install；未新增驱动）
POSTGRESQL_INSTALLED        = 0（未安装 PG；未启动 Docker daemon；未拉取镜像）
CONTAINER_STARTED           = 0
INSTANCE_CREATED            = 0
FORMAL_DB_WRITE             = 0（仅读取运行期状态 JSON；正式库运行中被独占，未做任何写入/停机操作）
INSTANCE_STARTED_OR_STOPPED = 0（live 实例由 owner 通过 Launcher 控制，本阶段未操作）
PRIVATE_COMPANION_CHANGED   = 0
SCHEDULER_CODE_CHANGED      = 0
M0_M4_FROZEN_SURFACE_CHANGED = 0
COMMITS_CREATED             = 0
HISTORY_REWRITTEN           = FALSE
本阶段新增文件               = reports/M5_FINAL_CLOSEOUT.md、docs/pre_m6_pg_gate_audit.md（未跟踪，未提交）
```

---

## 6. 审计报告字段（机器可读返回块）

```
PRE_M6_PG_GATE_AUDIT_REPORT
AUDITED_REVISION                        = ac8d422aab6c49f67852b90c3bcc60686058c4dc
AUDIT_MODE                              = READ_ONLY
CODE_CHANGES                            = 0

PG_DRIVER_AVAILABLE                     = FALSE
PG_SERVER_AVAILABLE                     = FALSE
CONTAINER_RUNTIME_AVAILABLE             = FALSE
TEST_DSN_AVAILABLE                      = FALSE

POSTGRES_CONNECTIVITY                   = BLOCKED
SCHEMA_MIGRATION                        = NOT_VERIFIED
FRESH_DB                                = NOT_VERIFIED
EXISTING_DB                             = NOT_VERIFIED
SINGLE_WRITER                           = NOT_VERIFIED
FENCING                                 = NOT_VERIFIED
STALE_WRITER_MUTATIONS                  = NOT_MEASURED_ON_PG
DETERMINISM                             = NOT_VERIFIED
CHUNK_EQUIVALENCE                       = NOT_VERIFIED
RESTART_EQUIVALENCE                     = NOT_VERIFIED
HISTORY_ORPHAN_LINKS                    = NOT_MEASURED_ON_PG
HISTORY_CAUSAL_CYCLES                   = NOT_MEASURED_ON_PG
HISTORY_INVALID_REFS                    = NOT_MEASURED_ON_PG
DUPLICATE_TICKS                         = NOT_MEASURED_ON_PG
DUPLICATE_HISTORY_EVENTS                = NOT_MEASURED_ON_PG
LOST_TICKS                              = NOT_MEASURED_ON_PG
FORKED_HISTORY                          = NOT_MEASURED_ON_PG
NO_BLIND_RETRY                          = NOT_VERIFIED_ON_PG
SQLITE_ONLY_PRODUCTION_SQL              = FAIL（PG-001）

BLOCKING_DEFECTS                        = PG-001, PG-002, PG-003, PG-004
NON_BLOCKING_GAPS                       = PG-005, PG-006, PG-007, PG-009
DOC_CODE_DRIFT                          = PG-008
FAVORABLE_ISOLATION_POINTS              = PG-010

PRE_ACTIVATION_PG_GATE                  = NOT_READY_FOR_EXECUTION
PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_GATE = NOT_READY_FOR_EXECUTION
M6_ACTIVATION                           = PROHIBITED
WORLD_ACTIVATED                         = FALSE
WORLD_SEED_CONSUMED                     = FALSE

REQUIRED_OWNER_DECISION                 = 如何提供 PostgreSQL 环境（Docker 容器 / 原生安装 / 独立测试主机）+ 是否授权离线安装 PG 驱动
NEXT_ACTION                             = STOP（等待 owner 授权后再进入 PG-D0；未授权前不执行任何 PG 相关变更）
```

# PRE-M6 POSTGRESQL ENVIRONMENT BRING-UP — 报告

- 报告时间：2026-09-14（本地）
- 阶段授权：`PRE_M6_PG_PORTABILITY_STAGE = PASS`、`POSTGRES_ENVIRONMENT_BRINGUP_AUTHORIZED = TRUE`
- 权威基准修订：
  - `PORTABILITY_HEAD = 4268e4549b0b75d67233ab22c6ac00944fb4a31b`
  - `PORTABILITY_CODE_HEAD = 6c3d24b`（fix: harden postgres portability before activation）
  - `CURRENT_ALEMBIC_HEAD = f2a7c4e9b1d6`
- 阶段结论：**Docker 隔离 PG 16 测试环境已成功建立并 healthy；psycopg 3 安装被网络策略拒绝
  （403），按 owner 指令 §5 判定 `PG_DRIVER_STATUS = BLOCKED_INSTALL` 并 STOP。**
  依赖驱动的验收项（connectivity / migration / PG-006 实跑 / PG-001 smoke / PG 集成入口）
  **均未执行，不得视为 PASS**。
- `M6_ACTIVATION = PROHIBITED`（未进入 M6）

---

## 1. 本轮完成 / 未完成

| 步骤 | 状态 |
| --- | --- |
| 1. 启动隔离 Docker PostgreSQL 16 测试环境 | **DONE**（daemon READY、容器 healthy） |
| 2. 独立 dev/test 环境安装 psycopg 3 | **BLOCKED_INSTALL**（网络策略 403；无本地合法 artifact） |
| 3. SQLAlchemy PostgreSQL connectivity | NOT_RUN（依赖 2） |
| 4. fresh / existing / idempotent migration | NOT_RUN（依赖 2） |
| 5. PG-001 / PG-006 最小 integration smoke | NOT_RUN（依赖 2） |
| 6. 返回报告后 STOP | **DONE**（本报告） |

未进入（按 §14 保留给下一阶段）：single-writer stress、fencing takeover、
determinism 全量、真实 commit ambiguity harness、process-kill ambiguity、M6 activation。

---

## 2. Docker daemon（§2）

```
DOCKER_CLI_STATUS   = PRESENT
                      docker.exe 29.7.2（API 1.55，context = desktop-linux）
DOCKER_DAEMON_STATUS = READY
                      Server: Docker Desktop 4.88.0 (237115)
                      Engine: 29.7.2 / API 1.55 / linux / x86_64 / overlay2
```

- 启动前：daemon NOT_RUNNING（`npipe:////./pipe/dockerDesktopLinuxEngine` 不存在），
  Docker Desktop 进程未运行。
- 前置检查（只读）：Docker Desktop 已安装（`C:\Program Files\Docker\Docker\Docker Desktop.exe`）；
  **WSL 已安装**（`wsl --status` 正常，发行版 `docker-desktop` v2，启动前为 Stopped）
  → 无系统前置阻塞。
- 处置：按 §2 授权**正常启动 Docker Desktop**（`Start-Process`，最小化窗口），
  等待 daemon ready（< 8 分钟），复验 `docker version` / `docker info` 均正常。
- **未执行**任何系统级变更：无 `wsl --install`、无 Windows 功能启用、无 Docker 重装、
  无重启、无系统修复。

---

## 3. PostgreSQL 测试容器（§3 / §4）

```
PG_CONTAINER_NAME = blr-pre-m6-postgres
PG_IMAGE          = postgres:16-alpine
PG_IMAGE_ID       = sha256:75f5a96988cdf694a215073c3e9c001b706b371e2f94df3967f2efdec2787f6b
PG_SERVER_VERSION = PostgreSQL 16.15 on x86_64-pc-linux-musl（Alpine 15.2.0）
PG_HOST           = 127.0.0.1
PG_PORT           = 55432（容器内 5432；HostIp 仅 127.0.0.1，**未绑定 0.0.0.0**）
PG_DATABASE       = blr_pre_m6
PG_USER           = blr_test
PG_PASSWORD       = REDACTED（随机生成 32 字符，仅存 %TEMP%\blr_pre_m6_pg_env.json）
PG_HEALTH         = healthy（healthcheck = pg_isready -U blr_test -d blr_pre_m6）
PG_VOLUME         = blr_pre_m6_pgdata → /var/lib/postgresql/data（TEST ONLY，可删除可重建）
PG_NETWORK        = bridge（默认网络；**未**加入他人网络 stayops_default）
PG_ENCODING/TZ    = UTF8 / UTC
```

- 镜像本地已存在（4 周前拉取）→ **本轮未拉取新镜像**（无 registry 网络行为）。
- 容器与卷均带显式标签：`com.xiaoguang.blr.purpose = XiaoguangBlessedLandRuntime TEST ONLY`、
  `com.xiaoguang.blr.stage = pre-m6-pg-environment-bringup`、`com.xiaoguang.blr.synthetic = true`；
  `--restart no`（不自动重启，避免残留后台行为）。
- **他人资源未触碰**：同机另有他人项目容器 `stayops-postgres`（镜像同为 postgres:16-alpine，
  端口 `0.0.0.0:5432`，卷 `stayops_stayops_pgdata`、网络 `stayops_default`）——本轮**只读观测**，
  未启动/停止/删除/连接其资源。
- 可销毁性证据（容器内只读检查）：
  - `pg_isready` → `accepting connections`
  - `information_schema.tables`（public schema）→ **0**（尚无任何表，未被任何 SQLite 正式库内容污染）
  - `pg_database` → `blr_pre_m6 / postgres / template0 / template1`（无任何正式世界痕迹）

**凭据纪律**：密码由 `Get-Random` 生成，仅写入 `%TEMP%\blr_pre_m6_pg_env.json`
（`scope = DEV_TEST_ONLY`）；**未**写入仓库、**未**进入 git、**未**出现在本报告。
未使用任何真实生产凭据。

---

## 4. PostgreSQL 驱动安装（§5 / §6）— 阻塞点

```
PG_DRIVER              = psycopg（psycopg 3，目标）
PG_DRIVER_VERSION      = N/A（未安装）
PG_DRIVER_ENV          = %TEMP%\blr-pre-m6-pg-venv
                         （独立 dev/test venv，Python 3.11.9；非 live venv）
PG_DRIVER_INSTALL_SCOPE = DEV_TEST_ONLY
PG_DRIVER_STATUS       = BLOCKED_INSTALL
```

- 已建立**独立** venv（`python -m venv`，Python 3.11.9）；**未**使用 live AstrBot venv，
  **未**修改 live Python 环境，**未**复制任何 package 目录 / site-packages
  （未重演 Alembic/Mako 手工拷贝事故）。
- 安装命令：`<venv>\Scripts\python.exe -m pip install "psycopg[binary]>=3,<4"`
  （正常 package manager 路径）。
- **失败原因（策略拒绝，非代码问题）**：

```
ProxyError('Cannot connect to proxy.',
           OSError('Tunnel connection failed: 403 Forbidden')): /simple/psycopg/
...
ERROR: Could not find a version that satisfies the requirement psycopg<4,>=3
ERROR: No matching distribution found for psycopg<4,>=3
```

  harness 网络策略代理对本 shell 拒绝访问 PyPI（HTTP 403）。按策略要求**未尝试绕过**
  （未切换 index/mirror、未改代理、未用容器网络或其他路径下载）。

- **合法本地 artifact 检索结果（均为空）**：
  - pip HTTP/wheel cache：`%LOCALAPPDATA%\pip\Cache` 存在，但 `*.whl` = 0、无 `*psycopg*` 文件；
  - 工作区 / `%TEMP%` 递归检索 `*.whl`：0；
  - 用户 Python 目录下 `psycopg*` 目录：0；
  - dev python 与新建 venv：`psycopg / psycopg2 / pg8000 / asyncpg` 全部不可导入。

- 因此无法构成「由 package manager 安装合法本地 wheel」的替代路径 → 判定
  `PG_DRIVER_STATUS = BLOCKED_INSTALL`，并按 owner 指令 **STOP**。
- **不再需要 DSN 构造**：`PG_TEST_DSN = REDACTED`；ALLOW flag 真实变量名（从代码读取，
  未猜测）为 `BLR_TEST_PG_ALLOW=1`，配套 DSN 变量名为 `BLR_TEST_PG_DSN`
  （见 `tests/test_pg_recovery_checkpoint_portability.py::_pg_dsn_or_skip`，
  其守卫要求 DSN 库名必须含 `test` 且非 sqlite，否则 fail-closed）。

---

## 5. 依赖驱动的验收项（全部 NOT_RUN，禁止记为 PASS）

```
PSYCOPG_CONNECTIVITY                 = NOT_RUN（BLOCKED_INSTALL）
SQLALCHEMY_CONNECTIVITY              = NOT_RUN（BLOCKED_INSTALL）
POSTGRES_FRESH_DB_MIGRATION          = NOT_RUN
POSTGRES_EXISTING_DB_MIGRATION       = NOT_RUN
POSTGRES_SECOND_UPGRADE_IDEMPOTENT   = NOT_RUN
POSTGRES_ALEMBIC_HEAD                = N/A（PG 上未执行任何迁移；代码 head 仍为 f2a7c4e9b1d6）
PG_EVENT_INSERT                      = NOT_RUN
PG_EVENT_UPDATE_PROTECTION           = NOT_RUN
PG_EVENT_DELETE_PROTECTION           = NOT_RUN
PG_EVENT_TRUNCATE_PROTECTION         = NOT_RUN
PG_RECOVERY_QUERY_EXECUTES           = NOT_RUN
PG_RECOVERY_SEMANTICS                = NOT_RUN
PG_INTEGRATION_ENTRY                 = NOT_RUN（该测试仍按设计 skip：缺 DSN + ALLOW flag）
```

**PG-006 状态维持不变**：`PG006_STATUS = FIXED_AT_SCHEMA_LEVEL`
（**不得**升级为 `PASS_ON_REAL_POSTGRES`——真实 PG 上的 INSERT/UPDATE/DELETE/TRUNCATE
行为本轮未验证）。

---

## 6. 本轮可执行且已完成的非驱动项（§12）

```
SCANNED_PRODUCTION_FILES    = 90
SQLITE_ONLY_PRODUCTION_SQL  = 0
ALLOWLIST                   = 1（services/backup_service.py，fail-closed 守卫由测试断言）
```

**扫描器非空过证据（可复现，本轮重跑）**：

```
THEN（ac8d422 = PRE_FIX_HEAD）: violations = 3
    line 33 [json_extract] json_extract(meta, '$.checkpoint_kind') = '
    line 43 [json_extract] SELECT COUNT(*) FROM simulation_checkpoints WHERE complete = 1 AND json_extract(
    line 47 [json_extract] SELECT COUNT(*) FROM simulation_checkpoints WHERE complete = 1 AND json_extract(
NOW（4268e45 = PORTABILITY_HEAD）: violations = 0
```

即静态门禁在本阶段依然**能捕获真实缺陷**（对历史修订仍报 3 处），并非空过。
补充：分块回归中 `tests/test_pg_portability_static_audit.py` 的合成非空过用例
（`test_scanner_flags_pg001_shape_unguarded_json_extract`）亦为 PASS。

---

## 7. 正式世界与 live 复核（§16）

环境操作**前后**均实测，结论一致：

```
WORLD_RUNTIME_STATUS   = NOT_ACTIVATED（world_id = FORMAL-UNSEEDED）
CURRENT_BLESSED_TICK   = NULL
OFFICIAL_WORLD_EVENTS  = 0
OFFICIAL_WORLD_MUTATIONS = 0
WORLD_SEED_CONSUMED    = FALSE
SCHEDULER_STATUS       = DORMANT（counters 全 0：cycle / batches_total / recovery /
                         lease_takeover / stale_writer_rejection / commit_ambiguity /
                         last_successful_commit / last_batch_ticks；last_error = null）
FORMAL_WORLD_TOUCHED   = FALSE
```

- 正式库 `blessed_land.sqlite` 536576 B，mtime `09-12 09:53:41`（未变），`-wal` = 0 B；
  `authoritative_db.json` 校验和 `1d84ee37…52cf2`（与冻结值一致）。
- live 实例 PID 56560 / 1744（start `00:46:00`）持续运行、未重启；live 插件源码未被改动。
- 未迁移正式世界、未创建正式 `world_runtime`、未消费 World Seed、未进入 M6。
- **未触碰**：live AstrBot venv、live Runtime plugin、live plugin_data、正式
  `blessed_land.sqlite`、Private Companion、AstrBot Core、AstrBot Launcher。

---

## 8. 环境残留物与清理方式（TEST ONLY）

| 对象 | 位置 | 清理命令 |
| --- | --- | --- |
| 容器 | `blr-pre-m6-postgres`（**当前运行中，healthy**，供下一阶段复用） | `docker stop blr-pre-m6-postgres` / `docker rm blr-pre-m6-postgres` |
| 卷 | `blr_pre_m6_pgdata` | `docker volume rm blr_pre_m6_pgdata` |
| venv | `%TEMP%\blr-pre-m6-pg-venv` | 直接删除目录 |
| 凭据 | `%TEMP%\blr_pre_m6_pg_env.json` | 直接删除文件 |

容器与卷**不含**任何正式数据、不含 World Seed、与正式世界无关，可随时删除重建。
Docker Desktop 由本轮启动，保持运行（他人项目容器亦依赖它）。

---

## 9. 返回字段（PRE_M6_PG_ENVIRONMENT_BRINGUP_REPORT）

```
PRE_M6_PG_ENVIRONMENT_BRINGUP_REPORT

DOCKER_CLI_STATUS                   = PRESENT（29.7.2 / context desktop-linux）
DOCKER_DAEMON_STATUS                = READY（Docker Desktop 4.88.0 / Engine 29.7.2 / linux x86_64）

PG_CONTAINER_NAME                   = blr-pre-m6-postgres
PG_IMAGE                            = postgres:16-alpine
PG_IMAGE_ID                         = sha256:75f5a96988cdf694a215073c3e9c001b706b371e2f94df3967f2efdec2787f6b
PG_SERVER_VERSION                   = PostgreSQL 16.15（x86_64-pc-linux-musl）
PG_HEALTH                           = healthy
PG_HOST / PG_PORT                   = 127.0.0.1 / 55432（→ 容器 5432；未绑定 0.0.0.0）
PG_DATABASE / PG_USER               = blr_pre_m6 / blr_test
PG_PASSWORD                         = REDACTED（%TEMP%\blr_pre_m6_pg_env.json，DEV_TEST_ONLY）

PG_DRIVER                           = psycopg（目标；未安装）
PG_DRIVER_VERSION                   = N/A
PG_DRIVER_ENV                       = %TEMP%\blr-pre-m6-pg-venv（Python 3.11.9，独立）
PG_DRIVER_INSTALL_SCOPE             = DEV_TEST_ONLY
PG_DRIVER_STATUS                    = BLOCKED_INSTALL（策略代理 403 → PyPI 不可达；无本地合法 wheel）
PG_TEST_DSN                         = REDACTED
PG_TEST_ALLOW_FLAG                  = BLR_TEST_PG_ALLOW（配套 DSN 变量 = BLR_TEST_PG_DSN）

PSYCOPG_CONNECTIVITY                = NOT_RUN
SQLALCHEMY_CONNECTIVITY             = NOT_RUN

POSTGRES_FRESH_DB_MIGRATION         = NOT_RUN
POSTGRES_EXISTING_DB_MIGRATION      = NOT_RUN
POSTGRES_SECOND_UPGRADE_IDEMPOTENT  = NOT_RUN

POSTGRES_ALEMBIC_HEAD               = N/A（PG 未执行迁移；代码 head = f2a7c4e9b1d6）

PG_EVENT_INSERT                     = NOT_RUN
PG_EVENT_UPDATE_PROTECTION          = NOT_RUN
PG_EVENT_DELETE_PROTECTION          = NOT_RUN
PG_EVENT_TRUNCATE_PROTECTION        = NOT_RUN
PG006_STATUS                        = FIXED_AT_SCHEMA_LEVEL（未升级）

PG_RECOVERY_QUERY_EXECUTES          = NOT_RUN
PG_RECOVERY_SEMANTICS               = NOT_RUN

SCANNED_PRODUCTION_FILES            = 90
SQLITE_ONLY_PRODUCTION_SQL          = 0（非空过证据：PRE_FIX_HEAD 3 违规 → 当前 0）

PG_INTEGRATION_ENTRY                = NOT_RUN（仍按设计 skip）

FORMAL_WORLD_TOUCHED                = FALSE
WORLD_SEED_CONSUMED                 = FALSE
WORLD_RUNTIME_STATUS                = NOT_ACTIVATED
SCHEDULER_STATUS                    = DORMANT

PRE_ACTIVATION_PG_GATE              = REQUIRED（NOT_YET_PASS；本轮未提前 PASS）
PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_GATE = REQUIRED
M6_ACTIVATION                       = PROHIBITED

REQUIRED_OWNER_DECISION             = 解除 PyPI 访问阻塞（允许 harness 代理访问 pypi.org，
                                      或提供合法本地 psycopg 3 wheel/artifact），
                                      否则驱动依赖的门禁无法推进
NEXT_ACTION                         = AWAIT_OWNER_REVIEW_FOR_PG_FUNCTIONAL_AND_COMMIT_AMBIGUITY_GATE
```

**STOP** — 未进入 M6；未开始 single-writer / fencing / commit ambiguity；
未对 live 做任何改动。环境（daemon + 隔离容器 + 独立 venv）保留就绪，待驱动安装条件满足后即可续跑。

# FINAL PRE-M6 LIVE STAGING — 报告

- 报告时间：2026-09-15（本地）
- 阶段：`FINAL PRE-M6 LIVE STAGING`（M6 World Activation 之前最后一个 live staging 阶段）
- `CURRENT_HEAD = 138a2c620f452f97900951877fd9baab7fef8aa9`（工作区 clean；
  `PRE_M6_CODE_READY = TRUE`）
- 结论：**`FINAL_PRE_M6_LIVE_STAGING = PASS`**；`PRE_M6_LIVE_READY = TRUE`；
  **`M6_ACTIVATION = PROHIBITED_PENDING_OWNER_EXPLICIT_ACTIVATION_AUTHORIZATION`**

本阶段**未**消费 World Seed、未创建正式 `world_runtime` 行、未推进 blessed tick、
未运行 simulation、未生成正式 history、未进入 M6。

---

## 1. Preflight（§2）与 Pre-Staging 快照（§3）

开始时 live 实例**正在运行**（PID 23472/7476，6185 监听）→ 按 §2 由 Owner 经
AstrBot Launcher **正常停止**（未使用 kill/taskkill/Stop-Process python）。停止后复核：

```
LIVE_PROCESS_COUNT = 0
PORT_6185          = NOT_LISTENING
SQLITE_WRITER      = 无活动 writer
```

Pre-Staging 快照（只读）：

```
FORMAL_DB_PATH             = <instance>\core\data\plugin_data\
                             astrbot_plugin_blessed_land_runtime\blessed_land.sqlite
FORMAL_DB_SHA256_PRE       = 1d84ee370167b047265bd2200c69c7373372fb0b594bf7ac073b33097de52cf2
FORMAL_DB_SIZE_PRE         = 536576
FORMAL_DB_MTIME_PRE        = 2026-09-12T09:53:41
FORMAL_DB_INTEGRITY_PRE    = ok
FORMAL_DB_ALEMBIC_HEAD_PRE = d7f9b1c3e5a7
WORLD_RUNTIME_ROWS_PRE     = 0
WORLD_EVENTS_ROWS_PRE      = 0
SIMULATION_RUN_ROWS_PRE    = 0
RUNTIME_LOCK_ROWS_PRE      = 0
TIME_RATIO_HISTORY_ROWS_PRE = 0
CURRENT_BLESSED_TICK_PRE   = NULL
WORLD_SEED_CONSUMED_PRE    = FALSE
TABLES_PRE                 = 46
SIDECARS                   = blessed_land.sqlite-wal (0 B) / -shm (32768 B)
```

WAL 为 0 字节；**仍使用 SQLite 在线备份 API**（`Connection.backup`）建立一致备份，
不以裸拷贝主库为唯一手段。

## 2. 回滚点（§4）

```
PRE_M6_ROLLBACK_PATH     = D:\MY SELF\IKUN\小光\incident_quarantine\
                           pre_m6_live_staging_20260915_141027
PRE_M6_PLUGIN_TREE_HASH  = e2d0bf6b08d61af25b4e11d7945f1b2290a288be35bdd032fc878206a2735fc9
                           （99 源文件；副本与源逐字节一致 COPY_MATCHES_SOURCE = TRUE）
PRE_M6_DB_BACKUP_SHA256  = ac4d2e53f17a0f313ac3ab5c4897665067bcfd2cadb6ffc7a9c1b7d4d708c89f
                           （SQLite backup API 产物；integrity ok、head d7f9b1c3e5a7、
                             world_runtime 0 行）
状态文件                  = plugin_source/（A）、plugin_data/blessed_land.sqlite（B）、
                           plugin_data/runtime_state/{authoritative_db.json,
                           scheduler_state.json}（C/D）
```

说明：一致备份的**字节哈希与源库不同属正常**（SQLite 备份会重写页布局/空闲页），
逻辑一致性由 integrity ok + head 一致 + 行数 0 验证。原文件全部未被修改。

## 3. 部署包（§5）

使用仓库正式构建器 `scripts/build_deployment_package.py`（**未复用** M5.1/M5.2 旧包）：

```
PACKAGE_SOURCE_HEAD = 138a2c620f452f97900951877fd9baab7fef8aa9
PACKAGE_PATH        = D:\MY SELF\IKUN\小光\astrbot_plugin_blessed_land_runtime_pre_m6_final.zip
PACKAGE_SHA256      = 5640024c5337cd1d2a3a6bf2e5ed675f50dcfb5ea16bced080e787be71e9bbd7
FILE_COUNT          = 101
METADATA_VISIBLE_AT_EXPECTED_ROOT = TRUE
MAIN_VISIBLE_AT_EXPECTED_ROOT     = TRUE
NESTED_ROOT                       = FALSE
FORBIDDEN_CONTENT                 = FALSE
PACKAGE_STRUCTURE_VALID           = TRUE
```

内容验证（zip CRC 全部通过）：

```
migration f2a7c4e9b1d6（PG TRUNCATE 不可变）  = PRESENT
migration a9d4f2b7c1e8（decision_policy 加宽） = PRESENT
services/scheduler/core.py                    = PRESENT（含 PG-012 修复）
PG012 标记（except sa_exc.DBAPIError / _read_durable_tick_resilient） = PRESENT
tests/ reports/ docs/ scripts/ __pycache__/ .pytest_cache/ venv/
plugin_data/ runtime_state/ backups/ *.db / *.sqlite / World Seed / 凭据 = ABSENT
（唯一 `backup` 命中为生产模块 services/backup_service.py —— 必须存在，非备份数据）
```

## 4. 只替换 plugin source（§6）

```
解压 staging → 逐文件 CRC 校验 → 只清空并重建
  core\data\plugins\astrbot_plugin_blessed_land_runtime
plugin_data（含正式 DB、runtime_state）**完全未触碰**：
PLUGIN_DATA_UNTOUCHED = TRUE（5 个文件哈希前后一致）

LIVE_PLUGIN_TREE_HASH_PRE（部署前）= e2d0bf6b08d61af25b4e11d7945f1b2290a288be35bdd032fc878206a2735fc9
LIVE_RUNTIME_TREE_HASH_POST_DEPLOY = 60e63db1fe969d32f56708c119c905af81752e83abdcb7ff1a50359bb11dc230
LIVE_PLUGIN_SOURCE_MATCH_PACKAGE   = TRUE（staging 与 live 同哈希）
live 源文件数 99 → 101；无 tests 目录；两个 migration 与 PG-012 均在位
```

## 5. 第一次 Launcher 启动（§8）与迁移验证（§9）

由 Owner 经 Launcher 正常启动（生产启动路径：Plugin load → RuntimeHost boot →
`db_lifecycle` → embedded Alembic）：

```
PLUGIN_DISCOVERED / PLUGIN_LOADED = TRUE
  证据：10 个 __pycache__ 目录、.pyc 于 17:55:17 生成（模块确实被导入）；
        插件自身写出 runtime_state 两个文件；HTTP 200
PLUGIN_ERROR        = NONE（scheduler_state.last_error = null；无 UndefinedFunction /
                      DataError / migration failure 迹象）
RUNTIME_HOST_BOOTED = TRUE（authoritative_db.json 于 17:55:17 重新写出）
SCHEDULER_ATTACHED  = TRUE（scheduler_state.json 持续更新，状态 DORMANT）
LAUNCHER_STATE      = RUNNING
STARTUP_TIMEOUT     = FALSE
DASHBOARD_HTTP_6185 = 200
M5.1 logging fix    = 未回归（启动正常、无 300s 超时）
```

迁移结果（只读）：

```
FORMAL_DB_INTEGRITY_POST    = ok
FORMAL_DB_ALEMBIC_HEAD_POST = a9d4f2b7c1e8   ← 由 d7f9b1c3e5a7 正常升级
DECISION_POLICY_COLUMN_WIDTH = 64（VARCHAR(64)）
TABLES_POST                 = 46
world_events 触发器          = blr_world_events_no_update / _no_delete（在位）
FORMAL_DB_SHA256_POST       = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837
FORMAL_DB_SIZE_POST         = 544768
```

PG-only 的 `f2a7c4e9b1d6`（TRUNCATE 触发器）在 SQLite 上按设计 **no-op** ✓
（由 SQLite 分支 `return` 实现，迁移链正常前进且无方言错误）。

## 6. 迁移后世界语义（§10 / §11 / §12）

```
WORLD_RUNTIME_ROWS_POST    = 0        WORLD_EVENTS_ROWS_POST      = 0
SIMULATION_RUN_ROWS_POST   = 0        RUNTIME_LOCK_ROWS_POST      = 0
TIME_RATIO_HISTORY_ROWS_POST = 0      SIMULATION_CHECKPOINTS_POST = 0
PERSONS / POPULATION_GROUPS / SETTLEMENTS / RESOURCE_NODES /
TRIBULATIONS / TIMELINE_ENTRIES / WORLD_STATE_CHANGES = 全部 0
CURRENT_BLESSED_TICK_POST  = NULL（world_runtime 0 行）
WORLD_RUNTIME_STATUS       = NOT_ACTIVATED
WORLD_SEED_CONSUMED        = FALSE
OFFICIAL_WORLD_MUTATIONS   = 0
SCHEDULER_STATUS           = DORMANT（cycle / batches_total /
                             last_successful_commit / 其余计数全 0；last_error = null）
```

**DB hash 变化口径（§11）**：`1d84ee37…` → `7754b1d4…` 属**合法 schema migration**
（head d7f→a9d、decision_policy 加宽），**不判为世界 mutation**；判定依据为
「head 按预期变化 + 官方数据行仍为 0 + World Seed 未消费 + 无 authoritative
simulation rows/events」。该哈希记为
**PRE-M6 STAGED FORMAL DB baseline candidate**。

**authoritative_db.json（§12）**：启动后由 Runtime 重写，
`checksum_sha256 = 7754b1d4…` **等于** `FORMAL_DB_SHA256_POST`
→ `AUTHORITATIVE_DB_CHECKSUM_MATCH = TRUE`（若不一致本阶段即判 FAIL 且不进入第二次启动）。

## 7. 正常停止（§13）

由 Owner 经 Launcher 正常停止：

```
PROCESS_COUNT                        = 0
PORT_6185                            = NOT_LISTENING
FORMAL_DB_INTEGRITY_AFTER_FIRST_STOP = ok
ALEMBIC_HEAD_AFTER_FIRST_STOP        = a9d4f2b7c1e8
FORMAL_DB_SHA256_AFTER_FIRST_STOP    = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837
                                       （与 POST 一致 → 停机期间稳定）
WAL = 0 B / SHM = 32768 B
```

## 8. 第二次 Launcher 启动（§14）与第二次世界复核（§15）

```
SECOND_PLUGIN_LOAD         = PASS
SECOND_RUNTIME_HOST_BOOT   = PASS
SECOND_LAUNCHER_STATE      = RUNNING
SECOND_STARTUP_TIMEOUT     = FALSE
SECOND_DASHBOARD_HTTP      = 200
ALEMBIC_HEAD（第二次启动后） = a9d4f2b7c1e8（不再产生 schema change）
FORMAL_DB_SHA256_POST_SECOND_START = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837
                                       （与 POST / AFTER_FIRST_STOP 完全一致）
MIGRATION_IDEMPOTENT       = PASS

第二次世界安全复核：WORLD_RUNTIME_ROWS = 0、WORLD_EVENTS = 0、SIMULATION_RUN = 0、
RUNTIME_LOCK = 0、TIME_RATIO_HISTORY = 0、CURRENT_BLESSED_TICK = NULL、
WORLD_RUNTIME_STATUS = NOT_ACTIVATED、WORLD_SEED_CONSUMED = FALSE、
SCHEDULER_STATUS = DORMANT、OFFICIAL_WORLD_MUTATIONS = 0
```

## 9. PG-012 / Private Companion / PG 测试环境（§16 / §17 / §18）

```
PG012_PRESENT_IN_LIVE = TRUE
   证据：live services/scheduler/core.py 含 `except sa_exc.DBAPIError` 分支与
         `_read_durable_tick_resilient()`（与 HEAD 同内容；live 树哈希 == 包哈希）
   未在 live SQLite 上制造连接故障（PG-012 已由真实 PG gate 验证）

PRIVATE_COMPANION_SOURCE_UNCHANGED = TRUE（529/529 条目哈希一致，missing 0）
   说明：初次比对出现 1 处差异，查明为**基线文件首行 BOM** 导致的解析假报
   （该文件真实哈希与基线一致；Companion 源码最新 mtime 为 2026-09-08，本阶段未触碰）。
   本阶段未测试 Q1–Q6；KL-M5-001 / KL-M5-002 保持 OWNER_DEFERRED。

PG 测试环境（未改动）：blr-pre-m6-postgres = healthy（PostgreSQL 16.15，TEST ONLY）；
stayops-postgres 未触碰。
```

## 10. 失败/回滚预案（§19，未触发）

本阶段未出现 plugin import failure、migration failure、schema mismatch、
Launcher timeout、Scheduler 非 DORMANT、`world_runtime` 行被创建、World Seed 被消费
或世界事件被创建。回滚点（§2）保持可用；未执行任何回滚。

## 11. Git

```
138a2c6 docs: record the final pre-m6 activation review（staging 起始 HEAD）
（本报告单独 commit；normal fast-forward push；无 amend / rebase / force / 未创建 M6 tag）
packages：D:\MY SELF\IKUN\小光\astrbot_plugin_blessed_land_runtime_pre_m6_final.zip
rollback：D:\MY SELF\IKUN\小光\incident_quarantine\pre_m6_live_staging_20260915_141027
```

## 12. 返回字段（FINAL_PRE_M6_LIVE_STAGING_REPORT）

```
FINAL_PRE_M6_LIVE_STAGING_REPORT

CURRENT_HEAD        = 138a2c620f452f97900951877fd9baab7fef8aa9
PACKAGE_SOURCE_HEAD = 138a2c620f452f97900951877fd9baab7fef8aa9
PACKAGE_SHA256      = 5640024c5337cd1d2a3a6bf2e5ed675f50dcfb5ea16bced080e787be71e9bbd7

PRE_M6_ROLLBACK_PATH    = D:\MY SELF\IKUN\小光\incident_quarantine\pre_m6_live_staging_20260915_141027
PRE_M6_PLUGIN_TREE_HASH = e2d0bf6b08d61af25b4e11d7945f1b2290a288be35bdd032fc878206a2735fc9
PRE_M6_DB_BACKUP_SHA256 = ac4d2e53f17a0f313ac3ab5c4897665067bcfd2cadb6ffc7a9c1b7d4d708c89f

LIVE_PLUGIN_SOURCE_MATCH_PACKAGE = TRUE

FORMAL_DB_ALEMBIC_HEAD_PRE  = d7f9b1c3e5a7
FORMAL_DB_ALEMBIC_HEAD_POST = a9d4f2b7c1e8

FORMAL_DB_SHA256_PRE              = 1d84ee370167b047265bd2200c69c7373372fb0b594bf7ac073b33097de52cf2
FORMAL_DB_SHA256_POST             = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837
FORMAL_DB_SHA256_AFTER_FIRST_STOP = 7754b1d4658ea94ce509ae7fb7c06c33c44f98782021b3708e6f29ce69102837

FORMAL_DB_INTEGRITY = ok

DECISION_POLICY_COLUMN_WIDTH = 64

AUTHORITATIVE_DB_CHECKSUM_MATCH = TRUE

FIRST_PLUGIN_LOADED    = TRUE
FIRST_PLUGIN_ERROR     = NONE
FIRST_LAUNCHER_STATE   = RUNNING（STARTUP_TIMEOUT = FALSE）
FIRST_DASHBOARD_HTTP   = 200
FIRST_SCHEDULER_STATUS = DORMANT

FIRST_LAUNCHER_STOP = PASS（PROCESS_COUNT 0 / PORT 6185 NOT_LISTENING / integrity ok）

SECOND_PLUGIN_LOADED    = TRUE
SECOND_PLUGIN_ERROR     = NONE
SECOND_LAUNCHER_STATE   = RUNNING（STARTUP_TIMEOUT = FALSE）
SECOND_DASHBOARD_HTTP   = 200
SECOND_SCHEDULER_STATUS = DORMANT

MIGRATION_IDEMPOTENT = PASS

PG012_PRESENT_IN_LIVE = TRUE

WORLD_RUNTIME_ROWS      = 0
CURRENT_BLESSED_TICK    = NULL
OFFICIAL_WORLD_EVENTS   = 0
OFFICIAL_WORLD_MUTATIONS = 0
WORLD_SEED_CONSUMED     = FALSE

PRIVATE_COMPANION_SOURCE_UNCHANGED = TRUE

FINAL_PRE_M6_LIVE_STAGING = PASS
PRE_M6_LIVE_READY         = TRUE

M6_ACTIVATION = PROHIBITED_PENDING_OWNER_EXPLICIT_ACTIVATION_AUTHORIZATION

NEXT_ACTION = AWAIT_OWNER_REVIEW_FOR_M6_WORLD_ACTIVATION
```

**STOP** — 未进入 M6；未消费 World Seed；未创建正式 `world_runtime` 行；
未推进 blessed tick；未运行 simulation；未生成正式 history。

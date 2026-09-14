# PRE-M6 POSTGRESQL GATE IMPLEMENTATION — 第一阶段报告（PG Portability Hardening）

- 报告时间：2026-09-14（本地）
- 阶段：`PRE-M6 POSTGRESQL GATE IMPLEMENTATION` 第一阶段（§22：先做 PG-001 / PG-002 / PG-006 / PG-008）
- 基准修订：`ac8d422aab6c49f67852b90c3bcc60686058c4dc`（`M5_FINAL_HEAD`）
- 权威依据：owner 裁决 `PRE_M6_PG_ENVIRONMENT_DECISION = DOCKER_POSTGRES`、
  `PG_DRIVER_INSTALL_AUTHORIZED = TRUE`（`PG_DRIVER_SCOPE = DEVELOPMENT_AND_TEST_ONLY`）、
  `M6_ACTIVATION = PROHIBITED`
- 本阶段**未**进行：Docker 环境建设、PG 驱动安装、任何 PG 实跑（属下一阶段，须等 owner 复核）

---

## 1. 执行顺序与状态（§1 / §22）

```
PG portability code hardening        = DONE（PG-001 / PG-002 / PG-006 / PG-008）
portability regression（SQLite）      = PASS（全量 fast 回归已完成，见 §7）
Docker environment bring-up          = NOT_STARTED（§7 门禁：须 owner 复核后进入）
PostgreSQL driver                    = NOT_INSTALLED（未安装，未触碰 live venv）
schema / fresh / existing DB         = NOT_STARTED
single writer / fencing              = NOT_STARTED
determinism / restart / chunk        = NOT_STARTED
history integrity on PG              = NOT_STARTED
real commit ambiguity harness        = NOT_STARTED（PG-009 下一阶段）
full PG gate review                  = NOT_STARTED
```

**未跳过 portability hardening**，也未据此声称 PG gate ready。

---

## 2. PG-001 — 生产代码 SQLite-only SQL 修复

**缺陷**：`services/simulation/recovery.py`（权威恢复路径，被
`services/simulation/coordinator.py:46` 直接导入）使用 SQLite 私有
`json_extract(meta, '$.checkpoint_kind')`（3 处），且 `count_checkpoints_by_kind`
使用 `complete = 1` 这种 SQLite 隐式布尔比较（PG 布尔列拒绝与整数比较）。

**修法（按 owner 指定优先级：先 SQLAlchemy 可移植表达式）**：
不使用「if postgres: 另一段字符串 SQL」，而是改用 ORM 可移植 JSON 比较
`SimulationCheckpoint.meta["key"].as_string() == value`，方言由 SQLAlchemy 适配，
并把查询抽成可复用的 statement 工厂（供执行与跨方言编译测试复用）：

- `authoritative_checkpoint_statement(world_id)`
- `checkpoint_count_statement(world_id, key, value)`
- `latest_authoritative_world_checkpoint()` / `count_checkpoints_by_kind()` 语义不变

**编译结果（实测）**：

| 方言 | 生成 SQL 片段 |
| --- | --- |
| SQLite | `... AND simulation_checkpoints.complete IS 1 AND JSON_EXTRACT(meta, '$."checkpoint_kind"') = 'WORLD_COMMITTED'` |
| PostgreSQL | `... AND simulation_checkpoints.complete IS true AND CAST((meta ->> 'checkpoint_kind') AS VARCHAR) = 'WORLD_COMMITTED'` |

**等价性证据（old vs new，同一合成 SQLite 库，5 个用例）**：

```
[mixed]              old_tick=80  new_tick=80   counts 一致 EQUIVALENT=True
[empty]              old=None     new=None      counts 一致 EQUIVALENT=True
[only_catchup]       old=None     new=None      counts 一致 EQUIVALENT=True
[incomplete_only]    old=None     new=None      counts 一致 EQUIVALENT=True
[same_tick_tiebreak] old=70       new=70        counts 一致 EQUIVALENT=True
ALL_EQUIVALENT = True
```

要求对照：`SQLite behavior unchanged = TRUE`、`PostgreSQL behavior equivalent =
（编译级等价；**PG 实跑待环境建设后验证**）`、`determinism unchanged = TRUE`
（全量回归覆盖）。

## 3. PG-002 — 兼容性审计覆盖面扩大

**新增** `tests/pg_portability_scan.py`（AST 级静态扫描器）：

1. 扫描范围 = 授权生产路径 `main.py` / `config/` / `domain/` / `database/` /
   `services/` / `plugin_shell/`；排除 `tests/`、`docs/`、`scripts/`、`__pycache__`；
2. **方言分支规则**：SQLite 专有构造只允许出现在显式 `if <test 含 "sqlite">:`
   分支体内（契约 §2/§7 许可的 adapter 形态），否则违规；
3. **最小白名单**：仅 `services/backup_service.py`（契约 §2 唯一许可的
   sqlite3/PRAGMA adapter，且 `_require_sqlite` 对非 sqlite URL fail-closed）；
   白名单的防护符号存在性由测试断言，防止白名单静默腐烂；
4. 只扫描**非 docstring 字符串常量**（注释/文档不执行 SQL，避免误判）。

**覆盖构造**：`json_extract`/`json_each`/`json_tree`/`json_set` 等 JSON1 函数族、
`PRAGMA`、`sqlite_master`/`sqlite_schema`/`sqlite_sequence`、`INSERT OR REPLACE`/
`INSERT OR IGNORE`/`UPDATE OR REPLACE`、`AUTOINCREMENT`、`rowid`/`WITHOUT ROWID`、
`RAISE(...)`、`ATTACH`/`DETACH`/`VACUUM`、`strftime(`/`julianday(`/`datetime(`/
`ifnull(`/`instr(`/`iif(`/`group_concat(`/`last_insert_rowid(`/`randomblob(`/
`printf(`、`GLOB`。

**扫描结果**：`files_scanned = 90`、`violations = 0`（白名单 1 个文件）。

**非空过证明（关键）**：对修复前（`git show HEAD:…recovery.py`）运行扫描器：

```
HEAD（修复前）    : violations = 3  → line 33 / 43 / 47 全部 [json_extract]
WORKTREE（修复后）: violations = 0
```

`tests/test_ta59_postgresql_contract_audit` 已改为委托该扫描器（覆盖全生产路径 +
显式包含 `recovery.py`），原来的 3 文件局部扫描不再存在。

## 4. PG-006 — PostgreSQL TRUNCATE 不可变保护

**缺口**：PG 的 `BEFORE UPDATE OR DELETE FOR EACH ROW` 触发器**不拦 `TRUNCATE`**
（TRUNCATE 不产生行事件）→ `TRUNCATE TABLE world_events` 会静默清空事件历史。

**方案选择（§4：优先与既有 schema/migration 模型一致的方案）**：采用 **方案 A
BEFORE TRUNCATE 触发器**（与 `b2d4e8f9a6c3` 的触发器 + plpgsql 函数写法一致）；
不采用 `REVOKE TRUNCATE`（依赖角色/属主，且属主与超级用户可绕过，不构成 DB 层硬保证）。

**新增 migration**：`database/alembic/versions/f2a7c4e9b1d6_p1_pg_event_truncate_immutability.py`

- `revision = f2a7c4e9b1d6`，`down_revision = d7f9b1c3e5a7`
- PG 分支：`CREATE OR REPLACE FUNCTION blr_world_events_no_truncate()` +
  `CREATE TRIGGER blr_world_events_no_truncate BEFORE TRUNCATE ON world_events
  FOR EACH STATEMENT EXECUTE FUNCTION …`（`RAISE EXCEPTION`）
- SQLite 分支：**no-op**（SQLite 无 TRUNCATE 语句；DELETE 已由既有触发器拦截）
- 未知方言：`NotImplementedError`（fail-closed，与既有 migration 风格一致）
- 范围仅 `world_events`（当前 schema 中唯一具 DB 层不可变保护的权威表）；
  不静默扩大保护面

**invariants 扩展**：`database/invariants.py` 新增
`event_truncate_protection_present(engine)` 并纳入 `verify_event_immutability`：
- SQLite：恒为 True 且**不发起查询**（行为与扩展前完全一致）
- PostgreSQL：要求 `pg_trigger` 中存在 `blr_world_events_no_truncate`
- 缺失即 `IntegrityError`（fail-closed），不依赖应用层「不调用 TRUNCATE」

**测试覆盖（SQLite 可执行部分 + PG 分支逻辑）**：UPDATE 拒绝、DELETE 拒绝、
INSERT 允许、SQLite 无 TRUNCATE 语句（语法错误）、migration 在 SQLite 为 no-op、
`downgrade → upgrade` 往返、head 前进、触发器数量仍为 2；
PG 分支用 stub engine 覆盖（计数 0 → 保护缺失、计数 1 → 在位、
`verify_event_immutability` 在 TRUNCATE 触发器缺失时 fail-closed、未知方言 False）。

**待验证（不掩盖）**：PG 触发器 DDL 的真实执行与 `TRUNCATE` 拒绝行为
**必须在 PG 环境建设后实测**（本阶段无 PG，属未验证项）。

## 5. PG-008 — 文档勘误（不得伪称能力）

- `POSTGRESQL_COMPATIBILITY_CONTRACT.md`
  - §1：递归 CTE 改为「允许但当前未使用」；
  - §5：明确允许 SQLAlchemy 可移植 JSON 索引比较（`…as_string() == value`，
    方言由 SQLAlchemy 适配），仍禁止手写方言函数与隐式布尔比较；
  - §6.5：`PG_RECURSIVE_CTE_REQUIREMENT = N/A`，
    `APPLICATION_DFS_CAUSAL_CYCLE_CHECK = IMPLEMENTED`
    （环检测为应用层迭代式 3-color DFS：`services/history/service.py::_find_cycles`）；
    并注明「不得为满足旧文字新写递归 CTE」；
  - 新增 §8.5（TRUNCATE 保护）与 §9（本轮勘误与硬化记录表）。
- `runtime_design/M3_PREFLIGHT_TRIBULATION_AND_HISTORY_CONTRACT.md` §21：
  明确实现选择为应用层图遍历（无递归 CTE）。
- `docs/pre_m6_pg_gate_audit.md`：顶部新增阶段更新说明（PG-001/002/006/008 状态、
  head 变更），审计当时的快照内容保持原样不改写。

## 6. 连带变更：ALEMBIC_HEAD 与常量同步

```
ALEMBIC_HEAD: d7f9b1c3e5a7 → f2a7c4e9b1d6
```

三处常量同步（并由测试断言与 alembic 链一致，防 head 漂移）：
`tests/conftest.py::HEAD_REVISION`、`plugin_shell/runtime_host.py::EXPECTED_SCHEMA_HEAD`、
`scripts/migrate_db_to_plugin_data.py::EXPECTED_SCHEMA_HEAD`。

**对 live / 正式库的影响（须 owner 知晓）**：

- 本阶段**未部署**、**未重启** live 实例：live 插件源码与 `EXPECTED_SCHEMA_HEAD`
  仍为 `ac8d422` / `d7f9b1c3e5a7`，与正式库现状自洽；
- 未来若部署本次改动并启动，`alembic upgrade head` 会在正式库上执行本 migration
  （SQLite 侧为 no-op：仅更新 `alembic_version` 一行 + `world_runtime.schema_version`
  校正），**不新增表、不改数据、不触碰世界状态**；
- 该部署动作**不在本阶段授权范围内**，须 owner 单独批准。

## 7. 回归结果（SQLite，全量 fast 回归已完整结束）

```
SQLITE_REGRESSION          = PASS
VERDICT（runner 判定）      = PASS
FAILED                     = 0
ERRORS                     = 0
SKIPPED                    = 13（全部为预期 skip，见下）
UNEXPECTED_SKIPS           = 0
COLLECTED                  = 784
PASSED                     = 771
DURATION                   = 26417.9s（7h20m18s）
GOLDEN_BASELINE_MUTATIONS  = 0（tests/baselines 全目录零改动：git diff --exit-code 通过，
                              36 个基线文件与 HEAD 逐字节一致）
M0_M4_SEMANTICS_CHANGES    = 0（services/scheduler 与 M0–M4 语义面零改动；
                              services/simulation 仅 recovery.py 可移植性重构，
                              已由 5 用例 old/new 等价性 + 定向测试证明行为不变）
```

**分块明细（分块 = 独立 JUnit + 独立退出码；测试文件按轮转均匀分配）**：

| 分块 | 文件数 | COLLECTED | PASSED | FAILED | ERRORS | SKIPPED | EXIT | 耗时 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Group 1 | 11 | 178 | 174 | 0 | 0 | 4 | 0 | 7880.3s（2h11m） |
| Group 2 | 10 | 166 | 163 | 0 | 0 | 3 | 0 | 6443.6s（1h47m） |
| Group 3 | 10 | 136 | 135 | 0 | 0 | 1 | 0 | 9420.2s（2h37m） |
| Group 4 | 10 | 130 | 129 | 0 | 0 | 1 | 0 | 1445.1s（0h24m） |
| Group 5 | 10 | 174 | 170 | 0 | 0 | 4 | 0 | 1228.7s（0h20m） |
| **合计** | **51** | **784** | **771** | **0** | **0** | **13** | **0** | **26417.9s** |

**覆盖完整性核验（防止分块造成漏测）**：`tests/test_*.py` 共 51 个文件，
分块并集 = 51，`MISSING_FROM_GROUPS = []`、`EXTRA_IN_GROUPS = []`、
跨分块重复文件 = `[]`、跨分块重复用例 = `[]`。

**13 个 SKIP 分类（全部预期，`UNEXPECTED_SKIPS = 0`）**：

- 12 个为**正式库守卫**（`EXPECTED_FORMAL_DB_SKIP`）：在 Decision A 的
  「规范未设置 `BLR_FORMAL_DB_PATH`」模式下按设计跳过
  （`test_mr11 / ec44 / ec45 / hb36 / sd54 / sd55 / ma26 / pa34_pa35 / tp30 /
  rb52 / rb53 / ta56`）；
- 1 个为**PG 集成入口**：`test_pg_recovery_integration_entrypoint` 需
  `BLR_TEST_PG_DSN` + `BLR_TEST_PG_ALLOW=1`，属 PG 环境建设阶段启用项。

**执行环境事故与恢复（如实记录）**：本环境周期性投递 `0xC000013A`
（STATUS_CONTROL_C_EXIT）。第一版 detached runner 的 pytest 子进程未做进程组隔离，
于 22.3 分钟处被杀（JUnit 未写出 → 该次结果作废）。v2 runner 修正为：包装器与
**每个 pytest 子进程**均 `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP |
CREATE_NO_WINDOW`，按文件分 5 块、每块独立 JUnit、分块不完整自动重试、
最终 verdict 仅在「所有分块完成且 failed/errors = 0」时为 PASS。
期间发生 DeepSeek API 中断（约 05:31–10:48 期间无法观测），**测试进程与结果不受影响**：
5 个分块全部在无人干预下跑完（09:11:03 结束），`incomplete_groups = []`、
`failed_groups = []`、`attempts = 1`（无重试即完成），
故本阶段**未重跑任何已通过的分块**（Group 1–5 均为首次尝试即 PASS）。

**定向测试（已完成，全部通过）**：

| 批次 | 内容 | 结果 |
| --- | --- | --- |
| 批次 1 | 3 个新测试文件 + `test_database.py`（schema/迁移/触发器） | 40 collected → 修正 1 处断言后全通过 |
| 批次 2 | `test_ta59` + `test_logging_isolation.py` + `test_backup_events.py` + `test_plugin_shell.py` + `test_hardening_hp.py` | 52 passed |
| 批次 3 | `test_fencing` / `test_writer_recovery` / `test_scheduler_fencing` / `test_scheduler_single_writer` / `test_scheduler_commit_ambiguity` / `test_scheduler_ack_lost` / `test_scheduler_crash_recovery` / `test_m2b_commit_ambiguity` | 53 passed |
| 批次 4 | `test_pg_event_truncate_protection.py`（含新增 stub 覆盖与 migration 往返） | 15 passed |

**被回归覆盖的产物指纹**：分块运行开始前记录的 13 个关键文件 sha256 前缀，
在回归结束后**逐一比对无漂移**（`FINGERPRINT_UNCHANGED`）→
「被测试产物 == 当前工作区产物」，回归结论对本阶段交付物有效。

## 8. 新增/修改文件清单

**代码与迁移（生产面）**

| 文件 | 变更 |
| --- | --- |
| `services/simulation/recovery.py` | PG-001 修复：可移植 JSON 表达式 + statement 工厂 |
| `database/invariants.py` | PG-006：TRUNCATE 保护校验 + 触发器名常量 |
| `database/alembic/versions/f2a7c4e9b1d6_p1_pg_event_truncate_immutability.py` | **新增 migration**（PG TRUNCATE 保护；SQLite no-op） |
| `plugin_shell/runtime_host.py` | `EXPECTED_SCHEMA_HEAD` 同步 |
| `scripts/migrate_db_to_plugin_data.py` | `EXPECTED_SCHEMA_HEAD` 同步 |

**测试面**

| 文件 | 变更 |
| --- | --- |
| `tests/pg_portability_scan.py` | **新增**：PG portability 静态扫描器 |
| `tests/test_pg_portability_static_audit.py` | **新增**：8 项（含扫描器自证/非空过/白名单守卫/覆盖断言） |
| `tests/test_pg_recovery_checkpoint_portability.py` | **新增**：11 项（SQLite 行为、跨方言编译、PG 集成入口 + DSN 守卫） |
| `tests/test_pg_event_truncate_protection.py` | **新增**：15 项（migration 链/静态分支/SQLite no-op/PG stub 分支/fail-closed） |
| `tests/test_m3a_tribulation.py` | `test_ta59` 改为委托全生产路径扫描器 |
| `tests/conftest.py` | `HEAD_REVISION` 同步 |

**文档面**：`POSTGRESQL_COMPATIBILITY_CONTRACT.md`、
`runtime_design/M3_PREFLIGHT_TRIBULATION_AND_HISTORY_CONTRACT.md`、
`docs/pre_m6_pg_gate_audit.md`（阶段更新说明）、
`reports/M5_FINAL_CLOSEOUT.md`（上一阶段产物，本阶段一并入库）。

## 9. 世界安全与禁令遵守

```
WORLD_RUNTIME_STATUS      = NOT_ACTIVATED（未改变）
CURRENT_BLESSED_TICK      = NULL（未改变）
OFFICIAL_WORLD_EVENTS     = 0
OFFICIAL_WORLD_MUTATIONS  = 0
WORLD_SEED_CONSUMED       = FALSE
M6_ACTIVATION             = PROHIBITED（未进入 M6）
live AstrBot 实例          = 保持运行原状（PID 56560 / 1744 未重启、未部署新代码）
formal DB 写入             = 0（未对正式库执行任何迁移/DDL/DML）
PRIVATE_COMPANION         = 未修改（KL-M5-001/002 保持 DEFERRED，未扩大 scope）
PG 驱动安装                = 未执行（未安装到 dev/test，更未触碰 live venv）
Docker 容器                = 未创建（未启动 Docker daemon）
手工复制 site-packages      = 未发生
```

**世界安全核验证据（回归结束后实测）**：

| 项 | 实测 | 结论 |
| --- | --- | --- |
| `runtime_state/scheduler_state.json` | `world_id = FORMAL-UNSEEDED`、`scheduler_state = DORMANT`、`pause_state = false`、`last_error = null`，counters **全 0**（cycle / batches_total / recovery / lease_takeover / stale_writer_rejection / commit_ambiguity / last_successful_commit / last_batch_ticks） | 世界零 mutation、零接管、零歧义 |
| `runtime_state/authoritative_db.json` | `checksum_sha256 = 1d84ee370167b047265bd2200c69c7373372fb0b594bf7ac073b33097de52cf2`，`written_at = 2026-09-13T16:46:08Z` | 与 M5 冻结校验和**逐字一致**，正式库自本次启动以来未被改写 |
| 正式库文件 | `blessed_land.sqlite` 536576 B，mtime `09-12 09:53:41`（早于本次启动）；`-wal` = 0 B | 主库文件在回归期间 mtime/大小未变 |
| 回归环境 | runner info JSON：`formal_db_env_present = false` | 回归在 Decision A 规范模式下执行，**未注入 `BLR_FORMAL_DB_PATH`**，测试不可能写到正式库 |
| live 插件源码 | 源文件 99；**不存在** `f2a7c4e9b1d6_p1_pg_event_truncate_immutability.py`，**不存在** `tests/` 目录 | 未发生任何 live 部署，live 仍为 M5.2 包 |
| 进程面 | 仅 live 实例 PID 56560（venvlauncher stub）与 1744（真实后端，`…\core\main.py`）存活；**无任何 PRE-M6 测试进程** | 测试进程已全部退出；未按名称批量 kill 任何进程 |

## 10. 环境状态（下一阶段输入）

```
DOCKER_CLI                 = PRESENT（C:\Program Files\Docker\Docker\resources\bin\docker.exe）
DOCKER_DAEMON_STATUS       = NOT_RUNNING（npipe:////./pipe/dockerDesktopLinuxEngine 不存在）
PG_DRIVER_STATUS           = ABSENT（psycopg / psycopg2 / asyncpg / pg8000 在 dev python 均不可导入）
POSTGRESQL_SERVER          = ABSENT（psql/pg_ctl/服务/5432 均无）
```

## 11. 返回字段（PRE_M6_PG_PORTABILITY_FIX_REPORT）

```
PRE_M6_PG_PORTABILITY_FIX_REPORT

FILES_MODIFIED            = 8（生产/测试/文档面被跟踪文件）+ 5 新增文件
MIGRATIONS_ADDED          = 1（f2a7c4e9b1d6_p1_pg_event_truncate_immutability）
TESTS_ADDED               = 34（8 + 11 + 15，全部通过）

PG001_STATUS              = FIXED（源码 0 处 SQLite-only SQL；SQLite 行为等价已验证；
                            PG 侧为编译级等价，实跑待 PG 环境）
PG002_STATUS              = FIXED（全生产路径静态门禁；90 文件扫描 0 违规；
                            修复前同一扫描器可捕获 3 处 json_extract → 非空过）
PG006_STATUS              = FIXED_AT_SCHEMA_LEVEL（migration + invariants + 测试；
                            PG 触发器实际创建/TRUNCATE 拒绝行为待 PG 实跑验证）
PG008_STATUS              = CORRECTED（PG_RECURSIVE_CTE_REQUIREMENT = N/A；
                            APPLICATION_DFS_CAUSAL_CYCLE_CHECK = IMPLEMENTED）

SQLITE_ONLY_PRODUCTION_SQL = 0（生产面；白名单仅 services/backup_service.py，
                            且其 fail-closed 守卫由测试断言）
SQLITE_REGRESSION          = PASS（784 collected / 771 passed / 0 failed /
                            0 errors / 13 expected skips；5 分块全部 exit 0；
                            26417.9s；覆盖 51/51 测试文件，无漏测无重复）
GOLDEN_BASELINE_MUTATIONS  = 0

DOCKER_DAEMON_STATUS       = NOT_RUNNING
PG_DRIVER_STATUS           = ABSENT（本阶段未安装）

WORLD_RUNTIME_STATUS       = NOT_ACTIVATED
WORLD_SEED_CONSUMED        = FALSE

NEXT_ACTION                = AWAIT_OWNER_REVIEW_FOR_PG_ENVIRONMENT_BRINGUP
```

## 12. 现场恢复与结果接管（PRE_M6_REGRESSION_RECOVERY_REPORT）

DeepSeek API 中断期间测试在 detached 模式下继续运行并已完成；本节为**接管核验**结果
（只读，未重跑任何已通过分块，未修改任何代码）。

```
PRE_M6_REGRESSION_RECOVERY_REPORT

LIVE_TEST_PROCESSES        = NONE（所有 PRE-M6 runner/pytest 进程已退出；
                             存活 python 进程仅 live 实例 PID 56560 / 1744）
GROUP_1_STATUS             = PASS（178 collected / 174 passed / 4 skipped / exit 0 / 7880.3s）
GROUP_2_STATUS             = PASS（166 collected / 163 passed / 3 skipped / exit 0 / 6443.6s）
GROUP_3_STATUS             = PASS（136 collected / 135 passed / 1 skipped / exit 0 / 9420.2s）
GROUP_4_STATUS             = PASS（130 collected / 129 passed / 1 skipped / exit 0 / 1445.1s）
GROUP_5_STATUS             = PASS（174 collected / 170 passed / 4 skipped / exit 0 / 1228.7s）

COMPLETED_GROUPS           = 1,2,3,4,5（attempts = 1，均首次尝试即完成）
INTERRUPTED_GROUPS         = NONE
NOT_STARTED_GROUPS         = NONE
RERUN_GROUPS               = NONE（未重跑任何分块）

GROUP_TOTALS               = collected 784 / passed 771 / failed 0 / errors 0 / skipped 13
FAILED                     = 0
ERRORS                     = 0
SKIPPED                    = 13（12 × EXPECTED_FORMAL_DB_SKIP + 1 × PG 集成入口）
UNEXPECTED_SKIPS           = 0

GOLDEN_BASELINE_MUTATIONS  = 0（git diff --exit-code -- tests/baselines 通过；
                             36 个基线文件与 HEAD 逐字节一致）
WORLD_RUNTIME_STATUS       = NOT_ACTIVATED
WORLD_SEED_CONSUMED        = FALSE

PORTABILITY_STAGE_READY_TO_CLOSE = TRUE
NEXT_REQUIRED_ACTION       = AWAIT_OWNER_AUTHORIZATION_FOR_PG_ENVIRONMENT_BRINGUP
                             （Docker daemon 启动 + 专用测试容器 + dev/test-only
                             psycopg3 安装；在此之前 M6_ACTIVATION = PROHIBITED）
```

**STOP** — 未进入 M6；等待 owner 复核后再进入 Docker/PG 环境建设与驱动安装。

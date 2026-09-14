# PRE-M6 PG DRIVER OFFLINE WHEELHOUSE PREPARATION + INSTALL — 报告

- 报告时间：2026-09-14（本地）
- 阶段：`PRE_M6_PG_DRIVER_AND_ENV_CONTINUATION`
- 权威基准修订：`HEAD = 6bbca16`（`docs: record pre-m6 postgres environment bring-up (blocked on driver install)`）
- 代码 head：`ALEMBIC_HEAD = f2a7c4e9b1d6`（未漂移）
- 阶段结论：**驱动离线门禁全部通过；PG 迁移/连通性/事件不可变性已在真实 PostgreSQL 上实跑通过。**
  过程中门禁发现 2 个真实缺陷（PG-009 迁移缺 `USING`、PG-010 集成入口不完整），已最小修复并复验。
- `M6_ACTIVATION = PROHIBITED`（未进入 M6）

---

## 0. 关键发现：wheelhouse 与主人描述不一致（如实记录，未做任何删除）

`D:\MY SELF\IKUN\小光\pg-wheelhouse\` 在审计时为**空目录**（`COUNT=0`，
仅目录本身，创建时间与本轮开始时间同刻）。截图中描述的 4 个文件
（`psycopg_binary-3.3.5-cp314-cp314-win_amd64.whl`、`psycopg-3.3.5.tar.gz`、
`typing_extensions-4.16.0.tar.gz`、`tzdata-2026.3.tar.gz`）**在审计时不存在**。

```
CURRENT_BAD_ARTIFACTS = NONE_PRESENT（目录为空；无 cp314 wheel、无任何 tar.gz）
```

处置：**未安装、未删除、未改动**任何既有文件（不存在可删除对象）；
在 `/d/MY SELF/IKUN` 全树递归检索 `*.whl` / `*.tar.gz` 结果为空，
在 `Downloads` / `Desktop` 检索 `*.whl` / `*.tar.gz` 结果为空。
→ 无「保留的来源记录」可保留，此项以 `NONE_PRESENT` 如实回报，不做补造。

---

## 1. 正确官方 wheel 获取（§3）

网络策略：本轮 harness 代理**允许**访问官方 PyPI（与上一轮 403 状态不同）。

```
curl https://pypi.org/simple/psycopg/      → HTTP 200
curl https://files.pythonhosted.org/       → HTTP 200
pip config list                            → 空（无第三方 index 配置）
env | grep -i proxy                        → 空（无 proxy 变量）
```

**独立来源确认**：四个文件的官方 PyPI JSON API 摘要
（`https://pypi.org/pypi/<pkg>/<ver>/json`）给出的 `digests.sha256`
与主人给定 EXPECTED_SHA256 **逐字符一致**——在下载之前即完成交叉验证，
证明主人给的期望值就是官方 artifact 的摘要（非猜测值）。

下载目标与 URL 均来自 `files.pythonhosted.org`（官方 CDN）：

| 文件 | 大小 (B) | SHA256 |
| --- | --- | --- |
| `psycopg-3.3.5-py3-none-any.whl` | 213 598 | `ce5aa5cd…21af4e` |
| `psycopg_binary-3.3.5-cp311-cp311-win_amd64.whl` | 3 665 235 | `7b443f94…252080` |
| `typing_extensions-4.16.0-py3-none-any.whl` | 45 571 | `481caa48…70c2e8` |
| `tzdata-2026.3-py2.py3-none-any.whl` | 348 168 | `dc096730…e54931` |

`schemaVersion=1` 语义：以上四文件即 `CORRECT_WHEELS_PRESENT` 全集。

**未使用**：第三方下载站、未知镜像、手工构造 wheel、site-packages 拷贝、
`--trusted-host`、关闭 TLS 校验。

---

## 2. SHA256 强校验（§5）

逐个计算并与 EXPECTED 比对：

```
PSYCOPG_WHEEL_HASH_MATCH          = TRUE
PSYCOPG_BINARY_WHEEL_HASH_MATCH   = TRUE
TYPING_EXTENSIONS_WHEEL_HASH_MATCH = TRUE
TZDATA_WHEEL_HASH_MATCH           = TRUE
```

附加完整性：4 个 wheel 的 ZIP 结构 `testzip()` 全部 `OK`（无损坏）。
无任何 FALSE → 未触发 `BLOCKED_ARTIFACT_HASH_MISMATCH`。

---

## 3. Wheel 标签兼容性（§6）

运行环境实测：`Python 3.11.9 (tags/v3.11.9:de54cf5) [MSC v.1938 64 bit (AMD64)]`、
`platform.machine() = AMD64`、`sys.platform = win32`。

wheel 内 `*.dist-info/WHEEL` 实读：

| wheel | Tag |
| --- | --- |
| `psycopg_binary-3.3.5-cp311-cp311-win_amd64.whl` | `cp311-cp311-win_amd64` ✅ |
| `psycopg-3.3.5-py3-none-any.whl` | `py3-none-any` |
| `typing_extensions-4.16.0-py3-none-any.whl` | `py3-none-any` |
| `tzdata-2026.3-py2.py3-none-any.whl` | `py2-none-any` / `py3-none-any` |

无 `cp314` / `cp312` / `linux` / `macOS` 标签。

```
WHEEL_TAG_COMPATIBILITY = PASS
```

---

## 4. 完全离线 pip 安装（§7 / §8）

安装范围（唯一）：

```
PG_DRIVER_INSTALL_SCOPE = DEV_TEST_ONLY
PG_DRIVER_ENV           = %TEMP%\blr-pre-m6-pg-venv
                          （全新独立 venv，pyvenv.cfg: include-system-site-packages = false）
```

**未触碰**：系统 Python、live AstrBot venv、Private Companion、Runtime live environment。

执行（owner 指定命令；仅追加 `--disable-pip-version-check` 以杜绝 pip 自更新探测，
属**收紧**而非绕过——`--no-index` 本身已禁止任何 index 访问）：

```
<pg-venv>\Scripts\python.exe -m pip install ^
  --no-index ^
  --disable-pip-version-check ^
  --find-links "D:\MY SELF\IKUN\小光\pg-wheelhouse" ^
  "psycopg[binary]==3.3.5"
```

实跑输出（关键行）：

```
Looking in links: d:\MY SELF\IKUN\小光\pg-wheelhouse
Processing ...\psycopg-3.3.5-py3-none-any.whl (from psycopg[binary]==3.3.5)
Processing ...\typing_extensions-4.16.0-py3-none-any.whl (from psycopg==3.3.5->psycopg[binary]==3.3.5)
Processing ...\tzdata-2026.3-py2.py3-none-any.whl (from psycopg==3.3.5->psycopg[binary]==3.3.5)
Processing ...\psycopg_binary-3.3.5-cp311-cp311-win_amd64.whl (from psycopg[binary]==3.3.5)
Successfully installed psycopg-3.3.5 psycopg-binary-3.3.5 typing_extensions-4.16.0 tzdata-2026.3
```

- 全部 4 个依赖均从本地 wheelhouse 解析（含两个传递依赖 `typing-extensions`/`tzdata`）；
- **零网络**（`--no-index`，无任何 index/URL 访问行）；
- **零 source build**（无 `Building wheel` / `Running setup.py`）——未触碰任何 tar.gz。

```
PG_DRIVER              = psycopg（psycopg 3，binary 实现）
PG_DRIVER_VERSION      = 3.3.5
PG_DRIVER_STATUS       = READY
```

---

## 5. 安装后验证（§9）

```
PSYCOPG_IMPORT     = PASS
psycopg.__version__ = 3.3.5
libpq impl         = binary（psycopg_binary 3.3.5，libpq 18.0.4）
DEPENDENCY_CHECK   = PASS（pip check → "No broken requirements found."）
```

PG venv 最终包集：
`psycopg 3.3.5 / psycopg-binary 3.3.5 / typing_extensions 4.16.0 / tzdata 2026.3 /
SQLAlchemy 2.0.52 / alembic 1.19.2 / Mako 1.4.1 / MarkupSafe 3.0.3 /
pytest 9.1.1 / pluggy 1.6.0 / iniconfig 2.3.0 / packaging 26.3 / Pygments 2.21.0 / colorama 0.4.6`

**测试运行依赖的补充说明（诚实标注）**：§8 的离线门禁只覆盖 `psycopg[binary]==3.3.5`。
要执行 §10 的 SQLAlchemy 连通性与 alembic 迁移门禁，同一解释器还需
`SQLAlchemy / alembic / pytest`。处理方式：以 `pip download --only-binary=:all:`
从官方 PyPI 取**与 dev 环境同版本**的 wheel 到独立的
`D:\MY SELF\IKUN\小光\pg-wheelhouse-testdeps\`，再以
`--no-index --find-links <该目录>` **离线**装入同一 PG venv。
主 wheelhouse（`pg-wheelhouse`）内容**保持恰为 §3 的 4 个文件**，psycopg 门禁未被稀释。

---

## 6. PostgreSQL 连通性（§10 前两项）

容器复用（**未重建**）：`blr-pre-m6-postgres`，`Up (healthy)`，`127.0.0.1:55432`，
PostgreSQL 16.15，`TEST ONLY`。

```
PSYCOPG_CONNECTIVITY    = PASS
  server_version        : PostgreSQL 16.15 on x86_64-pc-linux-musl
  current_database/user : blr_pre_m6 / blr_test
  rolcreatedb           : True
SQLALCHEMY_CONNECTIVITY = PASS
  dialect/driver        : postgresql / psycopg
  SELECT 1 = 1 ；current_database() = blr_pre_m6 ；SHOW server_version = 16.15
  session scalar        : 42
```

测试库（均建于隔离容器内，库名含 `test` 以满足门禁 fail-closed 守卫）：

```
blr_pre_m6_test_fresh       （fresh 迁移）
blr_pre_m6_test_existing    （existing DB 迁移）
blr_pre_m6_test             （PG-006 / PG-001 集成入口）
```

---

## 7. PG 迁移门禁（§10 中三项）— 门禁捕获真实缺陷 PG-009

### 7.1 首次实跑：fresh 迁移**失败**（真实缺陷，非环境问题）

```
sqlalchemy.exc.ProgrammingError: (psycopg.errors.DatatypeMismatch)
column "current_blessed_time" cannot be cast automatically to type integer
HINT:  You might need to specify "USING current_blessed_time::integer".
[SQL: ALTER TABLE world_runtime ALTER COLUMN current_blessed_time TYPE INTEGER]
  ← database/alembic/versions/5aef35f022b4_m0_blessed_time_integer.py
```

根因：契约 §1 明确「batch_alter 在 PG 上直通原生 `ALTER`」。而
`5aef35f022b4`（String(32)→Integer，6 列）与 `a1c9f3d77e21`（String(24/32)→BigInteger，
6 列）依赖 `batch_alter_table` 的表重建语义；PG 的
`ALTER COLUMN ... TYPE` 对 `varchar → integer/bigint` **无赋值转换**，必须显式 `USING`。
契约 §6.1 早已把「migrations 在 PG 上从 0 upgrade head」列为必验项 —— 本轮首次实跑即命中。

### 7.2 最小修复（PG-009）

- `5aef35f022b4`：`alter_column(..., postgresql_using=f"{col}::integer")`
  （downgrade 对称补 `::varchar(32)`）；顺带把重复列清单提为模块常量 `_COLS`。
- `a1c9f3d77e21`：新增 `_pg_using(column, target)`，
  仅在**无赋值转换**的方向产出 USING（varchar→bigint / bigint→varchar）；
  `integer ↔ bigint` 返回 `None`，保持最小改动。

**转换语义**：直接取旧列文本转换；项目原则「禁止静默错转」
（`e9f4b7c2d8a6` 同口径）意味着若真存在非数值历史数据，PG 会**报错中止本迁移**，
而不是静默写入错误值。此刻世界未播种、无历史数据，该路径为空。

**SQLite 行为不变的证明（决定性、可复现）**：用 `git archive HEAD`（不触碰 `.git`）
导出改动前源码，与叠加当前改动的副本，各自对全新 SQLite 库执行
`migrate_database(..., "head")`，然后 dump `sqlite_master` 全部对象：

```
pristine HEAD : objects=122  alembic_version=f2a7c4e9b1d6
                schema_sha256=237bd0e25bb6bf2e601eee7852f9542d4c36500736a687943ac2874bfb42e2
worktree      : objects=122  alembic_version=f2a7c4e9b1d6
                schema_sha256=237bd0e25bb6bf2e601eee7852f9542d4c36500736a687943ac2874bfb42e2
SQLITE_SCHEMA_MIGRATION_OUTPUT_IDENTICAL = TRUE
```

即：表/索引/触发器 DDL 与 alembic head **逐字节一致**，SQLite 行为未改变。

### 7.3 复验结果（三项全 PASS）

```
POSTGRES_FRESH_DB_MIGRATION = PASS
  blr_pre_m6_test_fresh: 0 → upgrade head → version=f2a7c4e9b1d6,
  tables=46, world_events 触发器 = [blr_world_events_no_modify, blr_world_events_no_truncate]
  immutability_triggers_present = True ; truncate_protection_present = True ; verify_event_immutability = OK

POSTGRES_EXISTING_DB_MIGRATION = PASS
  blr_pre_m6_test_existing: upgrade→d7f9b1c3e5a7（PREV，触发器仅 1 个 = UPDATE/DELETE）
  → 写入 world_runtime 1 行 + world_events 3 行 → upgrade→head
  → version=f2a7c4e9b1d6，触发器补齐为 2 个
  → 数据保留：world_events=3（ticks 7/11/13 全部 intact）、world_runtime=1

POSTGRES_SECOND_UPGRADE_IDEMPOTENT = PASS
  fresh    : (version, tables, triggers, events, runtime) 二次 upgrade 前后完全相同
  existing : 同上完全相同（含存量行与触发器计数）
```

```
CURRENT_ALEMBIC_HEAD_ON_PG = f2a7c4e9b1d6（与脚本 head 一致）
POSTGRES_ALEMBIC_HEAD      = f2a7c4e9b1d6
```

---

## 8. PG-006 真实 TRUNCATE 保护（§10）

**门禁缺口（PG-010）**：`tests/test_pg_event_truncate_protection.py` 的 PG 分支此前
**只有 stub engine**，没有任何真实 PostgreSQL 路径 —— 即 `PG006_STATUS` 只能停在
`FIXED_AT_SCHEMA_LEVEL`，无法升级。本轮补上 gated 真实入口：

`tests/test_pg_event_truncate_protection.py::test_pg_truncate_protection_integration_entrypoint`
（守卫复用 `tests/test_pg_recovery_checkpoint_portability.py::_pg_dsn_or_skip`，
单一来源；缺 `BLR_TEST_PG_DSN` / `BLR_TEST_PG_ALLOW=1` → skip；库名不含 `test` → fail-closed）

真实 PG 实测：

```
PG_EVENT_INSERT = ALLOWED（EventRepository.append × 2 → world_events 计数 = 2）
PG_EVENT_UPDATE_PROTECTION   = ENFORCED  sqlstate=P0001  "world_events is append-only: UPDATE forbidden"
PG_EVENT_DELETE_PROTECTION   = ENFORCED  sqlstate=P0001  "world_events is append-only: DELETE forbidden"
PG_EVENT_TRUNCATE_PROTECTION = ENFORCED  sqlstate=P0001  "world_events is append-only: TRUNCATE forbidden"
攻击后 world_events 计数仍 = 2（TRUNCATE 未生效、历史未被清空）
verify_event_immutability(engine) 攻击后依然通过
```

关键点：`TRUNCATE forbidden` 由**语句级** `blr_world_events_no_truncate`
（migration `f2a7c4e9b1d6`）抛出——证明行级触发器之外的那道缺口确实已被 PG 侧补上
（行级 `BEFORE UPDATE OR DELETE` 不会拦 TRUNCATE）。
异常类型为 `psycopg.errors.RaiseException`（SQLSTATE `P0001`）→ SQLAlchemy
`ProgrammingError`；门禁断言因此按 `sqlalchemy.exc.DatabaseError` + 消息关键词判定，
而不是照搬 SQLite 侧的 `IntegrityError`（PG 上 PL/pgSQL `RAISE EXCEPTION` 不映射为 23xxx 约束类）。

```
PG006_STATUS = VERIFIED_ON_REAL_POSTGRES（原 FIXED_AT_SCHEMA_LEVEL 已可升级）
```

---

## 9. PG-001 recovery smoke + PG 集成入口（§10 后两项）

`tests/test_pg_recovery_checkpoint_portability.py::test_pg_recovery_integration_entrypoint`
在真实 PG 上执行：迁移 → 合成 world + 3 条 checkpoint（含 CATCHUP 干扰行与 incomplete 行）
→ 权威恢复查询必须选中 tick=90（非 120 incomplete、非 150 CATCHUP）
→ `count_checkpoints_by_kind` = `{time_committed: 1, world_committed: 2}`。

```
PG_RECOVERY_QUERY_EXECUTES = PASS
PG_RECOVERY_SEMANTICS      = PASS（与 SQLite 侧语义一致）
```

**门禁可重跑性缺陷（PG-010，一并修复）**：该入口原先只删 `simulation_checkpoints`、
不删 `world_runtime` 行 → 第二次运行必在 `uq_world_runtime_world_id` 上失败
（已实测复现）。修复：抽出 `_purge_world(factory, world_id)`
（先删 checkpoint 再删 world_runtime 行），**前置调用（清残留）+ finally 调用（清本次）**，
两个 PG 入口语义统一。

复验：连续 **两轮** 全量 PG gated 套件

```
run #1: 35 passed in 26.84s
run #2: 35 passed in 29.55s
事后库内残留：world_runtime=0  world_events=0  simulation_checkpoints=0
          触发器：[blr_world_events_no_modify, blr_world_events_no_truncate]
```

且**非空过证明**：取消 `BLR_TEST_PG_DSN`/`BLR_TEST_PG_ALLOW` 后
两个入口均按设计 `SKIPPED`（不是静默通过）。

```
PG_INTEGRATION_ENTRY = PASS（35/35 项含 2 个真实 PG 入口全部执行，非 skip；gated 三文件 16+11+8）
```

---

## 10. SQLite 回归（确认修复不改变 SQLite 行为）

**决定性直接证据**：同一 migration 集在改动前（`git archive HEAD` 纯净副本）与改动后
（当前工作区）分别对全新 SQLite 库执行 `upgrade head`，导出 `sqlite_master` 全量对象
（表 / 索引 / 触发器 SQL）+ `alembic_version` 后逐字节比对：

```
SQLITE_SCHEMA_MIGRATION_OUTPUT_IDENTICAL = TRUE
  objects          = 122（两侧相同）
  alembic_version  = f2a7c4e9b1d6（两侧相同）
  schema_sha256    = 237bd0e25bb6bf2e601eee7852f9542d4c36500736a687943ac2874bfb42e2e9（两侧相同）
```

即 `postgresql_using` 是**纯 PG 专属 kwarg**，SQLite 路径产物逐字节未变。

**针对性套件回归**（dev 环境 Python 3.11.9 / SQLAlchemy 2.0.52 / alembic 1.19.2 /
pytest 9.1.1；规范模式，**未注入** `BLR_FORMAL_DB_PATH`）：

```
SQLITE_TARGETED_REGRESSION = PASS
  collected 80 / passed 78 / failed 0 / errors 0 / skipped 2；85.5s；exit 0
  模块：test_database / test_backup_events / test_hardening_hp / test_guards /
        test_deployability / test_pg_event_truncate_protection /
        test_pg_portability_static_audit / test_pg_recovery_checkpoint_portability
  2 skipped = 两个 PG 集成入口在未注入 DSN 时按设计 skip
             （已单独验证其在注入 DSN 后真实执行，非 skip）
```

**全量套件回归 = NOT_RUN（本轮）**：本项目全量回归是**分块长跑**（上一阶段 5 分块
合计 ≈ 6.9 小时：7880.3s / 6443.6s / 9420.2s / 1445.1s / 1228.7s；M5 全量为
4h54m / 5h09m），由专用 detached runner 以规范模式执行，属**独立的回归阶段**，
不在本轮范围。

本轮曾以 detached 后台进程启动单进程全量跑（日志 `%TEMP%\blr_prem6_sqlite_regression.log`），
在 11:21:58 → 11:43:14 期间完成 **124 项、0 failed / 0 errors**；囿于其确为数小时级
活动而主动停止，**未声称通过**。建议下一阶段复用既有分块 runner 跑全量。

### 10.1 附带发现：正式库守护测试当前“恒 skip”，注入变量时反而失败（**未修改**）

`tests/zz_formal_db_guard.py::test_pf20_formal_world_zero_m2_entities_after_suite`
在注入 `BLR_FORMAL_DB_PATH` 时**失败**：

```
assert after == formal_db_guard                     ← 通过（校验和全程未变 = 正式库未被修改）
assert row == ("NOT_ACTIVATED", None, None, None)
AssertionError: None                                ← 失败：正式库**没有 world_runtime 行**
```

- 成因：该断言假定正式库已存在一行 `NOT_ACTIVATED` 的 `world_runtime`；但本阶段实测
  正式库 `world_runtime` = **0 行**（世界从未播种，与“未创建正式 world_runtime”一致）。
  本文件**未被本轮改动**（见 §12 diff 清单），属**存量不一致**。
- 影响：规范模式下不注入变量 → 该守护**恒 skip**；注入变量 → 因与“是否被篡改”
  无关的原因失败。即当前它既未生效、也不能用作篡改证据。
- 处置：**仅记录，未修改**（守护语义属主人决策项）。本报告“正式库未篡改”的结论由
  §11 的 sha256 + mtime 独立证据支撑。

---

## 11. 正式世界与 live 红线复核（§12）

环境操作**前后**均实测：

```
WORLD_RUNTIME_STATUS     = NOT_ACTIVATED（正式库 world_runtime 无行 → 世界未播种）
CURRENT_BLESSED_TICK     = NULL
OFFICIAL_WORLD_EVENTS    = 0
OFFICIAL_WORLD_MUTATIONS = 0
WORLD_SEED_CONSUMED      = FALSE
FORMAL_DB_TOUCHED        = FALSE
```

- 正式库 `blessed_land.sqlite` sha256 = `1d84ee370167b047265bd2200c69c7373372fb0b594bf7ac073b33097de52cf2`
  （与冻结值 / `authoritative_db.json` 完全一致），size `536576`，mtime `2026-09-12 09:53:41`（未变）。
- 只读抽查（`mode=ro` URI）：`world_runtime` 0 行；`world_events` / `persons` /
  `population_groups` / `simulation_run` / `simulation_checkpoints` 全为 0；表数 46。
- live AstrBot 进程 PID `56560` / `1744` 持续运行，启动时间 `2026/9/14 0:46:00` 未变。
- **未触碰**：live AstrBot venv、live Runtime plugin、live plugin_data、正式 `blessed_land.sqlite`、
  Private Companion、AstrBot Core、AstrBot Launcher。
- 未迁移正式世界、未创建正式 `world_runtime`、未消费 World Seed、未进入 M6。
- 不得连接正式 DB 做测试：本轮所有 PG 测试均只连隔离容器内的 `blr_pre_m6_test*`。

---

## 12. 本轮代码改动（**未提交**，待主人复核）

`git diff --numstat`（5 文件，+204 / −29）：

```
41	1	POSTGRESQL_COMPATIBILITY_CONTRACT.md                    （§9 勘误 PG-009/PG-010 + 新增 §10 实跑记录）
24	20	database/alembic/versions/5aef35f022b4_m0_blessed_time_integer.py（postgresql_using）
21	3	database/alembic/versions/a1c9f3d77e21_m0_canonical_blessed_tick.py（_pg_using）
101	0	tests/test_pg_event_truncate_protection.py              （PG-006 真实 PG 入口 + _purge_world）
17	5	tests/test_pg_recovery_checkpoint_portability.py        （_purge_world 前置+彻底清理）
```

性质：**PG 专属分支**修复 + 测试入口补齐；SQLite 路径零行为变化（§7.2 逐字节证明）。
行尾保持仓库既有 CRLF。**未 commit、未 push**（按 `AWAIT_OWNER_REVIEW` 保留在主人手中）。
建议提交信息：`fix: make alembic migrations and pg gates runnable on postgresql`

---

## 13. 环境残留物与清理（TEST ONLY）

| 对象 | 位置 | 清理方式 |
| --- | --- | --- |
| PG venv | `%TEMP%\blr-pre-m6-pg-venv` | 删除目录 |
| 凭据 | `%TEMP%\blr_pre_m6_pg_env.json` | 删除文件 |
| 主 wheelhouse | `D:\MY SELF\IKUN\小光\pg-wheelhouse\`（4 官方 wheel） | 保留（离线门禁凭据） |
| 测试依赖 wheelhouse | `D:\MY SELF\IKUN\小光\pg-wheelhouse-testdeps\`（11 wheel） | 保留（可离线重建 venv） |
| 测试库 | `blr_pre_m6_test` / `_test_fresh` / `_test_existing` | `DROP DATABASE`（容器内，TEST ONLY） |
| 容器 / 卷 | `blr-pre-m6-postgres`（healthy，保留供下一阶段）/ `blr_pre_m6_pgdata` | `docker stop` + `docker rm` + `docker volume rm` |

未重建容器；未触碰同机他人容器 `stayops-postgres`。

---

## 14. 返回字段（PRE_M6_PG_DRIVER_AND_ENV_CONTINUATION_REPORT）

```
WHEELHOUSE_PATH = D:\MY SELF\IKUN\小光\pg-wheelhouse\

CURRENT_BAD_ARTIFACTS  = NONE_PRESENT（审计时空目录；无 cp314 wheel、无 tar.gz）
                         —— 与主人截图描述不一致，已如实回报，未删除/未补造
CORRECT_WHEELS_PRESENT = psycopg-3.3.5-py3-none-any.whl
                         psycopg_binary-3.3.5-cp311-cp311-win_amd64.whl
                         typing_extensions-4.16.0-py3-none-any.whl
                         tzdata-2026.3-py2.py3-none-any.whl
                         （来源 files.pythonhosted.org；PyPI JSON API 摘要与期望值预先交叉验证一致）

PSYCOPG_WHEEL_HASH_MATCH           = TRUE  (ce5aa5cdb4f9379f00f487590e5890bfa7df9a164648c969ffa628505e21af4e)
PSYCOPG_BINARY_WHEEL_HASH_MATCH    = TRUE  (7b443f943abfe35aa5a776630cea27c9348aa66659286cee0b99084332252080)
TYPING_EXTENSIONS_WHEEL_HASH_MATCH = TRUE  (481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8)
TZDATA_WHEEL_HASH_MATCH            = TRUE  (dc096730c87af6cab1b171c9d532be840741ff5d459015e7f6947bd7d7e54931)

WHEEL_TAG_COMPATIBILITY = PASS（cp311-cp311-win_amd64；无 cp314/cp312/linux/macOS）

PG_DRIVER               = psycopg（binary 实现，libpq 18.0.4）
PG_DRIVER_VERSION       = 3.3.5
PG_DRIVER_STATUS        = READY
PG_DRIVER_INSTALL_SCOPE = DEV_TEST_ONLY（%TEMP%\blr-pre-m6-pg-venv，全新独立 venv）

PSYCOPG_IMPORT    = PASS（3.3.5）
DEPENDENCY_CHECK  = PASS（pip check 无破损依赖）

PSYCOPG_CONNECTIVITY    = PASS（PostgreSQL 16.15 @ 127.0.0.1:55432）
SQLALCHEMY_CONNECTIVITY = PASS（postgresql/psycopg）

POSTGRES_FRESH_DB_MIGRATION         = PASS（0 → f2a7c4e9b1d6，46 表，2 触发器）
POSTGRES_EXISTING_DB_MIGRATION      = PASS（d7f9b1c3e5a7 → head，存量 3 行保留，触发器补齐）
POSTGRES_SECOND_UPGRADE_IDEMPOTENT  = PASS（fresh + existing 双双幂等）
POSTGRES_ALEMBIC_HEAD               = f2a7c4e9b1d6（与脚本 head 一致）

PG_EVENT_INSERT              = ALLOWED
PG_EVENT_UPDATE_PROTECTION   = ENFORCED（P0001 "append-only: UPDATE forbidden"）
PG_EVENT_DELETE_PROTECTION   = ENFORCED（P0001 "append-only: DELETE forbidden"）
PG_EVENT_TRUNCATE_PROTECTION = ENFORCED（P0001 "append-only: TRUNCATE forbidden"）
PG006_STATUS                 = VERIFIED_ON_REAL_POSTGRES（原 FIXED_AT_SCHEMA_LEVEL）

PG_RECOVERY_QUERY_EXECUTES = PASS
PG_RECOVERY_SEMANTICS      = PASS

PG_INTEGRATION_ENTRY = PASS（两入口真实执行非 skip；连续两轮 35 passed）

SQLITE_SCHEMA_MIGRATION_OUTPUT_IDENTICAL = TRUE（122 schema 对象 + head 逐字节一致）
SQLITE_TARGETED_REGRESSION = PASS（80 collected / 78 passed / 2 skipped /
                             0 failed / 0 errors；exit 0）
SQLITE_FULL_REGRESSION     = NOT_RUN_THIS_ROUND（数小时级分块长跑，属独立回归阶段；
                             本轮后台跑 124 项 0 failed 后主动停止，未声称通过）

FORMAL_WORLD_TOUCHED = FALSE
WORLD_SEED_CONSUMED  = FALSE
WORLD_RUNTIME_STATUS = NOT_ACTIVATED
CURRENT_BLESSED_TICK = NULL
OFFICIAL_WORLD_EVENTS = 0
OFFICIAL_WORLD_MUTATIONS = 0

PG_GATE_DEFECTS_FOUND_AND_FIXED = PG-009（迁移缺 USING → 直接失败）
                                  PG-010（PG 入口不完整 / PG-001 不可重跑）
CHANGES_COMMITTED = NO（5 文件改动保留在工作区待复核）

NEXT_ACTION = AWAIT_OWNER_REVIEW_FOR_PG_FUNCTIONAL_AND_COMMIT_AMBIGUITY_GATE
```

**STOP** — 未进入 M6；未执行 single writer stress / fencing takeover /
real commit ambiguity / worker kill / server kill / 5000y PG endurance；
未对 live 与正式世界做任何改动。

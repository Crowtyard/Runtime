# DSH_M0_INDEPENDENT_QA_REPORT

> 执行方：DSH（Runtime 唯一实现与维护方）。日期：2026-09-06。
> 对象：`D:\MY SELF\IKUN\小光\XiaoguangBlessedLandRuntime\`（M0 Foundation，前序 Agent 交付）。
> 原则：前序报告不算证据；代码 + 实测才算证据。禁止为测试污染正式库（测试全部使用 tmp 临时库）。

---

## 1. 前序 M0 报告经验证属实的内容

| 前序声明 | 实测结论 |
|---|---|
| Python 3.11.9 / SQLAlchemy 2.0.52 / Alembic 1.19.2 / pytest 9.1.1 | ✅ 实测一致 |
| 20 张表，Base.metadata = DB 表集合 | ✅ 实测一致（sqlite_master 20 张业务/核心表） |
| 23 tests / 23 PASS | ✅ 基线复跑 23/23 通过 |
| SQLite WAL + foreign_keys=ON + busy_timeout | ✅ 正式库 journal_mode=wal（-wal/-shm 文件存在）；连接级 PRAGMA 由引擎工厂设置 |
| Alembic 2 migrations，正式库 upgrade head | ✅ 当时属实（alembic_version=5aef35f022b4） |
| World Bible hash lock（DB 行 = 冻结 MANIFEST 复算值） | ✅ 重新从 VERSION.json + MANIFEST.sha256.txt 复算 18 文件，manifest_hex 与 DB 行完全一致 |
| TIME_RATIO_HISTORY 自然态行（365.0, blessed_effective_from=NULL） | ✅ 属实；该行是 World Rule 元数据，不是激活 |
| Single Writer：第二个 writer 被拒绝 | ✅ 实测通过 |
| Atomic Tick：异常整事务回滚 | ✅ 实测通过（0 事件 0 run） |
| Deterministic RNG（确定性/子系统隔离/scope 隔离） | ✅ 实测通过 |
| Backup：在线备份 + integrity + 现有备份文件健康 | ✅ 实测通过（现有 world_backup.db.* integrity=ok） |
| Idempotency：committed_until >= target → skip | ✅ 基线行为属实（但身份缺 simulation_version，见 §3.4 已修正） |
| WORLD_NOT_ACTIVATED 守卫 + 测试 | ✅ 守卫存在且有测试 |
| 正式库为空世界（业务表 0 行 / NOT_ACTIVATED / tick=NULL） | ✅ 实测属实 |

## 2. 与前序报告不一致 / 前序实现的缺陷（全部已修正）

1. **Blessed Time 设计缺陷（最高优先级）**：`blessed 刻度 = 整数福地年`，只能表示 Year N，
   无法表达子年事件/灾劫前兆/恢复/演替/人生节点/ratio 变更/adaptive resolution。
   且 core 表虽被 migration 0002 改为 Integer，world 业务表仍为 `String(24)`（birth/start/end/
   updated/blessed_time），前后不一致。→ 改为 CANONICAL_BLESSED_TICK（§3）。
2. **naive UTC 全库使用**：`utcnow()` 返回 naive，SQLite 存储无 offset 后缀的裸文本。→
   aware UTC + 显式 ISO-8601 UTC（§5）。
3. **Single Writer 跨进程空洞**：租约在 `with world_writer` 退出时才 commit，持有期间
   其他进程根本看不到锁 → 可并发双写。→ acquire 即时提交 + select-first 竞争协议 +
   STALE_WRITER_RECOVERY（§7）。
4. **Idempotency 未绑定 simulation_version**：`committed_until >= target` 查询不过滤版本，
   旧版本的 committed_until 会阻止新版合法推进。→ 版本化 TICK_IDENTITY（§8）。
5. **Event 不可变只是代码约定**：Repository 无 update/delete，但 DB 层裸 SQL 可改。→
   DB 触发器强制（§9）。
6. **schema_version 存旧值**：正式库 runtime 行 schema_version=7253f352f69e（0001），
   而库已到 0002 head —— 与报告"schema_version=alembic head"不符。→ init_db 每次校正。
7. **守卫可被绕过**：`require_world_activated` 只查 status==ACTIVE（seed 为 NULL 也放行）；
   事件可直接走 EventRepository.append 绕过守卫；run_atomic_tick 不校验激活。→ 收紧。
8. **bible hash 校验可被空串绕过**：`if row.world_bible_manifest_hash and ...` 使空 hash 通过。
   → 严格相等。
9. **migration 0001 含重复 UNIQUE 约束**（world_events 两行同名 UniqueConstraint，
   SQLite 容忍但 PostgreSQL 会直接建表失败）→ 0001 已去重（仓库无历史，允许整理）。
10. **causal chain 主键/uid 混用**（parent_event_ref 存 int 主键）→ 统一 event_uid。
11. **无 restore 实现/无 checksum/WAL 恢复测试**；**integrity_check 无方言护栏**。
12. 文档缺陷：README 引用不存在的 requirements.txt；init_db docstring 声称播种
    system_configuration（实际未播种）。→ 已修正文档。

## 3. Blessed Time：原实现 → CANONICAL_BLESSED_TICK

### 3.1 原实现
- `world_runtime.current_blessed_time` 等 6 个 core 列为 Integer，语义"整数福地年"；
  world 表 5 个 blessed 列为 String(24)。`time_service` 以浮点福地年做分段积分
  （`blessed_years_for_real_seconds` 返回 float）。

### 3.2 是否已改为 Canonical Blessed Tick
**是。** 全部 11 个 blessed 时间列（core 7 + world 4 位置 5 列）经 migration
`a1c9f3d77e21` rename + 类型变更为 BigInteger：
`current_blessed_tick` / `blessed_effective_from_tick` / `target_blessed_tick` /
`committed_until_tick` / `checkpoint_blessed_tick` / `blessed_tick`（events、state_changes、
timeline）/ `birth_blessed_tick` / `updated_blessed_tick` / `start_blessed_tick` /
`end_blessed_tick`。`domain/blessed_time.py` 提供换算/投影；`time_service` 分段积分返回整数。
禁止浮点累计世界时间：每段增量 = `(µ_real × p) // (q × 86400)`（ratio 经
`float.as_integer_ratio()` 精确还原为有理数，纯整数运算），总量只做整数加法。

### 3.3 Tick 单位与理由
**1 canonical tick = 1 micro-blessed-year（µy，1e-6 福地年；TICKS_PER_BLESSED_YEAR=1_000_000）**

- 精度：1 µy 远小于子年需求（quarter=250,000µy；自然态 ratio 下 1 tick≈0.24ms 现实）。
- 溢出安全：64-bit ≈ 9.22e18 tick = 9.22e12 福地年；自然态 ratio 下 ≈ 6.9e7 现实年才溢出。
  必须用 BigInteger：32-bit Integer 在 ~2147 福地年（µy 刻度）即溢出。
- 转换成本：年投影 = `tick // 1e6`（纯整数 div/mod，零浮点）。
- SQLite/PostgreSQL 兼容：SQLite INTEGER（64-bit affinity）/ PG BIGINT 均原生承载。
- 历法 Canon 边界：tick 只锚定 Bible 唯一定义的时间量"福地年"（WS-0201 ratio 语义），
  不锚定日/月（Bible 未定义一年多少天/月制/纪年）。year 只是算术投影；
  month/day 投影在历法 Canon 定义前只以 µy 余数呈现，禁止生成叙事纪年。

## 4. Real Time UTC 最终方案
应用层 aware UTC + `UtcDateTime` TypeDecorator（`database/base.py`）边界强制归一化 +
migration `d8e1b3a5c7f9` 把存量 SQLite 文本补显式 `+00:00` 后缀：

- 应用层只产/耗 aware UTC（`utcnow()` 返回 aware；naive 输入按 UTC 解释，兼容旧数据）。
- SQLite 存储显式 ISO-8601 UTC 文本（含 +00:00，字典序安全、无歧义）；
  PostgreSQL 落原生 TIMESTAMPTZ。
- 实测：+08:00 输入 → 存 UTC；旧无后缀行 → 读回 aware UTC；字节级 roundtrip 保瞬时。
- 不依赖机器本地时区、不受 DST 影响、无 ambiguous datetime。

## 5. TIME_RATIO_HISTORY 是否安全
**安全。** 正式库 1 行自然态（365.0，`blessed_effective_from_tick=NULL`=未开始计，
`runtime_status=NOT_ACTIVATED`，`world_seed_version=NULL`）——是 World Rule 元数据，
**不是** World Seed Activation（测试 `test_metadata_creation_does_not_activate`）。
未来 ratio 变更：`RatioSegment` + `blessed_ticks_over_segments` 按 effective interval
分段整数积分（测试覆盖 A=365/B=100 分段 ≠ 拿最新 ratio 倒推）。Offline catch-up 的
切分执行属 M1，但数据结构与纯函数接口已就绪且被禁"最新值倒推"。

## 6. WORLD_NOT_ACTIVATED 是否真实有效
**有效。** 实测：`advance_world` / `simulate_tick` / `offline_catchup` /
`create_world_event_from_simulation` 在 NOT_ACTIVATED 下全部拒绝（WorldNotActivated）；
`run_atomic_tick`（真实 tick 执行）与 `create_simulation_event`（受保护事件入口）同样被拒。
激活判定收紧为 status==ACTIVE **且** world_seed_version 非空。创建 metadata / time rule
不改变激活态。

## 7. Single Writer 与 STALE_WRITER_RECOVERY
**支持。** 设计（`services/writer_lock.py`）：acquire 即时 commit（跨进程可见）→
select-first 竞争协议（INSERT PK 冲突 → 重读重判；过期 → `UPDATE ... WHERE expires_at<=now`
CAS 接管，rowcount=0 即冲突）→ owner identity（host:pid:runid）+ 随机 token →
renew 仅同 token → release 仅同 token（fencing）。实测：崩溃（未 release）后未过期拒绝、
过期后接管成功且 owner/token 更换；旧 token release 不动新租约；续约/被接管后续约失败；
release 失败被记录且租约保留、过期后仍可接管 → **世界不会永久锁死**。
边界：接管只校验过期（"旧 owner 仍活着但心跳丢失"的强 fencing 属 M1；M0 未激活无写负载）。

## 8. Idempotency 是否绑定 simulation version
**是。** TICK_IDENTITY = world_id + simulation_version(=CURRENT) + status=COMMITTED +
committed_until_tick。实测：同版本同 target → skip 且 run_id 稳定；**旧版本
committed_until=1e8 不阻止新版推进 target=5e6**；失败事务不推进 committed_until_tick
（回滚后 0 run 0 event）。run identity（run_id）落库并在 skip 时返回。

## 9. RNG 是否真正隔离
**是。** seed=sha256(world_id|simulation_version|period_tick|subsystem|entity_scope)。
实测：确定性重放；子系统独立流；**ECONOMY 调用数 0→50 不改变
DEMOGRAPHY/RESOURCE/TRIBULATION 流**；entity scope 隔离；simulation_version 隔离；
world 隔离。period 身份改为 canonical tick。

## 10. Event History 是否不可变
**数据库层强制。** migration `b2d4e8f9a6c3` 建触发器：SQLite BEFORE UPDATE/DELETE →
RAISE(ABORT)；PG BEFORE UPDATE OR DELETE → RAISE EXCEPTION。实测：裸 SQL UPDATE/DELETE
world_events 均抛 IntegrityError 且行不变；INSERT 正常；纠错=新事件（supersedes/reverses）
流程通过；`database/invariants.py::verify_event_immutability` 校验触发器在位（init_db 启动即检）。

## 11. Backup / Restore 是否实测
**是。** 在线备份 API（WAL 内容一致）+ integrity_check + pre-migration 备份 + 新增
`restore_from_backup`（引擎释放 → 清 -wal/-shm → 原子替换 → integrity）。实测：备份→事故→
恢复→数据一致；**WAL 活跃状态下恢复**；checkpoint 后逻辑内容 checksum 一致（文件字节级比较
对 SQLite 无效：文件头 change counter 不同，故用全表逻辑摘要）；Windows 全程通过。
正式库迁移前已做 pre-migration 备份（integrity=ok，捕获迁移前状态）。

## 12. World Bible Hash 是否通过
**通过。** 从 `VERSION.json`(v1.0 FROZEN) + `MANIFEST.sha256.txt`(18 文件) 逐文件复算
SHA256 全一致；DB 只存 version + manifest identity（manifest_hex 与复算一致），无第二份
Bible 内容。bible hash 校验收紧为严格相等（空串/缺失拒绝）。

## 13. PostgreSQL Compatibility 是否满足 M0
**满足（契约级）。** SQLite 私有 SQL 仅存在于 database/db.py（PRAGMA，URL 分流）、
services/backup_service.py（sqlite3 在线备份/恢复，按 URL 分支）与 invariants 的方言分支；
Domain/Repository 无方言泄漏；时间换算在应用层；canonical tick 用 BigInteger；
UtcDateTime 在 PG 落 TIMESTAMPTZ；0005 触发器带 PG 分支。已修正 0001 的重复约束
（PG 下会建表失败的隐患）。PG 实跑验证（migrations from 0 + 全测试）按契约属未来部署项
（M0 不部署 PG）。

## 14. 正式 DB 是否仍为空世界
**是。** 实测（迁移后）：persons=0、population=0、settlements=0、world_events=0、
tribulations=0、timeline=0、全部 18 张业务表 0 行；`WORLD_SEED=NOT_ACTIVATED`；
`current_blessed_tick=NULL`；`world_seed_version=NULL`；ratio 历史 1 行（自然态元数据）；
integrity_check=ok。QA 全程使用 tmp 临时库，正式库仅被 migrate/seed 触碰（幂等，
重跑无副作用）。

## 15. 测试数量与全部结果
**60 tests / 60 PASS（0 fail，0 warning-as-error）**，覆盖：迁移与 schema 集合、
canonical tick 列、WAL/PRAGMA、事务回滚、原子 tick 回滚、未激活拒绝、单写者、
stale recovery ×7、幂等 + 版本绑定、RNG ×7、bible 哈希 ×4（含严格绑定）、
守卫 ×5（含 seed 条件/事件入口/元数据≠激活）、时钟异常、tick 数学 ×9、
UTC 边界 ×6、备份/恢复/checksum/pre-migration ×6、事件不可变（DB 触发器 + 纠错 + 因果链）。

## 16. Git commits
仓库此前**不存在任何 git 历史**（前序报告未提 git），由 DSH 建立：

```
127523f  M0 Foundation: prior-agent delivery baseline for DSH independent QA   ← pre-handover commit
a135942  DSH M0 independent QA: canonical blessed tick, aware UTC, …           ← DSH QA/fix commit
```

（QA/fix 提交经一次 amend 定稿；本哈希行由随后的 docs 提交最终记录。）

pre-handover commit = 前序代码原样快照（仅加 .gitignore，排除 world.db/pycache/备份文件），
不 squash 任何有价值历史（本仓库此前无历史，故基线为单次导入）。修复内容为独立 commit。

## 17. 仍存在的风险
1. PG 从未实跑：契约文档列明未来验证清单（migrations from 0、全测试、backup 切换）。
2. SQLite Alembic batch_alter 重建 world_events 会丢触发器 → 已在 migration docstring +
   contract + invariants 校验三重设防，但需未来迁移者遵守。
3. 强 fencing（接管前验证旧 owner 已死）未实现——M1 引入长 tick/多机部署前必须补；
   M0 无写负载，过期接管足够。
4. 单进程内"第二个 writer"只能靠租约表拒绝，无同进程 reentrancy 检测（with 嵌套会
   CAS 覆盖自身——M1 若需要可加）。
5. World Seed 激活流程（谁有权置 ACTIVE、seed 内容）属 M1，当前只有守卫没有激活 API。

## 18. 是否建议 M0 正式验收
**建议验收。** 前序报告的 13 项核心声明经实测基本属实；发现的 12 项缺陷（最关键是
blessed 时间模型、跨进程单写者空洞、事件不可变仅靠约定、幂等未绑版本）已全部在
World Seed 激活前的低成本窗口修正并实测；正式库仍为受守卫保护的空世界；测试从 23
扩展到 60 且全部通过；Git 已由 DSH 接管并形成 pre-handover + QA 两个干净 commit。

---

```
M0_DSH_QA_READY_FOR_REVIEW
```

（本阶段只完成 M0 接管与独立 QA：未开发 Population/Resource/Economy/Ecology/
Offline Catch-up/Tribulation 引擎与 AstrBot Adapter，未推进世界、未激活 Seed。）

# PHASE_1_9_1_M0_FOUNDATION_REPORT（2026-09-06）

> World Bible v1.0 冻结哈希于 M0 启动前修复并复验（冻结清单 18 文件，含报告；MANIFEST 在 index 版本更新后重新生成——完整性检查在工作首日即拦截到一次真实不一致并已修复）。

## 1. 工程目录
`D:\MY SELF\IKUN\小光\XiaoguangBlessedLandRuntime\`（独立于 AstrBot 与 KB；结构按 PHASE_1_9 §三，含 database/domain/services/scripts/tests/config/backups + alembic + alembic.ini + pyproject）。

## 2. Python / 依赖版本
Python 3.11.9 ｜ SQLAlchemy 2.0.52 ｜ Alembic 1.19.2 ｜ pytest 9.1.1（requirements 未单独文件，pyproject 声明）。

## 3. SQLite 配置
WAL mode、foreign_keys=ON、busy_timeout=30s（PRAGMA 仅存在于 database/db.py 引擎工厂，URL 前缀分流）；单世界单文件 world.db；事务统一 ORM session。

## 4. ORM / Migration 状态
SQLAlchemy 2.x Declarative（20 表，Base.metadata 校验 = DB 表集合一致）；Alembic 2 个 migration：`7253f352f69e`(m0_initial_schema) → `5aef35f022b4`(m0_blessed_time_integer)。正式库已 upgrade head。

## 5. Schema 表数量
**20**（core 9：world_runtime/time_ratio_history/simulation_run/simulation_checkpoints/world_events/world_state_changes/narrative_records/runtime_lock/system_configuration；world 11：settlements/population_groups/persons/lineages/institutions/industries/resource_nodes/ecological_regions/tribulations/timeline_entries/cultural_elements）。

## 6. World Bible Integrity Check
services/bible_integrity + domain/versions：启动校验 VERSION=1.0 + MANIFEST SHA256 全文件复算；DB 行绑定 version+manifest hash（防双套真相）。测试覆盖 OK/篡改检测（WORLD_BIBLE_HASH_MISMATCH）。

## 7. Version Locks
三重：world_bible_version=1.0（world_runtime 列 + DB 行）；simulation_version=0.1.0-dev（constants 唯一源 + run 记录）；schema_version（alembic head 写入 runtime 行；migrations-only）。

## 8. TIME_RATIO_HISTORY
已建立：time_ratio_history 表（ratio_id/world_id/real_effective_from/blessed_effective_from/ratio_value/reason/source/created_at）+ TimeRatioRepository；正式库含自然态行（365.0, BIBLE_V1_WS-0201_NATURAL_RATIO, blessed_effective_from=NULL=未激活）；time_service 提供 RatioSegment 分段积分接口（禁当前值倒推全史）。

## 9. Single Writer 实现
runtime_lock 租约表 + WriterLease（acquire 检查未过期锁→冲突即 WriterLockConflict；release 删行）；world_writer 上下文。测试：writer2 在锁持有期间被拒绝；释放后可再获取。

## 10. Atomic Tick 实现
services/atomic_tick.run_atomic_tick：单事务（session.begin）内 查幂等→写 simulation_run(committed_until)→执行 simulate_fn；异常整事务回滚。测试：fn 抛错→0 事件 0 run；成功提交。

## 11. RNG 派生
derive_seed = sha256(world_id|simulation_version|blessed_period|subsystem|entity_scope) 前 8 字节；RngService 每子系统独立 RngStream（DEMOGRAPHY/RESOURCE/ECONOMY/ECOLOGY/SOCIAL/TRIBULATION/DISTURBANCE）；禁全局 random.seed。测试：确定性、子系统隔离、scope 隔离。

## 12. Backup 实现
SQLite 在线备份 API（sqlite3 Connection.backup）+ integrity_check + 版本化 id 文件 + backup_manifest.jsonl（backup_id/schema 等元数据）；pre_migration_backup 同入口。测试：备份→清库→恢复→1 行还原；integrity=ok；PRE_MIGRATION 标记。Windows 瞬时占用已加容错与直接终名写入。

## 13. Crash / Retry 防重复
TICK_IDENTITY：simulation_run.committed_until ≥ target → skipped（测试：同 target 二次调用 skip，事件仅 1 条）；catch-up 分段 checkpoint 结构+恢复接口（CheckpointRepository.latest_complete）就绪（真实补算属 M1）。

## 14. 当前数据库是否绝对为空世界
是：业务表（persons/population/settlements/tribulations/world_events/timeline…16 表）**0 行**；world_runtime=1 行 NOT_ACTIVATED（world_seed_version NULL、current_blessed_time NULL）；time_ratio_history=1 行（自然态配置）；alembic_version=2。WorldNotActivated 守卫拦截 advance/simulate/catchup/create_event（测试覆盖）。

## 15. 测试数量与结果
**23 tests / 23 PASS**（migrations、schema 集合、PRAGMA、事务回滚、原子 tick 回滚、单写者、retry 幂等、RNG 确定性×2、子系统隔离、scope 隔离、bible OK/篡改、binds、未激活守卫、时钟异常、时钟前进、backup restore/integrity/pre-migration/helper、事件不可变+correction、因果链）。

## 16. 架构设计需要修改的地方
a) blessed 时间刻度定为整数福地年（原先 String "YYYY.MM" 草案在实现期修正 → migration 0002）；b) DB 时间统一 naive UTC（SQLite 无时区存储，避免 aware/naive 混比）；c) world_bible_manifest_hash 置为必填并由 init seed 提供（加固）；d) 冻结 MANIFEST 生成顺序修正（先终态文件后哈希）。均为实现期收紧，未改变 PHASE_1_9 架构语义。

## 17. 是否建议进入 M1
**建议**（M0 验收证据齐全、空世界状态受守卫保护），但按流程由主人/ChatGPT 对 M0 报告裁决后再启动 M1（时间引擎正式补算等），不自动继续。

## 结论

```
M0_FOUNDATION_READY_FOR_REVIEW
```

（RUNTIME_PROJECT=CREATED；DATABASE_SCHEMA=CREATED；WORLD_DATABASE=EMPTY；WORLD_SEED=NOT_ACTIVATED；未推进世界、未开始纪年、未生成任何 NPC/事件/灾劫。）

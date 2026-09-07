# DSH_M2_PREFLIGHT_ENGINE_CONTRACTS_AND_MINIWORLD_HARNESS_FINAL_REPORT

> 执行方：DSH。阶段：M2_PREFLIGHT（DESIGN FREEZE / ENGINE CONTRACT / TEST
> HARNESS / DETERMINISM PREFLIGHT）。不是 M2 引擎实现、不是 Activation、不是 M3。
> 基线：M0/M1/M1.1 全 ACCEPTED，M1_1_LIVE_VERIFIED=TRUE。

## 1. Baseline
- tag `m1.1-live-verified` 冻结于实载验收基线（f6cc39f 之后的 live 修复链
  83e0097/16d99c3）。
- 迁移前 125/125；本阶段完成后 **148/148**（125 回归 + 23 新增 PF）。

## 2. Source Design Recovery
从 `XIAOGUANG_CROW_KB/runtime_design/` 恢复（只读，未改任何原文档）：
- 20_implementation_roadmap：M2=四引擎 + mini_world 120 福地年零 LLM 验收。
- 04_time_engine §2/§3/§4：年度默认步进 + ADAPTIVE_TIME_RESOLUTION；
  **引擎顺序明文固定**（TIME→DEMOGRAPHY→RESOURCE→ECONOMY→ECOLOGY→SOCIAL→
  TRIBULATION→EVENT）。
- 06/07/08/09：四引擎设计（08 §1 每 tick 单向评估；09 §5 人口/经济互馈；
  08 §5 灾后代谢与 M3 联动）。
- 18_testing_strategy：mini_world = 2 聚落/1 种族/1 资源节点。

## 3. Engine Pipeline Contract
M1 catch_up（持有 fencing 事务）→ simulate_fn = `SimulationCoordinator.run_step`
→ WorldSnapshot → StagedWorld（内存 Feed-Forward）→ 按冻结顺序逐引擎 →
所有权校验 → Proposed Mutation 统一写入当前 fenced session → M1 COMMIT →
Checkpoint（M1 时间 + M2 世界）→ world_state_hash v2。
**引擎零 commit、零独立事务**（PF9 静态强制）。

## 4. Engine Order（CONFIRMED_EXISTING_SCOPE）
DEMOGRAPHY → RESOURCE → ECONOMY → ECOLOGY → SOCIAL；TRIBULATION 槽位 =
NOT_REGISTERED（M3）。同一 simulation_version 内不可变（PF4 违约拒绝测试）。

## 5. Snapshot Semantics（冻结 = B：Staged Feed-Forward）
后序引擎读取前序引擎 propose 后的暂存视图（互馈所需）；暂存只存内存，
绝不提前 authoritative（PF10 证明 staged 数据不因失败泄露）。

## 6. Mutation Semantics
引擎只经 `ctx.propose(engine_id, table, entity_id, field, new_value)` 声明；
coordinator 按所有权表（§契约 5）校验 → 违例 INTEGRITY_ERROR（PF-ownership
测试）；全部变更统一由 coordinator 在当前 fenced session 写入。

## 7. RNG Contract
沿用 M1 `derive_seed(world_id, simulation_version, period_tick=step_start,
subsystem=engine_id, scope="WORLD")`；引擎独立 substream（PF7：DEMOGRAPHY
抽样数 3→7 不漂移其余四引擎）；run_id(UUID) 不参与派生（世界结果与 run 身份
无关）；master_seed 载体 = world_seed_version（M6）或测试 world_id。

## 8. Event Contract
State Mutation / Domain Event / Diagnostic Log 三分。domain event 确定性
identity = sha256(world|simver|interval|engine|seq)[:12]（禁止 UUID4）；
重试幂等双防线（M1 区间 skip + 确定性 uid）——PF8 实测重试零重复、
不同库同输入同 identity。

## 9. simulation_version Contract
= WORLD EVOLUTION SEMANTICS VERSION。必须升级：引擎算法/顺序/RNG 派生/事件
语义/状态转移/Snapshot 契约变化；UI/日志/注释不得升级。Preflight 测试世界 =
`0.2.0-preflight`；正式世界保持 `0.1.0-dev`（PF3）。

## 10. world_state_hash v2 Design
WORLD_STATE_HASH_SCHEMA_VERSION=2；canonical JSON（sort_keys+紧凑分隔符+
UTF-8）；覆盖 clock/六类实体表/双版本/引擎版本；实体按语义键排序；排除
autoincrement id、行物理顺序、now() 时间戳、日志、事件日志（PF18：不同插入
顺序 → 同哈希）。

## 11. Checkpoint Extension
M2 世界 checkpoint（每 step，与 M1 时间 checkpoint 同事务）：last run /
world_state_hash v2 / simulation_version / pipeline_version + engine_versions
（meta JSON）。无强制 migration（正式 schema 零改动，PF2 静态保证）。

## 12. Crash Boundary
C1–C10 harness（`crash_after` 注入：before_snapshot / engine:X / after_engines
/ before_checkpoint / after_checkpoint 等）：全部 = 事务原子、无部分权威写入、
干净重试后状态与一次成功完全一致（PF17 参数化实测）。

## 13. Fencing Compatibility
PF10 实测：stale writer 的 staged mutation 在 commit-time fence 重验处被拒
（FencingViolation），DB 零写入；M1 F1–F8 全部保留。

## 14. mini_world Definition
`mini_world_v1`：MINIWORLD-TEST-001 / 2 settlements / 1 species（2 groups，
400 人）/ 1 resource node / 1 ecological region；全部 TEST_FIXTURE_ONLY 常量；
不读正式 Seed Package（PF1 静态断言）；只运行于 tmp DB。

## 15. 120-Year Harness
`run_mini_world_120y()`：120 个年度 step（年度粒度 = CONFIRMED 04 §2），
逐年度 catch_up（合成现实时间 EPOCH0+n 年；wall-clock 零参与，PF13）；
NoOp/Fake 引擎全链运行。PF14 实测：120 steps / 120 runs / 240 checkpoints /
120 TIME_ADVANCE / tick=120,000,000 / 确定性 hash。
PF15：one-shot == 分段重启（30y×4）→ tick/hash/引擎 metrics/事件数全等。
PF16：60y 中断续跑 60y == 一次 120y（hash 等价）。

## 16. Metrics Schema
MiniWorldReport：population(start/end/births/deaths/migrations)、
economy(stock/production/consumption/shortages)、ecology(state/pressure)、
society(households/lineages/institution_events)、infra(steps/runs/events/
checkpoints/final_hash)。**只定义 schema，不预设数值**（真实 baseline 待
M2a–M2d 跑出后冻结）。

## 17. LLM=0 Proof
PF11：simulation 包静态零 astrbot/provider/llm import + 运行时 sentinel
（socket/urllib/http 打桩即炸）下 3 年 harness 正常完成。

## 18. Network=0 Proof
PF12（与 PF11 同 guard）：socket.socket / urllib / http.client 全部打桩为
AssertionError，harness 完成 120 年等价路径无任何调用。

## 19. Formal DB Audit
PF20 + 独立终检（BLR_FORMAL_DB_PATH 会话级 checksum 守护）：整个 148-test
套件运行后正式库 sha256 不变（7a222326…）；NOT_ACTIVATED；seed=NULL；
tick=NULL；cursor=NULL；16 张业务/基建表全 0；TIME_ADVANCE=0；
M2_PREFLIGHT checkpoint=0。**FORMAL_AUDIT=PASS**。

## 20. World Seed Freeze Audit
`XIAOGUANG_CROW_KB/world_seed/`（21 项文件）只读验证存在；本阶段零读取、
零复制、零消费、零 checksum 更新（PF1 静态保证 simulation 包不引用该路径）。

## 21. M1/M1.1 Regression
125/125 保留（F1–F8、crash A–G、时间模型、PL1–PL22、迁移升降级等全部原样）。

## 22. New PF Test Matrix
PF1–PF20 全部 PASS（23 个测试函数，含参数化 crash×5 与所有权违约）。
`tests/test_preflight_pf.py` + `tests/zz_formal_db_guard.py`。

## 23. Conflicts Found（未静默修正，仅标记）
1. **04_time_engine §1 时间模型过时**：原文"福地年.月（integer 年+0~11 月）/
   REAL 1 DAY≈BLESSED 1 YEAR=365"与已验收的 M0 TIME_MODEL_UNIT_BLOCKER 修正
   （canonical tick µy；有理速率 1,000,000/86,400,000,000）冲突。
   裁决：以 M0/M1 已验收实现为准；04 原文不改（历史文档），冲突已在
   契约文档 §时间粒度处显式记录。
2. **04 §1 "world_runtime.time_ratio 唯一权威"** 与 M0 修正
   （time_ratio_history + rate_numerator/denominator）冲突：同上裁决。
3. 04 §4 的 RNG 公式（HASH(world_id, blessed_time, sim_version, tick_kind)）
   与 M1 derive_seed（world_id|sim_version|period_tick|subsystem|scope）是
   兼容细化而非矛盾（标注，不视为冲突）。

## 24. New Proposals（不冒充旧规划）
1. Engine Order 的四个候选顺序中采用**旧设计明文顺序**（DEMOGRAPHY 优先），
   未采用任务示例（Ecology 优先）——旧 Canon 优先。
2. Snapshot 语义 A/B 原文档未定义 → 冻结 B（staged feed-forward），依据为
   08 §1"每 tick 单向评估"+ 09 §5"互馈"；标记为 PREFLIGHT 冻结决定。
3. 引擎版本号与 pipeline_version 写入 checkpoint meta（无 migration）。
4. 120 年等价性以 state 等价（hash+tick）定义，事件数量允许随 chunk 划分
   不同（事件=历史，非状态）。
5. RNG master_seed 载体定义（world_seed_version / 测试 world_id）。

## 25. Recommended M2a–M2d Order
M2a Population Group → M2b Resource-Economy → M2c Ecology → M2d Social
Foundation（每步 mini_world 回归 + 零 LLM/网络 + ACTIVATION_TRAP=PASS；
M3 前 TRIBULATION 槽位保持 NOT_REGISTERED）。**仅建议，未自行进入。**

## 26. Git commit/tag
- tag `m1.1-live-verified`（基线）。
- 本阶段提交：`<M2-PREFLIGHT>`（contract 文档 + services/simulation 包 +
  PF 测试 + 报告）。
- 契约文档同步副本：`XIAOGUANG_CROW_KB/runtime_design/M2_PREFLIGHT_ENGINE_CONTRACT.md`
  （KB 非 git 仓库，仅文件副本；git 权威 = Runtime 仓库 runtime_design/）。

## 27. Workspace clean
`git status` = clean（world.db*、backups/*.db 由 .gitignore 排除）。

## 28. Known Risks
1. Engine Order 为 04 号文档明文，但 04 与 M0 时间模型存在已标记冲突——若主人
   裁决需要以新时间模型重读 04，顺序不变但建议在 M2a 前复核一次。
2. SQLite JSON meta 查询用 json_extract（json1 内置可用；PG 侧 jsonb 需在
   M2a 时按契约切换，当前无 migration）。
3. world_state_hash v2 覆盖六类实体表；M2a 起若新增实体表须同步哈希 schema
   并升版本。
4. Fake 引擎只为 harness 证明管线；真实引擎上线后 PF14/15/16 的等价性断言
   需以新基线数据复核。
5. 正式 DB 的 schema 零改动；M2a 如需真实 schema 扩展必须单独 migration +
   单独报告。

## 最终值
```
WORLD_RUNTIME_STATUS = NOT_ACTIVATED
seed                 = NULL
current_blessed_tick = NULL
official_world_events= 0
formal_population    = 0
formal_settlements   = 0
（正式库 sha256 不变：7a2223266fd136cf…）
```

---

```
M2_PREFLIGHT_READY
```

（完成后立即停止：不进入 M2a、不实现任何真实引擎、不进入 M3、不激活 World
Seed。等待主人下一条明确批准。）

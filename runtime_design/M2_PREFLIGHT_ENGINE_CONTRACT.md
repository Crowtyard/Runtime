# M2_PREFLIGHT_ENGINE_CONTRACT

> M2 前置冻结（DESIGN FREEZE / ENGINE CONTRACT / TEST HARNESS）。
> 本文件是 M2 引擎执行契约的唯一冻结来源（git 权威 = Runtime 仓库
> `runtime_design/M2_PREFLIGHT_ENGINE_CONTRACT.md`；KB/runtime_design/ 同步副本）。
> 本阶段只做接口/契约/fixture/harness/no-op/fake，不实现真实演化算法。
> 正式世界保持 NOT_ACTIVATED；mini_world 与正式 world_seed 完全隔离。

## 1. Pipeline

```
M1 Time Engine（catch_up，fencing WorldMutationContext 由 M1 持有）
  → 计算 Blessed Time Interval
  → simulate_fn 钩子 = Simulation Coordinator.run_step()
      → WorldSnapshot（start-of-step 权威读取）
      → StagedWorld（内存暂存，Feed-Forward）
      → 按冻结顺序调用引擎 simulate(ctx)（每引擎独立 RNG substream）
      → Proposed World Mutation（state changes + domain events + metrics）
      → 统一验证（ownership / invariants / 确定性事件 identity）
      → 经当前 fenced session 写入（禁止引擎自建 transaction/commit）
  → M1 统一 COMMIT（commit-time fencing validation）
  → Checkpoint（M1 时间 checkpoint + M2 世界 checkpoint，同一事务）
  → world_state_hash v2
```

硬规则：**一个 simulation step 只有一个确定世界**。引擎绝不 commit；一个 step 的
authoritative write 统一进入 M1 已持有的 WorldMutationContext。

## 2. Engine Protocol

```python
class Engine(Protocol):
    engine_id: str                      # DEMOGRAPHY|RESOURCE|ECONOMY|ECOLOGY|SOCIAL
    engine_version: str                 # 该引擎语义版本（进入 simulation_version 语义）
    def simulate(self, ctx: SimulationContext) -> EngineResult
```

SimulationContext（frozen）：
`world_id / simulation_version / pipeline_version / step_index / blessed_start_tick /
blessed_end_tick / real_interval_start_us / real_interval_end_us /
snapshot（start-of-step 权威快照）/ staged（只读视图 + propose 通道）/ rng（本引擎
独立 substream）/ log（诊断通道）`。

EngineResult：
`proposed_changes: list[StateChange]`（table/entity_id/field/old_value/new_value）、
`domain_events: list[DomainEventDraft]`（engine/event_type/cause/effect/severity/scope）、
`metrics: dict`（浮点仅允许统计用途，不得为身份真值）、`warnings: list[str]`、
`deterministic_meta: dict`（engine_id/engine_version/draw_count/step）。

引擎禁止：直接 commit DB / wall-clock now() / LLM / 网络 / UUID4 / 自建
transaction / 修改其他引擎私有状态（所有权表见 §5）/ 读取正式 Seed Package。

## 3. Snapshot 与 Staged Mutation 语义（冻结 = B：Feed-Forward）

- **WorldSnapshot**：step 开始时从权威 DB 一次性读取（时钟 + 世界实体表），
  规范化排序后不可变。
- **StagedWorld**：start snapshot 的内存拷贝；后一个引擎读取的是前序引擎
  `propose()` 后的暂存视图（互馈所需，见 09 §5、08 §1「每 tick 单向评估」）。
- 中间暂存**只存在于内存/事务暂存**，绝不提前成为 authoritative DB。
- 引擎只能通过 `ctx.propose(...)` 声明变更；coordinator 校验所有权后应用，
  全部变更最终合并为单一 Proposed Mutation，在 M1 事务内一次性写入。
- 快照契约变更 = simulation_version 必须升级（§8）。

## 4. Engine Order（CONFIRMED_EXISTING_SCOPE，恢复自 04_time_engine §4）

原设计明文：「顺序固定：TIME→DEMOGRAPHY→RESOURCE→ECONOMY→ECOLOGY→SOCIAL→
DISTURBANCE/TRIBULATION→EVENT」。M2 引擎顺序冻结为：

```
1. DEMOGRAPHY   (Population Group Engine)
2. RESOURCE     (Resource side of Resource-Economy Engine)
3. ECONOMY      (Economy side of Resource-Economy Engine)
4. ECOLOGY      (Ecology Engine)
5. SOCIAL       (Social Foundation)
```

- TRIBULATION 槽位 = **NOT_REGISTERED**（M3 预留，见 §13）。
- 同一 simulation_version 内 Engine Order 不可隐式改变；顺序/引擎集变更 →
  simulation_version 升级。

## 5. 状态所有权（读写边界）

| 引擎 | 可写实体 | 可读 |
|---|---|---|
| DEMOGRAPHY | population_groups | 全部 |
| RESOURCE | resource_nodes | 全部 |
| ECONOMY | industries | 全部 |
| ECOLOGY | ecological_regions | 全部 |
| SOCIAL | lineages / institutions | 全部 |

coordinator 强制：`mutation.entity_type ∉ 引擎所有权表 → INTEGRITY_ERROR`。
（persons 表在 M2 阶段不生成正式 Persistent Person；边界见 §12。）

## 6. RNG Contract

- 禁止 random 全局态/secrets/os.urandom/UUID4/wall-clock seed。
- 派生（沿用 M1 已验收实现）：
  `seed = sha256(world_id | simulation_version | blessed_period_tick(=step_start_tick)
   | engine_subsystem | entity_scope="WORLD") 前 8 字节`。
- **引擎独立 substream**：某引擎抽样次数变化不得漂移其它引擎序列（M1 已测）。
- master_seed 载体：正式世界 = world_seed_version（M6 后）；测试/夹具 = world_id
  （如 MINIWORLD-TEST-001）。run_id（UUID）**不参与**任何派生（世界结果与
  run 身份无关）。
- RNG 派生变更 = simulation_version 升级。

## 7. Event Contract（State / Domain Event / Diagnostic 三分）

- **State Mutation**：实体字段变更（world_state_changes 语义，propose 通道）。
- **Domain Event**：机器级领域事件（POPULATION_CHANGE 等），写入不可变
  world_events；M2 不创建正式历史叙事系统（历史叙事属后续阶段）。
- **Diagnostic Log**：只进日志，永远不成为正式历史。
- 事件确定性 identity（重试幂等，**EVENT_UID_SCHEMA_VERSION=1，≥128-bit**）：
  `event_uid = sha256("v1|world_id|simulation_version|interval_start|
  interval_end|engine_id|event_type|stable_local_sequence") 的 hex 前 32 字符`。
  禁止 UUID4 / wall clock / DB autoincrement / 随机值；event_type 参与语义身份
  （不同 event_type 不得同 identity）。TIME_ADVANCE 基础设施事件同样使用
  确定性 uid（engine_id="TIME", event_type="TIME_ADVANCE", seq=0）。
  重试幂等双防线：M1 区间幂等 skip + 确定性 uid 唯一约束。

## 7b. Event Stream Hash（EVENT_STREAM_HASH_SCHEMA_VERSION=1）

- 与 world_state_hash **语义分离**：state hash = authoritative state digest；
  event_stream_hash = 截至某 simulation run 的机器级 Domain Event Stream 的
  确定内容与顺序证明。
- 增量链：`h_0 = H("event-stream-v1|world_id|simulation_version")`；
  `h_i = H(schema|world_id|simver|h_{i-1}|step_i 的 domain events（发射顺序）)`；
  每事件 canonical 字段 = event_uid/blessed_tick/event_type/source/cause/
  effect/severity/scope（无 wall-clock/行 id）。Diagnostic Log 永不进入。
- 存储：M2 世界 checkpoint meta.event_stream_hash（+ prev_event_stream_hash）。
- 不变量：相同 initial state + semantics + RNG → state hash 相同 **且**
  event stream hash 相同；最终 State 相同而事件序列不同 → state hash 可以
  相同、event stream hash 必须不同。

## 8. simulation_version Contract

WORLD EVOLUTION SEMANTICS VERSION（不是软件版本号）。必须升级（+不可重算历史）：
引擎算法变化 / 引擎顺序变化 / RNG 派生变化 / 事件语义变化 / 状态转移规则变化 /
Snapshot 契约变化。只改 UI/日志/注释不得升级。M2_PREFLIGHT 测试世界使用
`0.2.0-preflight`；正式世界保持 `0.1.0-dev`（未激活，M6 前不动）。

## 9. world_state_hash v2（WORLD_STATE_HASH_SCHEMA_VERSION = 2）

- canonical serialization：UTF-8 JSON（sort_keys=True、紧凑分隔符），
  字段顺序固定、实体按语义键元组排序（见下表）。
- 覆盖：world clock（tick/cursor/rate_id/remainder）、settlements、
  population_groups、resource_nodes、industries、ecological_regions、
  lineages、institutions、simulation_version、engine_pipeline_version、
  各 engine_version。
- 禁止作为输入：DB 行物理顺序 / autoincrement id 顺序 / now() 时间戳 / 日志
  元数据 / 事件日志（事件是历史，不属于状态哈希）。
- 语义键排序（每表）：settlements=(settlement_type,working_name,id)；
  population_groups=(species,settlement_ref,age_cohort,occupation_group,id)；
  resource_nodes=(kind,region_ref,id)；industries=(kind,node_ref,id)；
  ecological_regions=(terrain,climate,water,id)；lineages=(lineage_type,head_person_ref,id)；
  institutions=(kind,settlement_ref,owner_ref,id)。id 仅作同语义去重 tiebreaker
  —— fixture 禁止同语义重复行。哈希 schema 版本字段可升级（v3+ 兼容读取 v2）。

## 10. Checkpoint Contract（M1 扩展，无强制 migration）

checkpoint_kind 语义（冻结）：
- **TIME_COMMITTED（M1 CATCHUP 层，kind="CATCHUP"）**：时间引擎 checkpoint ——
  现实游标/进位的最低限度恢复（快速时钟恢复）。
- **WORLD_COMMITTED（M2 层，kind="M2_PREFLIGHT" + checkpoint_kind=
  "WORLD_COMMITTED" + phase="COMMITTED"）**：世界语义 checkpoint ——
  world_state_hash v2 + event_stream_hash + simulation_version +
  engine_pipeline_version（meta）—— **crash recovery 的权威 checkpoint**。

规则：每 1 个 committed simulation step 严格产生 1 TIME_COMMITTED +
1 WORLD_COMMITTED（共 2 个；120 steps → 240 为契约内预期，非重复写入）。
恢复一律以 complete=True 且 checkpoint_kind=WORLD_COMMITTED 的最新 M2
checkpoint 为准（CATCHUP 行不参与世界语义恢复；
`latest_authoritative_world_checkpoint`）。真实 schema 扩展留到 M2a 需要时
单独迁移与报告；本阶段全部增量字段写入 meta JSON。

## 11. Crash Boundaries（C1–C10 harness）

C1 before snapshot / C2 after snapshot / C3 mid engine pipeline / C4 after all
engine results / C5 before mutation transaction / C6 during DB writes /
C7 before fence recheck / C8 commit ack lost / C9 before checkpoint /
C10 after checkpoint。全部语义 = 事务原子：崩溃点前无部分权威写入；
崩溃后重试/恢复不重复累计（M1 幂等 + 确定性事件 uid）。

## 12. mini_world fixture（mini_world_v1，仅测试）

- world_id=`MINIWORLD-TEST-001`；2 settlements（1 MAIN + 1 SATELLITE）、
  1 species（2 个 population_groups，每聚落一个）、1 resource_node，
  最小必要字段（ecological_regions 1 行、可选 lineage/institution 0 行）。
- 全部数值 = **TEST_FIXTURE_ONLY** 固定常量；不读取、不复制
  `XIAOGUANG_CROW_KB/world_seed/` 任何内容；不冒充 Local Canon。
- 只运行于 tmp/test DB；正式 blessed_land.sqlite 永不运行 mini_world。

## 13. 120 Blessed Years Harness

- 时间粒度（CONFIRMED，04 §2/§3）：**默认年度步进**（1 blessed year = 1
  simulation step）；自适应分辨率（季度/月度/event step）属未来调度器，
  本阶段只冻结默认。120 年 = 120 个年度 step。
- `run_mini_world_120y(session_factory, engines, chunk_years=...)`：逐年度调用
  M1 catch_up（合成现实时间输入 EPOCH0+1y×i；wall-clock 永不参与），
  simulate_fn = coordinator.run_step；NoOp/Fake 引擎即可运行整链。
- 等价性定义：**state 等价** = 最终 world_state_hash v2 + 最终 tick 相等；
  事件日志数量允许因 chunk 划分不同（事件是历史，非状态）。
- Metrics 见 §14。真实 baseline 数值等 M2a–M2d 引擎实现后跑出再冻结，
  本阶段不预设"人口 120 年必须到多少"。

## 14. 120y Metrics Schema（仅定义 schema，不预设数值）

population：start/end/births/deaths/migrations；economy：stock/production/
consumption/shortages；ecology：state/pressure；society：households/lineages/
institution_events；infra：runs/events/checkpoints/steps/final_hash。
浮点仅限统计字段；身份/索引字段禁止浮点真值。

## 15. Future M2a–M2d Integration Boundary（仅建议顺序，不自行进入）

M2a Population Group → M2b Resource-Economy → M2c Ecology → M2d Social
Foundation（每步 mini_world 回归 + 零 LLM/网络 + ACTIVATION_TRAP=PASS）。
TRIBULATION 槽位保持 NOT_REGISTERED 直至 M3 批准。

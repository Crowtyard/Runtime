# M2_SCOPE_RECOVERY_REPORT

> 执行方：DSH。性质：只读范围恢复（不设计新 M2、不进入 M2 编码）。
> 证据来源：`XIAOGUANG_CROW_KB/runtime_design/`（PHASE_1_9 全套 20 篇 +
> RUNTIME_ARCHITECTURE.json + PHASE_1_9_RUNTIME_ARCHITECTURE_REPORT）、
> `design/phase1_8/`、M0/M1/M1.1 报告、git 历史（无任何 M2 代码提交）。

## 1. 权威 M2 定义（已恢复，证据确凿）

**`runtime_design/20_implementation_roadmap.md`（IMPLEMENTATION_ROADMAP）**：

> **M2 基础引擎（Simulation core）**：人口群体引擎（06）；资源-经济引擎（08）；
> 生态引擎（09）；社会引擎基础（07：自治事件/家庭/lineage）。
> **验收：mini_world 跑 120 福地年回归基线；零 LLM 调用。**

顺序依赖：M0→M1→(M2 并行引擎按依赖推进)→M3→M4→M5；每里程碑向主人交付验收
证据，不自动进入下一里程碑。M6 World Seed 激活另行裁决（SNAPSHOT_V1 批准 →
写入 world_seed_version、纪年开始）。

配套文档（均为 PHASE_1_9 正式产物）：
- `06_population_engine.md`：群体模型（population_groups）/确定性/Persistent
  Person 子集/寿命与代际/关系标签/展示关系；输出=cohort 计数变化→
  demographic events（出生潮/老龄化/劳动力缺口，仅叙事价值时生成）。
- `07_social_engine.md`：社会实体/自治与干预门槛（WS-0603）/规则与事件类型/
  确定性与随机/文化扩散（WS-1002/WS-1004）/输出契约。
- `08_resource_economy_engine.md`：生产链（每 tick 单向评估）/资源节点状态机
  （WS-0703）/产业/市场简化模型（v1 不模拟金融）/灾后代谢（与 10 号联动）/输出契约。
- `09_ecology_engine.md`：生态区域状态/生态关系（不是随机刷怪，WS-0804）/
  异兽边界（硬性）/事件类型/与人口经济互馈/输出契约。
- `18_testing_strategy.md`：**mini_world = 小型固定世界（2 聚落/1 种族/
  1 资源节点）单元集成基准**；seed_world（激活后）才是正式基线快照；
  「模拟引擎核心测试全绿前，不进入 World Seed 激活（运行时验收另行裁决）」。
- `PHASE_1_9_RUNTIME_ARCHITECTURE_REPORT.md`：M2=人口/经济/生态/社会规则引擎；
  World Seed 激活与正式纪年、EVENT_NOTIFICATION_SERVICE、Persistent NPC 正式
  生成等「以后再做」。

## 2. 三类区分

### CONFIRMED_EXISTING_SCOPE（有正式文档定义）
1. M2 四引擎范围：人口群体引擎、资源-经济引擎、生态引擎、社会引擎基础
   （自治事件/家庭/lineage）——roadmap + 06/07/08/09 四篇设计文档。
2. M2 验收标准：mini_world 跑 120 福地年回归基线 + **零 LLM 调用**。
3. mini_world fixture 定义：2 聚落 / 1 种族 / 1 资源节点（18_testing_strategy）。
4. 引擎确定性要求：各引擎「确定性与随机」节 + M1 RNG 子系统
   （DEMOGRAPHY/RESOURCE/ECONOMY/ECOLOGY/SOCIAL）已预置。
5. 引擎输出契约：各引擎「输出契约」节（state changes + 有叙事价值的 events）。
6. 联动接口：08 §5 灾后代谢与 10 号（M3 灾劫）联动；09 §5 与人口/经济互馈。
7. 顺序与门禁：M1→M2；M2 不激活正式世界（激活=M6 主人裁决）。

### IMPLIED_NEXT_STEP（架构明显暗示，但无正式 M2 定义文本）
1. M2 引擎接入 M1 tick 管线：M1 catch_up 已预留 `simulate_fn(session,
   advance_info)` 钩子，但「引擎如何注册进 tick、每 tick 调度顺序」无正式文档。
2. 引擎与 checkpoint/world_state_hash 的整合：M1 时钟哈希如何升级为
   含世界状态的哈希（M1 报告已列为风险）。
3. 引擎事件写入纪律：经 fencing 统一入口 + 不可变 world_events（M0/M1 基建
   已就绪，引擎侧用法无正式文档）。
4. simulation_version 的引擎语义（算法变更升版本、禁止重算历史）仅存于
   M0 constants 注释，无 M2 级定义。
5. mini_world 的 120 年验收基线的具体指标（哪些曲线/不变量）未定义。
6. World Seed 激活的预检清单（激活前必须 PASS 的项）部分散见于各报告，
   无单一正式文档。

### NEW_PROPOSAL（DSH 建议，不得冒充旧规划）
1. M2 拆为 4 个可独立验收的子里程碑：2a 人口 → 2b 资源经济 → 2c 生态 →
   2d 社会基础，每步跑 mini_world 回归（与「并行引擎按依赖推进」一致）。
2. 新增 `M2_PREFLIGHT`：先建 mini_world fixture + tick-driver harness
   （M1 catch_up 钩子 + 四引擎空壳），确认 120 年零 LLM 管线可重复运行，再写引擎。
3. 引擎回归快照：把 M1 `world_state_hash`（时钟哈希）升级为 mini_world 全状态
   哈希，作 120 年基线快照。
4. M2 全程维持 LIVE_ACTIVATION_TRAP=PASS 与 NOT_ACTIVATED 正式世界（新增 CI 断言）。
5. 每引擎验收附加「RNG 调用数扰动不影响其他子系统」回归（M1 测试模式的引擎化）。
6. 灾劫接口（M3）以 08 §5 的「灾后代谢」为对接面，M2 仅实现接口空位。

## 3. 15 个候选领域逐项标记

| # | 候选领域 | 标记 | 证据/说明 |
|---|---|---|---|
| 1 | World Activation | LATER_MILESTONE | Roadmap M6（另行裁决）；需 WORLD_ACTIVATION_APPROVED_BY_OWNER |
| 2 | Seed Initialization | LATER_MILESTONE | 正式 Seed=M6 SNAPSHOT_V1（phase1_8/11_initial_world_snapshot_proposal）；M2 只用 mini_world fixture |
| 3 | Blessed Tick / Time Progression | NOT_APPLICABLE | 已于 M1 交付（M2 消费之） |
| 4 | Runtime Cursor | NOT_APPLICABLE | 已于 M1 交付（last_committed_real_us） |
| 5 | Scheduler | LATER_MILESTONE | 引擎按 tick 跑=复用 M1 catch_up 钩子（IMPLIED）；日程服务=M4；常在线通知=以后再做 |
| 6 | Offline Catch-up | NOT_APPLICABLE | 已于 M1 交付 |
| 7 | Official World Event creation | LATER_MILESTONE | 正式 WORLD_EVENT/HISTORY 服务=M3；M2 引擎按输出契约写基础设施事件 |
| 8 | Tribulation scheduling | LATER_MILESTONE | M3（10_tribulation_engine，T-3M 九阶段） |
| 9 | Runtime persistence | NOT_APPLICABLE | 已于 M0/M1 交付（checkpoint/backup/immutability） |
| 10 | Query Layer | LATER_MILESTONE | M5 ASTRBOT_WORLD_ADAPTER（只读 API，14 号文档）；M1.1 已记录只读边界 |
| 11 | Private Companion read integration | LATER_MILESTONE | M5；M1.1 调研结论 NO_PUBLIC_CONTRACT，走官方 hook |
| 12 | AstrBot official hooks | LATER_MILESTONE | M5（on_llm_request 等，见 M1.1 ARCHITECTURE §6） |
| 13 | World State API | LATER_MILESTONE | M5 adapter（14 号「暴露 API（bible 23 节）」） |
| 14 | Owner explicit activation command | LATER_MILESTONE | M6 门禁（OWNER_ACTION_API 本体=M4） |
| 15 | Activation rollback / backup policy | LATER_MILESTONE | M1 备份基建已交付；激活回滚政策未见正式定义（IMPLIED，建议并入 M6 门禁文档） |

## 4. 结论

```
M2_SCOPE_RECOVERED = TRUE
```

M2 的正式定义已完整恢复（四引擎 + mini_world 120 福地年零 LLM 验收 + M1→M2
顺序与门禁）；IMPLIED_NEXT_STEP 已列出 6 项；NEW_PROPOSAL 6 项仅作建议，
不冒充旧规划。M2 启动仍需主人批准；World Seed 激活在任何情况下都不属于 M2。

# M3B_CAUSAL_WORLD_HISTORY_SERVICE

> M3b 因果世界历史服务实现文档。CONFIRMED_EXISTING_SCOPE = 恢复自旧设计
> （05/06/08/09 号为主）；IMPLIED = 旧设计隐含但未定量；NEW_PROPOSAL =
> DSH 冻结决定；CONFLICT_FOUND = 与 M3b 任务的显式边界冲突及裁决。
> History Service = READ ONLY；LLM_CALLS=0、LLM_TOKENS=0、NETWORK_CALLS=0。
> 自然语言叙事留给 M5（Narrative Renderer）。

## 1. Scope

机器可审计的 CAUSAL WORLD HISTORY：因果图（为什么）+ 实体历史 +
Episode 历史 + State Change Provenance + Timeline + why 查询 +
完整性审计 + Correction/Supersede。禁止：LLM 历史写作、自然语言编年史、
Scheduler、Private Companion、Seed 激活。

## 2. Baseline

M3a ACCEPTED（a111b5a，tag m3a-tribulation-engine-ready，519/519）。
正式世界 NOT_ACTIVATED、seed=NULL、tick=NULL、formal content EMPTY。
M3b 纯历史索引：不改任何模拟语义（§17）。

## 3. History ≠ Event Log

world_events 记录「发生了什么」（immutable，已有）；M3b 增加「为什么 +
造成什么 + 之后怎样」：EVENT → STATE CHANGE → RESULT → NEXT EVENT →
CURRENT STATE。按时间排序 events ≠ 历史系统。

## 4. History Graph 模型

节点（NODE_KINDS 冻结）：EVENT（world_events.event_uid）、
STATE_CHANGE（history_state_changes.id）、EPISODE（episode_id）、
PLAN（plan_id）、DECISION（decision_id）、RECOVERY_STATE（episode_id）、
RESIDUAL（tribulation_residual_changes.id）、SUCCESSION
（candidate_id）、ENTITY（type:id）、CHECKPOINT（id）。
边：causal_history_links（source → target，附 tick/episode/entity_scope/
owner_decision_id/status/semantic_version）。

## 5. Relation 词表（冻结）

CAUSES / TRIGGERS / RESULTS_IN / AFFECTS / CONTINUES / RECOVERS_FROM /
CORRECTS / SUPERSEDES / REVERSES / DECIDED_BY / PART_OF_EPISODE /
DERIVED_FROM / MATERIALIZES_IN（13 个，新增须版本化）。
方向约定：source = 解释/前因，target = 被解释/结果；trace 只走入边。

## 6. Tick 规则（防止 Year100 造成 Year50）

- FORWARD（source.tick <= target.tick）：CAUSES/TRIGGERS/RESULTS_IN/
  AFFECTS/CONTINUES/RECOVERS_FROM/DERIVED_FROM/MATERIALIZES_IN；
- BACKWARD（source.tick >= target.tick）：PART_OF_EPISODE（归属边，
  事件 tick ≥ episode 进入 tick）；
- NONE（任一方无 tick，如 PLAN）：DECIDED_BY；
- FREE（retrospective correction，显式分类，绝不用 CAUSES）：
  CORRECTS/SUPERSEDES/REVERSES。

## 7. Causal Link ID

link_id = deterministic_hex_id([world, relation, source_kind, source_id,
target_kind, target_id, episode_id|"", history-v1], bits=128,
schema=causal-link-id-v1)。无 UUID4；重放/ack-lost 幂等（同 id skip）。

## 8. Cycle 防护

禁环集合 = 除 correction 三关系外全部（DAG-like）。插入时防御：
自环拒绝 + 反向二环拒绝 + EVENT CONTINUES 链深度受限 DFS（64）；
完整图环保证由 HISTORY_INTEGRITY_AUDIT（拓扑 DFS）提供。

## 9. Missing Reference

任何 source/target 节点不存在 → IntegrityError（禁止 silent orphan）。
存在性按 kind 批量/缓存解析（EVENT/STATE_CHANGE/EPISODE/PLAN/
DECISION/RECOVERY_STATE/RESIDUAL/SUCCESSION/ENTITY/CHECKPOINT）。

## 10. State Change Provenance

每个权威 state change（history_state_changes）内联 provenance：
simulation_run_id / engine_id / event_ref（domain_event_id）/
trigger_event_id / episode_id / owner_decision_id / committed_tick
（=blessed_tick）/ old_value / new_value。旧数据（M0-M3a 未索引运行）
缺字段 = NULL，不伪造（audit 报告 legacy_world_state_changes）。

## 11. M3b 账本独立（Hash 中性关键决策）

history_state_changes 为 M3b 自有账本；绝不向 M0 world_state_changes
插行。否则 M3a 的 tribulation_causal_links.state_change_ids（进 v6 哈希）
的 autoincrement id 会漂移 → world_state_hash 改变。实测：history 开启/
关闭 30y 世界与事件流哈希逐字节一致。

## 12. 与 Domain Events 的原子性

HistoryLinkBuilder 在 SimulationCoordinator.run_step 内、事件写入之后、
before_checkpoint 崩溃点之前，同一 WorldMutationContext 事务内构建。
事件提交而索引缺失的静默间隙不存在；崩溃 → 一起回滚（HB11）。

## 13. Fencing

History Link 创建属 world mutation：全部经 WorldMutationContext
commit-time fencing（HB10：stale writer 不得提交）。

## 14. Idempotency

确定性 link_id + (world_id, link_id) 唯一约束：同一 simulation retry /
ack-lost 不重复创建（HB2/HB9）。

## 15. 构建规则（冻结）

- 引擎账本：每引擎每步的非记账字段变更 → history_state_changes
  （old 取自 start-of-step 快照行）；
- 事件匹配：事件 payload（cause/effect）深扫实体 scope 键
  （settlement_ref/zone_ref/resource_profile_ref 等，SCOPE_KEYS 冻结）
  → 命中则 AFFECTS（seq 最后命中）；无命中 → event_ref=NULL
  （不伪造归属）；
- CONTINUES：同 (entity_type, entity_id, field) 前一变更 → 本变更
  （source=prev, target=new）；
- 跨域 CAUSES（同 Step 前馈）：resource_nodes reserve/extraction →
  ecology_state 压力/质量（scope：settlement_relation/region_ref）；
- 灾劫图：SCHEDULED RESULTS_IN EPISODE；阶段事件 PART_OF_EPISODE +
  前阶段 CONTINUES 后阶段；DECISION/自治事件 DECIDED_BY PLAN；
  PLAN RESULTS_IN IMPACT_STARTED/IMPACT_APPLIED；IMPACT_APPLIED
  AFFECTS adapter 变更；冲击 RECOVERS_FROM 恢复状态；冲击
  DERIVED_FROM 残留；残留 DERIVED_FROM 继承候选；
- Episode 索引同步 + 水印（history_index_state.indexed_through_tick）。

## 16. 只读查询 API

HistoryService（0 mutation）：
- get_timeline(world_id, start/end_tick, event_types) — 按时间；
- get_entity_history(entity_type, entity_id) — 直接影响该实体；
- get_scope_history / get_region_history / get_settlement_history /
  get_resource_history / get_lineage_history / get_institution_history；
- get_tribulation_history(episode_id) — 完整 Episode；
- explain_state(entity_type, entity_id, field) — CAUSAL_HISTORY_CHAIN；
- trace_causes(kind, id) — 上游追溯；
- history_integrity_audit() — 完整性；
- causal_history_hash() — v1。

## 17. explain_state()（M3b 核心）

current_value → last relevant state change（prev/new/event_ref/provenance）
→ 入边原因（事件/上游变更/Episode 上下文）→ 递归。多因分支列表；
不强制单根因；无真实归因权重则只列 contributing causes（§36）。

## 18. 深度控制

max_depth / max_nodes / start_tick / end_tick / relation filters /
include_superseded。默认返回最相关有限因果路径（HB40）。

## 19. Deterministic 排序（冻结）

事件：ORDER BY (blessed_tick, id)；links：ORDER BY (committed_tick,
relation priority, source_id, target_id, link_id)。禁止 DB physical row
order / Python set order / wall-clock。RELATION_PRIORITY 冻结
（CAUSES=0 … REVERSES=12）。

## 20. Tribulation Episode History

返回 schedule/profile/targets/precursor/preparation/decision/mitigation/
impact/domain effects/stabilization/residual/recovery/succession/
new normal + 状态派生：COMPLETED；ACTIVE（stage）；IN_RECOVERY
（stage=RECOVERY）；completion=INCOMPLETE（未完成，绝不伪装 COMPLETED）。

## 21. 第 30 窗口（300y 截止）

300y 末窗 Episode（entered_tick=300M，PRECURSOR）：History Service 返回
status=ACTIVE、completion=INCOMPLETE、stage=PRECURSOR；不丢失、
不补完、不在 timeline 隐藏（HB15/HB33）。

## 22. Entity History 边界

只返回直接影响该实体（或其 scope 实体）的变更/事件：entity_history_index
（entity → link）+ 账本。Resource Node 看到开采/灾劫损伤/恢复/生态反馈/
succession；看不到无关聚落家庭拆分。

## 23. Timeline 与 History Graph 分离

Timeline = 按时间看发生了什么（get_timeline）；History Graph = 按因果
看为什么（explain_state/trace_causes）。共享底层数据，API 分离。

## 24. Correction / Supersede（append-only）

错误不原地改旧 event：submit_history_correction（fenced）→ 新
HISTORY_CORRECTION 事件（确定性 uid，进 event stream）+ CORRECTS/
SUPERSEDES/REVERSES 新边。SUPERSEDES 把旧事件出边（ACTIVE）置
SUPERSEDED。默认查询显示当前有效解释；include_superseded=true 看
审计链。supersede 环防护：每事件至多被取代一次（HB8）。

## 25. Corrections 不改旧 hash

旧 event payload/uid/历史 hash 全部不变；correction 事件进新 stream。

## 26. WorldEpisode（NEW_PROPOSAL）

通用 history_episode_index（kind 字段）：当前仅 TRIBULATION；未来迁徙
周期/资源开发/机构兴衰复用。不过度抽象：仅索引字段，无行为逻辑。

## 27. Resource Succession 链

Tribulation → Residual Change → Succession Candidate →（未来）
Ecology stabilization → Resource discovery → Node materialization。
M3b 已建立完整关系能力（DERIVED_FROM 链）；物化由 Resource Engine
后续决定（History 不生成 Resource）。

## 28. History 不生成 Resource

History Service = READ ONLY：查询历史绝不触发 materialization / state
transition / event creation。0 mutation（HB25 用 DB checksum 实测）。

## 29. LLM / Network / Wall-clock = 0

services/history/* 源码扫描：无 openai/anthropic/requests/httpx/socket/
urllib/token_usage；无 datetime.now/time.*（HB26-28）。查询确定性输出
不含 wall-clock（性能测量仅进基线 summary，不进 hash）。

## 30. History Index（性能设计）

索引：links(committed_tick)、links(source)、links(target)、
links(episode)、links(relation,tick)、entity_history_index(scope,tick)、
history_state_changes(entity,tick)、history_state_changes(episode)、
history_episode_index(status)。避免「北山过去 100 年」全表扫描。

## 31. Database Growth

History Index 只存关系/index 与数值字段（old/new 为 {"v": …} 小 JSON），
不复制完整 event payload。300y 实测规模见基线 summary（§35）与报告。

## 32. Causal History Hash（v1）

causal_history_hash v1：versioned（causal-history-hash-v1）/ canonical
（ORDER BY link_id）/ 行序无关。覆盖 link identity + relation +
source/target ids + episode + status + committed_tick +
semantic_version；不重复 hash event payload（event_stream_hash 已覆盖）。
与 world_state_hash / event_stream_hash 语义分离。

## 33. HISTORY_INTEGRITY_AUDIT

orphan links / causal cycles（禁环子图拓扑 DFS）/ missing events（=orphan）
/ missing state changes / missing episodes（=orphan）/ duplicate links /
invalid relation type / tick paradox / supersede loops / 未索引 legacy
state changes / 水印。300y 后 clean（HB31/32）。

## 34. 300y 历史图基线

tests/baselines/m3b_causal_history_300y_v1/：summary.json /
episode_history_samples.json / entity_history_samples.json /
why_query_samples.json（A-F 六问）/ timeline_samples.json /
causal_graph_digest.json + causal_history_hash。
M3b 收口审计新增：metric_audit.json / episode_state_audit.json /
entity_cardinality_audit.json / relation_density_audit.json /
query_performance.json / growth_projection.json（不覆盖旧原始基线）。
Metric 命名修正（收口审计）：OLD_METRIC_NAME=entities_with_history →
NEW_METRIC_NAME=entity_history_index_rows（REASON：旧值 64,858 为
entity_history_index 原始行数（每 (entity, link) 一行，含重复），
非 distinct 实体数）；新增 distinct_entities_with_history=134
（domain entity 口径）。Episode 口径修正：互斥状态分类
（COMPLETED=28 + NEW_NORMAL_PENDING=1 + PRECURSOR=1 = 30 indexed；
M3a 的 completed=29 为 stage==NEW_NORMAL 口径，M3b 的 incomplete=2
为 status!=COMPLETED 口径，二者一致不冲突）。
复用 M3A_TRIBULATION_SYNTHETIC_WORLD 只读夹具；world_state_hash /
event_stream_hash 与 M3a 冻结基线逐字节一致（HB34/MA22/MA23）。

## 35. Query Performance

synthetic 300y：entity history / episode history / why query / timeline
各测 p50/p95/max（warm-up 排除；进 query_performance.json，不进 hash）。
收口审计修复：entity_history 逐 link SELECT → 批量分块 + 列裁剪加载
（p50 778ms → 189.7ms，p95 219.7ms）。全表扫描审计：
FULL_TABLE_SCAN_RISK=[]，新增 ix_world_events_tick（migration
d7f9b1c3e5a7）。

## 36. M2/M3a 回归

519/519 保留；M2a/b/c/d/1000y + M3a 300y 基线逐字节复现。
history 关闭 → 行为与 M2/M3a 完全一致；history 开启 → 只写 5 张新表
+ history_state_changes（不进任何既有哈希域）。

## 37. Formal World 保护

正式库：仅 schema migration（head c5e7a9b1d3f5）；NOT_ACTIVATED；
5 张 history 表 0 行；formal episodes=0；official events=0（HB36）。

## 38. World Seed 保护

world_seed/ byte-for-byte unchanged；禁止消费（HB37）。

## 39. PostgreSQL

SQLite live + PG code audit：无 json_extract/rowid/INSERT OR REPLACE；
JSON 经 ORM；BigInteger 整数列。PRE_ACTIVATION_PG_GATE /
PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_GATE 保持 REQUIRED。

## 40. Migration

c5e7a9b1d3f5_m3b_causal_history（down_revision=f1b3c5d7e9a2，只 ADD）：
causal_history_links / entity_history_index / history_state_changes /
history_episode_index / history_index_state。

## 41. Files

- services/history/relations.py（词表/tick 规则/优先级/identity）
- services/history/entities.py（entity_type 注册表 + scope 键）
- services/history/builder.py（HistoryLinkBuilder + StepHistoryBundle）
- services/history/service.py（HistoryService：查询/审计/hash）
- services/history/corrections.py（Correction API）
- services/simulation/coordinator.py（同事务挂接；hash 路由不变）
- services/catchup.py（info["simulation_run_id"] 增量键）
- database/models_world.py（5 模型）+ migration c5e7a9b1d3f5
- tests/test_m3b_history.py（HB1–HB43）
- tests/baselines/m3b_causal_history_300y_v1/

## 42. STOP Conditions

交付后 STOP：不进入 M3c/M4/M5/M6；不激活世界；不注册 TRIBULATION
槽位；不推进正式时钟；不暴露 Companion/聊天接口；M5 再做生产 Query
Layer 与小光语言叙事。

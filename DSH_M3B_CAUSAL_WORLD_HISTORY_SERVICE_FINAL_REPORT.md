# DSH_M3B_CAUSAL_WORLD_HISTORY_SERVICE_FINAL_REPORT

> 执行方：DSH。阶段：M3B_CAUSAL_WORLD_HISTORY_SERVICE（真实历史服务 /
> 因果图 / 实体历史索引 / 世界状态解释基础）。
> 基线：M3a ACCEPTED @ a111b5a（tag m3a-tribulation-engine-ready，
> 519/519）+ 正式世界 NOT_ACTIVATED / seed=NULL / tick=NULL / content EMPTY。
> 交付后立即 STOP：不进入 M3c/M4/M5/M6，不激活世界，等待主人明确批准。

## 1. Baseline

M3a @ a111b5a（519/519）；M2_ENGINE_SET_FROZEN=TRUE；M3_PREFLIGHT
ACCEPTED。M3b 开工前正式库 head=f1b3c5d7e9a2。

## 2. Source Design

CONFIRMED_EXISTING_SCOPE（05/06/08/09）：灾劫为世界代谢、因果历史链、
资源继承候选。IMPLIED：为什么/造成什么/之后怎样三层追问、State Change
溯源。CONFLICT_FOUND：叙事写作 → M5；历史查询服务 ≠ 事件排序。

## 3. History Architecture

HistoryLinkBuilder（写索引，模拟事务内）→ 5 张 history 表 →
HistoryService（只读查询/审计/哈希）→ Correction API（append-only）。
History Index 是对已发生事实的索引：不改任何模拟表语义、不进
world_state_hash / event_stream_hash。

## 4. Graph Model

节点 10 类（EVENT/STATE_CHANGE/EPISODE/PLAN/DECISION/RECOVERY_STATE/
RESIDUAL/SUCCESSION/ENTITY/CHECKPOINT）；边 = causal_history_links
（source → target，附 tick/episode/entity_scope/owner_decision_id/
status/semantic_version）。

## 5. Relation Types

13 个冻结关系：CAUSES/TRIGGERS/RESULTS_IN/AFFECTS/CONTINUES/
RECOVERS_FROM/CORRECTS/SUPERSEDES/REVERSES/DECIDED_BY/
PART_OF_EPISODE/DERIVED_FROM/MATERIALIZES_IN。
方向约定：source=解释/前因，target=被解释/结果；trace 只走入边。

## 6. State Provenance

history_state_changes 内联 provenance：simulation_run_id / engine_id /
event_ref（domain_event_id）/ trigger_event_id / episode_id /
owner_decision_id / blessed_tick / old_value / new_value。
M3b 自有账本，绝不写 M0 world_state_changes（保证 M3a
tribulation_causal_links.state_change_ids 逐字节不变 → world_state_hash
逐字节不变）。旧数据缺字段 = NULL，不伪造。

## 7. Entity History

get_entity_history / get_scope_history / get_region_history /
get_settlement_history / get_resource_history / get_lineage_history /
get_institution_history：只返回直接影响该实体（或 scope 实体）的
state change + 关联事件（entity_history_index → links → EVENT）。

## 8. Episode History

get_tribulation_history：schedule/profile/targets/阶段事件链/决策/
计划/domain effects/恢复/残留/继承候选 + 状态派生（COMPLETED /
ACTIVE(stage) / IN_RECOVERY / completion=INCOMPLETE）。

## 9. Timeline

get_timeline(start/end_tick, event_types)：按 (blessed_tick, id) 冻结
排序；与 History Graph API 分离（共享底层数据）。

## 10. Why Query

explain_state(entity_type, entity_id, field) → CAUSAL_HISTORY_CHAIN：
current_value → last relevant state change（prev/new/event_ref/
provenance）→ 入边原因递归 → Episode/决策上下文。trace_causes(kind,
id) 通用上游追溯。

## 11. Multi-cause

多因分支列表；不强制单根因。无真实归因权重 → 只列 contributing
causes，不伪造百分比（§36 遵守）。

## 12. Correction/Supersede

submit_history_correction（fenced）：新 HISTORY_CORRECTION 事件
（确定性 uid，进 event stream）+ CORRECTS/SUPERSEDES/REVERSES 新边；
SUPERSEDES 置旧事件出边 SUPERSEDED。默认查询显示当前有效解释；
include_superseded=true 看审计链。supersede 环防护：每事件至多被
取代一次。旧 event payload/uid/hash 永不修改。

## 13. Identity

link_id = deterministic 128-bit（causal-link-id-v1）；无 UUID4；
correction 事件 uid = deterministic_event_uid（engine_id=HISTORY）。

## 14. Integrity

HISTORY_INTEGRITY_AUDIT：orphan / cycles（禁环子图拓扑 DFS）/
duplicate links / invalid relation / tick paradox / supersede loops /
legacy 未索引 state changes / 水印。300y 后 clean。

## 15. Cycle Protection

禁环 = 除 correction 三关系外全部。插入防御：自环 + 反向二环 +
EVENT CONTINUES 链深度受限 DFS；全图保证 = audit 拓扑 DFS。

## 16. Tick Semantics

FORWARD（CAUSES/TRIGGERS/RESULTS_IN/AFFECTS/CONTINUES/RECOVERS_FROM/
DERIVED_FROM/MATERIALIZES_IN）；BACKWARD（PART_OF_EPISODE）；
NONE（DECIDED_BY）；FREE（CORRECTS/SUPERSEDES/REVERSES，retrospective
显式分类，绝不用 CAUSES）。HB7：Year100 CAUSES Year50 拒绝，
CORRECTS 允许。

## 17. Causal History Hash

causal_history_hash v1（causal-history-hash-v1）：versioned / canonical
（ORDER BY link_id）/ 行序无关；覆盖 link identity + relation +
source/target ids + episode + status + committed_tick +
semantic_version；不重复 hash payload（event_stream_hash 已覆盖）。

## 18. Atomicity

Builder 在 run_step 内、事件写入后、before_checkpoint 崩溃点之前，
同一 WorldMutationContext 事务内构建 → 事件提交而索引缺失的静默
间隙不存在；崩溃 → 一起回滚（HB11 实测）。

## 19. Fencing

History link 创建属 world mutation：经 WorldMutationContext
commit-time fencing（HB10：stale writer 零提交）。

## 20. Idempotency

确定性 link_id + (world_id, link_id) 唯一：retry/ack-lost 不重复
（HB2/HB9）。

## 21. 300y History Graph

M3a 合成世界只读复跑 + history 索引（300 年）：
causal_links = 65,742；entity_history_index_rows = 64,858（收口审计更名，
OLD_METRIC_NAME=entities_with_history，REASON=实为索引行数而非实体数）；
distinct_entities_with_history = 134；episodes_indexed = 30；
state_changes_indexed = 37,818；
incomplete_episodes = 2（NEW_NORMAL_PENDING@y290 + PRECURSOR@y300，
status!=COMPLETED 口径；terminal COMPLETED=28）；orphan=0；
cycle=0；superseded=0；average_chain_depth≈112.8；max_chain_depth=330。
world_state_hash=0fc6ece0…（= M3a 基线）；event_stream_hash=8b117097…
（= M3a 基线）；causal_history_hash=c1293e59…。

## 22. Example Queries

基线 why_query_samples.json 覆盖任务 §33 六问：A Major 灾劫后果
（episode history）；B 生态区质量下降（explain_state）；C 资源储量下降
（explain_state）；D 社会压力来源（explain_state）；E succession
candidate 溯源（trace_causes）；F 末窗 Episode 阶段（episode history
= ACTIVE/INCOMPLETE/PRECURSOR）。

## 23. Incomplete Episode

300y 末窗（entered_tick=300M）：status=ACTIVE、completion=INCOMPLETE、
stage=PRECURSOR；不丢失、不伪装 COMPLETED、不自动补完、不在 timeline
隐藏（HB15/HB33）。

## 24. Resource Succession Trace

SUCCESSION ←DERIVED_FROM← RESIDUAL ←DERIVED_FROM←
TRIBULATION_IMPACT_APPLIED ←RESULTS_IN← PLAN ←DECIDED_BY← 决策/
自治事件（HB19）。物化由 Resource Engine 后续决定（History 不生成
Resource，READ ONLY）。

## 25. Query Performance

synthetic 300y 单次延迟（毫秒级，进 summary 不进 hash）：
entity_history / episode_history / why_query / resource_why /
social_why / succession_trace / timeline（见
tests/baselines/m3b_causal_history_300y_v1/summary.json
query_latency_ms）。全部走索引，无秒级全表扫描。

## 26. DB Growth

300y：links 65,742 + entity_index 64,858 + state_changes 37,818 ≈
168k 索引行（无 payload 复制：links 只存 id/关系/tick，账本只存
{"v": …} 数值）。折算 ≈ 56k 行/100y；索引型数据，非事件 payload 重复。

## 27. LLM/Tokens

LLM_CALLS = 0；LLM_TOKENS = 0。输出为 structured JSON/DTO（M5 再转
小光语言）。

## 28. Network

NETWORK_CALLS = 0。services/history/* 源码扫描：无 requests/httpx/
socket/urllib。

## 29. Formal DB Audit

正式库 pre-m3b 备份（blessed_land.sqlite.pre-m3b-backup）→ 仅 schema
migration（f1b3c5d7e9a2 → c5e7a9b1d3f5）→ FORMAL_AUDIT_M3B PASS：
NOT_ACTIVATED、45 表全 0 行（含 5 张 history 表）、TIME_ADVANCE=0、
integrity=ok。

## 30. World Seed Freeze

world_seed/ byte-for-byte unchanged（MANIFEST.sha256.txt 校验，HB37）；
禁止消费。

## 31. M2/M3a Regression

全量回归（fast + long）：519/519 保留 + 新增 HB 测试全过。M2a/b/c/d
120y + 1000y 基线逐字节复现（套件后经 git checkout 还原冻结文件）；
M3a 300y 基线复现且 history 开启时 world_state_hash /
event_stream_hash 与 M3a 冻结基线逐字节一致（HB34）。

## 32. PostgreSQL

无 json_extract/rowid/INSERT OR REPLACE；JSON 经 ORM 赋新 dict；
BigInteger 整数列。PRE_ACTIVATION_PG_GATE / PRE_ACTIVATION_PG_COMMIT_
AMBIGUITY_GATE 保持 REQUIRED（激活前 PG 实测门禁）。

## 33. Migration

c5e7a9b1d3f5_m3b_causal_history（down_revision=f1b3c5d7e9a2，只 ADD
不改旧）：causal_history_links / entity_history_index /
history_state_changes / history_episode_index / history_index_state。
表总数 40 → 45。

## 34. Tests

新增 tests/test_m3b_history.py：41 个测试项（覆盖 HB1–HB43 验收要求，
部分合并实现：HB26/27/28 合一、HB34/35 精简断言等）：只读/确定性 id/
orphan×2/非法 relation/环/tick paradox/supersede 环/重放/stale writer/
原子性/provenance/确定性排序/episode 完整性/未完成表达/why 链/多因/
决策链/succession 溯源/资源·生态·社会上游/timeline 确定性/行序无关/
0 mutation/0 LLM/网络/哈希中性/300y 图/无 orphan/无环/末窗/基线不变/
形式库/种子/深度上限/纠错 append-only/include_superseded/基线产物。
fast 506 → 547；详见 Verdict 总数。

## 35. Git

M3b 独立 commit（不混 M3c/M4/M5/M6）；tag m3a-tribulation-engine-ready
保留；工作区 clean；M2/M3a 冻结基线文件 checkout 还原。

## 36. Workspace

删除 scratch 脚本；新增 services/history/（5 模块）、migration、
M3B_HISTORY_SEMANTICS_MANIFEST.json、runtime_design/M3B_…_SERVICE.md、
tests/test_m3b_history.py、tests/baselines/m3b_causal_history_300y_v1/。

## 37. Risks

- 300y 索引构建时长（~3-5 min）随事件规模线性增长；正式规模需
  长期观测（§39 预估已录基线）；
- EVENT CONTINUES 链深度上限 64 为插入防御；全图环保证由 audit 提供；
- M0 world_state_changes 与 M3b history_state_changes 双账本并存：
  查询层以 M3b 账本为准，M0 账本为 M3a 冻结语义保留；
- 正式激活前 PG 双门禁必须实测通过。

## 38. M3c Recommendation

M3c 可在本 History 层之上接入领域查询/展示（资源继承物化决策归属
Resource Engine）；M5 生产 Query Layer + 小光语言渲染。
M3b 不进入：M3c/M4/M5/M6、世界激活、Seed 激活、Companion/聊天接口。

## Verdict

TOTAL_TESTS = 560
TOTAL_PASS = 560
TOTAL_SKIP = 0

causal_links = 65742
entity_history_index_rows = 64858   # OLD_METRIC_NAME: entities_with_history
distinct_entities_with_history = 134
episodes_indexed = 30
incomplete_episodes = 2
orphan_links = 0
causal_cycles = 0

LLM_CALLS = 0
LLM_TOKENS = 0
NETWORK_CALLS = 0

WORLD_RUNTIME_STATUS = NOT_ACTIVATED
seed = NULL
current_blessed_tick = NULL
formal_history_links = 0
official_world_events = 0

M3B_CAUSAL_WORLD_HISTORY_READY

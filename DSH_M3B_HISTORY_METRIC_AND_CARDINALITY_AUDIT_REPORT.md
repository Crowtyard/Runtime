# DSH_M3B_HISTORY_METRIC_AND_CARDINALITY_AUDIT_REPORT

> 执行方：DSH。任务：M3B_HISTORY_METRIC_AND_CARDINALITY_AUDIT（收口审计）。
> 性质：METRIC SEMANTICS AUDIT / CARDINALITY AUDIT / CAUSAL GRAPH DENSITY
> AUDIT / QUERY PERFORMANCE CHECK / FINAL FREEZE GATE。
> 不是新功能、不是 M3c/M4/M5/M6；不激活正式福地。
> 基线：M3b @ 8e49eb7（tag m3b-causal-history-ready，560/560）。

## 1. Baseline

M2_ENGINE_SET_FROZEN=TRUE；M3A ACCEPTED（519/519）；M3B IMPLEMENTED
（560/560）。本审计开工前正式库 head=c5e7a9b1d3f5、NOT_ACTIVATED、全空。

## 2. Episode State Definitions

- 互斥状态（MUTUALLY_EXCLUSIVE_EPISODE_STATES，冻结于
  services/history/metrics.py）：EPISODE_STATE_COMPLETED（status=
  COMPLETED）优先；否则按 current_stage 映射 PRECURSOR/PREPARATION/
  IMPACT/RESPONSE/STABILIZATION/RESIDUAL_CHANGE/RECOVERY/
  RESOURCE_SUCCESSION；NEW_NORMAL+ACTIVE → NEW_NORMAL_PENDING。
- incomplete 布尔条件（代码口径，MA4 断言）：
  `episode.status != "COMPLETED"`。
- M3a 基线 writer 的 completed 口径（代码实测）：
  `episode.current_stage == "NEW_NORMAL"`（含 NEW_NORMAL_PENDING）。

## 3. 30 Episode Full Audit

30 个 Episode 全部输出结构化状态（tests/baselines/
m3b_causal_history_300y_v1/episode_state_audit.json，字段：episode_id/
scheduled_tick/tier/current_stage/status/entered_tick/completed_tick/
indexed/completed/active/recovering/incomplete/
mutually_exclusive_state）。要点：
- y10–y280：28 个 COMPLETED（status=COMPLETED，stage=NEW_NORMAL）；
- y290 REGULAR：stage=NEW_NORMAL、status=ACTIVE（COMPLETED 事件在
  tick 301M 才触发，超出 300y 窗口）→ NEW_NORMAL_PENDING；
- y300 CENTENNIAL：stage=PRECURSOR、status=ACTIVE → PRECURSOR。

## 4. Completed / Active / Recovering / Incomplete Reconciliation

30 scheduled = 28 COMPLETED + 1 NEW_NORMAL_PENDING + 1 PRECURSOR。
30/29/2 冲突的唯一解释：
- M3a 的 completed=29 = stage==NEW_NORMAL（28 终态 + 1 pending）；
- M3b 的 incomplete=2 = status!=COMPLETED（pending + precursor）；
- 两个口径都合法，无重复统计；terminal COMPLETED=28；
  nonterminal_total = 2 = scheduled - completed ✓；
  互斥口径 sum = 28+1+1 = 30 = episodes_indexed ✓（MA2/MA3）。

## 5. Entity Metric Source

- metric_source_query = SELECT COUNT(*) FROM entity_history_index
  WHERE world_id = :w（HB43 baseline writer 实测来源）；
- metric_source_table = entity_history_index；
- metric_semantics = raw index row count：每 (entity_type, entity_id,
  link_id) 一行（同一实体多条 link → 多行）；不是 distinct 实体数。

## 6. Entity Cardinality Breakdown

- entity_history_index_rows = 64,858；
- distinct_entity_ids = 134；distinct_domain_entities = 134；
- distinct_entities_with_history = 134（真实实体口径）；
- distinct_event_ids_indexed = 2,184；distinct_state_change_ids_indexed
  = 37,759；distinct_episode_ids_indexed = 30；
- distinct_relation_targets = 37,992；distinct_relation_sources =
  39,768。
按类型：ecology_state 9,810 行/2 实体；population_groups 29,322/80；
resource_stocks 6,372/4；economic_pressure_state 5,116/2；
social_feedback_state 4,649/2；ecology_feedback_state 3,759/2；
resource_nodes 2,458/2；settlement_social_state 2,171/2；households
663/30；lineages 537/7；institutions 1/1（完整表见
entity_cardinality_audit.json）。

## 7. Domain Entity vs Index Reference

entity_history_index 中的 11 类全部为 DOMAIN_ENTITY（真实世界实体）；
INDEX_REFERENCE_ONLY 类型 = []（EVENT/STATE_CHANGE/EPISODE/PLAN/
DECISION/RECOVERY_STATE/RESIDUAL/SUCCESSION 是图节点 kind，不进实体
索引，不混算）。graph_node_cardinality 单列。

## 8. Metric Rename Decision

确认旧指标命名错误（把索引行数当实体数）→ 更名：
- OLD_METRIC_NAME = entities_with_history；
- NEW_METRIC_NAME = entity_history_index_rows；
- NEW_DISTINCT_METRIC = distinct_entities_with_history；
- REASON = 旧值 64,858 为 entity_history_index 原始行数（每
  (entity, link) 一行，含重复），非 distinct 实体数（134）。
已同步修正：M3B 最终报告 §21/Verdict、设计文档 §34/35、baseline
summary.json（含 metric_rename 记录）、metrics 模块（唯一权威口径）。

## 9. Causal Link Density

domain_events = 4,479（SIMULATION 且非 TIME_ADVANCE）；
state_changes = 37,818；causal_links = 65,742；
links_per_domain_event = 14.68；links_per_state_change = 1.74。

## 10. Relation Type Distribution

CONTINUES 37,723（57.38%）；AFFECTS 22,654（34.46%）；CAUSES 4,682
（7.12%）；PART_OF_EPISODE 508（0.77%）；RESULTS_IN 88（0.13%）；
DERIVED_FROM 58（0.09%）；DECIDED_BY 29（0.04%）；CORRECTS/
MATERIALIZES_IN/RECOVERS_FROM/REVERSES/SUPERSEDES/TRIGGERS = 0。
13 类冻结词表全部在分布中（relation_density_audit.json）。

## 11. Duplicate Link Audit

duplicate_semantic_links = 0（完全相同的 source/target/relation/
episode/semantic scope 无重复；link_id 确定性 + 唯一约束保证，MA10）。

## 12. Transitive Materialization Audit

candidate_transitive_materializations = 0；
semantically_justified = 0；purely_redundant_transitive_links = 0。
构建规则逐对独立语义（CONTINUES 只连相邻变更、AFFECTS 只连同 Step
事件→变更、RESULTS_IN 只连同 Step 计划→事件），从不机械物化传递
闭包（MA11，按 relation semantics 判定，非数量判断）。

## 13. Growth Projection

LINEAR_PROJECTION_ONLY（正式世界复杂度可能变化，非容量承诺）：
causal_links_per_100y = 21,914；history_index_rows_per_100y = 21,619；
state_provenance_rows_per_100y = 12,606；episode_index_rows_per_100y
= 10；estimated_1000y_causal_links = 219,140；
estimated_5000y_causal_links = 1,095,700；
estimated_1000y_history_rows = 216,193；
estimated_5000y_history_rows = 1,080,967。

## 14. DB Growth

history_db_bytes_added_300y = 66,912,256 B（history 300y 库 67.4 MB
- 仅 schema 空库 0.54 MB）；history_mb_per_100y = 21.27 MB；
estimated_1000y = 212.7 MB；estimated_5000y = 1,063.5 MB。
禁止 destructive compaction；只报告。

## 15. Query Performance

300y 库实测（20 次迭代，warm-up 排除，query_performance.json）：
- entity_history：p50 189.7ms / p95 219.7ms（收口修复前 778ms：逐
  link SELECT → 批量分块 + 列裁剪加载）；
- episode_history：p50 2.5ms / p95 3.0ms；
- explain_state：p50 13.6ms / p95 14.7ms；
- trace_causes：p50 2.2ms（基准 session 实测）；
- timeline：p50 0.78ms / p95 0.96ms。
（性能计时不进 simulation truth、不进任何 deterministic hash。）

## 16. Query Plan / Index Audit

EXPLAIN QUERY PLAN 全部命中预期索引：
timeline → ix_world_events_tick（新 migration d7f9b1c3e5a7，收口
审计新增，纯索引不重构 schema）；entity_history →
ix_hist_sc_entity；episode_history_links → ix_hist_links_target；
why_walk → ix_hist_links_target；entity_index_scope →
ix_entity_history_scope。FULL_TABLE_SCAN_RISK = []；
MISSING_INDEXES = []。

## 17. Six Why Queries

300y 复核（MA18，全部结构化可追溯）：
A Major（y50）灾劫后果：1 plan + 8 domain effects（COMPLETED）；
B 生态区质量下降：chain 含 TRIBULATION_IMPACT_APPLIED；
C 资源储量下降：chain 含灾劫 AFFECTS + RESOURCE 引擎变更；
D 社会压力变化：chain 含 TRIBULATION_IMPACT_APPLIED；
E succession candidate：DERIVED_FROM RESIDUAL → 灾劫链；
F 末窗 Episode：ACTIVE / INCOMPLETE / PRECURSOR。

## 18. Multi-Cause Verification

explain_state（ecology_state.habitat_quality，end_tick=293M）链上
三类 contributing causes 并存：AFFECTS（灾劫影响）+ CAUSES（正常
资源开采压力）+ CONTINUES（状态延续）。HistoryService 不压缩为
单根因（MA19，递归收集关系断言）。

## 19. Causal History Hash

causal_history_hash v1 = c1293e59d96753e2b3488746f86f176bceb84d2ef6
93c9760944c8727046a44（与 M3b 基线一致）。同 DB 重复计算一致
（MA20）；行序无关（MA21：随机打乱行序 → 同 hash，内部 ORDER BY
link_id）。world_state_hash / event_stream_hash 不变（MA22/23）。

## 20. M3a Hash Freeze

M3a 300y 基线 world_state_hash=0fc6ece0… 与 event_stream_hash=
8b117097… 逐字节不变（MA22/MA23；M3a 基线六文件存在，MA24）。
本次审计未改任何模拟语义。

## 21. M2 Regression

M2a/b/c/d 120y + M2 integrated 1000y（seed_001/005/summary）基线
文件存在且经全量回归逐字节复现（MA25 + 全量套件，套件后 git
checkout 还原冻结文件）。M2 语义清单零修改。

## 22. Formal DB Audit

正式库 pre-audit 备份（blessed_land.sqlite.pre-m3b-audit-backup）→
仅 index migration（c5e7a9b1d3f5 → d7f9b1c3e5a7）→ 终检 PASS：
WORLD_RUNTIME_STATUS=NOT_ACTIVATED、seed=NULL、current_blessed_tick
=NULL、formal history 5 表 0 行、tribulation_episodes=0、
world_events=0、integrity=ok（MA26 + FORMAL_AUDIT）。

## 23. World Seed Freeze

world_seed/ byte-for-byte unchanged；MANIFEST.sha256.txt 全文件校验
通过；VERSION 不变；禁止消费（MA27）。

## 24. PostgreSQL Audit

新增 migration 仅为标准 CREATE INDEX（SQLite+PG 双兼容，无
SQLite-only 语法）；metrics/service 无 json_extract/rowid/INSERT OR
REPLACE。PRE_ACTIVATION_PG_GATE / PRE_ACTIVATION_PG_COMMIT_
AMBIGUITY_GATE 保持 REQUIRED。

## 25. Tests

新增 tests/test_m3b_metric_audit.py：MA1–MA29（episode 穷举/互斥
求和/scheduled-completed 一致/incomplete 语义显式/索引行数/distinct
实体/domain vs index-ref/类型分组/密度/重复链接=0/传递审计确定性/
增长投影可复现/4 类性能实测/查询计划索引/六问复核/多因保留/hash
稳定/行序无关/world·event hash 不变/M3a·M2 基线不变/正式库空/
种子冻结/审计基线产物/DB 增长）。全部 PASS；既有 560/560 保留。

## 26. Git

独立 commit（不混 M3c/M4/M5/M6）；tag m3b-history-metrics-validated；
工作区 clean；旧 tag（m1-golden-baseline … m3b-causal-history-ready）
保留。

## 27. Risks

- growth projection 为 LINEAR_PROJECTION_ONLY：正式世界复杂度不同，
  不能当生产容量承诺（M2 1000y 事件规模佐证：索引行数随 Step 线性）；
- entity_history 输出规模与实体热度正相关（ecology_state 9,810 行），
  max_items/时间窗参数应在上层查询界面默认启用；
- 收口修复的 entity_history 批量化改动行为输出与修复前逐字节一致
  （排序规则未变：blessed_tick → event_uid）；
- 若未来重构图模型，duplicate/transitive 审计（metrics 模块）应作为
  冻结门禁持续运行。

## 28. Final Recommendation

M3B_HISTORY_METRICS_VALIDATED
建议：M3B_CAUSAL_WORLD_HISTORY = READY_FOR_FINAL_FREEZE
（本报告不自行宣布冻结；等待主人/ChatGPT 验收后 STOP，
不进入 M3c/M4/M5/M6，不激活正式福地。）

---

scheduled_episodes = 30
indexed_episodes = 30
completed_episodes = 28
active_episodes = 2
recovering_episodes = 0
incomplete_episodes = 2
nonterminal_total = 2
missing_episodes = 0

entity_history_index_rows = 64858
distinct_entity_ids = 134
distinct_domain_entities = 134
distinct_entities_with_history = 134

domain_events = 4479
state_changes = 37818
causal_links = 65742
links_per_domain_event = 14.68
duplicate_semantic_links = 0
purely_redundant_transitive_links = 0

causal_links_per_100y = 21914
history_index_rows_per_100y = 21619
estimated_1000y_causal_links = 219140
estimated_5000y_causal_links = 1095700

entity_history_p50_ms = 189.7
entity_history_p95_ms = 219.7
episode_history_p50_ms = 2.5
episode_history_p95_ms = 3.0
explain_state_p50_ms = 13.6
explain_state_p95_ms = 14.7
timeline_p50_ms = 0.78
timeline_p95_ms = 0.96

WORLD_STATE_HASH_UNCHANGED = TRUE
EVENT_STREAM_HASH_UNCHANGED = TRUE
M3A_BASELINE_UNCHANGED = TRUE
M2_BASELINES_UNCHANGED = TRUE

WORLD_RUNTIME_STATUS = NOT_ACTIVATED
seed = NULL
current_blessed_tick = NULL
formal_history_rows = 0
official_world_events = 0

LLM_CALLS = 0
LLM_TOKENS = 0
NETWORK_CALLS = 0

TOTAL_TESTS = 589
TOTAL_PASS = 589
TOTAL_SKIP = 0

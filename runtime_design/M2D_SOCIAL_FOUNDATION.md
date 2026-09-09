# M2D_SOCIAL_FOUNDATION

> M2d 交付文档。CONFIRMED_EXISTING_SCOPE = 恢复自旧设计（07 号为主）；
> IMPLIED = 旧设计隐含但未定量；NEW_PROPOSAL = DSH 冻结决定；
> CONFLICT_FOUND = 与 M2d 任务的显式边界冲突及裁决。
> 正式种族/机构社会参数保持 SOCIAL_UNCONFIGURED；一切数值 TEST_FIXTURE_ONLY。

## 1. Scope
社会跨世代持续存在的最小结构：Population → Household Aggregate →
Persistent Lineage → Institution → Settlement Social State →
Autonomous Social Events。目标不是模拟每个人每天在干什么。
禁止：LLM NPC/大规模 Persistent Person/政治完整版/国家朝廷/战争/犯罪/
宗教完整版/阶级斗争/灾劫/历史叙事/Scheduler/Companion/Seed 激活。

## 2. Source Recovery
- CONFIRMED_EXISTING_SCOPE（07 号）：households（统计级 + 锚点级）、
  lineages（PERSISTENT_LINEAGE）、institutions（PERSISTENT_INSTITUTION）、
  population_groups 劳动力池、后台社会事件（birth/death/harvest/工坊扩大/
  市场变化/资源发现/道路维修/争执/节庆/迁居/产业合作/学徒出师/房屋建设）、
  CAUSE_BASED 原则、事件 scope 分级（AMBIENT/LOCAL/REGIONAL/WORLD/
  MILESTONE）、RNG 只决定"谁遇到机会或不幸"不生成规则。
- IMPLIED：家庭形成/消亡率、lineage 涌现阈值的定量化。
- CONFLICT_FOUND：07 号 婚姻/职业流动/争执仲裁/文化扩散
  （MEDIUM_DIFFUSION 五阶段）> M2d 范围 → 裁决延后（属 M2d 后续或
  文化子系统）。
- 06/08/09 与 M2 Preflight/M2A/M2B/M2C 文档：管线顺序、staged
  feed-forward、双层 checkpoint、feedback latency 机制沿用。

## 3. Social Engine
engine_id=SOCIAL，engine_version=m2d-social-1。零 RNG/LLM/网络/
wall-clock/commit；只做确定性 aggregate 社会演化；Persistent Person
晋升接口冻结、默认 0。

## 4. Ownership
SOCIAL 只 propose：households / lineages / institutions /
settlement_social_state / social_feedback_state。禁止直接修改
population/resource/inventory/ecology（SOC_INV_21/22/23）。跨系统
影响只经 SocialFeedbackSignal（committed social_feedback_state）。

## 5. Household Aggregate
households：household_id（确定性 id）/settlement_ref/species/
represented_population/generation/lineage_ref/anchor_group_ref/state
（ACTIVE/DISSOLVED）/formation_version。不是家庭成员个人模拟；可表达
形成/延续/拆分/合并/消亡，全部 aggregate。

## 6. Population Reconciliation
人口归属契约（m2d-coverage-v1：full）：每 (settlement, species) 的
ACTIVE household represented_population 之和 == population 总量。
每 Step：DEMOGRAPHY 先改人口 → SOCIAL 做 allocation（增长 round-robin
按 id 序、衰减规模大者先扣、无户则形成、超阈值则拆分、归零则溶解）——
绝不第二次出生/死亡。unallocated_population 恒 0（full 契约）。

## 7. Family Boundary
只表达家庭形成/延续/拆分/消亡的 aggregate 事实；禁止恋爱过程/父母姓名/
孩子姓名/婚礼/私人聊天/性生活/个人性格。

## 8. Persistent Lineage
lineages（M0 表扩展）：lineage_id/origin_settlement/represented_
population/household_count/generation/status（ACTIVE/DORMANT/EXTINCT）/
founded_tick/parent_lineage_ref。目的不是完整族谱，而是重要家系跨
数十年/数百年延续。Lineage ≠ Household：一个 lineage 多个 household；
一个 household 至多一个 lineage 或 none。

## 9. Lineage Lifecycle
- 涌现（NEW_PROPOSAL）：household generation ≥ 3 且 size ≥ 6 且无
  lineage → 立 lineage（每聚落每步 ≤ 1）。
- 分化：lineage household_count ≥ 12 → 最大成员户立子 lineage
  （parent_lineage_ref；无自引用/无环，SOC_INV_11/12）。
- 灭绝：represented=0 且 household_count=0 → EXTINCT；identity 永久
  保留（SOC_INV_13/14），绝不删除。
- 跨聚落：household 迁移归属自然支持（SD16 实测）。

## 10. Persistent Person Boundary
M2d 不实现 PersistentPerson lifecycle；晋升接口冻结（未来仅：长期
叙事意义/关键机构职务/重大事件参与者/主人关注 → materialize）。
正常 120y 运行 persons=0（SD33 实测）。

## 11. Institution Foundation
institutions（M0 表扩展）：institution_id/kind（结构类型：market/craft/
administration/community/knowledge）/settlement_ref/state/founded_tick/
profile_ref。不生成正式学校/商会/政权/宗门名字（仅 TEST fixture）。

## 12. Institution Lifecycle
ACTIVE → DECLINING（cohesion < 500,000）→ DORMANT（< 300,000）→
DISSOLVED（pop < 50）；恢复 ACTIVE（cohesion ≥ 600,000）；DISSOLVED
终态。成立：pop ≥ 80 且无存续机构（每聚落每步 ≤ 1）。机构不产生
active modifier（SD19 实测）；状态变化不生成自然语言剧情。

## 13. Settlement Social State
settlement_social_state：social_stress/social_cohesion/household_
stability/mobility_pressure/unallocated_population + stress_min_seen/
stress_max_seen（见证值持久化）。权威状态整数 fixed-point
0..SOCIAL_STATE_SCALE（m2d-scale-1）；无 float truth。

## 14. Pressure Inputs
SOCIAL 读取 staged：人口（增长/迁移差）、经济压力（unmet/demand
ratio）、生态压力（environmental_stress）。输入≠结果：shortage≠骚乱、
生态退化≠政治崩溃 —— 必须经明确 Social transition 公式。只读声明
输入；不读 resource_nodes/resource_stocks/production_state（SD21/22）。

## 15. Social Feedback
social_feedback_state（committed）：migration_modifier（1 + stress×1/2
/SCALE）、fertility_context（1 − stress×1/4/SCALE）、social_support
（1 − stress×1/2/SCALE）、social_stress（stress/SCALE 约分）。
全部 fixed-point num/den。

## 16. Feedback Lag
SOCIAL_FEEDBACK_LATENCY = NEXT_COMMITTED_STEP。Year N Social 结果
绝不回写 Year N DEMOGRAPHY/RESOURCE/ECONOMY/ECOLOGY（SD23 实测：
第 1 步 DEMOGRAPHY 与无社会夹具全等）；Year N+1 DEMOGRAPHY 经
snapshot 读取（SD24 实测：预置高迁移压力 → 次年迁出上升，确定性）。

## 17. Autonomous Social Events
Domain Events（非自然语言故事）：HOUSEHOLD_FORMED/SPLIT/DISSOLVED、
LINEAGE_FOUNDED/EXTINCT、INSTITUTION_FOUNDED/STATE_CHANGED/
DISSOLVED、SOCIAL_STRESS_THRESHOLD_CROSSED。LINEAGE_DECLINED 只作
机器叙述留给 M3/M5；M2d 不生成原因故事。

## 18. Event Volume
只在 formation/dissolution/significant transition/threshold crossing
发事件；普通计数变化留在 State/metrics —— 数百年事件流不爆炸。

## 19. Identity
IDENTITY_SCHEMA_VERSION="social-v1"：
id = sha256(social-v1|world|kind|settlement|species|founded_tick|seq)
前 16 hex。seq = 同类 staged 实体数 + 本步已插入数 + 1 —— retry 不生成
第二 identity（SD34-36 实测）；无 UUID4/rowid/set order（SD12/17）。

## 20. Fixed-Point State
stress/cohesion/stability/mobility ∈ [0, 1_000_000] 整数；
SOCIAL_STATE_SCALE_VERSION="m2d-scale-1"。有界、无 NaN/Inf
（SD20 实测）。

## 21. RNG
SOCIAL 独立 substream（coordinator 派生）；算法本身零 RNG（确定性
规则优先；无"为了像模拟"的随机）。extra_draws 测试旋钮证明独立
（SD32 实测：多抽 11 次 → 五引擎结果与哈希全不变）。

## 22. World State Hash
WORLD_STATE_HASH_SCHEMA_VERSION 4 → 5：v5 覆盖 households/lineages/
institutions/settlement_social_state/social_feedback_state + 全部既有
状态域；canonical 行序无关（SD31）、restart 稳定。v2/v3/v4 显式冻结
（M2a/b/c 基线逐字节复现回归实测）。

## 23. Event Stream Hash
EVENT_STREAM_HASH_SCHEMA_VERSION=1 不变；社会事件 canonical payload
全覆盖（SD29 实测）；uid v1 128-bit（SD28 实测）。

## 24. Checkpoint
TIME_COMMITTED + WORLD_COMMITTED 双层原子；权威恢复 = latest
complete WORLD_COMMITTED；Social state 与人口/资源/经济/生态/时间同
一 committed world semantic step（SD44 实测 checkpoint hash == v5）。

## 25. Fencing
Writer A 算完五引擎但 lease 已丢 → commit 被 FENCING_VIOLATION 拒绝；
Social 0 authoritative write（SD38/S9 实测）。

## 26. Crash Recovery（S1–S10）
S1 before Social / S2 mid household / S3 after household staged /
S4 mid lineage / S5 after lineage staged / S6 mid institution /
S7 after Social staged / S8 during Social DB write / S9 before fencing
recheck / S10 durable commit ACK lost。恢复后 tick/population/resource/
economy/ecology/households/lineages/institutions/feedback/events/
双哈希全一致（S1–S8 参数化 + SD39-42 + S9 + SD43 实测）。

## 27. Commit Ambiguity
复用 hardened 注入（post-durable-commit）：ACK lost → restart →
ALREADY_COMMITTED；Household 不重复形成、Lineage 不重复 founded、
Institution 不重复创建、事件/反馈不重复（SD43 实测）。

## 28. Idempotency
同 interval retry：零重复 household/lineage/institution/事件/checkpoint/
时间推进（SD34-37 实测）。

## 29. 120y Baseline
mini_world_v1（M2d integrated：2 settlements + 5 引擎 + 80 聚合家庭
（5 人/户）+ B 的 1 条 synthetic lineage（3 户）+ 2 个 synthetic
COMMUNITY_BODY + TEST_SOCIAL_PROFILE_001），120 福地年；
`tests/baselines/m2d_social_miniworld_120y_v1.json`。场景：人口世代
变化 → 家庭拆分/溶解 → lineage 涌现/延续/灭绝 → B 机构 DECLINING →
压力阈值跨域 → 社会反馈跨 Step 存续。全数字 TEST_FIXTURE_ONLY。

## 30. Performance
aggregate：每步 O(households + lineages + institutions) 整数运算；
无 per-person agent。120y wall time 记录于基线 performance 字段
（不进哈希）。

## 31. PostgreSQL
BigInteger 全整数权威列；确定性 id 字符串；唯一约束显式命名；无
json_extract/rowid 依赖。NOT LIVE VERIFIED；
PRE_ACTIVATION_PG_GATE / PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_GATE =
REQUIRED 继续登记。

## 32. Canon / Seed Boundary
正式人/毛民/石人/鲛人/菇人的家庭大小/婚姻模式/宗族倾向/社会凝聚/
机构偏好/政治倾向一律 SOCIAL_UNCONFIGURED（SD52 实测：注册表仅
TEST-SOCIAL-PROFILE-001）；不把现实家庭/婚姻/政治结构写成智慧种族
默认；不消费 world_seed/ 的任何正式值。

## 33. Known Limitations
- 合并（household merge）未实现（拆分/溶解/形成已覆盖；合并属
  NEW_PROPOSAL 留待后续）。
- DORMANT lineage 状态仅枚举（无进入规则）。
- Institution 成员列表/机构内部治理不建模（M0 members 列留给未来）。
- 家庭锚点 anchor_group_ref 只在形成时校验（cohort 行永存 → 恒有效）。
- 社会压力公式为 m2d 版本化 NEW_PROPOSAL，非 07 号定量恢复。
- PG 兼容为代码级审计，NOT LIVE VERIFIED。

## 34. NEW_PROPOSAL / CONFLICT_FOUND 汇总
- CONFLICT_FOUND：07 号 婚姻/职业流动/争执仲裁/文化扩散 > M2d 范围。
- CONFLICT_FOUND：07 号「RNG 决定谁遇到机会」vs M2d 零 RNG 决定 →
  裁决：M2d 确定性规则优先；机会性选择属后续里程碑。
- NEW_PROPOSAL：full-coverage 对账契约（m2d-coverage-v1）；round-robin
  分配与拆分/形成/溶解规则（m2d-formation-v1）；lineage 涌现/分化阈值；
  institution 生命周期阈值与成立门槛；四压力加权公式；社会反馈映射
  （migration +1/2·s、fertility −1/4·s、support −1/2·s）；确定性 ID
  方案（social-v1）；StateChange INSERT 语义扩展（coordinator 统一
  写入）；world_state_hash v5（v2/v3/v4 冻结）。

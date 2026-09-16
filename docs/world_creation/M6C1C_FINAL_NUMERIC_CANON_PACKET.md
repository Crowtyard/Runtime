# M6C1C — FINAL NUMERIC CANON DECISION PACKET

```
STATUS                       = AWAITING_OWNER_FINAL_NUMERIC_CANON_SELECTION
OWNER_NUMERIC_DECISION_COUNT = 5（NUMERIC_OD_P1 / RE1 / E1 / S1 / T1）
MATERIALIZER_ALLOWED         = FALSE
FORMAL_ACTIVATION_ALLOWED    = FALSE
MACHINE_DATA                 = docs/world_creation/M6C1C_NUMERIC_PACKET_DATA.json
```

> 只读、只算、只提案：**不物化、不激活、不消费 Seed、不写正式库**。
> 本阶段把 M6C.1B 的 OD-2/3/4/5/6/7/9 中的**数值部分**压缩成 5 个数值决策。

## 0. 证据等级（必须先声明）

```
PROJECTION_EVIDENCE_CLASS = ANALYTIC_REIMPLEMENTATION_OF_FROZEN_STEP_EQUATIONS
ENGINE_RUN_VERIFICATION   = DEFERRED（下一阶段：coordinator + 真实 DB 复算）
所有候选                   = NOT_CANON_UNTIL_OWNER_APPROVAL
```

轨迹由**逐步复算 frozen 方程**得到（逐条引用源码行），不是引擎运行结果：
`population.py:284-339`（年龄推进 → 死亡 → 出生）、`economy.py:188-211,266-294`、
`ecology.py:254-296`、`social.py:267-345,499-540`、`tribulation.py:696-729`。
所选候选在进入 SNAPSHOT_V1 前**必须**用真实引擎（临时库 + synthetic bootstrap）复算一次。

### 本阶段发现的三个真实问题（已修正，供主人知情）

1. **RA-COHORT-001 v1.0 的末位 bucket 处理不完整**：末位是**开区间**（`[N-1, ∞)`，`population.py:67`），
   其成员**不会老化出去**、会持续累积（引擎 `aged_new[min(b+years, N-1)] += n`）。
   v1.0 只给末位 `(1-q)^(N-1)`，**漏掉了尾部累积项** `1/q`。→ 本阶段提出 **v1.1** 权重
   （末位 = `(1-q)^(N-1)/q`），并据此解驻定出生率。
2. **没有"精确驻定"的常数死亡率解**：离散整数过程 + 引擎步序下，恒死亡率 + 恒出生率
   只能做到**近似**平稳；三候选在 100 年尺度漂移 ≤ 0.6%，300 年尺度缓慢下行（见下表）。
   这不构成"立即崩溃/爆炸"，符合 owner §15（不追求静态世界）。
3. **birth_rate 必须对引擎步序数值求解**（bisection over one frozen year），
   而不是用解析式 —— 解析式忽略步序会给出 +400%/年的爆炸（首轮扫描实测）。

---

## NUMERIC_OD_P1 — DEMOGRAPHY

**单位**（owner §3）：cohort bucket 宽 = 1 福地年；`birth_rate` = /fertile 人/福地年（Fraction）；
`mortality_by_bucket` = 每 bucket 每年死亡概率（Fraction）；`emigration_rate` = /福地年；
`migration_weights` = 无量纲（和=1，长度 ≥ 2；引擎 EC-3 强制）。

**population_capacity 语义**（owner §5）：`settlements.population_capacity` **不是**"当前人口"，
它只进入出生倍率 `factor = max(capacity − total_after, 0)/capacity`（`population.py:187-189,329-332`）：
`NULL` → factor = 1（无容量法则）；`capacity == 初始人口` → **出生恒为 0（人口冻结）**。
因此本包以**比值 r = capacity / 初始人口**表达，并给出 r 的长期后果。

三候选（均含：四族共享**同一** profile；`emigration_rate = 0`；`migration_weights = [1/2, 1/2]`）：

| | P-A 短寿 | P-B 中寿 | P-C 长寿 |
| --- | --- | --- | --- |
| 寿命上限（bucket 数 N） | 60 年（N=61） | 100 年（N=101） | 300 年（N=301） |
| 年死亡概率 | 1/60 | 1/100 | 1/300 |
| **expected lifespan** | **≈ 60.0 年** | **≈ 100.0 年** | **≈ 300.0 年** |
| 生育区间 | 15–45 | 15–50 | 18–90 |
| **birth_rate（驻定解）** | **185/4096 ≈ 0.045166** | **41/2048 ≈ 0.020020** | **3/512 ≈ 0.005859** |
| 初始年龄结构 <15 / 生育 / >生育 | 0.158 / 0.559 / 0.283 | 0.129 / 0.485 / 0.386 | 0.056 / 0.283 / 0.661 |
| 第 1 年净自然增长 | −29（−0.24%） | −58（−0.48%） | −26（−0.22%） |
| 4 年人口 | 12,012 | 12,008 | 12,000 |
| **100 年人口** | **11,981** | **11,527** | **11,586** |
| **300 年人口** | **10,272** | **3,515** | **8,138** |
| cohort 行数（48×N） | 2,928 | 4,848 | 14,448 |

**capacity 比值后果（实测，P-A profile，cap = r × 12,000）**：

| r | 100 年人口 | 300 年人口 | 结论 |
| --- | --- | --- | --- |
| `NULL`（无容量法则） | **11,981** | **10,272** | 本包三候选所用设定 |
| 1.25 | 5,553 | 3,451 | **强刹车** |
| 1.5 | 6,531 | 4,501 | 强刹车 |
| 2.0 | 7,394 | 6,467 | 仍显著刹车 |

> **重要发现**：`factor = (capacity − pop)/capacity` 用的是**当前空位**，不是"软上限"，
> 所以**任何有限 capacity 都会强力压低出生率**（r = 1.25 时 300 年只剩 1/3 人口）。
> → **建议 `population_capacity = NULL`**；若主人要设容量，请把 r 理解成"该聚落长期人口天花板"，
> 而不是"初始人口附近的安全垫"。

```
RECOMMENDED_NEUTRAL_CANDIDATE = P-A（100 年漂移最小、无爆炸、无快速灭绝；且 N 最小 → 行数 2,928）
CAPACITY_RECOMMENDATION      = NULL（任何有限 capacity 都会强刹车人口，见上表实测）
OWNER_MUST_CHOOSE = P-A / P-B / P-C / CUSTOM（+ capacity = NULL / 1.25 / 1.5 / 2）
RULES_NEEDING_RATIFICATION = RA-COHORT-001 v1.1（尾部项）、RA-MORTALITY-001（年龄带压缩）
```

> 石人「寿千余（有载，`world_bible/05:11`）」在 **OD-2 = OPTION A（四族共享一份 profile）** 下
> **不表达** —— 若主人日后要为石人单列寿命，那需要新的 OD（本包不擅自引入）。

---

## NUMERIC_OD_RE1 — RESOURCE_ECONOMY_BASELINE（owner §6/§7/§8）

**基准年需求**（frozen）：`demand = Σ_species(per_capita_demand[resource] × pop × interval)`
（`economy.py:266-294`，minor units）。本包用 **人均 1/4 canonical unit/福地年**（EXPERIMENTAL 输入）
→ 12,000 人 **年需求 = 3,000 minor units**。

**policy 形式**（不是让主人填几十个数）：`初始库存 = N 年基准需求`、`产能 = M × 年需求`。
注意 `M` 必须 > 1/(1−loss)：loss = 1/20 时 **M ≥ 1.0526**，否则产量永远补不上消耗（首轮扫描实测 RE-A 出现 80/100 年短缺）。

| | RE-A lean | RE-B balanced | RE-C reserve-heavy |
| --- | --- | --- | --- |
| N（初始库存年数） | 1 | 2 | 3 |
| M（产能/年需求） | 1.10 | 1.50 | 2.00 |
| 初始库存（minor） | 3,000 | 6,000 | 9,000 |
| 批数/年（input 100/批） | 33 | 45 | 60 |
| 产量/年（loss 1/20） | 3,135 | 4,275 | 5,700 |
| 年需求 | 3,000 | 3,000 | 3,000 |
| **第 1 年是否短缺** | 否 | 否 | 否 |
| 10 年库存 | 4,350 | 18,750 | 36,000 |
| **100 年库存** | **16,500** | **133,500** | **279,000** |
| 100 年内短缺年数 | 0 | 0 | 0 |
| 劳动力需求/可用 | 330 / 12,000 | 450 / 12,000 | 600 / 12,000 |

**MINIMUM_RESOURCE_NODE_TOPOLOGY**（owner §8）：

```
RESOURCE_NODE_COUNT   = 7
RESOURCE_NODE_KIND_MAP = {灵田: NODE-灵田-01, 药园: NODE-药园-01, 果园: NODE-果园-01,
                          矿脉: NODE-矿脉-01, 水源: NODE-水源-01, 林产: NODE-林产-01,
                          菌类点: NODE-菌类点-01}
WHY_MINIMAL = frozen RESOURCE 逐节点产出；跨聚落 transfer 只搬运**库存**、不创造产量
              （M2B:102-107）→ 每个消费类资源至少 1 节点，少一个即该资源永久零产出；
              第 2 个同 kind 节点只增加产量、不增加"可运行性" → 不创建（视觉丰富不是理由）
非消费类资源节点 = 0
```

```
RECOMMENDED_NEUTRAL_CANDIDATE = RE-B（库存有缓冲、无短缺、且不与"永久盈余"耦合过强）
OWNER_MUST_CHOOSE = RE-A / RE-B / RE-C / CUSTOM（N 与 M 可分别改）
```

---

## NUMERIC_OD_E1 — ECOLOGY（owner §9）

已知：`INITIAL_HABITAT_QUALITY = FULL_QUALITY`（owner 已批准）。
**关键引擎事实**：`recovery_ceiling <= ECOLOGY_STATE_SCALE`（`ecology.py` 的 `__post_init__`），
所以 quality = FULL 时恢复项为 **0**，任何持续压力都先退化、再在低于 ceiling 处取得固定点。
`carrying_capacity` **无任何冻结引擎消费**（仅 snapshot/state_hash 可见）→ 本包只作为登记值。

**单位**：`pop_pressure_per_person` = minor units/人；`sensitivity`、`recovery_rate` 为无量纲分数；
压力 `total_pressure ∈ [0, ECOLOGY_STATE_SCALE]`（`ecology.py:254-260`）。

本包固定 **ppp = 1**（1 人 = 1 minor pressure unit，最可解释的单位），
**反解 sensitivity** 使长期平衡命中主人给定的质量目标：

| | E-A 高质 | E-B 中质 | E-C 低质 |
| --- | --- | --- | --- |
| 目标平衡质量 | 98% | 95% | 90% |
| **sensitivity（反解）** | 3998/1275 ≈ 3.1357 | 3998/525 ≈ 7.6152 | 3998/275 ≈ 14.5382 |
| recovery_rate | 1/25 | 1/25 | 1/25 |
| 压力份额（MAIN 2000 人） | 0.0005 | 0.0005 | 0.0005 |
| 100 年质量 | 981,167（98.1%） | 953,075（95.3%） | 906,703（90.7%） |
| 300 年质量 | 980,838 | 952,119 | 904,406 |
| 12 区配置下的平衡 | 见机器数据 `equilibrium_if_12_zones` | 同 | 同 |

**12 区配置**（每聚落 1 区，单区压力落到 2,000 人）：解析固定点落在 ceiling（≈100%），
因为 `p_pop` 随区人口线性下降而损失被 `w_pop = 2/8` 再次稀释 —— 三候选在 12 区下都会
**趋于满质量**；因此若主人要"生态可观测地变化"，应用 **1 区 + 该区聚合压力**（本包默认）
或下调 `recovery_rate`。机器数据：`equilibrium_if_12_zones`。

```
POLICY（结构）：zone_count = 1（最小 root set）→ 若要每聚落一区则为 12（放大 12 倍行数）
carrying_capacity = 2 × 聚落人口（**仅登记**，无引擎消费）
RECOMMENDED_NEUTRAL_CANDIDATE = E-B（平衡在 95%，留出可观测的退化/恢复空间）
OWNER_MUST_CHOOSE = E-A / E-B / E-C / CUSTOM（质量目标 + zone_count + carrying 登记值）
```

---

## NUMERIC_OD_S1 — SOCIAL_THRESHOLDS（owner §10）

方法已批准：**POPULATION_SCALED_DETERMINISTIC_DERIVATION**（阈值 = 聚落人口的百分比）。
引擎语义：`formation_size` → `n = ceil(pop / formation_size)` 户（`social.py:267-299`）；
`split_threshold` → 户数超过即拆分（`:300-345`）；`institution_found_pop` → 人口达到即成立机构（`:499-540`）。

| | S-A 小户 | S-B 中户 | S-C 大户 |
| --- | --- | --- | --- |
| formation 占比 | 0.25% 人口 | 0.5% 人口 | 1% 人口 |
| **MAIN (2000) formation_size** | **5 人/户** | **10 人/户** | **20 人/户** |
| MAIN 首步成户数 | 400 | 200 | 100 |
| MAIN split_threshold | 200 户 | 80 户 | 30 户 |
| MAIN institution_found_pop | 80 | 120 | 160 |
| **SAT (500) formation_size** | **2 人/户** | **2 人/户** | **5 人/户** |
| SAT 首步成户数 | 250 | 250 | 100 |
| SAT institution_found_pop | 20 | 30 | 40 |

**长期差异**：S-A → 户极小、成户极多（MAIN 400 户）、机构门槛低（80 人即成立）→ 机构多而碎；
S-C → 户大、户数少（MAIN 100 户）、机构门槛高（160 人）→ 机构少而稳、lineage 出现更晚、迁移压力更低。

```
RECOMMENDED_NEUTRAL_CANDIDATE = S-B（户规模与机构门槛居中，SAT 与 MAIN 尺度差可接受）
OWNER_MUST_CHOOSE = S-A / S-B / S-C / CUSTOM（各占比可单独改）
```

---

## NUMERIC_OD_T1 — TRIBULATION_PROFILE_INTENSITY（owner §11）

周期 10/50/100 与首个前兆 tick 10,000,000 **已锁定，不再讨论**。
只处理**剩余风险/强度字段**。包络按 frozen plan 公式 `f = intensity/100` 缩放六项风险
（`tribulation.py:696-707`），风险比例设为 `resource_damage = population_risk/4`、
`inventory_damage = population_risk/2`（可由主人替换）。**六项不得全 0**（owner 要求）。

| | T-A 温和 | T-B 中度 | T-C 剧烈 |
| --- | --- | --- | --- |
| REGULAR intensity / 人口风险 | 5–15（典型 10）/ 0.2% | 10–25（15）/ 0.4% | 20–40（30）/ 1% |
| **10 年 REGULAR 包络** | 死亡 2 人 / 库存损 0 | 死亡 7 人 / 库存损 1 | 死亡 36 人 / 库存损 9 |
| MAJOR intensity / 人口风险 | 20–40（30）/ 1% | 30–50（40）/ 2% | 45–70（60）/ 5% |
| **50 年 MAJOR 包络** | 死亡 36 人 / 库存损 9 | 死亡 96 人 / 库存损 24 | 死亡 360 人 / 库存损 90 |
| CENTENNIAL intensity / 人口风险 | 50–70（60）/ 3% | 60–85（75）/ 5% | 80–100（90）/ 10% |
| **100 年 CENTENNIAL 包络** | 死亡 216 人 / 库存损 54 | 死亡 450 人 / 库存损 112 | 死亡 1,080 人 / 库存损 270 |
| theme 池 | 灵气潮汐 / 地脉波动 / 生态失衡（canon 主题池） | 同 | 同 |
| steps | precursor/preparation/impact = 1、recovery = 3 | 同 | 同 |

```
RECOMMENDED_NEUTRAL_CANDIDATE = T-B（三 tier 后果可感知但不摧毁 bootstrap 人口/库存）
OWNER_MUST_CHOOSE = T-A / T-B / T-C / CUSTOM（强度区间与六项风险比例可改）
```

---

## 覆盖检查（owner §12 / §19）

| M6C.1B 决策 | 本阶段归属 |
| --- | --- |
| OD-2 人口世界法则 | **NUMERIC_OD_P1** |
| OD-3 资源（S-5） | **NUMERIC_OD_RE1**（profile 类型已批准 8 类；实例拓扑 = 7 节点；库存/产能 = N/M policy） |
| OD-4 经济与产业（S-4） | **NUMERIC_OD_RE1**（7 sector 各有 profile/recipe；库存与产能由 N/M 表达） |
| OD-5 生态（D-B8） | **NUMERIC_OD_E1** |
| OD-6 社会阈值（S-7） | **NUMERIC_OD_S1** |
| OD-7 灾劫 profile | **NUMERIC_OD_T1** |
| OD-8 RA-STRUCT-001 | 已 APPROVED（本阶段沿用：区=聚落数、state/feedback 行数由引擎要求派生） |
| OD-9 DYNAMIC_NEUTRAL | **已吸收**：`habitat_quality = FULL_QUALITY`（owner）+ E1/RE1 提供其余（stocks→RE1、pressure/social/feedback = 引擎 server default，M6C.1B 已列明）；技术中性 `AUTO_ACK APPROVED` |
| OD-1 种族身份 | 已由 owner 批准（A）：`Hairy Men/Rockmen/Mermen/Mushroommen`；`Human = 0` |

```
NUMERIC_OD_* 全部覆盖 → UNTRACKED_BLOCKING_FIELDS = 0
```

## 不变量与停止点

```
RA_STRUCT_001 = APPROVED（本阶段未改其语义）
FORMAL_DB_AUTHORITY = PASS（authoritative marker；legacy stale DB 不作为 world truth）
SNAPSHOT_V1 = NOT_APPROVED
MATERIALIZER_ALLOWED = FALSE
```

```
STOP。不得实现 materializer。不得激活世界。等待主人对 P1/RE1/E1/S1/T1 的数值裁决。
```

# M5 Query Layer Architecture（M5.0 Preflight）

> 基线：m4-scheduler-frozen（d39355a）；分支 m5-query-companion。
> 目标：只读世界查询层 + AstrBot 官方 hook 上下文注入；零世界语义修改。

## 1. AstrBot 官方集成面（实测 live 实例 API 审计）

| 关注点 | 官方接口 | 来源 |
|---|---|---|
| LLM 请求 hook | `@on_llm_request()`（`astrbot.api.event.filter` 导出） | astrbot.core.star.register |
| hook 签名 | `async def handler(self, event: AstrMessageEvent, req: ProviderRequest) -> None` | 注册器 docstring（务必两个参数 event, req） |
| 注入点 | `req.extra_user_content_parts.append(TextPart(text=...).mark_as_temp())` | builtin group_chat_context / astr_main_agent 官方用法 |
| TextPart | `astrbot.core.agent.message.TextPart`（builtin stars 同路径；无 api 层再导出） | builtin 源码 |
| ProviderRequest | dataclass：prompt/session_id/extra_user_content_parts/contexts/system_prompt/conversation/... | astrbot.core.provider.entities |
| 事件文本 | `event.message_str`（property）/ `event.get_messages()`（Plain.text） | astrbot.core.platform.astr_message_event |
| 插件生命周期 | Star.initialize/terminate（M1.1 已用） | — |

决策：
- hook 由 Runtime plugin（Star 子类）方法注册一次；每 ProviderRequest 至多追加一份
  Capsule（单 handler 天然 exactly-once；reload 由 AstrBot 插件生命周期管理，
  我们不在运行时重复注册）。
- `mark_as_temp()`：世界上下文不进 Companion 长期记忆（瞬时世界状态）。
- 只 APPEND 到 extra_user_content_parts；绝不改 system_prompt / prompt /
  conversation / contexts（不覆盖 Persona，不覆盖 Private Companion 上下文）。
- TextPart 导入带 fallback（ImportError → dict {"type":"text","text":...}），
  stub 环境提供 stub TextPart。

## 2. Query Layer（services/query/，astrbot-free）

```
services/query/
├── query_models.py      # 版本常量 / QueryType / Fact(provenance) / WorldContextCapsule
├── provenance.py        # Fact 构造 + stable ordering + UNKNOWN 标记
├── world_query_service.py  # 只读查询 API（NOT_ACTIVATED → UNKNOWN 语义）
├── context_builder.py   # Capsule 组装 + 模型向格式 + token 预算 + 确定性裁剪
└── intent_router.py     # 确定性关键词路由（无 LLM）
```

- READ ONLY：所有查询零写入；`ReadOnlyGuard` 前后比对
  world_state_hash / event_stream_hash / causal_history_hash / current_tick /
  checkpoint 数 / event 数（M5Q27/41-44）。
- NOT_ACTIVATED：status=NOT_ACTIVATED；current_population=UNKNOWN；
  settlements=UNKNOWN；current_resources=UNKNOWN；recent_history=NONE_OFFICIAL；
  next_tribulation=UNKNOWN；current_blessed_tick=NULL（渲染为 UNKNOWN/NOT_STARTED，
  绝不 Year 0，绝不 0 人）。
- NULL != 0（延续 M4 语义）。
- Static Rule vs Dynamic Fact：动态事实只来自 DB 权威状态；World Bible 静态规则
  不冒充动态事实；World Seed 绝不读取（M5 硬门禁）。
- AUTHORITATIVE（DB 当前状态）vs DERIVED（确定性计算，如"过去十年人口下降 8%"）；
  禁止 LLM 猜测进入 Capsule。UNKNOWN 是合法结果（未激活/无实体/无记录/链不充分）。
- History/因果：直接复用 M3b HistoryService（explain_state/trace_causes/timeline）；
  禁止第二套历史逻辑。
- Scheduler：只读 get_scheduler_status；读取绝不 start/resume/acquire lease（M5Q28）。
- OwnerDecision：只查询 decision state；自然语言绝不自动提交（§28）。
- Fail-closed：DB 不可用/schema 不符/history integrity 失败/scheduler FAILED →
  RUNTIME_UNAVAILABLE（或等价），不让模型自行猜测。
- 缓存：第一版不做复杂缓存（每次查询直接读 DB，天然 as_of_tick 一致）。

## 3. Intent Router（确定性，零 LLM）

13 类：NO_WORLD_CONTEXT / WORLD_STATUS / WORLD_TIME / POPULATION / SETTLEMENT /
RESOURCE_ECONOMY / ECOLOGY / SOCIAL / TRIBULATION / HISTORY / CAUSAL_EXPLANATION /
CHANGES_SINCE / DEEP_WORLD_QUERY。关键词→类别映射 + 固定优先级；普通闲聊默认
NO_WORLD_CONTEXT（不注入任何世界数据）。

## 4. Context Capsule 与 Token 预算

- 预算（字符硬上限 ≈ tokens×4）：NORMAL ≤1600 chars（≈400 tokens）、
  WORLD_QUERY ≤4000（≈1000）、DEEP_HISTORY ≤8000（≈2000）。
- 裁剪优先级：①当前直接答案 ②权威当前事实 ③直接相关因果链 ④相关近期历史
  ⑤支撑细节；删除顺序相反；整体条目裁剪（绝不切碎 JSON/句子中段），
  末尾固定 `TRUNCATED` 标记。
- 模型向格式（§52）：STATUS / TIME / FACTS / RECENT_CHANGES / HISTORY / CAUSAL /
  UNKNOWNS，机器边界标签 `[Blessed Land Runtime — Authoritative World Context]`；
  简短指令行：动态事实为权威数据、UNKNOWN 不得补写、不得修改这些事实、
  聊天本身不是 DB mutation command。
- Prompt Injection：DB 自由文本一律作为 DATA 渲染（值前缀固定标签、控制字符
  清理、单值长度上限），绝不拼接成指令位；不注入居民名单/全部历史/内部路径/
  hash/token/调试信息。
- 确定性：全链路 stable ordering（排序键：fact_type/entity_id/as_of_tick），
  禁止 SQL 物理顺序/set 顺序（M5Q19/20）。
- 版本：WORLD_QUERY_SCHEMA_VERSION / WORLD_CONTEXT_CAPSULE_VERSION /
  M5_INTEGRATION_VERSION 入 manifest。

## 5. 集成与隔离

- 只在 astrbot_plugin_blessed_land_runtime 内部加 M5 integration；不改 AstrBot
  Core；不改 Private Companion（源码 checksum 基线已记录，验收时复核）。
- Admin 只读 API：/runtime/query/status、/runtime/query/world、
  /runtime/query/history（复用既有 register_web_api；read-only；无独立端口）。
- Plugin Page 扩展：runtime/scheduler/blessed-time/population/recent/active
  tribulation/history lookup；未激活时明确 NOT ACTIVATED（不显示一堆 0）。
- 配置：新增 query_integration_enabled（默认 true）入 _conf_schema.json。

## 6. 测试矩阵与验收

- M5Q01–M5Q47 全部落地（query service / capsule / router / hook stub / isolation /
  freeze protection）。
- synthetic E2E（M3LONG synthetic 激活世界：时间/人口/聚落/资源/生态/社会/灾劫/
  历史/因果/区间变化）；formal NOT_ACTIVATED E2E（多轮聊天不启动世界）。
- 真实 AstrBot 环境 smoke：live 实例 venv 内用真实 astrbot 包跑 hook handler +
  ProviderRequest 注入验证；部署与真实对话验证按 §55 执行（不干扰 Companion）。
- 回归：M0-M4 全量；M2/M3 baselines unchanged；M4 scheduler golden unchanged。

# M5 Query Companion Integration Acceptance

> M5 = READ-ONLY WORLD QUERY LAYER + ASTRBOT OFFICIAL HOOK INTEGRATION。
> 基线：m4-scheduler-frozen（d39355a）；分支 m5-query-companion。
> 不是 World Seed Activation；禁止修改 Private Companion 源码。

## 验收结论（回归完成后填最终数字）

```
TOTAL_TESTS     = （fast 回归 + M5 矩阵 + M2/M3c long 回归）
TOTAL_PASS      =
TOTAL_SKIP      = 13（EXPECTED_FORMAL_DB_SKIP，不变）
TOTAL_FAIL      = 0

QUERY_LAYER_STATUS             = PASS
ASTRBOT_INTEGRATION            = PASS（官方 on_llm_request + ProviderRequest 注入）
PRIVATE_COMPANION_SOURCE_UNCHANGED = TRUE（529 文件逐字节 == 开工基线 cf259085…）

NORMAL_CONTEXT_MAX   = 400 chars（≈400 tokens，char 硬上限保守等价）
WORLD_CONTEXT_MAX    = 1000 chars
DEEP_HISTORY_CONTEXT_MAX = 2000 chars

FORMAL_RUNTIME_STATUS     = NOT_ACTIVATED
FORMAL_CURRENT_BLESSED_TICK = NULL
FORMAL_OFFICIAL_EVENTS    = 0
FORMAL_WORLD_MUTATIONS    = 0

WORLD_SEED_CONSUMED  = FALSE
WORLD_SEED_UNCHANGED = TRUE

DUPLICATE_HOOKS              = 0（真实注册器 module_name 去重实测 + stub registry 唯一）
DUPLICATE_CONTEXT_INJECTIONS = 0（每 ProviderRequest 至多一份）

RUNTIME_QUERY_LLM_CALLS   = 0
RUNTIME_QUERY_LLM_TOKENS  = 0
RUNTIME_QUERY_NETWORK_CALLS = 0

M2_BASELINES_UNCHANGED = TRUE
M3_BASELINES_UNCHANGED = TRUE
M4_GOLDEN_UNCHANGED    = TRUE

PRE_ACTIVATION_PG_GATE               = REQUIRED
PRE_ACTIVATION_PG_COMMIT_AMBIGUITY_GATE = REQUIRED
```

## 1. Baseline

m4-scheduler-frozen@d39355a；正式世界 NOT_ACTIVATED；World Seed
PREPARED_NOT_ACTIVATED；PG 双 gate REQUIRED（M5 未触碰）。

## 2. Query Architecture

services/query/（astrbot-free，零 LLM/网络）：
- world_query_service.py：16 个只读 API + ReadOnlyGuard（三哈希/tick/
  checkpoint/event 计数前后一致，违例即抛 IntegrityError）
- query_models.py / provenance.py：Fact(AUTHORITATIVE/DERIVED/STATIC_RULE)
  + stable ordering + UNKNOWN 语义
- intent_router.py：13 类确定性路由（零 LLM；闲聊默认 NO_WORLD_CONTEXT）
- context_builder.py：Capsule + 模型向渲染 + 预算 + 确定性整行裁剪 +
  注入防护（DATA sanitize）

## 3. Authority Model

Runtime Authoritative Dynamic State > approved owner input > Local Canon
静态规则 > Source Lore；AUTHORITATIVE（DB 当前状态）vs DERIVED（确定性
计算）；LLM guessed 禁止进入 Capsule；World Seed 禁止作为当前事实。

## 4. NOT_ACTIVATED 语义

- “现在多少人？” → UNKNOWN / WORLD_NOT_ACTIVATED（绝不 0）
- “现在是哪一年？” → NOT_STARTED（绝不 Year 0）
- “最近发生了什么？” → NONE_OFFICIAL（绝不 synthetic 历史）
- “下一次灾劫是什么时候？” → UNKNOWN
- 空正式库 ≠ “世界存在且为零”

## 5. Query Types / 6. Capsule / 7. Routing / 8. Budget / 9. Provenance /
10. UNKNOWN / 11. Failure / 12. Hook

详见 docs/m5_query_layer_architecture.md + M5_QUERY_COMPANION_INTEGRATION_
MANIFEST.json（全部冻结条款）。

## 13. Private Companion Isolation

- 源码 checksum 基线（529 文件 cf259085…）开工记录、验收复核一致；
- M5 代码零 import/patch/写其 DB；集成仅官方 hook + 公开只读 Query Service。

## 14. Reload/Restart / 15. Exactly-once

- 真实注册器（live venv 实测）：按 module_name+handler_name 去重，
  reload 后 count=1（DUPLICATE_HOOKS=0）；
- stub：每 ProviderRequest 至多一份 Capsule；disable→零注入；
  enable→恢复；restart 循环零孤儿。

## 16-22. Recent Changes / History / Causal / E2E / Security / Perf / LLM

- changes-between-ticks：确定性 meaningful 分类 + 聚合（30y 区间测试）；
- History/因果：复用 M3b HistoryService；
- synthetic E2E：M3LONG 激活世界全查询面（人口/聚落/资源/经济/生态/
  社会/灾劫/时间线/因果/区间）；
- formal NOT_ACTIVATED E2E：多轮聊天注入验证 + 查询后 tick NULL/events 0/
  runtime_lock 0（聊天不会偷偷启动世界）；
- 注入防护：DATA sanitize（换行剥离/长度上限/固定标签）；
- 性能（300y 库）：runtime_status 1.1ms / population 1.9ms / snapshot
  11.6ms / recent_changes 6.6ms / timeline 7.0ms / explain 9.9ms（p50）；
- LLM/network：RUNTIME_QUERY=0；真实 AstrBot smoke PASS。

## 23. LLM Boundary / 24. Network / 25. Regression / 26. Formal DB /
27. World Seed / 28. PG / 29. Git / 30. Risks / 31. M6 Recommendation

（最终数字与结论见最终报告）

## 真实 AstrBot Smoke 记录

live 实例 venv + 真实 astrbot 包（独立进程、temp cwd、不触碰 live 数据）：
real_registry_registered PASS；duplicate_hooks_after_reload PASS（count=1）；
extra_user_content_parts_is_plain_list PASS；injection_append_once PASS；
injection_is_textpart PASS；injection_marked_temp PASS（_no_save）；
provider_request_fields_intact PASS；persona_fields_untouched PASS。
→ M5_REAL_ASTRBOT_SMOKE = PASS

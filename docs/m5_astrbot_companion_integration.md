# M5 AstrBot / Companion Integration

> 集成方式：AstrBot 官方 hook（`@on_llm_request()` + `ProviderRequest.
> extra_user_content_parts`）＋ Runtime 公开只读 Query Service。
> **Private Companion source unchanged**（本阶段不修改其任何源码/数据/内部对象）。

## 1. 数据流

```
用户消息
  ↓ AstrBot 官方 on_llm_request hook（Runtime plugin 注册）
  ↓ WorldQueryIntentRouter（确定性关键词路由，零 LLM）
  ↓ WorldQueryService（只读查询；NOT_ACTIVATED → UNKNOWN）
  ↓ WorldContextCapsule（provenance + stable ordering）
  ↓ ContextBuilder.render（token 预算 + 确定性裁剪 + 模型向格式）
  ↓ req.extra_user_content_parts.append(TextPart(...).mark_as_temp())
  ↓ Private Companion / Persona 正常生成回复（人格/语气/记忆仍由其负责）
```

- M5 不接管 Persona；小光的语气、关系、记忆、主动消息全部继续由
  Private Companion 负责。
- Runtime 只提供 **Authoritative World Facts**。

## 2. Hook 契约（实测 live 实例 API）

- 注册：`from astrbot.api.event.filter import on_llm_request`，装饰在
  Star 子类方法上（类定义一次 = 注册一次）。
- 签名：`async def handler(self, event: AstrMessageEvent, req: ProviderRequest) -> None`。
- 注入：`req.extra_user_content_parts.append(TextPart(text=...).mark_as_temp())`
  （TextPart 路径 = builtin stars 同款 `astrbot.core.agent.message`，
  带 dict fallback）。
- `mark_as_temp()`：世界上下文为瞬时状态，不进 Companion 长期记忆。
- 只 APPEND，绝不修改 `system_prompt` / `prompt` / `contexts` /
  `conversation`——不覆盖人设与 Companion 上下文。

## 3. Exactly-once 与重复防护

- 每个 ProviderRequest 至多一份 Capsule（单 handler、单 append）。
- 普通闲聊（NO_WORLD_CONTEXT）零注入。
- Runtime reload / AstrBot restart：hook 注册由类定义驱动；测试验证
  registry 唯一 + 每请求恰一份（stub harness + 真实包 smoke）。
- `query_integration_enabled=false` 时彻底不注入；恢复 true 后恢复注入。

## 4. NOT_ACTIVATED 语义（正式世界）

| 问题 | 结果 |
|---|---|
| “福地现在怎么样？” | 明确：正式福地尚未启动（不编人口/历史） |
| “现在有多少人？” | UNKNOWN / WORLD_NOT_ACTIVATED（绝不 0） |
| “现在是哪一年？” | NOT_STARTED（绝不 Year 0） |
| “最近发生了什么？” | NONE_OFFICIAL（绝不引用 synthetic baseline） |
| “下一次灾劫是什么时候？” | UNKNOWN |

## 5. 隔离与安全

- Private Companion：源码 checksum 基线（cf259085…，529 文件）已记录，
  验收复核；M5 代码零 import/patch/写其 DB。
- Prompt injection：DB 自由文本一律 DATA 渲染（sanitize + 长度上限），
  不进入指令位。
- 隐私：只注入当前问题所需；不注入居民名单/全部历史/内部路径/hash/token。
- Admin API：只读 `/runtime/query/{status,world,history}`（AstrBot 官方
  认证机制，无独立端口）。
- Plugin Page：扩展查询面板；未激活时明确 NOT ACTIVATED（不显示一堆 0）。

## 6. 验证

- stub harness：test_query_astrbot_hook.py（M5Q32-36、M5Q51）。
- 真实 AstrBot 环境 smoke：scripts/m5_real_astrbot_smoke.py（live 实例
  venv + 真实 astrbot 包：hook 注册唯一性、ProviderRequest 注入、
  formal NOT_ACTIVATED 多轮语义）。
- synthetic E2E：test_query_service / test_query_context_builder
  （激活世界全查询面）。

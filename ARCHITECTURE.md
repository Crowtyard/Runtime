# ARCHITECTURE（M1.1 AstrBot 插件外壳迁移后）

> 本文件定义 Runtime 作为 AstrBot 独立插件的架构边界。运行时原则不变：
> PLUGIN SHELL ≠ DOMAIN CORE；WORLD FIRST, CHARACTER SECOND。

## 1. 插件拓扑（物理独立 / 逻辑协作）

```
AstrBot
├── astrbot_plugin_private_companion      # 小光人格、陪伴、日程、主动消息
└── astrbot_plugin_blessed_land_runtime   # 福地世界状态、时间、历史与未来模拟
```

- 二者是 **Sibling Plugins**，不是 Parent / Child。
- Runtime 不 import Private Companion、不访问其私有数据库/文件/方法/页面。
- Private Companion 整体替换不得影响 Runtime（已由 PL11 测试验证）。

## 2. 分层与模块边界

| 层 | 模块 | 允许 import astrbot |
|---|---|---|
| AstrBot 适配壳 | main.py、plugin_shell/paths.py | 是（仅这两个） |
| 宿主层 | plugin_shell/runtime_host.py | 否 |
| 领域核心 | domain/、services/、database/、config/ | 否（测试强制） |

- main.py：生命周期 + 只读 Web API + Page 支撑。不塞任何时间引擎/领域逻辑。
- runtime_host.py：boot / status / diagnostics / runtime_info / backup_now / shutdown。
- domain/services/database：M1 验收原样（Golden Baseline 保护）。

## 3. 持久数据路径（最高级硬门禁）

```
<AstrBot data>/plugin_data/astrbot_plugin_blessed_land_runtime/
├── blessed_land.sqlite            # 唯一权威正式世界 DB（AUTHORITATIVE_DB_PATH）
├── runtime_state/authoritative_db.json   # 权威标记（路径 + checksum）
├── backups/                       # 备份（不随插件代码更新丢失）
├── exports/  runtime_state/  logs/
```

- DB 路径动态解析：官方 `get_astrbot_plugin_data_path()`（等价回退 `data/plugin_data`）。
- 禁止硬编码任何磁盘绝对路径；正式世界数据绝不位于插件源码目录/仓库根目录。
- 运行时只打开一个正式世界 DB（authoritative marker）；旧 DB 保留 rollback copy，
  绝不自动删除（迁移脚本 scripts/migrate_db_to_plugin_data.py）。

## 4. 只读边界与激活时间陷阱

- M1.1 不提供任何 mutation 端点（/activate /advance-time /seed /create-person
  /create-event 等全部禁止）；Web API 仅 GET /status /diagnostics /runtime-info。
- Plugin load / reload / restart / status / page open / diagnostics 均不得写入：
  `last_committed_real_us`、`current_blessed_tick`、simulation run、TIME_ADVANCE。
- **Activation Time Trap**：NOT_ACTIVATED 期间现实经过的时间不得累积为未来福地历史。
  激活纪元的建立属于 M2 Activation Transaction（当前 World Activation = LOCKED）。

## 5. LLM → World 禁写原则

核心不变量：**WORLD FIRST, CHARACTER SECOND**。

- 正确链路：Runtime 确定性模拟 → DB 正式事件 → 小光读取 → 告诉主人。
- 错误链路（禁止）：小光台词声称某事发生 → Runtime 为配合台词补写事件。
- LLM output 永远不得成为 authoritative world mutation。
- 未来世界写入只能来自：deterministic simulation / approved admin action /
  future explicit world action API。

## 6. 未来 Integration Boundary（M2+，本阶段不实现）

```
World DB → BlessedLandRuntime Query Layer（READ ONLY）
        → AstrBot Plugin Adapter（on_llm_request / extra_user_content_parts）
        → LLM
```

- 动态世界上下文只读注入；LLM 永远不得获得 write_world()/create_event()/
  edit_population() 等 mutation 能力。
- 对外契约届时以 Runtime 自己发布的公开接口为准，不依赖 Private Companion 私有方法
  （调研结论：NO_PUBLIC_CONTRACT，见 M1.1 报告 §19）。

## 7. 版本与迁移

- Golden Baseline：git tag `m1-golden-baseline`（103 tests）。
- Alembic 9 个 migration 历史保留，禁止 squash / reset；无 schema 变更不强行造 migration。
- 插件依赖：requirements.txt（SQLAlchemy>=2.0、alembic>=1.13；pytest 不进生产依赖）。

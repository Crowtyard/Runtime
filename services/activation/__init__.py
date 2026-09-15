# -*- coding: utf-8 -*-
"""M6A ACTIVATION SERVICE —— 正式世界激活的唯一 public production entrypoint。

```
from services.activation import ActivationRequest, activate_formal_world
```

不变量（由静态门禁 ``tests/test_m6_world_seed_safety.py`` 强制）：

- ``WORLD_SEED_ACTIVATION_ACCESS_ALLOWLIST = M6_ACTIVATION_SERVICE_ONLY``：
  只有本包（``services/activation/``）允许引用 World Seed 包的激活原语；
  scheduler / query / simulation / history / plugin_shell boot 全部禁止；
- 普通 runtime boot **绝不**自动激活（RuntimeHost 继续报告
  ``world_activation = LOCKED``）；激活只能由 owner-only 控制面显式发起
  （``scripts/activate_formal_world.py``）；LLM 与聊天永不具备激活权限。
"""
from __future__ import annotations

from .seed_package import (
    REQUIRED_DECLARED_STATUS, SeedPackage, default_seed_dir, load_seed_package)
from .service import (
    ACTIVATION_ID_SCHEMA, GENESIS_ENGINE_ID, OUTCOME_ALREADY_COMMITTED,
    OUTCOME_COMMITTED, ActivationOutcome, ActivationRequest,
    activate_formal_world)

#: §17 唯一 seed 激活访问 allowlist 声明（静态门禁 test_m6_world_seed_safety 强制）：
#: 只有本包可以引用 World Seed 激活原语。
WORLD_SEED_ACTIVATION_ACCESS_ALLOWLIST = "M6_ACTIVATION_SERVICE_ONLY"

#: allowlist 成员（相对仓库根的包路径前缀）
WORLD_SEED_ACTIVATION_ALLOWED_PREFIXES = ("services/activation/",)

__all__ = [
    "ACTIVATION_ID_SCHEMA",
    "ActivationOutcome",
    "ActivationRequest",
    "GENESIS_ENGINE_ID",
    "OUTCOME_ALREADY_COMMITTED",
    "OUTCOME_COMMITTED",
    "REQUIRED_DECLARED_STATUS",
    "SeedPackage",
    "WORLD_SEED_ACTIVATION_ACCESS_ALLOWLIST",
    "WORLD_SEED_ACTIVATION_ALLOWED_PREFIXES",
    "activate_formal_world",
    "default_seed_dir",
    "load_seed_package",
]

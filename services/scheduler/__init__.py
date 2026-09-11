# -*- coding: utf-8 -*-
"""services.scheduler —— Runtime 自动调度层（M4）。

Scheduler = orchestration（什么时候跑、跑多少、谁写、失败如何恢复）；
Engine = semantics（世界里发生什么）。两者不得混淆。

对冻结设施的全部使用：
- catch_up（唯一权威推进原语）
- coordinator.run_step / next_tribulation_boundary（冻结 engine 接口）
- WriterLease + WorldMutationContext（单写者 + fencing）
- time_engine 原语（只读规划）
"""
from .config import SchedulerConfig
from .core import RuntimeScheduler
from .state import SchedulerState, SchedulerStatusSnapshot

__all__ = ["SchedulerConfig", "RuntimeScheduler", "SchedulerState",
           "SchedulerStatusSnapshot"]

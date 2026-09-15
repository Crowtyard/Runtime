"""领域枚举与常量（M0）。"""
from __future__ import annotations


class RuntimeStatus:
    NOT_ACTIVATED = "NOT_ACTIVATED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ERROR = "ERROR"


class WorldBibleVersion:
    CURRENT = "1.0"
    FROZEN = True


class WorldSeedVersion:
    """World Seed 包版本（M6A）。

    来源：World Seed 包 ``VERSION.json`` 的 ``version`` 字段
    （XIAOGUANG_BLESSED_LAND_WORLD_SEED_PACKAGE v1.0，status=PREPARED_NOT_ACTIVATED）。
    这里只**转写**包已声明的版本号，不发明版本语义。
    """
    CURRENT = "1.0"


class WorldActivationPolicy:
    """正式世界激活的 owner canon 取值（M6B）。

    ``OWNER_CANON_DECISION_1``：初始 blessed tick 恒为 **0**
    —— tick=0 是 Runtime 内部的正式时间原点（不是自然语言里的"福地第 0 年"）。
    NOT_ACTIVATED 时 ``current_blessed_tick`` 仍是 **NULL**（NULL ≠ 0）。

    ``OWNER_CANON_DECISION_2``：激活 anchor = 显式正式激活操作发生的
    canonical UTC instant，且必须作为 durable authoritative fact 与 activation
    operation 一起持久化；因此 ``PRE_ACTIVATION_BACKLOG = 0``。
    """

    INITIAL_BLESSED_TICK = 0
    ANCHOR_POLICY = "EXPLICIT_DURABLE_ACTIVATION_UTC_INSTANT"


class ActivationState:
    """正式世界激活的 durable 状态（M6A；由 DB 真值判定，绝不依赖进程内状态）。

    - NOT_STARTED：世界从未激活（canonical 表示 = world_runtime 0 行，
      或存在 NOT_ACTIVATED 行但尚未激活）；
    - COMMITTED：激活事务已 durable 提交（ACTIVE + seed 版本 + genesis 事件）。
    """
    NOT_STARTED = "NOT_STARTED"
    COMMITTED = "COMMITTED"


class SimulationVersion:
    """模拟算法版本（M0 初始开发版本；算法变更必须升版本并禁止重算历史）。"""
    CURRENT = "0.1.0-dev"


class EventSources:
    DEMOGRAPHIC = "DEMOGRAPHIC"
    SOCIAL = "SOCIAL"
    ECONOMIC = "ECONOMIC"
    RESOURCE = "RESOURCE"
    ECOLOGICAL = "ECOLOGICAL"
    TRIBULATION = "TRIBULATION"
    CULTURAL = "CULTURAL"
    OWNER_INPUT = "OWNER_INPUT"
    XIAOGUANG_ACTION = "XIAOGUANG_ACTION"
    SIMULATION = "SIMULATION"


class Scopes:
    AMBIENT = "AMBIENT"
    LOCAL = "LOCAL"
    REGIONAL = "REGIONAL"
    WORLD = "WORLD"
    MILESTONE = "MILESTONE"


class ActorTypes:
    XIAOGUANG = "XIAOGUANG"
    OWNER = "OWNER"
    NPC = "NPC"
    GROUP = "GROUP"
    SETTLEMENT = "SETTLEMENT"
    INDUSTRY = "INDUSTRY"
    ECOSYSTEM = "ECOSYSTEM"
    TRIBULATION = "TRIBULATION"
    WORLD = "WORLD"


class RateReasons:
    BIBLE_NATURAL = "BIBLE_V1_WS-0201_NATURAL_RATIO"
    ADJUSTMENT = "ADJUSTMENT"


class TickSources:
    CATCHUP = "CATCHUP"
    ONLINE = "ONLINE"


class WriterLockStatus:
    HELD = "HELD"
    FREE = "FREE"


class RunStatus:
    """SIMULATION RUN 生命周期（M1）：PENDING → RUNNING → COMMITTED；异常 RUNNING → FAILED。"""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"

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


class RatioReasons:
    BIBLE_NATURAL = "BIBLE_V1_WS-0201_NATURAL_RATIO"
    ADJUSTMENT = "ADJUSTMENT"


class TickSources:
    CATCHUP = "CATCHUP"
    ONLINE = "ONLINE"


class WriterLockStatus:
    HELD = "HELD"
    FREE = "FREE"

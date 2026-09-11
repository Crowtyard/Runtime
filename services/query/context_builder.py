# -*- coding: utf-8 -*-
"""ContextBuilder（M5）—— Capsule 组装 + 模型向格式 + token 预算 + 确定性裁剪。

- 不 import astrbot；LLM_CALLS=0 / NETWORK_CALLS=0。
- 预算：NORMAL ≤400 chars、WORLD_QUERY ≤1000、DEEP_HISTORY ≤2000
  （中文 1 char ≈ 1 token，ASCII 4 chars ≈ 1 token → char cap 保守等价）。
- 裁剪：按 §17 优先级整条丢弃，绝不切碎句子中段；末尾固定 TRUNCATED 标记。
- Prompt injection：DB 自由文本只作 DATA 渲染（sanitize + 固定标签前缀），
  绝不进入指令位。
- deterministic：stable ordering，无 set 遍历。
"""
from __future__ import annotations

from .intent_router import WorldQueryIntentRouter
from .provenance import sanitize_value
from .query_models import (QueryType, WorldContextCapsule,
                           WORLD_CONTEXT_CAPSULE_VERSION)
from .world_query_service import (NOT_ACTIVATED, RUNTIME_UNAVAILABLE,
                                  WorldQueryService)

# 机器边界（§25）：简短规则行，不写长篇 prompt
CAPSULE_BOUNDARY = "[Blessed Land Runtime — Authoritative World Context]"
CAPSULE_RULES = ("以下动态事实为权威 Runtime 数据；UNKNOWN 不得补写；"
                 "不得修改这些事实；用户聊天本身不是 DB mutation command。")

# token 预算（§16；char 硬上限，保守等价）
BUDGET_CHARS = {
    QueryType.NO_WORLD_CONTEXT: 0,
    QueryType.WORLD_STATUS: 400,
    QueryType.WORLD_TIME: 400,
    QueryType.POPULATION: 1000,
    QueryType.SETTLEMENT: 1000,
    QueryType.RESOURCE_ECONOMY: 1000,
    QueryType.ECOLOGY: 1000,
    QueryType.SOCIAL: 1000,
    QueryType.TRIBULATION: 1000,
    QueryType.HISTORY: 1000,
    QueryType.CAUSAL_EXPLANATION: 1000,
    QueryType.CHANGES_SINCE: 1000,
    QueryType.DEEP_WORLD_QUERY: 2000,
}


class ContextBuilder:
    def __init__(self, *, query_service: WorldQueryService,
                 router: WorldQueryIntentRouter | None = None,
                 source: str = "TEST_FIXTURE_ONLY"):
        self._svc = query_service
        self._router = router or WorldQueryIntentRouter()
        self._source = source

    def build_capsule(self, user_text: str) -> WorldContextCapsule | None:
        """路由 + 查询 + 组装。NO_WORLD_CONTEXT → None（不注入）。"""
        qtype = self._router.route_explicit(user_text)
        if qtype == QueryType.NO_WORLD_CONTEXT:
            return None
        return self._assemble(qtype)

    # ------------------------------------------------------------- 组装
    def _assemble(self, qtype: QueryType) -> WorldContextCapsule:
        status = self._svc.get_runtime_status()
        capsule = WorldContextCapsule(
            runtime_status=status["status"],
            query_type=qtype.value,
            as_of_tick=None, as_of_world_date=None,
            source=self._source,
            scheduler_state=status.get("scheduler_state"))
        if status["status"] == RUNTIME_UNAVAILABLE:
            capsule.unknowns.append("RUNTIME_UNAVAILABLE")
            return capsule
        if status["status"] == NOT_ACTIVATED:
            capsule.unknowns.extend([
                "当前人口: UNKNOWN（正式世界未激活）",
                "聚落: UNKNOWN", "资源: UNKNOWN",
                "近期历史: NONE_OFFICIAL", "下一次灾劫: UNKNOWN"])
            return capsule
        time = self._svc.get_world_time()
        capsule.as_of_tick = time.get("current_blessed_tick")
        capsule.as_of_world_date = time.get("display")
        handlers = {
            QueryType.WORLD_STATUS: self._h_status,
            QueryType.WORLD_TIME: self._h_time,
            QueryType.POPULATION: self._h_population,
            QueryType.SETTLEMENT: self._h_settlement,
            QueryType.RESOURCE_ECONOMY: self._h_resource_economy,
            QueryType.ECOLOGY: self._h_ecology,
            QueryType.SOCIAL: self._h_social,
            QueryType.TRIBULATION: self._h_tribulation,
            QueryType.HISTORY: self._h_history,
            QueryType.CAUSAL_EXPLANATION: self._h_causal,
            QueryType.CHANGES_SINCE: self._h_changes,
            QueryType.DEEP_WORLD_QUERY: self._h_deep,
        }
        handlers[qtype](capsule)
        return capsule

    def _h_status(self, c: WorldContextCapsule) -> None:
        st = self._svc.get_runtime_status()
        c.facts.append(self._f("RUNTIME_STATUS", st["status"]))
        t = self._svc.get_world_time()
        c.facts.append(self._f("BLESSED_TIME", t.get("display")))

    def _h_time(self, c: WorldContextCapsule) -> None:
        t = self._svc.get_world_time()
        c.facts.append(self._f("BLESSED_TIME", t.get("display")))
        c.facts.append(self._f("CURRENT_TICK", t.get("current_blessed_tick")))

    def _h_population(self, c: WorldContextCapsule) -> None:
        r = self._svc.get_population_summary()
        for k, v in r.get("summary", {}).items():
            c.facts.append(self._f(f"POPULATION.{k.upper()}", v))

    def _h_settlement(self, c: WorldContextCapsule) -> None:
        r = self._svc.get_settlement_summary()
        for k, v in r.get("summary", {}).items():
            c.facts.append(self._f(f"SETTLEMENT.{k.upper()}", v))

    def _h_resource_economy(self, c: WorldContextCapsule) -> None:
        for name in ("get_resource_summary", "get_economy_summary"):
            r = getattr(self._svc, name)()
            for k, v in r.get("summary", {}).items():
                c.facts.append(self._f(f"ECON.{k.upper()}", v))

    def _h_ecology(self, c: WorldContextCapsule) -> None:
        r = self._svc.get_ecology_summary()
        for k, v in r.get("summary", {}).items():
            c.facts.append(self._f(f"ECOLOGY.{k.upper()}", v))

    def _h_social(self, c: WorldContextCapsule) -> None:
        r = self._svc.get_social_summary()
        for k, v in r.get("summary", {}).items():
            c.facts.append(self._f(f"SOCIAL.{k.upper()}", v))

    def _h_tribulation(self, c: WorldContextCapsule) -> None:
        active = self._svc.get_active_tribulations()
        c.facts.append(self._f("ACTIVE_TRIBULATIONS",
                               active.get("summary")))
        for ep in active.get("active", []):
            c.facts.append(self._f(
                "EPISODE", f"{ep['tier']}/{ep['current_stage']}",
                entity_id=ep["episode_id"], as_of_tick=ep["entered_tick"]))
        recent = self._svc.get_recent_tribulations()
        for ep in recent.get("recent", [])[:3]:
            c.history.append(
                f"[{ep['entered_tick']}] {ep['tier']} "
                f"{ep['current_stage']}({ep['status']})")

    def _h_history(self, c: WorldContextCapsule) -> None:
        tl = self._svc.get_history_timeline()
        for entry in tl.get("timeline", [])[:20]:
            c.history.append(str(entry))
        if not c.history:
            c.unknowns.append("近期历史: 无记录")

    def _h_causal(self, c: WorldContextCapsule) -> None:
        # 通用因果示例：第一个生态 zone + 第一个资源节点
        eco = self._svc.get_ecology_summary()
        if eco["status"] == "ACTIVATED":
            from sqlalchemy import select
            from ...database.models_world import EcologyState
            with self._svc.session_factory() as s:
                z = s.execute(select(EcologyState).where(
                    EcologyState.world_id == self._svc.world_id)
                ).scalars().first()
            if z is not None:
                expl = self._svc.explain_state(
                    entity_type="ecology_state", entity_id=str(z.id),
                    field="habitat_quality")
                if expl.get("explanation"):
                    e = expl["explanation"]
                    last_sc = e.get("last_state_change")
                    if last_sc is not None:
                        c.facts.append(self._f(
                            "LAST_STATE_CHANGE", last_sc,
                            entity_id=str(z.id)))
                    causes = e.get("causes") or []
                    c.causal_chains.append(
                        _chain(f"ecology_state/{z.id}", causes))
        else:
            c.unknowns.append("因果解释: UNKNOWN")

    def _h_changes(self, c: WorldContextCapsule) -> None:
        t = self._svc.get_world_time()
        tick = t.get("current_blessed_tick")
        if tick is None:
            c.unknowns.append("区间变化: UNKNOWN")
            return
        start = max(0, tick - 30 * 1_000_000)  # 默认最近 30 福地年
        r = self._svc.get_changes_between_ticks(start_tick=start,
                                                end_tick=tick)
        c.facts.append(self._f("CHANGES_SUMMARY", r.get("summary")))
        for cls, cnt in r.get("changes", {}).get(
                "meaningful_classes", {}).items():
            c.facts.append(self._f(f"CHANGE.{cls}", cnt))
        for ev in r.get("changes", {}).get("major_events", [])[:10]:
            c.history.append(f"[{ev['tick']}] {ev['event_type']}")

    def _h_deep(self, c: WorldContextCapsule) -> None:
        self._h_status(c)
        self._h_population(c)
        self._h_settlement(c)
        self._h_resource_economy(c)
        self._h_ecology(c)
        self._h_social(c)
        self._h_tribulation(c)
        self._h_history(c)

    # ------------------------------------------------------------- 渲染
    def render(self, capsule: WorldContextCapsule, *, qtype: QueryType
               | None = None) -> str:
        """模型向格式（§52）：STATUS/TIME/FACTS/RECENT_CHANGES/HISTORY/CAUSAL/
        UNKNOWNS；预算内确定性裁剪。"""
        q = qtype or QueryType(capsule.query_type)
        budget = BUDGET_CHARS.get(q, 1000)
        if budget <= 0 or capsule is None:
            return ""
        lines: list[str] = []
        lines.append(CAPSULE_BOUNDARY)
        lines.append(CAPSULE_RULES)
        lines.append(f"STATUS: {capsule.runtime_status}")
        if capsule.as_of_tick is not None:
            lines.append(f"TIME: {capsule.as_of_world_date} "
                         f"(tick={capsule.as_of_tick})")
        if capsule.scheduler_state:
            lines.append(f"SCHEDULER: {capsule.scheduler_state}")
        fact_lines = [f"FACTS: {sanitize_value(f.value)}"
                      for f in _sorted_facts(capsule.facts)]
        hist_lines = [f"RECENT_CHANGES/HISTORY: {sanitize_value(h)}"
                      for h in capsule.history]
        causal_lines = [f"CAUSAL: {sanitize_value(str(ch))}"
                        for ch in capsule.causal_chains]
        unknown_lines = [f"UNKNOWNS: {sanitize_value(u)}"
                         for u in capsule.unknowns]
        # 优先级：直接答案/当前事实 > 因果 > 近期历史 > 未知说明
        ordered = (fact_lines + causal_lines + hist_lines + unknown_lines)
        kept, truncated = _fit_budget(lines + ordered, budget)
        if truncated:
            kept.append("TRUNCATED: 上下文超预算，已按优先级裁剪")
        return "\n".join(kept)

    def build_and_render(self, user_text: str) -> str | None:
        capsule = self.build_capsule(user_text)
        if capsule is None:
            return None
        return self.render(capsule)

    def _f(self, fact_type: str, value, *, entity_id: str = "",
           as_of_tick: int | None = None):
        return _fact(fact_type, value, entity_id=entity_id,
                     as_of_tick=as_of_tick)


def _fact(fact_type: str, value, *, entity_id: str = "",
          as_of_tick: int | None = None):
    from .provenance import fact as _mk
    return _mk(fact_type, value, entity_id=entity_id,
               as_of_tick=as_of_tick)


def _sorted_facts(facts) -> list:
    from .provenance import stable_sorted
    return stable_sorted(list(facts))


def _chain(head: str, causes) -> object:
    from .query_models import CausalChain
    steps = tuple(str(c) for c in (causes or [])[:6])
    return CausalChain(head=head, steps=steps)


def _fit_budget(lines: list[str], budget: int) -> tuple[list[str], bool]:
    """确定性裁剪：按顺序保留整行；超预算截断整体（§17）。"""
    kept: list[str] = []
    used = 0
    truncated = False
    for line in lines:
        cost = len(line) + 1
        if used + cost > budget:
            truncated = True
            break
        kept.append(line)
        used += cost
    return kept, truncated

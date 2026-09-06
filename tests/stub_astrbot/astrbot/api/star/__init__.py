# -*- coding: utf-8 -*-
"""stub astrbot.api.star：Star 基类 + Context。"""
from __future__ import annotations

import logging

logger = logging.getLogger("astrbot.stub")


class Context:
    def __init__(self):
        self.routes = {}  # route -> (handler, methods, desc)

    def register_web_api(self, route, view_handler, methods, desc):
        self.routes[route] = (view_handler, list(methods), desc)


class Star:
    def __init__(self, context: Context, config=None):
        self.context = context
        self.config = config if config is not None else {}

    async def initialize(self) -> None:  # noqa: B027
        pass

    async def terminate(self) -> None:  # noqa: B027
        pass

# -*- coding: utf-8 -*-
"""stub astrbot.core.agent.message：TextPart（测试 harness；同真实 API 语义）。"""
from __future__ import annotations


class TextPart:
    def __init__(self, text: str):
        self.text = text
        self._temp = False

    def mark_as_temp(self) -> "TextPart":
        self._temp = True
        return self

    def is_temp(self) -> bool:
        return self._temp

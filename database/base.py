"""Declarative Base、aware-UTC 时间列与通用工具（无 SQLite 私有依赖）。

时间策略（M0 DSH QA 修正，替代 naive UTC）：
- 应用层只生产/消费 timezone-aware UTC datetime（utcnow() 返回 aware UTC）。
- UtcDateTime 列类型在边界强制归一化：naive 输入按 UTC 解释，带时区输入转 UTC。
- DB 层：SQLite 落显式 ISO-8601 UTC 文本（含 +00:00 后缀，字典序安全）；
  PostgreSQL 落原生 TIMESTAMPTZ（UTC）。
- 不依赖机器本地时区、不受 DST 影响、不产生 ambiguous datetime。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class UtcDateTime(TypeDecorator):
    """aware-UTC 时间列：入/出库边界一律归一化为 aware UTC。

    - SQLite：绑定为显式 \"YYYY-MM-DD HH:MM:SS.ffffff+00:00\" 文本；
      读取时解析回 aware datetime（兼容旧 naive-UTC 文本行）。
    - PostgreSQL：TIMESTAMPTZ 原生 UTC 语义。
    """
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: ANN001
        if value is None:
            return None
        return _to_utc(value)

    def process_result_value(self, value, dialect):  # noqa: ANN001
        if value is None:
            return None
        return _to_utc(value)

    def bind_processor(self, dialect):  # noqa: ANN001
        if dialect.name == "sqlite":

            def proc(value):  # noqa: ANN001
                if value is None:
                    return None
                return _to_utc(value).isoformat(sep=" ", timespec="microseconds")

            return proc
        return super().bind_processor(dialect)

    def result_processor(self, dialect, coltype):  # noqa: ANN001
        if dialect.name == "sqlite":

            def proc(value):  # noqa: ANN001
                if value is None:
                    return None
                if isinstance(value, str):
                    value = datetime.fromisoformat(value.replace(" ", "T"))
                if isinstance(value, datetime):
                    return _to_utc(value)
                return value

            return proc
        return super().result_processor(dialect, coltype)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    """系统级现实时间：应用层统一 aware UTC。"""
    return datetime.now(timezone.utc)


class UTCTimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow,
                                                nullable=False)


def utc_column(nullable: bool = True) -> Mapped[datetime | None]:
    return mapped_column(UtcDateTime(), nullable=nullable)

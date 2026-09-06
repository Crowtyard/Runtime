"""数据库引擎/会话工厂（3 节：WAL + foreign_keys=ON + 事务）。

- business 层不得出现 SQLite 私有 SQL（方言由 SQLAlchemy 处理）。
- engine 参数集中于此；测试可用独立临时库。
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from config.settings import Settings


def create_db_engine(database_url: str | None = None, *, sqlite_file: Path | None = None) -> Engine:
    url = database_url or Settings().database_url
    if sqlite_file is not None:
        url = "sqlite:///" + str(sqlite_file.resolve()).replace("\\", "/")
    kwargs: dict = {"future": True}
    if url.startswith("sqlite"):
        # SQLite 连接级设置（未来 PG 不适用；由 URL 前缀分流，业务层无感）
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    engine = create_engine(url, **kwargs)

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _record):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """事务作用域：正常 commit / 异常 rollback（ATOMIC_TICK 的基础）。"""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

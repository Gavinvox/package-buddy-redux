"""Database engine and session helpers (SQLite in the /data volume)."""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


engine = None
SessionLocal: sessionmaker | None = None


def init_engine(db_path: str):
    global engine, SessionLocal
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _rec):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    from . import models  # noqa: F401  (register tables)

    Base.metadata.create_all(engine)
    return engine


@contextmanager
def session_scope() -> Iterator[Session]:
    assert SessionLocal is not None, "init_engine() was not called"
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    assert SessionLocal is not None
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()

"""Database engine/session helpers."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .models import Base


def make_engine(url: Optional[str] = None) -> Engine:
    return create_engine(url or get_settings().data.database_url, future=True)


def init_db(engine: Engine) -> None:
    """Create all tables (idempotent). Alembic migrations can replace this later."""
    Base.metadata.create_all(engine)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

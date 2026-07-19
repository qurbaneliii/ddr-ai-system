from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from ddr_ai.db.models import Base

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ENGINES: dict[str, Engine] = {}
_ENGINE_LOCK = RLock()


def get_engine(database_url: str) -> Engine:
    """Return an engine cached by the fully resolved database URL."""

    with _ENGINE_LOCK:
        existing = _ENGINES.get(database_url)
        if existing is not None:
            return existing
        connect_args = (
            {"check_same_thread": False, "timeout": 30} if database_url.startswith("sqlite") else {}
        )
        engine = create_engine(
            database_url,
            future=True,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        if database_url.startswith("sqlite"):

            @event.listens_for(engine, "connect")
            def _sqlite_pragmas(dbapi_connection: object, _record: object) -> None:
                cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.close()

        _ENGINES[database_url] = engine
        return engine


def dispose_engine(database_url: str) -> None:
    with _ENGINE_LOCK:
        engine = _ENGINES.pop(database_url, None)
    if engine is not None:
        engine.dispose()


def dispose_all_engines() -> None:
    with _ENGINE_LOCK:
        engines = list(_ENGINES.values())
        _ENGINES.clear()
    for engine in engines:
        engine.dispose()


def create_schema(database_url: str) -> None:
    Base.metadata.create_all(get_engine(database_url))


def upgrade_schema(database_url: str) -> None:
    """Apply repository migrations to exactly the resolved database URL."""

    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")


@contextmanager
def session_scope(database_url: str) -> Iterator[Session]:
    factory = sessionmaker(bind=get_engine(database_url), expire_on_commit=False, class_=Session)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

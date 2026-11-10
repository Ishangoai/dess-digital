import importlib
import pkgutil
from collections.abc import Iterator
from typing import Any

from sqlalchemy import JSON, Engine, create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

# JSONB on Postgres, plain JSON elsewhere (SQLite in tests / local dev).
JSONType = JSON().with_variant(JSONB(), "postgresql")


def enable_sqlite_foreign_keys(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_connection: Any, _record: Any) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        # Local dev fallback, e.g. DATABASE_URL=sqlite:///./data/dev.db
        sqlite_engine = create_engine(url, connect_args={"check_same_thread": False})
        enable_sqlite_foreign_keys(sqlite_engine)
        return sqlite_engine
    return create_engine(url, pool_pre_ping=True)


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    with SessionLocal() as session:
        yield session


def create_tables(bind: Engine | None = None) -> None:
    """Create any missing tables for every model in app.models (no migrations yet).

    Importing every module registers each model on Base.metadata. create_all never alters
    existing tables, so a column change during the POC means dropping the table.
    """
    import app.models

    for module in pkgutil.iter_modules(app.models.__path__):
        importlib.import_module(f"app.models.{module.name}")
    Base.metadata.create_all(bind or engine)

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import create_tables, enable_sqlite_foreign_keys
from app.minutes.profile_content import ProfileContent, load_profile_file

FIXTURES = Path(__file__).parent / "fixtures"
PROFILE_FIXTURE = FIXTURES / "minutes" / "profile.yaml"


@pytest.fixture
def engine() -> Iterator[Engine]:
    """Fresh in-memory SQLite per test; StaticPool shares it across TestClient threads."""
    eng = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    enable_sqlite_foreign_keys(eng)
    create_tables(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine)


@pytest.fixture
def db(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as session:
        yield session


@pytest.fixture
def profile_content() -> ProfileContent:
    return load_profile_file(PROFILE_FIXTURE)

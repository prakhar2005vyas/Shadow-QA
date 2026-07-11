"""
Database engine and session factory.

DATABASE_URL selects the backend. SQLite (local dev / tests) and PostgreSQL
(e.g. Neon in production, so runs survive Render restarts) are both driven by
the same code — the only differences are the driver-specific connect args and
the URL scheme, both normalized here so routes and models stay DB-agnostic.
"""

from sqlmodel import SQLModel, Session, create_engine

from .config import settings


def _normalized_url(url: str) -> str:
    """
    Pin the psycopg (v3) driver for Postgres URLs. Neon and Render hand out
    connection strings starting with `postgres://` or `postgresql://`, which
    SQLAlchemy would otherwise route to psycopg2 (not installed) or reject. We
    rewrite the scheme to `postgresql+psycopg://` to match requirements.txt.
    SQLite (and anything else) is passed through unchanged.
    """
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


_url = _normalized_url(settings.database_url)
_is_sqlite = _url.startswith("sqlite")

if _is_sqlite:
    # check_same_thread is a SQLite-only arg (FastAPI serves requests across a
    # thread pool); passing it to Postgres would raise a TypeError.
    engine = create_engine(
        _url,
        echo=False,
        connect_args={"check_same_thread": False},
    )
else:
    # pool_pre_ping recycles connections Neon has closed while idle, so they
    # don't surface as errors on the next request. prepare_threshold=None
    # disables psycopg's auto-prepared statements, which keeps this compatible
    # with Neon's pooled (PgBouncer) endpoint as well as the direct one.
    engine = create_engine(
        _url,
        echo=False,
        pool_pre_ping=True,
        connect_args={"prepare_threshold": None},
    )


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    """FastAPI dependency: yields a database session."""
    with Session(engine) as session:
        yield session

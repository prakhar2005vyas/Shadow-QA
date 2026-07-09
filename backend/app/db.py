"""
Database engine and session factory.
"""

from sqlmodel import SQLModel, Session, create_engine

from .config import settings

engine = create_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False},
)


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    """FastAPI dependency: yields a database session."""
    with Session(engine) as session:
        yield session

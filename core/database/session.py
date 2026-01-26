"""
Database session management
"""

import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from contextlib import contextmanager

from .models import Base

# Database configuration (env: DATABASE_URL)
# Default to PostgreSQL (shared with Temporal) or SQLite for local dev
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/artifacts.db")

# Create data dir for SQLite if needed
if DATABASE_URL.startswith("sqlite"):
    db_path = DATABASE_URL.replace("sqlite:///", "")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

# Create engine
# Use StaticPool for SQLite to avoid threading issues
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False  # Set to True for SQL debugging
    )
else:
    engine = create_engine(DATABASE_URL, echo=False)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Initialize database tables"""
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_session() -> Session:
    """
    Get database session with automatic cleanup

    Usage:
        with get_session() as session:
            chain = session.query(Chain).first()
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session_direct() -> Session:
    """
    Get database session without context manager (for dependency injection)

    Note: Caller is responsible for closing the session
    """
    return SessionLocal()

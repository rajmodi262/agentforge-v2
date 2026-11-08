"""AgentForge AI — Database Setup (SQLAlchemy)

Production-grade:
- PostgreSQL primary with SQLite fallback
- WAL mode for SQLite concurrency
- Soft-delete query helpers
- Session factory injectable for testing
"""

import os
import logging
from typing import Optional
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _get_engine():
    """Create engine — tries PostgreSQL first, falls back to SQLite."""
    db_url = settings.database_url

    # Empty DATABASE_URL → SQLite fallback (documented dev convenience)
    if not db_url or not db_url.strip():
        sqlite_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "agentforge_dev.db")
        db_url = f"sqlite:///{sqlite_path}"
        logger.info(f"No DATABASE_URL set — using SQLite: {sqlite_path}")

    # If PostgreSQL, try connecting; fall back to SQLite if unavailable
    if db_url.startswith("postgresql"):
        try:
            test_engine = create_engine(db_url, pool_pre_ping=True)
            with test_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                conn.commit()
            logger.info("Connected to PostgreSQL")
            return create_engine(db_url, pool_pre_ping=True, pool_size=5, max_overflow=10)
        except Exception as e:
            # Fall back to SQLite
            sqlite_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "agentforge_dev.db")
            db_url = f"sqlite:///{sqlite_path}"
            logger.warning(f"PostgreSQL unavailable ({e.__class__.__name__}) — using SQLite: {sqlite_path}")

    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False} if "sqlite" in db_url else {},
    )

    # Enable WAL mode + foreign keys in SQLite for better concurrency & integrity
    if "sqlite" in db_url:
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


engine = _get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def init_db():
    """Create all tables (for dev/SQLite — use Alembic for production)."""
    from app.models.db_models import User, Project, WorkflowRun, AgentTask, AgentMessage, ProjectReport  # noqa
    import app.phantom.models  # noqa: F401 — Phantom Hunter tables
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created/verified")


def get_db():
    """Dependency: yields a DB session, auto-closes after request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session_factory() -> sessionmaker:
    """Return the session factory for use in background tasks.
    
    This allows the orchestrator and other background services
    to create their own sessions without importing SessionLocal directly,
    making them testable with dependency injection.
    """
    return SessionLocal


# ─────────────────────────────── Query Helpers ───────────────────────────────


def soft_delete(db: Session, instance) -> None:
    """Soft-delete a model instance (sets is_deleted=True, records timestamp).
    
    Usage:
        project = db.query(Project).get(id)
        soft_delete(db, project)
        db.commit()
    """
    from datetime import datetime, timezone
    instance.is_deleted = True
    instance.deleted_at = datetime.now(timezone.utc)


def active_query(db: Session, model):
    """Return a query pre-filtered to exclude soft-deleted records.
    
    Usage:
        projects = active_query(db, Project).filter(Project.user_id == uid).all()
    """
    if hasattr(model, "is_deleted"):
        return db.query(model).filter(model.is_deleted == False)  # noqa: E712
    return db.query(model)

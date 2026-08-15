"""Database engine/session management for PsychAI.

Single entry point: ``get_engine`` / ``get_session_factory``.

The default DB path is ``data/psychai.db`` relative to the project root.
SQLite PRAGMAs are set for safety (foreign keys, WAL mode).
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from db.models import Base

# Project root = parent of the db/ package.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB_DIR = _PROJECT_ROOT / "data"
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "psychai.db"

SCHEMA_VERSION = 4


def get_db_path(override: str | None = None) -> Path:
    """Return the resolved DB file path, creating the parent directory."""
    path = Path(override) if override else _DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_engine(db_path: str | os.PathLike | None = None, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine for SQLite.

    ``db_path`` can be a full path or None for the default ``data/psychai.db``.
    """
    if db_path is None:
        resolved = get_db_path()
    else:
        resolved = Path(db_path)
        resolved.parent.mkdir(parents=True, exist_ok=True)

    # For raw-path use forward-slash form for cross-platform URL.
    url = f"sqlite:///{resolved.as_posix()}"
    engine = create_engine(url, echo=echo, future=True)

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


def get_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db(engine: Engine) -> None:
    """Create tables if absent and reconcile the schema version.

    ``create_all`` only adds missing tables; it never alters existing FK policies.
    We then reconcile the schema version honestly: if the on-disk FK policy already
    matches v2 we just record the version marker; if it is an incompatible older
    schema we raise (NEVER auto-drop or overwrite user data).
    """
    Base.metadata.create_all(engine)
    from db.migrations import migrate

    migrate(engine)  # raises SchemaMigrationError on incompatible old schema


def _ensure_schema_version(engine: Engine) -> None:
    """DEPRECATED: schema version is now reconciled by db.migrations.migrate().

    Kept only as a no-op guard in case any caller still references it; the real
    logic lives in ``migrate``. Will be removed once callers are confirmed gone.
    """
    from db.migrations import migrate

    migrate(engine)


__all__ = [
    "get_db_path",
    "get_engine",
    "get_session_factory",
    "init_db",
    "SCHEMA_VERSION",
]

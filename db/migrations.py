"""Versioned schema management (simple, replaces Alembic for MVP).

Why not Alembic:
    For a single-user local SQLite with one initial schema, Alembic's
    migration graph, env.py, and version-files directory add ceremony
    without value.  This module tracks ``schema_version`` and can run
    forward migrations when the schema evolves.  When PostgreSQL becomes
    the target, Alembic can be introduced and the initial migration can
    mirror ``Base.metadata`` as of SCHEMA_VERSION.
"""

from __future__ import annotations

from sqlalchemy.engine import Engine

from db.database import SCHEMA_VERSION


def get_schema_version(engine: Engine) -> int:
    """Return the current schema version, or 0 if table is empty/missing."""
    from sqlalchemy import text, inspect

    inspector = inspect(engine)
    if "schema_version" not in inspector.get_table_names():
        return 0
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT MAX(version) AS v FROM schema_version")
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else 0


def migrate(engine: Engine) -> int:
    """Run pending forward migrations. Returns the new schema version."""
    current = get_schema_version(engine)
    # Future migrations: if current < 2: _migrate_v2(engine); ...
    # For now only SCHEMA_VERSION == 1 exists.
    return SCHEMA_VERSION


__all__ = ["get_schema_version", "migrate", "SCHEMA_VERSION"]

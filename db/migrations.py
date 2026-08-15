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


# Target FK ON DELETE policy for schema v2 (the approved B1 deletion policy).
# Keyed by (child_table, referenced_table, child_column) -> expected on_delete.
_EXPECTED_FK_POLICY: dict[tuple[str, str, str], str] = {
    ("sessions", "clients", "client_id"): "RESTRICT",
    ("audio_tracks", "sessions", "session_id"): "CASCADE",
    ("transcript_segments", "sessions", "session_id"): "CASCADE",
    ("transcript_segments", "audio_tracks", "audio_track_id"): "SET NULL",
    ("dialogue_utterances", "sessions", "session_id"): "CASCADE",
    ("analyses", "sessions", "session_id"): "CASCADE",
    ("dialogue_utterance_segments", "dialogue_utterances", "utterance_id"): "CASCADE",
    ("dialogue_utterance_segments", "transcript_segments", "transcript_segment_id"): "NO ACTION",
}


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


def is_schema_compatible(engine: Engine) -> bool:
    """Inspect the ON-DISK FK policies and report whether they match v2.

    The ``schema_version`` row alone is NOT trustworthy: ``init_db`` would
    otherwise silently stamp v2 onto a pre-existing v1 DB whose FOREIGN KEY
    constraints were created as NO ACTION. We read the live ``PRAGMA
    foreign_key_list`` so an old DB is never mislabelled as current.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    required = {t for t, _, _ in _EXPECTED_FK_POLICY}
    if not required.issubset(existing):
        return False  # tables not even present -> not our schema

    with engine.connect() as conn:
        for (tbl, ref, col), want in _EXPECTED_FK_POLICY.items():
            try:
                rows = (
                    conn.execute(text(f"PRAGMA foreign_key_list({tbl})"))
                    .mappings()
                    .all()
                )
            except Exception:
                return False
            fk = {f"{r['table']}.{r['from']}": (r["on_delete"] or "NO ACTION") for r in rows}
            if fk.get(f"{ref}.{col}") != want:
                return False
    return True


class SchemaMigrationError(RuntimeError):
    """Raised when an in-place schema migration is not possible (e.g. SQLite FK ALTER)."""


def migrate(engine: Engine) -> int:
    """Apply pending forward migrations. Returns the new schema version.

    NOTE: SQLite cannot ALTER existing FOREIGN KEY constraints in place, and we
    must NOT auto-destroy the user's database (RAW data). The v1 -> v2 change only
    adds FK ON DELETE policies. Existing v1 databases therefore cannot be migrated
    automatically — the caller must back up and recreate the DB manually (e.g.
    ``python -m db.cli init`` after moving the old file aside). This function never
    drops or recreates tables.

    The Sprint 16 addition of ``clients.client_number`` (a new nullable column on an
    existing table) is applied here with a safe ADD COLUMN when missing — SQLite
    permits this without table rebuild, and existing rows simply get NULL.

    Raises ``SchemaMigrationError`` if the on-disk schema is an incompatible older
    version that cannot be migrated in place.
    """
    # Sprint 16: ensure the new client_number column exists on existing tables.
    _ensure_column(engine, "clients", "client_number",
                   "ALTER TABLE clients ADD COLUMN client_number INTEGER")

    # Sprint 17: ensure the analysis provenance columns exist on existing DBs.
    # Safe ADD COLUMN (no table rebuild, existing rows get NULL). The
    # existing v3 FK policy (analyses->sessions CASCADE) is untouched, so
    # is_schema_compatible() stays True and migrate() only fills columns
    # + stamps the version marker — never drops or rewrites user data.
    _ensure_column(engine, "analyses", "provider",
                   "ALTER TABLE analyses ADD COLUMN provider VARCHAR(64)")
    _ensure_column(engine, "analyses", "prompt_version",
                   "ALTER TABLE analyses ADD COLUMN prompt_version VARCHAR(32)")
    _ensure_column(engine, "analyses", "text",
                   "ALTER TABLE analyses ADD COLUMN text TEXT")

    if is_schema_compatible(engine):
        # Already has the correct FK policy; bring the version marker up to date
        # only if it is missing/lower (does NOT touch data or constraints).
        current = get_schema_version(engine)
        if current < SCHEMA_VERSION:
            from sqlalchemy import text
            from datetime import datetime, timezone

            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO schema_version (version, applied_at, description) "
                        "VALUES (:v, :t, :d)"
                    ),
                    {
                        "v": SCHEMA_VERSION,
                        "t": datetime.now(timezone.utc),
                        "d": "Sprint 17: add analyses.provider/prompt_version/text "
                             "(analysis provenance + text)",
                    },
                )
        return SCHEMA_VERSION

    current = get_schema_version(engine)
    raise SchemaMigrationError(
        f"Incompatible schema detected (DB reports version {current}, "
        f"expected FK policy for v{SCHEMA_VERSION}). SQLite cannot ALTER FOREIGN KEY "
        "ON DELETE policies in place, so this database cannot be migrated automatically. "
        "To apply the new deletion policy WITHOUT losing data:\n"
        "  1) back up data/psychai.db (e.g. copy it to data/psychai.db.v1.bak);\n"
        "  2) move the old file aside or delete it;\n"
        "  3) run `python -m db.cli init` to create a fresh v2 DB;\n"
        "  4) re-import experiments (`python -m db.cli import <dir>`).\n"
        "No user data is deleted by this tool."
    )


def _ensure_column(engine: Engine, table: str, column: str, ddl: str) -> None:
    """Add ``column`` to ``table`` if it is absent (safe SQLite ADD COLUMN)."""
    from sqlalchemy import inspect, text

    cols = {c["name"] for c in inspect(engine).get_columns(table)}
    if column in cols:
        return
    with engine.begin() as conn:
        conn.execute(text(ddl))


__all__ = [
    "get_schema_version",
    "is_schema_compatible",
    "migrate",
    "SCHEMA_VERSION",
    "SchemaMigrationError",
]

"""Persistence port implementation for live recording sessions.

The Session drives recording and needs three things from persistence:
create a session row, add audio tracks, finalize the session. That narrow
port is implemented here — the ONLY place in this path that touches
SQLAlchemy — on top of the existing repositories. No new persistence
layer, no schema change, deletion policy and migrations untouched.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from db.database import get_engine, get_session_factory, init_db
from db.repositories import AudioTrackRepository, SessionRepository


class SessionStore:
    """SQLite-backed store for live sessions (Session <-> persistence port)."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._engine = get_engine(db_path)
        init_db(self._engine)
        self._factory = get_session_factory(self._engine)

    # ------------------------------------------------------------------ #
    # Port: three methods, nothing else
    # ------------------------------------------------------------------ #
    def create_session(self, *, started_at: datetime) -> int:
        """Insert a session row in the ``recording`` state; return its id."""
        with self._factory() as db:
            row = SessionRepository(db).create(
                source_session_id=uuid.uuid4().hex[:12],
                source="live",
                status="recording",
                started_at=_naive(started_at),
            )
            db.commit()
            return int(row.id)

    def add_audio_track(
        self,
        *,
        session_id: int,
        source: str,
        file_path: Optional[str],
        duration: Optional[float],
        sample_rate: Optional[int],
        channels: Optional[int],
        metadata: Optional[dict] = None,
    ) -> int:
        with self._factory() as db:
            row = AudioTrackRepository(db).create(
                session_id=session_id,
                source=source,
                file_path=file_path,
                duration=duration,
                sample_rate=sample_rate,
                channels=channels,
                metadata=metadata,
            )
            db.commit()
            return int(row.id)

    def finalize_session(
        self,
        *,
        session_id: int,
        ended_at: datetime,
        status: str,
    ) -> None:
        with self._factory() as db:
            row = SessionRepository(db).get(session_id)
            if row is None:
                return
            row.ended_at = _naive(ended_at)
            row.status = status
            db.commit()


def _naive(value: Optional[datetime]) -> Optional[datetime]:
    """Drop tzinfo: the existing schema stores naive UTC datetimes."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.replace(tzinfo=None)


__all__ = ["SessionStore"]

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
from db.models import DialogueUtterance, TranscriptSegment
from db.repositories import (
    AudioTrackRepository,
    DialogueRepository,
    SessionRepository,
    TranscriptRepository,
)

# Speaker mapping shared with the experiment importer: which role each
# audio source represents in the RAW transcript. Keep in one place.
SPEAKER_MAP = {
    "microphone": "psychologist",
    "loopback": "client",
}


class SessionStore:
    """SQLite-backed store for live sessions (Session <-> persistence port)."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._engine = get_engine(db_path)
        init_db(self._engine)
        self._factory = get_session_factory(self._engine)

    # ------------------------------------------------------------------ #
    # Port: recording lifecycle (three methods) + post-stop transcription
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

    # ------------------------------------------------------------------ #
    # Port: post-stop transcription (read tracks, write RAW segments)
    # ------------------------------------------------------------------ #
    def get_tracks(self, session_id: int) -> list[dict]:
        """Return the recorded tracks needed for transcription.

        Each dict: id, source, file_path, sample_rate, channels, duration.
        SQLAlchemy objects are NOT returned, so the ORM layer stays behind
        this port (Session never sees it).
        """
        with self._factory() as db:
            rows = AudioTrackRepository(db).get_by_session(session_id)
            return [
                {
                    "id": int(t.id),
                    "source": t.source,
                    "file_path": t.file_path,
                    "sample_rate": t.sample_rate,
                    "channels": t.channels,
                    "duration": t.duration,
                }
                for t in rows
            ]

    def get_session_status(self, session_id: int) -> Optional[str]:
        with self._factory() as db:
            row = SessionRepository(db).get(session_id)
            return row.status if row is not None else None

    def set_session_status(self, session_id: int, status: str) -> None:
        with self._factory() as db:
            row = SessionRepository(db).get(session_id)
            if row is None:
                return
            row.status = status
            db.commit()

    def add_transcript_segments(
        self,
        *,
        session_id: int,
        audio_track_id: int,
        source: str,
        model: Optional[str],
        segments: list[dict],
    ) -> int:
        """Persist RAW transcript segments for one audio track.

        Idempotent per track: if segments already exist for the track,
        they are left untouched and a ``skipped`` count of 0 is returned.
        ``segments`` is a list of {"start", "end", "text", "confidence"}.
        Returns the number of segments actually written.
        """
        speaker = SPEAKER_MAP.get(source, source)
        with self._factory() as db:
            repo = TranscriptRepository(db)
            existing = repo.get_by_audio_track(audio_track_id)
            if existing:
                return 0
            objs = [
                TranscriptSegment(
                    session_id=session_id,
                    audio_track_id=audio_track_id,
                    speaker=speaker,
                    start=float(s["start"]),
                    end=float(s["end"]),
                    text=s["text"],
                    confidence=s.get("confidence"),
                    model=model,
                )
                for s in segments
            ]
            if objs:
                repo.bulk_create(objs)
            db.commit()
            return len(objs)

    def get_transcript_segments(self, session_id: int) -> list[dict]:
        """Return RAW transcript segments of a session as plain dicts.

        SQLAlchemy objects are NOT returned, so the ORM layer stays behind
        this port (Session never sees it). Each dict: id, audio_track_id,
        source, speaker, start, end, text, confidence. ``source`` is the
        AudioTrack source ("microphone"/"loopback"); ``speaker`` is the
        role already assigned by SPEAKER_MAP.
        """
        with self._factory() as db:
            tracks = {int(t.id): t.source for t in AudioTrackRepository(db).get_by_session(session_id)}
            segs = TranscriptRepository(db).get_by_session(session_id)
            return [
                {
                    "id": int(s.id),
                    "audio_track_id": int(s.audio_track_id) if s.audio_track_id is not None else None,
                    "source": tracks.get(int(s.audio_track_id)) if s.audio_track_id is not None else None,
                    "speaker": s.speaker,
                    "start": float(s.start),
                    "end": float(s.end) if s.end is not None else None,
                    "text": s.text,
                    "confidence": s.confidence,
                }
                for s in segs
            ]

    def add_dialogue_utterances(
        self,
        *,
        session_id: int,
        utterances: list[dict],
    ) -> int:
        """Persist built DialogueUtterances for a session.

        Idempotent per session: existing utterances are deleted first, so a
        repeat call rebuilds the derived layer without duplicates. RAW
        transcript_segments are untouched (DB-level ON DELETE CASCADE clears
        only the junction rows).

        ``utterances`` is a list of {"speaker", "start", "text", "source",
        "end", "confidence", "original_segment_id"}. Returns the number
        written.
        """
        with self._factory() as db:
            repo = DialogueRepository(db)
            repo.delete_by_session(session_id)  # clear derived layer only
            written = 0
            for u in utterances:
                repo.create(
                    session_id=session_id,
                    speaker=u["speaker"],
                    start=float(u["start"]),
                    end=float(u["end"]) if u.get("end") is not None else None,
                    text=u["text"],
                    source=u.get("source"),
                    confidence=u.get("confidence"),
                    normalization_version="12.0",
                    original_segment_ids=(
                        [u["original_segment_id"]] if u.get("original_segment_id") is not None else None
                    ),
                )
                written += 1
            db.commit()
            return written


def _naive(value: Optional[datetime]) -> Optional[datetime]:
    """Drop tzinfo: the existing schema stores naive UTC datetimes."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.replace(tzinfo=None)


__all__ = ["SessionStore"]

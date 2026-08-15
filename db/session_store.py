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
    AnalysisRepository,
    AudioTrackRepository,
    ClientRepository,
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
    def create_session(self, *, started_at: datetime, client_id: Optional[int] = None) -> int:
        """Insert a session row in the ``recording`` state; return its id."""
        with self._factory() as db:
            row = SessionRepository(db).create(
                client_id=client_id,
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

    # ------------------------------------------------------------------ #
    # Port: client layer (grouping sessions by client)
    # ------------------------------------------------------------------ #
    def create_client(self, name: str) -> object:
        """Create a client with a stable global sequential number; return ORM obj."""
        with self._factory() as db:
            client = ClientRepository(db).create_client(name)
            db.commit()
            return client

    def list_clients(self) -> list[dict]:
        """Return all clients as plain dicts (no ORM objects leak out).

        Each dict: id, display_name, client_number. Ordered by client_number
        (NULLs last). The UI renders "Тест 001" from display_name +
        client_number.
        """
        with self._factory() as db:
            rows = ClientRepository(db).list_clients()
            return [
                {
                    "id": int(c.id),
                    "display_name": c.display_name,
                    "client_number": c.client_number,
                }
                for c in rows
            ]

    def list_client_sessions(self, client_id: int) -> list[dict]:
        """Return sessions of one client as plain dicts (excludes others)."""
        with self._factory() as db:
            rows = SessionRepository(db).list_all()
            out = []
            for r in rows:
                if r.client_id is None or int(r.client_id) != int(client_id):
                    continue
                out.append(
                    {
                        "id": int(r.id),
                        "client_id": int(r.client_id) if r.client_id is not None else None,
                        "source_session_id": r.source_session_id,
                        "source": r.source,
                        "status": r.status,
                        "started_at": _naive(r.started_at),
                        "ended_at": _naive(r.ended_at),
                    }
                )
            return out

    # ------------------------------------------------------------------ #
    # Port: session viewer (read-only listing of completed sessions)
    # ------------------------------------------------------------------ #
    def list_sessions(self) -> list[dict]:
        """Return all sessions as plain dicts (no ORM objects leak out).

        Each dict: id, source_session_id, source, status, started_at,
        ended_at, client_id, client_name, client_number. Ordered by id. The
        UI renders these without ever touching SQLAlchemy. Sessions with
        client_id NULL surface under a "Без клиента" group in the viewer.
        """
        with self._factory() as db:
            rows = SessionRepository(db).list_all()
            return [
                {
                    "id": int(r.id),
                    "source_session_id": r.source_session_id,
                    "source": r.source,
                    "status": r.status,
                    "started_at": _naive(r.started_at),
                    "ended_at": _naive(r.ended_at),
                    "client_id": int(r.client_id) if r.client_id is not None else None,
                    "client_name": r.client.display_name if r.client is not None else None,
                    "client_number": r.client.client_number if r.client is not None else None,
                }
                for r in rows
            ]

    def get_session(self, session_id: int) -> Optional[dict]:
        """Return one session as a plain dict, or None if absent.

        Includes a lightweight ``audio_tracks`` summary (source, duration)
        for the detail view. No ORM objects escape the port.
        """
        with self._factory() as db:
            row = SessionRepository(db).get(session_id)
            if row is None:
                return None
            tracks = AudioTrackRepository(db).get_by_session(session_id)
            return {
                "id": int(row.id),
                "source_session_id": row.source_session_id,
                "source": row.source,
                "status": row.status,
                "started_at": _naive(row.started_at),
                "ended_at": _naive(row.ended_at),
                "client_id": int(row.client_id) if row.client_id is not None else None,
                "client_name": row.client.display_name if row.client is not None else None,
                "client_number": row.client.client_number if row.client is not None else None,
                "audio_tracks": [
                    {
                        "source": t.source,
                        "duration": float(t.duration) if t.duration is not None else None,
                    }
                    for t in tracks
                ],
            }

    def get_dialogue(self, session_id: int) -> list[dict]:
        """Return the built Dialogue of a session as plain dicts.

        Each utterance: id, speaker, start, end, text, source, confidence.
        ``start``/``end`` are TRACK-RELATIVE (verbatim from TranscriptSegment,
        NOT a cross-track session timeline — see Sprint 12 R1). Ordered by id.
        """
        with self._factory() as db:
            rows = DialogueRepository(db).get_by_session(session_id)
            return [
                {
                    "id": int(u.id),
                    "speaker": u.speaker,
                    "start": float(u.start),
                    "end": float(u.end) if u.end is not None else None,
                    "text": u.text,
                    "source": u.source,
                    "confidence": u.confidence,
                }
                for u in rows
            ]

    # ------------------------------------------------------------------ #
    # Port: LLM analysis (Sprint 17). Write/read the supervisor Analysis.
    # ------------------------------------------------------------------ #
    def save_analysis(
        self,
        *,
        session_id: int,
        provider: str,
        model: str,
        prompt_version: str,
        text: str,
        analysis_type: str = "supervisor",
        metadata: Optional[dict] = None,
    ) -> int:
        """Persist one Analysis result and return its new row id.

        A repeat analysis for the same session creates a NEW row (history is
        preserved). ``get_analysis`` returns the latest. No ORM objects leak
        out; the API key is never stored here.
        """
        with self._factory() as db:
            row = AnalysisRepository(db).create(
                session_id=session_id,
                type=analysis_type,
                provider=provider,
                model=model,
                prompt_version=prompt_version,
                status="completed",
                text=text,
                metadata=metadata,
            )
            db.commit()
            return int(row.id)

    def get_analysis(self, session_id: int) -> Optional[dict]:
        """Return the LATEST Analysis of a session as a plain dict, or None.

        Dict keys: id, session_id, provider, model, prompt_version, text,
        created_at. History is preserved in the table; this returns only the
        most recent. No ORM objects escape the port.
        """
        with self._factory() as db:
            row = AnalysisRepository(db).latest_by_session(session_id)
            if row is None:
                return None
            return {
                "id": int(row.id),
                "session_id": int(row.session_id),
                "provider": row.provider,
                "model": row.model,
                "prompt_version": row.prompt_version,
                "text": row.text,
                "created_at": _naive(row.created_at),
            }


def _naive(value: Optional[datetime]) -> Optional[datetime]:
    """Drop tzinfo: the existing schema stores naive UTC datetimes."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.replace(tzinfo=None)


__all__ = ["SessionStore"]

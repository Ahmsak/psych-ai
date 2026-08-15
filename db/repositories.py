"""Repository layer — the only place that touches SQLAlchemy sessions.

Business logic (importer, CLI, future services) calls these repositories.
No raw SQL leaks outside this module.

Repositories are intentionally thin: create/get/list per entity.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import (
    Analysis,
    AudioTrack,
    Client,
    DialogueUtterance,
    Session as SessionModel,
    TranscriptSegment,
    dialogue_utterance_segments,
)


# ── helpers ────────────────────────────────────────────────────────────


def _dump(obj: Any) -> Optional[str]:
    """Serialize a dict/list to JSON string, or None if falsy."""
    if obj is None:
        return None
    return json.dumps(obj, ensure_ascii=False, default=str)


def _load(s: Optional[str]) -> Any:
    if not s:
        return None
    return json.loads(s)


# ── Client ─────────────────────────────────────────────────────────────


class ClientRepository:
    def __init__(self, session: Session):
        self._s = session

    def create(
        self,
        display_name: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Client:
        client = Client(display_name=display_name, notes=notes)
        self._s.add(client)
        self._s.flush()
        return client

    def create_client(self, name: str) -> Client:
        """Create a client with a stable GLOBAL sequential number.

        ``display_name`` stores the base name only (e.g. "Тест"); the visual
        id "Тест 001" is rendered in the UI from ``client_number``. The number
        is global (not per-name) and never reused, even if a client is later
        deleted. Name is NOT a unique key — two clients may share a base name
        with different numbers.
        """
        name = (name or "").strip() or None
        # Global sequence: max existing client_number + 1 (starts at 1).
        from sqlalchemy import func, select as _select
        max_no = self._s.execute(
            _select(func.max(Client.client_number))
        ).scalar()
        next_no = 1 if max_no is None else int(max_no) + 1
        client = Client(display_name=name, client_number=next_no)
        self._s.add(client)
        self._s.flush()
        return client

    def list_clients(self) -> list[Client]:
        """All clients ordered by stable client_number (then id)."""
        from sqlalchemy import select as _select
        return list(
            self._s.execute(
                _select(Client).order_by(
                    Client.client_number.is_(None),
                    Client.client_number,
                    Client.id,
                )
            ).scalars()
        )

    def get(self, client_id: int) -> Optional[Client]:
        return self._s.get(Client, client_id)

    def list_all(self) -> list[Client]:
        return list(self._s.execute(select(Client).order_by(Client.id)).scalars())


# ── Session ────────────────────────────────────────────────────────────


class SessionRepository:
    def __init__(self, session: Session):
        self._s = session

    def create(
        self,
        *,
        client_id: Optional[int] = None,
        source_session_id: Optional[str] = None,
        source: str = "experiment",
        status: str = "imported",
        started_at=None,
        ended_at=None,
        metadata: Optional[dict] = None,
    ) -> SessionModel:
        sess = SessionModel(
            client_id=client_id,
            source_session_id=source_session_id,
            source=source,
            status=status,
            started_at=started_at,
            ended_at=ended_at,
            metadata_json=_dump(metadata),
        )
        self._s.add(sess)
        self._s.flush()
        return sess

    def get(self, session_id: int) -> Optional[SessionModel]:
        return self._s.get(SessionModel, session_id)

    def get_by_source_id(self, source_session_id: str) -> Optional[SessionModel]:
        stmt = select(SessionModel).where(
            SessionModel.source_session_id == source_session_id
        )
        return self._s.execute(stmt).scalar_one_or_none()

    def list_all(self) -> list[SessionModel]:
        return list(self._s.execute(select(SessionModel).order_by(SessionModel.id)).scalars())


# ── AudioTrack ─────────────────────────────────────────────────────────


class AudioTrackRepository:
    def __init__(self, session: Session):
        self._s = session

    def create(
        self,
        *,
        session_id: int,
        source: str,
        file_path: Optional[str] = None,
        duration: Optional[float] = None,
        sample_rate: Optional[int] = None,
        channels: Optional[int] = None,
        metadata: Optional[dict] = None,
    ) -> AudioTrack:
        track = AudioTrack(
            session_id=session_id,
            source=source,
            file_path=file_path,
            duration=duration,
            sample_rate=sample_rate,
            channels=channels,
            metadata_json=_dump(metadata),
        )
        self._s.add(track)
        self._s.flush()
        return track

    def get_by_session(self, session_id: int) -> list[AudioTrack]:
        stmt = select(AudioTrack).where(AudioTrack.session_id == session_id)
        return list(self._s.execute(stmt).scalars())


# ── TranscriptSegment ──────────────────────────────────────────────────


class TranscriptRepository:
    def __init__(self, session: Session):
        self._s = session

    def create(
        self,
        *,
        session_id: int,
        audio_track_id: Optional[int] = None,
        speaker: Optional[str] = None,
        start: float,
        end: float,
        text: str,
        confidence: Optional[float] = None,
        model: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> TranscriptSegment:
        seg = TranscriptSegment(
            session_id=session_id,
            audio_track_id=audio_track_id,
            speaker=speaker,
            start=start,
            end=end,
            text=text,
            confidence=confidence,
            model=model,
            metadata_json=_dump(metadata),
        )
        self._s.add(seg)
        self._s.flush()
        return seg

    def bulk_create(self, segments: list[TranscriptSegment]) -> None:
        self._s.add_all(segments)
        self._s.flush()

    def get_by_session(self, session_id: int) -> list[TranscriptSegment]:
        stmt = (
            select(TranscriptSegment)
            .where(TranscriptSegment.session_id == session_id)
            .order_by(TranscriptSegment.id)
        )
        return list(self._s.execute(stmt).scalars())

    def get_by_audio_track(self, audio_track_id: int) -> list[TranscriptSegment]:
        stmt = (
            select(TranscriptSegment)
            .where(TranscriptSegment.audio_track_id == audio_track_id)
            .order_by(TranscriptSegment.id)
        )
        return list(self._s.execute(stmt).scalars())


# ── DialogueUtterance ──────────────────────────────────────────────────


class DialogueRepository:
    def __init__(self, session: Session):
        self._s = session

    def create(
        self,
        *,
        session_id: int,
        speaker: str,
        start: float,
        end: Optional[float] = None,
        text: str,
        source: Optional[str] = None,
        confidence: Optional[float] = None,
        normalization_version: Optional[str] = None,
        metadata: Optional[dict] = None,
        original_segment_ids: Optional[list[int]] = None,
    ) -> DialogueUtterance:
        utt = DialogueUtterance(
            session_id=session_id,
            speaker=speaker,
            start=start,
            end=end,
            text=text,
            source=source,
            confidence=confidence,
            normalization_version=normalization_version,
            metadata_json=_dump(metadata),
        )
        self._s.add(utt)
        self._s.flush()

        # Link original transcript segments (m2m)
        if original_segment_ids:
            for seq, seg_id in enumerate(original_segment_ids):
                self._s.execute(
                    dialogue_utterance_segments.insert().values(
                        utterance_id=utt.id,
                        transcript_segment_id=seg_id,
                        sequence=seq,
                    )
                )
            self._s.flush()

        return utt

    def get_by_session(self, session_id: int) -> list[DialogueUtterance]:
        stmt = (
            select(DialogueUtterance)
            .where(DialogueUtterance.session_id == session_id)
            .order_by(DialogueUtterance.id)
        )
        return list(self._s.execute(stmt).scalars())

    def delete_by_session(self, session_id: int) -> int:
        """Delete all DialogueUtterances of a session (DERIVED layer only).

        DB-level ON DELETE CASCADE clears the junction rows
        (dialogue_utterance_segments); RAW transcript_segments are untouched.
        Returns the number of utterances deleted.
        """
        from sqlalchemy import delete

        n = (
            self._s.execute(
                delete(DialogueUtterance).where(DialogueUtterance.session_id == session_id)
            ).rowcount
        )
        self._s.flush()
        return n


# ── Analysis ───────────────────────────────────────────────────────────


class AnalysisRepository:
    def __init__(self, session: Session):
        self._s = session

    def create(
        self,
        *,
        session_id: int,
        type: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        prompt_version: Optional[str] = None,
        status: str = "pending",
        text: Optional[str] = None,
        result: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ) -> Analysis:
        a = Analysis(
            session_id=session_id,
            type=type,
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            status=status,
            text=text,
            result_json=_dump(result),
            metadata_json=_dump(metadata),
        )
        self._s.add(a)
        self._s.flush()
        return a

    def get_by_session(self, session_id: int) -> list[Analysis]:
        stmt = select(Analysis).where(Analysis.session_id == session_id)
        return list(self._s.execute(stmt).scalars())

    def latest_by_session(self, session_id: int) -> Optional[Analysis]:
        """The most recently created Analysis for a session, or None."""
        from sqlalchemy import desc

        stmt = (
            select(Analysis)
            .where(Analysis.session_id == session_id)
            .order_by(desc(Analysis.created_at), desc(Analysis.id))
            .limit(1)
        )
        return self._s.execute(stmt).scalar_one_or_none()


__all__ = [
    "ClientRepository",
    "SessionRepository",
    "AudioTrackRepository",
    "TranscriptRepository",
    "DialogueRepository",
    "AnalysisRepository",
]

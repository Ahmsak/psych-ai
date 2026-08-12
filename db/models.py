"""SQLAlchemy ORM models for PsychAI persistence layer.

Six domain tables + one schema-versioning table.

Layering:
    RAW      : audio_tracks, transcript_segments
    DERIVED  : dialogue_utterances, dialogue_utterance_segments
    ANALYSIS : analyses

No business logic here — pure data shapes.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    DateTime,
    Table,
    Column,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Declarative base shared by all models."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── RAW layer ─────────────────────────────────────────────────────────


class Client(Base):
    """A person receiving psychological consultations."""

    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)
    display_name = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)

    sessions = relationship("Session", back_populates="client")

    def __repr__(self) -> str:
        return f"<Client id={self.id} name={self.display_name!r}>"


class Session(Base):
    """One therapeutic consultation session.

    ``source_session_id`` stores the original experiment hex ID (e.g.
    ``269048afff41``) for idempotent re-import.
    """

    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("source_session_id", name="uq_sessions_source_session_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    source_session_id = Column(String(64), nullable=True)
    source = Column(String(64), nullable=False, default="experiment")
    status = Column(String(32), nullable=False, default="imported")
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    metadata_json = Column(Text, nullable=True)  # JSON string

    client = relationship("Client", back_populates="sessions")
    audio_tracks = relationship(
        "AudioTrack", back_populates="session", cascade="all, delete-orphan"
    )
    transcript_segments = relationship(
        "TranscriptSegment", back_populates="session", cascade="all, delete-orphan"
    )
    dialogue_utterances = relationship(
        "DialogueUtterance", back_populates="session", cascade="all, delete-orphan"
    )
    analyses = relationship(
        "Analysis", back_populates="session", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Session id={self.id} source={self.source_session_id!r}>"


class AudioTrack(Base):
    """A physical audio file belonging to a session (path, not BLOB)."""

    __tablename__ = "audio_tracks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    source = Column(String(32), nullable=False)  # microphone | loopback | combined
    file_path = Column(Text, nullable=True)  # absolute or project-relative path
    duration = Column(Float, nullable=True)  # seconds
    sample_rate = Column(Integer, nullable=True)
    channels = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    metadata_json = Column(Text, nullable=True)

    session = relationship("Session", back_populates="audio_tracks")
    transcript_segments = relationship(
        "TranscriptSegment", back_populates="audio_track"
    )

    def __repr__(self) -> str:
        return f"<AudioTrack id={self.id} source={self.source!r}>"


class TranscriptSegment(Base):
    """RAW Whisper output — never modified by normalization."""

    __tablename__ = "transcript_segments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    audio_track_id = Column(Integer, ForeignKey("audio_tracks.id"), nullable=True)
    speaker = Column(String(32), nullable=True)  # psychologist | client
    start = Column(Float, nullable=False)  # seconds from session timeline start
    end = Column(Float, nullable=False)
    text = Column(Text, nullable=False)
    confidence = Column(Float, nullable=True)
    model = Column(String(64), nullable=True)  # whisper model name
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    metadata_json = Column(Text, nullable=True)

    session = relationship("Session", back_populates="transcript_segments")
    audio_track = relationship("AudioTrack", back_populates="transcript_segments")

    def __repr__(self) -> str:
        return f"<TranscriptSegment id={self.id} start={self.start} end={self.end}>"


# ── DERIVED layer ──────────────────────────────────────────────────────

# Association table: utterance ↔ original transcript segments (many-to-many)
dialogue_utterance_segments = Table(
    "dialogue_utterance_segments",
    Base.metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("utterance_id", Integer, ForeignKey("dialogue_utterances.id"), nullable=False),
    Column(
        "transcript_segment_id",
        Integer,
        ForeignKey("transcript_segments.id"),
        nullable=False,
    ),
    Column("sequence", Integer, nullable=False, default=0),
    UniqueConstraint(
        "utterance_id",
        "transcript_segment_id",
        name="uq_utt_seg_pair",
    ),
)


class DialogueUtterance(Base):
    """Normalized dialogue utterance (derived from transcript_segments)."""

    __tablename__ = "dialogue_utterances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    speaker = Column(String(32), nullable=False)
    start = Column(Float, nullable=False)
    end = Column(Float, nullable=True)
    text = Column(Text, nullable=False)
    source = Column(String(32), nullable=True)  # microphone | loopback
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    normalization_version = Column(String(32), nullable=True)
    metadata_json = Column(Text, nullable=True)

    session = relationship("Session", back_populates="dialogue_utterances")
    original_segments = relationship(
        "TranscriptSegment",
        secondary=dialogue_utterance_segments,
        order_by=dialogue_utterance_segments.c.sequence,
    )

    def __repr__(self) -> str:
        return f"<DialogueUtterance id={self.id} speaker={self.speaker!r}>"


# ── ANALYSIS layer ─────────────────────────────────────────────────────


class Analysis(Base):
    """Analysis result for a session (LLM output, summaries, etc.)."""

    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    type = Column(String(64), nullable=False)  # summary | hypotheses | ...
    model = Column(String(64), nullable=True)
    status = Column(String(32), nullable=False, default="pending")
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)
    result_json = Column(Text, nullable=True)  # JSON string
    metadata_json = Column(Text, nullable=True)

    session = relationship("Session", back_populates="analyses")

    def __repr__(self) -> str:
        return f"<Analysis id={self.id} type={self.type!r} status={self.status!r}>"


# ── Schema versioning ──────────────────────────────────────────────────


class SchemaVersion(Base):
    """Simple versioned-schema tracker (replaces Alembic for MVP)."""

    __tablename__ = "schema_version"

    version = Column(Integer, primary_key=True)
    applied_at = Column(DateTime, default=_utcnow, nullable=False)
    description = Column(String(255), nullable=True)


__all__ = [
    "Base",
    "Client",
    "Session",
    "AudioTrack",
    "TranscriptSegment",
    "DialogueUtterance",
    "dialogue_utterance_segments",
    "Analysis",
    "SchemaVersion",
]

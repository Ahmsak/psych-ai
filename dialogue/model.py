"""Dialogue data types for the product (SQLite-backed) path.

Single responsibility: the data shape of a built dialogue. No I/O, no
STT, no analysis, no LLM. Just Utterance + Dialogue and (de)serialization.

Mirrors the experimental ``conversation/model.py`` but is the product
counterpart that is persisted through ``DialogueRepository``.

IMPORTANT (Sprint 12 contract, see R1):
``start`` / ``end`` are TRACK-RELATIVE timestamps taken verbatim from the
source ``TranscriptSegment``. They are NOT a cross-track aligned session
timeline. Alignment (ADR-007) is a separate future task.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class Utterance:
    """One reply in the dialog.

    ``text`` is verbatim Whisper output and is never modified.
    ``start`` / ``end`` are track-relative seconds (see module docstring).
    ``source`` is the audio source track ("microphone"/"loopback").
    ``original_segment_id`` links back to the RAW TranscriptSegment.
    """

    id: int
    speaker: str                     # "psychologist" / "client" (by source)
    start: float                     # TRACK-RELATIVE, not session-aligned
    text: str
    source: str                     # source track: "microphone"/"loopback"
    end: Optional[float] = None
    confidence: Optional[float] = None
    original_segment_id: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Utterance":
        return cls(
            id=d["id"], speaker=d["speaker"], start=d["start"],
            text=d["text"], source=d["source"],
            end=d.get("end"), confidence=d.get("confidence"),
            original_segment_id=d.get("original_segment_id"),
        )


@dataclass
class Dialogue:
    """Time-ordered list of utterances for a session."""

    session_id: Optional[int]
    utterances: List[Utterance] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "sprint": "12.0-dialogue-builder",
            "note": (
                "assembled dialogue from TranscriptSegments; "
                "speaker assigned by source track (NOT diarization); "
                "Whisper text unchanged; track-relative timestamps "
                "(no cross-track alignment); overlapping segments preserved"
            ),
            "utterance_count": len(self.utterances),
            "utterances": [u.to_dict() for u in self.utterances],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Dialogue":
        return cls(
            session_id=d.get("session_id"),
            utterances=[Utterance.from_dict(u) for u in d.get("utterances", [])],
        )

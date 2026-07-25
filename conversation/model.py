"""Conversation model: structured dialog data types.

Single responsibility: the data shape of a built conversation. No I/O,
no STT, no analysis, no LLM. Just Utterance + Conversation and their
(de)serialization.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class Utterance:
    """One reply in the dialog.

    ``text`` is verbatim Whisper output and is never modified.
    ``start_time`` / ``end_time`` are seconds from the session
    timeline_start (objective, from Timeline offsets).
    """

    id: int
    speaker: str                     # e.g. "psychologist" / "client"
    start_time: float
    text: str
    source: str                      # source track: "microphone"/"loopback"
    end_time: Optional[float] = None
    confidence: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Utterance":
        return cls(
            id=d["id"], speaker=d["speaker"], start_time=d["start_time"],
            text=d["text"], source=d["source"],
            end_time=d.get("end_time"), confidence=d.get("confidence"),
        )


@dataclass
class Conversation:
    """Time-ordered list of utterances for a session."""

    session_id: Optional[str]
    utterances: List[Utterance] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "sprint": "7.0-conversation-builder",
            "note": "assembled dialog; NO analysis/diarization/LLM; "
                    "Whisper text unchanged",
            "utterance_count": len(self.utterances),
            "utterances": [u.to_dict() for u in self.utterances],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Conversation":
        return cls(
            session_id=d.get("session_id"),
            utterances=[Utterance.from_dict(u) for u in d.get("utterances", [])],
        )

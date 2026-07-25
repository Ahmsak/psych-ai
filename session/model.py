"""Session domain model — the main product object of PsychAI.

A Session unifies ALL artifacts of one consultation: metadata, timeline,
conversation, artifacts, statistics, validation. It is the single entry
point for the Orchestrator.

No LLM, no Conversation analysis, no emotion/bias detection. Whisper text
is never modified. Statistics are objective metadata only.

Loading/saving are side-effect controlled: ``load_session`` never writes;
``save_session`` writes only when called.
"""

from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from session.statistics import SessionStatistics, compute_statistics

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Validation result levels.
PASS = "PASS"
WARNING = "WARNING"
FAIL = "FAIL"


@dataclass
class ValidationResult:
    status: str                       # PASS | WARNING | FAIL
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"status": self.status, "reasons": self.reasons}


def _latest_timeline_dir() -> str:
    dirs = sorted(glob.glob(os.path.join(_ROOT, "experiments", "*_timeline")))
    if not dirs:
        raise FileNotFoundError("no *_timeline experiment directory found")
    return dirs[-1]


def _load_json(path: str) -> Optional[dict]:
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


class Session:
    """Main domain object for one consultation.

    Also carries a minimal runtime lifecycle (``start``/``active``) so the
    Orchestrator has a single Session type for both live and loaded work.
    """

    def __init__(self, base_dir: Optional[str] = None,
                 metadata: Optional[dict] = None,
                 timeline: Optional[dict] = None,
                 conversation: Optional[dict] = None) -> None:
        self.base_dir = base_dir
        self._metadata = metadata
        self._timeline = timeline
        self._conversation = conversation
        self._statistics: Optional[SessionStatistics] = None
        self.active = False

    # ------------------------------------------------------------------ #
    # Runtime lifecycle (kept for Orchestrator compatibility)
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        self.active = True
        print("Session object started")

    # ------------------------------------------------------------------ #
    # Domain accessors
    # ------------------------------------------------------------------ #
    @property
    def metadata(self) -> Optional[dict]:
        return self._metadata

    @property
    def timeline(self) -> Optional[dict]:
        return self._timeline

    @property
    def conversation(self) -> Optional[dict]:
        return self._conversation

    @property
    def session_id(self) -> Optional[str]:
        for src in (self._timeline, self._metadata, self._conversation):
            if src and src.get("session_id"):
                return src["session_id"]
        return None

    @property
    def duration(self) -> Optional[float]:
        if self._timeline and isinstance(
                self._timeline.get("duration_sec"), (int, float)):
            return float(self._timeline["duration_sec"])
        return self.statistics.duration_sec

    @property
    def client_name(self) -> Optional[str]:
        # Placeholder for a future field; not inferred, never analyzed.
        if self._metadata:
            return self._metadata.get("client_name")
        return None

    @property
    def artifacts(self) -> Dict[str, str]:
        """Absolute paths of known artifact files that exist on disk."""
        out: Dict[str, str] = {}
        if not self.base_dir:
            return out
        for name in ("metadata.json", "timeline.json", "conversation.json",
                     "mic.wav", "loopback.wav", "mic_transcription.txt",
                     "loopback_transcription.txt", "mic_segments.json",
                     "loopback_segments.json"):
            p = os.path.join(self.base_dir, name)
            if os.path.exists(p):
                out[name] = p
        return out

    @property
    def statistics(self) -> SessionStatistics:
        if self._statistics is None:
            conv = self._conversation or {"utterances": []}
            self._statistics = compute_statistics(conv, self._timeline)
        return self._statistics

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate(self) -> ValidationResult:
        """Self-check the session. Returns PASS / WARNING / FAIL."""
        reasons: List[str] = []
        status = PASS

        if self._metadata is None:
            reasons.append("metadata missing")
            status = FAIL
        if self._timeline is None:
            reasons.append("timeline missing")
            status = FAIL
        if status == FAIL:
            return ValidationResult(FAIL, reasons)

        # session_id consistency across artifacts.
        ids = {src.get("session_id")
               for src in (self._metadata, self._timeline, self._conversation)
               if src and src.get("session_id")}
        if len(ids) > 1:
            reasons.append(f"session_id mismatch across artifacts: {ids}")
            status = FAIL
            return ValidationResult(FAIL, reasons)

        # Conversation-level warnings (not failures).
        if self._conversation is None:
            reasons.append("conversation missing")
            status = WARNING
        else:
            utts = self._conversation.get("utterances", [])
            if not utts:
                reasons.append("conversation has no utterances")
                status = WARNING
            else:
                if self.statistics.psychologist_utterances == 0:
                    reasons.append("no psychologist utterances")
                    status = WARNING
                if self.statistics.client_utterances == 0:
                    reasons.append("no client utterances")
                    status = WARNING

        return ValidationResult(status, reasons)

    # ------------------------------------------------------------------ #
    # Serialization
    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "sprint": "8.0-session-domain-model",
            "base_dir": self.base_dir,
            "metadata": self._metadata,
            "timeline": self._timeline,
            "conversation": self._conversation,
            "statistics": self.statistics.to_dict(),
            "validation": self.validate().to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict, base_dir: Optional[str] = None) -> "Session":
        return cls(
            base_dir=base_dir or d.get("base_dir"),
            metadata=d.get("metadata"),
            timeline=d.get("timeline"),
            conversation=d.get("conversation"),
        )

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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from session.statistics import SessionStatistics, compute_statistics

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Validation result levels.
PASS = "PASS"
WARNING = "WARNING"
FAIL = "FAIL"

# Live recording lifecycle states (strings, like the levels above).
IDLE = "idle"
RECORDING = "recording"
COMPLETED = "completed"
FAILED = "failed"


class SessionStateError(RuntimeError):
    """Raised on an invalid lifecycle transition (e.g. double start)."""


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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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

        # Live recording lifecycle (Sprint 10 vertical slice).
        self.state: str = IDLE
        self.started_at: Optional[datetime] = None
        self.ended_at: Optional[datetime] = None
        self.error: Optional[str] = None
        self.record_id: Optional[int] = None   # persistence row id
        self._tracks: List[Any] = []
        self._store: Optional[Any] = None

    # ------------------------------------------------------------------ #
    # Runtime lifecycle (kept for Orchestrator compatibility)
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        self.active = True
        print("Session object started")

    # -- Recording lifecycle ------------------------------------------- #
    # The Session owns the boundaries of a consultation: when it starts,
    # when it ends, and what was produced. It drives Capture and hands the
    # results to ``store`` -- a narrow persistence port with three methods
    # (create_session / add_audio_track / finalize_session). No SQL, no
    # SQLAlchemy, no UI knowledge here.

    @property
    def is_recording(self) -> bool:
        return self.state == RECORDING

    @property
    def elapsed_sec(self) -> float:
        """Seconds since the recording started (0 when never started).

        The single source of truth for the UI timer.
        """
        if self.started_at is None:
            return 0.0
        end = self.ended_at or _utcnow()
        return max(0.0, (end - self.started_at).total_seconds())

    def start_recording(self, tracks: List[Any], store: Any, client_id: Optional[int] = None) -> None:
        """Start ``tracks`` and register the session in ``store``.

        On any capture failure every started track is stopped again and
        nothing is persisted, so no false active session and no dangling
        rows are left behind.
        """
        if self.is_recording:
            raise SessionStateError("session is already recording")

        started: List[Any] = []
        try:
            for track in tracks:
                track.start()
                started.append(track)
        except Exception as exc:
            for track in reversed(started):
                try:
                    track.stop()
                except Exception:
                    pass
            self.state = FAILED
            self.error = f"capture failed to start: {exc}"
            self.started_at = None
            self._tracks = []
            raise

        self._tracks = started
        self._store = store
        self.started_at = _utcnow()
        self.state = RECORDING
        self.active = True
        self.error = None
        self.record_id = store.create_session(
            started_at=self.started_at, client_id=client_id)

    def stop_recording(self) -> Optional[int]:
        """Stop capture, persist the tracks and finalize the session.

        Safe to call when not recording (no-op returning the current
        ``record_id``), so a Stop after a failed Start cannot break.
        """
        if not self.is_recording:
            return self.record_id

        for track in self._tracks:
            try:
                track.stop()
            except Exception as exc:  # never block finalization
                self.error = f"capture stop error: {exc}"

        self.ended_at = _utcnow()
        store = self._store
        assert store is not None

        for track in self._tracks:
            result = track.save()
            store.add_audio_track(
                session_id=self.record_id,
                source=track.source,
                file_path=result["file_path"],
                duration=result["duration"],
                sample_rate=result["sample_rate"],
                channels=result["channels"],
                metadata={"errors": result["errors"]} if result["errors"] else None,
            )

        self.state = COMPLETED
        self.active = False
        store.finalize_session(
            session_id=self.record_id,
            ended_at=self.ended_at,
            status=self.state,
        )
        self._tracks = []
        return self.record_id

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

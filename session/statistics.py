"""Session statistics: objective metadata, no interpretation.

Single responsibility: compute plain counts/durations from a built
Conversation + timeline. No analysis, no emotions, no LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Optional


@dataclass
class SessionStatistics:
    duration_sec: Optional[float]
    utterance_count: int
    psychologist_utterances: int
    client_utterances: int
    psychologist_time_pct: Optional[float]
    client_time_pct: Optional[float]
    total_words: int

    def to_dict(self) -> dict:
        return asdict(self)


def _speaking_time(utterances, speaker: str) -> float:
    """Sum of (end-start) for a speaker's utterances with both bounds."""
    total = 0.0
    for u in utterances:
        st = u.get("start_time")
        en = u.get("end_time")
        if u.get("speaker") == speaker and st is not None and en is not None:
            total += max(0.0, float(en) - float(st))
    return total


def compute_statistics(conversation: dict,
                       timeline: Optional[dict] = None) -> SessionStatistics:
    """Compute objective session statistics.

    ``conversation`` is a Conversation.to_dict(); ``timeline`` optional
    for duration fallback. Pure counting, no interpretation.
    """
    utts = conversation.get("utterances", [])
    psych = [u for u in utts if u.get("speaker") == "psychologist"]
    client = [u for u in utts if u.get("speaker") == "client"]

    total_words = sum(len((u.get("text") or "").split()) for u in utts)

    # Duration: prefer timeline, else span of utterance times.
    duration = None
    if timeline and isinstance(timeline.get("duration_sec"), (int, float)):
        duration = float(timeline["duration_sec"])
    elif utts:
        starts = [u["start_time"] for u in utts if u.get("start_time") is not None]
        ends = [u["end_time"] for u in utts if u.get("end_time") is not None]
        if starts and ends:
            duration = round(max(ends) - min(starts), 3)

    # Speaking-time percentages (only if we have timed utterances).
    p_time = _speaking_time(utts, "psychologist")
    c_time = _speaking_time(utts, "client")
    spoken = p_time + c_time
    p_pct = round(100.0 * p_time / spoken, 1) if spoken > 0 else None
    c_pct = round(100.0 * c_time / spoken, 1) if spoken > 0 else None

    return SessionStatistics(
        duration_sec=duration,
        utterance_count=len(utts),
        psychologist_utterances=len(psych),
        client_utterances=len(client),
        psychologist_time_pct=p_pct,
        client_time_pct=c_pct,
        total_words=total_words,
    )

"""Format RAW transcript segments for the supervisor prompt.

The RAW ``transcript_segments`` are the SOLE source of truth for Sprint 17
analysis. We do NOT use the normalized Dialogue, and we do NOT attempt to
fix normalization/diarization here.

Each segment is rendered in its original order, preserving the start/end
timestamps (seconds from the session timeline start). The track ``source``
(microphone / loopback) is shown as a neutral, NON-authoritative label — it
is NOT treated as proof of who spoke. The supervisor prompt (see
``llm.prompt``) explicitly forbids the model from turning ``source`` into a
speaker-attribution fact.
"""

from __future__ import annotations

from typing import List, Optional


def _fmt_time(seconds: Optional[float]) -> str:
    """Format seconds as M:SS.mmm (e.g. '0:04.200').

    Preserves sub-second precision so timestamps stay meaningful; never
    emits an invalid marker when a bound is missing.
    """
    if seconds is None:
        return "?"
    m = int(seconds // 60)
    s = seconds - m * 60
    return f"{m}:{s:06.3f}"


def format_raw_transcript(segments: List[dict]) -> str:
    """Render RAW segments as a timestamped, ordered transcript.

    ``segments`` is the list of plain dicts from
    ``SessionStore.get_transcript_segments`` (each has ``start``, ``end``,
    ``text``, and an optional ``source``). The function preserves order and
    timestamps verbatim. Returns an empty string when there are no segments
    (so callers can detect "nothing to analyze").

    Output line shape:
        [M:SS.mmm -> M:SS.mmm] (source) текст

    ``source`` is shown in parentheses only as a raw-track hint — never as
    a speaker name.
    """
    if not segments:
        return ""
    lines: List[str] = []
    for seg in segments:
        start = seg.get("start")
        end = seg.get("end")
        text = (seg.get("text") or "").strip()
        source = seg.get("source")
        ts = f"[{_fmt_time(start)} -> {_fmt_time(end)}]"
        if source:
            lines.append(f"{ts} ({source}) {text}")
        else:
            lines.append(f"{ts} {text}")
    return "\n".join(lines)

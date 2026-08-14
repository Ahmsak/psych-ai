"""Dialogue builder (product path): TranscriptSegment rows -> Dialogue.

Single responsibility: assemble RAW TranscriptSegments of one session into
ONE time-ordered dialogue of DialogueUtterances. No semantic processing,
no diarization, no LLM. Whisper text is never changed.

Speaker is assigned by SOURCE track (objective, not diarization):
    microphone -> psychologist
    loopback   -> client

Timestamps are TRACK-RELATIVE (verbatim from TranscriptSegment.start/end).
No cross-track alignment is performed (Sprint 12 scope; ADR-007 is future).
Overlapping segments are preserved.

The builder depends ONLY on the product ``dialogue/model`` types and on the
shared source->speaker mapping in ``conversation.builder`` (a neutral
product module, no SQLAlchemy/DB dependency). It does NOT touch the DB;
persistence is the Orchestrator's responsibility via the SessionStore port.
"""

from __future__ import annotations

from typing import Dict, List

from dialogue.model import Dialogue, Utterance
# Source->speaker mapping is owned by the conversation module (product code,
# no DB dependency). Reuse it here so the rule lives in exactly one place.
from conversation.builder import SPEAKER_BY_SOURCE


def build_dialogue(segments_by_source: Dict[str, list]) -> Dialogue:
    """Build a Dialogue from per-source TranscriptSegment lists.

    ``segments_by_source``: {"microphone": [TranscriptSegment-like, ...],
    "loopback": [...]}. Each item must expose: id, start, end, text,
    confidence (None allowed). Utterances are sorted by start (stable);
    empty-text segments are skipped; original_segment_id is preserved for
    the m2m link back to RAW TranscriptSegment.

    Returns a Dialogue with ``utterances`` sorted by ``start`` and with
    sequential ``id`` assigned after the sort.
    """
    items: List[Utterance] = []

    for source, segs in segments_by_source.items():
        speaker = SPEAKER_BY_SOURCE.get(source, source)
        for seg in segs:
            text = (seg.get("text") if isinstance(seg, dict) else getattr(seg, "text", "")) or ""
            text = text.strip()
            if not text:
                continue
            start = float(seg.get("start") if isinstance(seg, dict) else seg.start)
            end_raw = seg.get("end") if isinstance(seg, dict) else getattr(seg, "end", None)
            end = float(end_raw) if end_raw is not None else None
            conf = seg.get("confidence") if isinstance(seg, dict) else getattr(seg, "confidence", None)
            orig_id = seg.get("id") if isinstance(seg, dict) else getattr(seg, "id", None)
            items.append(Utterance(
                id=0,  # assigned after sort
                speaker=speaker,
                start=start,
                text=text,
                source=source,
                end=end,
                confidence=conf,
                original_segment_id=orig_id,
            ))

    # Stable sort by start time (source groups keep order on ties).
    items.sort(key=lambda u: u.start)
    for i, u in enumerate(items):
        u.id = i

    return Dialogue(session_id=None, utterances=items)


def validate_dialogue(dialogue: Dialogue) -> List[str]:
    """Sensor-first consistency checks. Returns list of failure messages."""
    failures: List[str] = []

    if not dialogue.utterances:
        failures.append("no utterances — all tracks may be empty")
        return failures

    starts = []
    sources = set()
    speakers = set()
    for i, u in enumerate(dialogue.utterances):
        if u.start is None or u.end is not None and u.start > u.end:
            failures.append(f"utterance {i}: invalid time range")
        if not (u.text and u.text.strip()):
            failures.append(f"utterance {i}: empty text")
        if u.speaker not in SPEAKER_BY_SOURCE.values():
            failures.append(f"utterance {i}: unknown speaker '{u.speaker}'")
        if u.source not in SPEAKER_BY_SOURCE:
            failures.append(f"utterance {i}: unknown source '{u.source}'")
        if u.original_segment_id is None:
            failures.append(f"utterance {i}: missing original_segment_id")
        starts.append(u.start)
        sources.add(u.source)
        speakers.add(u.speaker)

    if starts != sorted(starts):
        failures.append("utterances are not ordered by start time")

    return failures

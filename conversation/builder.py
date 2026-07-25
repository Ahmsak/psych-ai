"""Conversation builder + consistency checks.

Single responsibility: assemble two independent transcripts into ONE
time-ordered dialog, using objective Timeline offsets. No semantic
processing, no diarization, no LLM. Whisper text is never changed.

Speaker is assigned by SOURCE track (objective, not diarization):
    microphone -> local user  (psychologist)
    loopback   -> remote party (client)

Absolute utterance time = track offset (from timeline) + segment start
(from Whisper). See ADR-008.
"""

from __future__ import annotations

from typing import Dict, List

from conversation.model import Conversation, Utterance

# Source track -> speaker label (source-based, NOT diarization).
SPEAKER_BY_SOURCE = {
    "microphone": "psychologist",
    "loopback": "client",
}


def build_conversation(timeline: dict, segments_by_track: Dict[str, list]
                       ) -> Conversation:
    """Assemble a Conversation from a timeline dict and per-track segments.

    ``segments_by_track``: {"microphone": [{start,end,text,confidence},...],
    "loopback": [...]}. Absolute times use timeline offsets. Result is
    sorted by start_time. No text modification.
    """
    offsets = timeline.get("offsets", {}).get("per_track_sec", {})
    items: List[Utterance] = []

    for track, segs in segments_by_track.items():
        offset = float(offsets.get(track, 0.0))
        speaker = SPEAKER_BY_SOURCE.get(track, track)
        for seg in segs:
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            start = round(offset + float(seg["start"]), 3)
            end = (round(offset + float(seg["end"]), 3)
                   if seg.get("end") is not None else None)
            items.append(Utterance(
                id=0,  # assigned after sort
                speaker=speaker,
                start_time=start,
                end_time=end,
                text=text,  # unchanged Whisper text
                source=track,
                confidence=seg.get("confidence"),
            ))

    items.sort(key=lambda u: u.start_time)
    for i, u in enumerate(items):
        u.id = i

    return Conversation(session_id=timeline.get("session_id"),
                        utterances=items)


def validate_conversation(conv: Conversation, timeline: dict) -> List[str]:
    """Sensor-first consistency checks. Returns list of failure messages."""
    failures: List[str] = []

    # Ordered by time.
    starts = [u.start_time for u in conv.utterances]
    if starts != sorted(starts):
        failures.append("utterances are not ordered by start_time")

    # Each utterance has speaker and text.
    for u in conv.utterances:
        if not u.speaker:
            failures.append(f"utterance {u.id}: missing speaker")
        if not (u.text and u.text.strip()):
            failures.append(f"utterance {u.id}: missing text")

    # Consistency with timeline: session_id + time bounds.
    if conv.session_id != timeline.get("session_id"):
        failures.append("session_id mismatch between conversation and timeline")

    tl_dur = timeline.get("duration_sec")
    if isinstance(tl_dur, (int, float)):
        for u in conv.utterances:
            if u.start_time < -0.001 or u.start_time > tl_dur + 0.001:
                failures.append(
                    f"utterance {u.id}: start_time {u.start_time} outside "
                    f"timeline [0, {tl_dur}]")
                break

    return failures

"""Experiment importer — file-based experiment → SQLite.

Reads the standard experiment directory layout:

    metadata.json
    mic.wav, loopback.wav           (paths stored, NOT blobs)
    mic_segments.json               (RAW transcript — microphone)
    loopback_segments.json          (RAW transcript — loopback)
    dialogue.json                   (DERIVED — raw merged dialogue)
    dialogue_normalized.json        (DERIVED — normalized dialogue)

Import is IDEMPOTENT: re-importing the same experiment returns the
existing Session row without creating duplicates.  Idempotency key is
``source_session_id`` (the hex ID from metadata.json).
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import TranscriptSegment, dialogue_utterance_segments
from db.repositories import (
    AudioTrackRepository,
    DialogueRepository,
    SessionRepository,
    TranscriptRepository,
)

# Source track → speaker label (matches tools/build_dialogue.py convention).
SPEAKER_MAP = {
    "microphone": "psychologist",
    "loopback": "client",
}

# Filename convention inside experiment directories.
TRACK_FILES = {
    "microphone": {
        "segments": "mic_segments.json",
        "wav": "mic.wav",
        "transcription": "mic_transcription.txt",
    },
    "loopback": {
        "segments": "loopback_segments.json",
        "wav": "loopback.wav",
        "transcription": "loopback_transcription.txt",
    },
}


def _load_json(path: Path) -> Optional[dict | list]:
    if not path.exists() or path.stat().st_size == 0:
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    """Parse an ISO timestamp string to datetime (best-effort)."""
    if not s:
        return None
    try:
        # Handle trailing 'Z' and microseconds.
        clean = s.rstrip("Z")
        return datetime.fromisoformat(clean)
    except (ValueError, TypeError):
        return None


def _abs_path(exp_dir: Path, filename: str) -> Optional[str]:
    """Return absolute path string if the file exists, else None."""
    p = exp_dir / filename
    return str(p.resolve()) if p.exists() else None


class ImportResult:
    """Summary of an import operation."""

    def __init__(
        self,
        session_id: int,
        source_session_id: str,
        skipped: bool = False,
        audio_tracks: int = 0,
        transcript_segments: int = 0,
        dialogue_utterances: int = 0,
    ):
        self.session_id = session_id
        self.source_session_id = source_session_id
        self.skipped = skipped
        self.audio_tracks = audio_tracks
        self.transcript_segments = transcript_segments
        self.dialogue_utterances = dialogue_utterances

    def __repr__(self) -> str:
        if self.skipped:
            return f"ImportResult(skipped, session_id={self.session_id})"
        return (
            f"ImportResult(session_id={self.session_id}, "
            f"tracks={self.audio_tracks}, "
            f"segs={self.transcript_segments}, "
            f"utts={self.dialogue_utterances})"
        )


def import_experiment(
    exp_dir: str | os.PathLike,
    db_session: Session,
    *,
    whisper_model: Optional[str] = None,
    normalization_version: Optional[str] = None,
) -> ImportResult:
    """Import a file-based experiment into SQLite.

    Parameters
    ----------
    exp_dir : path to the experiment directory (e.g. experiments/20260812_...).
    db_session : an open SQLAlchemy session.
    whisper_model : model name to stamp on transcript segments (optional).
    normalization_version : version label for normalized dialogue (optional).

    Returns
    -------
    ImportResult summary.

    The import is idempotent: if a Session with the same
    ``source_session_id`` already exists, it is returned as-is.
    """
    exp_dir = Path(exp_dir).resolve()
    if not exp_dir.is_dir():
        raise FileNotFoundError(f"Experiment directory not found: {exp_dir}")

    # ── Load metadata ──────────────────────────────────────────────────
    meta = _load_json(exp_dir / "metadata.json") or {}
    source_session_id = meta.get("session_id") or exp_dir.name

    session_repo = SessionRepository(db_session)

    # ── Idempotency: check if already imported ─────────────────────────
    existing = session_repo.get_by_source_id(source_session_id)
    if existing is not None:
        return ImportResult(
            session_id=existing.id,
            source_session_id=source_session_id,
            skipped=True,
        )

    # ── Create Session ─────────────────────────────────────────────────
    started_at = None
    # Try to parse record_start from mic or loopback metadata.
    for track_key in ("microphone", "loopback"):
        track_meta = meta.get(track_key, {})
        started_at = _parse_dt(track_meta.get("record_start"))
        if started_at:
            break

    session = session_repo.create(
        source_session_id=source_session_id,
        source="experiment",
        status="imported",
        started_at=started_at,
        metadata=meta,
    )

    # ── Audio tracks + RAW transcript segments ─────────────────────────
    track_repo = AudioTrackRepository(db_session)
    transcript_repo = TranscriptRepository(db_session)

    # Map: (source) → audio_track_id
    track_ids: dict[str, int] = {}

    for source, files in TRACK_FILES.items():
        segs_data = _load_json(exp_dir / files["segments"])
        wav_path = _abs_path(exp_dir, files["wav"])

        # Audio track — path only, no BLOB.
        track_meta = meta.get(source, {}) if meta else {}
        track = track_repo.create(
            session_id=session.id,
            source=source,
            file_path=wav_path,
            duration=track_meta.get("duration_sec"),
            sample_rate=(track_meta.get("stored_format") or {}).get("sample_rate"),
            channels=(track_meta.get("stored_format") or {}).get("channels"),
            metadata=track_meta,
        )
        track_ids[source] = track.id

        # RAW transcript segments (only if segments file exists).
        if segs_data and isinstance(segs_data, list):
            speaker = SPEAKER_MAP.get(source, source)
            seg_objs = [
                TranscriptSegment(
                    session_id=session.id,
                    audio_track_id=track.id,
                    speaker=speaker,
                    start=float(s["start"]),
                    end=float(s["end"]),
                    text=s.get("text", ""),
                    confidence=s.get("confidence"),
                    model=whisper_model,
                )
                for s in segs_data
            ]
            transcript_repo.bulk_create(seg_objs)

    # ── DERIVED: dialogue utterances ───────────────────────────────────
    dialogue_repo = DialogueRepository(db_session)

    # Prefer dialogue_normalized.json (has original_segments links).
    # Fall back to dialogue.json (raw merged, no normalization).
    norm_data = _load_json(exp_dir / "dialogue_normalized.json")
    raw_dialogue = _load_json(exp_dir / "dialogue.json")

    # Build a lookup: (source, start, end) → transcript_segment_id
    # to link dialogue utterances back to raw segments.
    all_segs = transcript_repo.get_by_session(session.id)
    seg_lookup: dict[tuple[str, float, float], int] = {}
    for seg in all_segs:
        # source is derived from speaker via reverse map
        src = "loopback" if seg.speaker == "client" else "microphone"
        seg_lookup[(src, round(seg.start, 4), round(seg.end, 4))] = seg.id

    utt_count = 0

    if norm_data and isinstance(norm_data, dict) and "utterances" in norm_data:
        # Normalized dialogue — has original_segments (dialogue.json IDs).
        # We need to resolve dialogue.json IDs → our transcript_segment IDs.
        # First build dialogue.json ID → (source, start, end) map.
        dialogue_id_map: dict[int, tuple[str, float, float]] = {}
        if raw_dialogue and isinstance(raw_dialogue, dict):
            for u in raw_dialogue.get("utterances", []):
                dialogue_id_map[u["id"]] = (
                    u.get("source", ""),
                    round(float(u["start"]), 4),
                    round(float(u["end"]), 4),
                )

        for u in norm_data["utterances"]:
            # Resolve original_segments (dialogue.json IDs) to our segment IDs
            resolved_seg_ids: list[int] = []
            for orig_id in u.get("original_segments", []):
                key = dialogue_id_map.get(orig_id)
                if key:
                    seg_id = seg_lookup.get(key)
                    if seg_id:
                        resolved_seg_ids.append(seg_id)

            # If no original_segments (e.g. 1:1 mapping), try direct lookup.
            if not resolved_seg_ids:
                src = u.get("source", "")
                key = (src, round(float(u["start"]), 4), round(float(u["end"]), 4))
                seg_id = seg_lookup.get(key)
                if seg_id:
                    resolved_seg_ids.append(seg_id)

            dialogue_repo.create(
                session_id=session.id,
                speaker=u["speaker"],
                start=float(u["start"]),
                end=float(u.get("end")),
                text=u["text"],
                source=u.get("source"),
                confidence=u.get("confidence"),
                normalization_version=normalization_version or "normalized",
                metadata={
                    "original_utterance_id": u.get("id"),
                    "original_segments": u.get("original_segments", []),
                },
                original_segment_ids=resolved_seg_ids,
            )
            utt_count += 1

    elif raw_dialogue and isinstance(raw_dialogue, dict) and "utterances" in raw_dialogue:
        # Fall back to raw dialogue.json (no normalization links).
        for u in raw_dialogue["utterances"]:
            src = u.get("source", "")
            key = (src, round(float(u["start"]), 4), round(float(u["end"]), 4))
            seg_id = seg_lookup.get(key)

            dialogue_repo.create(
                session_id=session.id,
                speaker=u["speaker"],
                start=float(u["start"]),
                end=float(u.get("end")),
                text=u["text"],
                source=u.get("source"),
                confidence=u.get("confidence"),
                normalization_version="raw_dialogue",
                metadata={"original_utterance_id": u.get("id")},
                original_segment_ids=[seg_id] if seg_id else None,
            )
            utt_count += 1

    # ── Count results ──────────────────────────────────────────────────
    from db.models import AudioTrack, TranscriptSegment as TS, DialogueUtterance

    track_count = db_session.execute(
        select(AudioTrack).where(AudioTrack.session_id == session.id)
    ).scalars().all()
    seg_count = db_session.execute(
        select(TS).where(TS.session_id == session.id)
    ).scalars().all()

    db_session.commit()

    return ImportResult(
        session_id=session.id,
        source_session_id=source_session_id,
        audio_tracks=len(track_count),
        transcript_segments=len(seg_count),
        dialogue_utterances=utt_count,
    )


__all__ = ["import_experiment", "ImportResult"]

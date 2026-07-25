"""Sprint 6 — build a Session Timeline from a Sprint-5 metadata.json.

Turns two independent audio streams (mic + loopback) into a single
TEMPORAL model of the conversation, per ADR-007. Objective data only:
no audio mixing, no diarization, no LLM, no speech analysis.

Timeline math (ADR-007):
    timeline_start = min(record_start of both streams)
    timeline_end   = max(record_start + duration) of both streams
    track offset   = first_frame_at - timeline_start
    inter-stream   = loopback.first_frame_at - mic.first_frame_at

Usage:
    python tools/build_timeline.py                 # newest _timeline run
    python tools/build_timeline.py <experiment_dir>

Writes timeline.json into the experiment directory and validates it.
Exit code != 0 if the timeline cannot be built or fails consistency
checks (sensor-first).
"""

from __future__ import annotations

import glob
import json
import os
import sys
from datetime import datetime
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _latest_timeline_dir() -> str:
    dirs = sorted(glob.glob(os.path.join(ROOT, "experiments", "*_timeline")))
    if not dirs:
        print("FAIL: no *_timeline experiment directory found")
        sys.exit(2)
    return dirs[-1]


def _ts(iso: Optional[str]) -> Optional[float]:
    """ISO-8601 -> epoch seconds, or None."""
    if not iso:
        return None
    return datetime.fromisoformat(iso).timestamp()


def build_timeline(meta: dict) -> dict:
    """Compute the Session Timeline dict from a metadata.json dict.

    Raises ValueError if required objective data is missing (so offset
    cannot be determined) — this is the sensor-first FAIL for Task 4.
    """
    tracks_meta = {"microphone": meta.get("microphone", {}),
                   "loopback": meta.get("loopback", {})}

    starts, ends, tracks, offsets = [], [], {}, {}
    for name, tm in tracks_meta.items():
        rec_start = _ts(tm.get("record_start"))
        first = _ts(tm.get("first_frame_at"))
        dur = tm.get("duration_sec")
        if rec_start is None or first is None or dur is None:
            raise ValueError(
                f"cannot determine offset for '{name}': missing "
                f"record_start/first_frame_at/duration_sec")
        starts.append(rec_start)
        ends.append(rec_start + float(dur))
        tracks[name] = {
            "role": tm.get("role"),
            "wav": tm.get("wav"),
            "transcription": tm.get("transcription"),
            "stored_format": tm.get("stored_format"),
            "record_start": tm.get("record_start"),
            "first_frame_at": tm.get("first_frame_at"),
            "duration_sec": dur,
            "audio_captured": tm.get("audio_captured"),
        }

    timeline_start = min(starts)
    timeline_end = max(ends)

    for name, tm in tracks_meta.items():
        first = _ts(tm.get("first_frame_at"))
        offsets[name] = round(first - timeline_start, 3)
    # inter-stream offset: positive => loopback started after mic
    inter = round(_ts(tracks_meta["loopback"]["first_frame_at"])
                  - _ts(tracks_meta["microphone"]["first_frame_at"]), 3)

    return {
        "session_id": meta.get("session_id"),
        "created_at": meta.get("created_at"),
        "sprint": "6.0-session-alignment",
        "source_metadata": "metadata.json",
        "timeline_start": datetime.fromtimestamp(timeline_start).isoformat(),
        "timeline_end": datetime.fromtimestamp(timeline_end).isoformat(),
        "duration_sec": round(timeline_end - timeline_start, 3),
        "unified_format": meta.get("unified_format"),
        "tracks": tracks,
        "offsets": {
            "per_track_sec": offsets,
            "loopback_minus_mic_sec": inter,
            "method": "first_frame_at - timeline_start (ADR-007)",
        },
        "artifacts": {
            name: {"wav": t.get("wav"), "transcription": t.get("transcription")}
            for name, t in tracks.items()
        },
        "note": "temporal model only; tracks NOT merged/synced/diarized",
    }


def validate_timeline(timeline: dict, meta: dict) -> list:
    """Sensor-first consistency checks. Returns a list of failure msgs."""
    failures = []

    def _fail(cond_ok: bool, msg: str):
        if not cond_ok:
            failures.append(msg)

    # required keys present / not corrupted
    for key in ("session_id", "timeline_start", "timeline_end",
                "tracks", "offsets", "artifacts"):
        _fail(key in timeline, f"timeline missing key '{key}'")
    if failures:
        return failures

    # timeline must not contradict metadata
    _fail(timeline["session_id"] == meta.get("session_id"),
          "session_id mismatch between timeline and metadata")
    for name in ("microphone", "loopback"):
        tl_t = timeline["tracks"].get(name, {})
        md_t = meta.get(name, {})
        _fail(tl_t.get("duration_sec") == md_t.get("duration_sec"),
              f"{name}: duration mismatch timeline vs metadata")
        _fail(tl_t.get("wav") == md_t.get("wav"),
              f"{name}: wav artifact name mismatch")

    # offsets must be determinable (finite numbers)
    off = timeline["offsets"]["per_track_sec"]
    for name in ("microphone", "loopback"):
        _fail(isinstance(off.get(name), (int, float)),
              f"{name}: offset not determined")

    # tracks must share a compatible format
    fmt_mic = timeline["tracks"]["microphone"].get("stored_format")
    fmt_loop = timeline["tracks"]["loopback"].get("stored_format")
    _fail(fmt_mic == fmt_loop and fmt_mic is not None,
          "tracks have incompatible stored_format")
    if timeline.get("unified_format") is not None:
        _fail(fmt_mic == timeline["unified_format"],
              "stored_format does not match unified_format")

    return failures


def process(base: str) -> int:
    meta_path = os.path.join(base, "metadata.json")
    if not (os.path.exists(meta_path) and os.path.getsize(meta_path) > 0):
        print(f"FAIL: metadata.json missing/empty in {base}")
        return 1
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except (ValueError, OSError) as exc:
        print(f"FAIL: metadata.json not parseable: {exc!r}")
        return 1

    try:
        timeline = build_timeline(meta)
    except ValueError as exc:
        print(f"FAIL: {exc}")
        return 1

    failures = validate_timeline(timeline, meta)
    if failures:
        for m in failures:
            print(f"FAIL: {m}")
        return 1

    tmp = os.path.join(base, "timeline.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(timeline, f, ensure_ascii=False, indent=2)
    os.replace(tmp, os.path.join(base, "timeline.json"))

    print(f"PASS: timeline.json written to {base}")
    print(f"  timeline_start={timeline['timeline_start']}")
    print(f"  timeline_end={timeline['timeline_end']}")
    print(f"  offsets={timeline['offsets']['per_track_sec']} "
          f"loop-mic={timeline['offsets']['loopback_minus_mic_sec']}s")
    return 0


def main() -> None:
    base = sys.argv[1] if len(sys.argv) > 1 else _latest_timeline_dir()
    sys.exit(process(base))


if __name__ == "__main__":
    main()

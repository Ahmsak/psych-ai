"""Conversation package: build a structured dialog from transcripts.

Public API:
    from conversation import load_conversation, build_conversation
    from conversation import Conversation, Utterance

Product module (single responsibility: assemble the dialog). No STT, no
analysis, no LLM. conversation.json is the main data source for later
analysis.
"""

from __future__ import annotations

import glob
import json
import os
from typing import Dict, Optional

from conversation.model import Conversation, Utterance
from conversation.builder import (build_conversation, validate_conversation,
                                  SPEAKER_BY_SOURCE)

__all__ = [
    "Conversation", "Utterance", "build_conversation",
    "validate_conversation", "load_conversation", "write_conversation",
    "SPEAKER_BY_SOURCE",
]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _latest_timeline_dir() -> str:
    dirs = sorted(glob.glob(os.path.join(_ROOT, "experiments", "*_timeline")))
    if not dirs:
        raise FileNotFoundError("no *_timeline experiment directory found")
    return dirs[-1]


def _load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _read_timeline(base: str) -> dict:
    """Load timeline.json, or build it in memory from metadata.json."""
    tl_path = os.path.join(base, "timeline.json")
    if os.path.exists(tl_path) and os.path.getsize(tl_path) > 0:
        return _load_json(tl_path)
    # Fall back to building via the session layer (tools/).
    import sys
    sys.path.insert(0, os.path.join(_ROOT, "tools"))
    import build_timeline as bt  # noqa: E402
    meta = _load_json(os.path.join(base, "metadata.json"))
    return bt.build_timeline(meta)


def _read_segments(base: str, timeline: dict) -> Dict[str, list]:
    segs: Dict[str, list] = {}
    for track, tinfo in timeline.get("tracks", {}).items():
        seg_name = tinfo.get("segments") or f"{track}_segments.json"
        seg_path = os.path.join(base, seg_name)
        if os.path.exists(seg_path) and os.path.getsize(seg_path) > 0:
            segs[track] = _load_json(seg_path)
        else:
            segs[track] = []
    return segs


def load_conversation(experiment_dir: Optional[str] = None,
                      write: bool = True) -> Conversation:
    """Build (and by default persist) a Conversation for an experiment run.

    Reads timeline.json (or builds from metadata) + per-track segment
    files, assembles a time-ordered Conversation, validates it, and writes
    conversation.json. Raises ValueError on consistency failure.
    """
    base = experiment_dir or _latest_timeline_dir()
    timeline = _read_timeline(base)
    segments = _read_segments(base, timeline)

    conv = build_conversation(timeline, segments)
    failures = validate_conversation(conv, timeline)
    if failures:
        raise ValueError(f"conversation consistency check failed: {failures}")

    if write:
        write_conversation(conv, base)
    return conv


def write_conversation(conv: Conversation, base: str) -> str:
    """Atomically write conversation.json into ``base``. Returns its path."""
    path = os.path.join(base, "conversation.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(conv.to_dict(), f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path

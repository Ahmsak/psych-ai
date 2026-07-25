"""Sprint 6 — Session Manager: load a Session Timeline via one interface.

Provides a single, stable entry point for downstream work (future
merging, UI, analysis) to consume the Timeline WITHOUT knowing how it is
stored. Objective data only: no audio, no LLM, no analysis here.

    from session_manager import load_session, load_timeline

    session = load_session()            # newest _timeline run
    session = load_session(exp_dir)     # a specific experiment dir

``load_session`` returns a Session object exposing the timeline dict plus
convenience accessors and absolute artifact paths. ``load_timeline`` is a
thin alias returning the raw timeline dict.

If timeline.json is missing, it is built in memory on demand from
metadata.json (via build_timeline) — the loader has NO write side
effects. To persist timeline.json, run tools/build_timeline.py. Raises
FileNotFoundError / ValueError on unrecoverable input so callers can
fail fast.
"""

from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

import build_timeline as _bt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _latest_timeline_dir() -> str:
    dirs = sorted(glob.glob(os.path.join(ROOT, "experiments", "*_timeline")))
    if not dirs:
        raise FileNotFoundError("no *_timeline experiment directory found")
    return dirs[-1]


@dataclass
class Session:
    """Loaded Session Timeline + resolved artifact paths.

    This is the structure downstream code works with. It is a read-only
    view over timeline.json; it does not mix audio or analyze anything.
    """

    base_dir: str
    timeline: Dict

    @property
    def session_id(self) -> Optional[str]:
        return self.timeline.get("session_id")

    @property
    def timeline_start(self) -> Optional[str]:
        return self.timeline.get("timeline_start")

    @property
    def timeline_end(self) -> Optional[str]:
        return self.timeline.get("timeline_end")

    @property
    def duration_sec(self) -> Optional[float]:
        return self.timeline.get("duration_sec")

    @property
    def tracks(self) -> Dict:
        return self.timeline.get("tracks", {})

    @property
    def offsets(self) -> Dict:
        return self.timeline.get("offsets", {})

    def offset_of(self, track: str) -> Optional[float]:
        return self.offsets.get("per_track_sec", {}).get(track)

    def wav_path(self, track: str) -> Optional[str]:
        wav = self.tracks.get(track, {}).get("wav")
        return os.path.join(self.base_dir, wav) if wav else None

    def transcription_path(self, track: str) -> Optional[str]:
        tr = self.tracks.get(track, {}).get("transcription")
        return os.path.join(self.base_dir, tr) if tr else None

    def transcription_text(self, track: str) -> Optional[str]:
        path = self.transcription_path(track)
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return f.read()
        return None

    def track_names(self) -> List[str]:
        return list(self.tracks.keys())


def load_timeline(experiment_dir: Optional[str] = None) -> Dict:
    """Return the raw Timeline dict, building it if needed."""
    base = experiment_dir or _latest_timeline_dir()
    tl_path = os.path.join(base, "timeline.json")
    if os.path.exists(tl_path) and os.path.getsize(tl_path) > 0:
        with open(tl_path, encoding="utf-8") as f:
            return json.load(f)

    # Build on demand from metadata.json.
    meta_path = os.path.join(base, "metadata.json")
    if not (os.path.exists(meta_path) and os.path.getsize(meta_path) > 0):
        raise FileNotFoundError(
            f"neither timeline.json nor metadata.json found in {base}")
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    timeline = _bt.build_timeline(meta)          # may raise ValueError
    failures = _bt.validate_timeline(timeline, meta)
    if failures:
        raise ValueError(f"timeline consistency check failed: {failures}")
    return timeline


def load_session(experiment_dir: Optional[str] = None) -> Session:
    """Load a Session (timeline + artifact accessors)."""
    base = experiment_dir or _latest_timeline_dir()
    return Session(base_dir=base, timeline=load_timeline(base))

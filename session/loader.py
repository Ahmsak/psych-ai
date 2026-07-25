"""Session load/save — side-effect controlled serialization.

``load_session`` never writes to disk. ``save_session`` writes a single
session.json only when called. Reuses the timeline builder and the
conversation package instead of duplicating logic.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Optional

from session.model import Session, _latest_timeline_dir, _load_json

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _build_timeline(base: str) -> Optional[dict]:
    tl = _load_json(os.path.join(base, "timeline.json"))
    if tl is not None:
        return tl
    meta = _load_json(os.path.join(base, "metadata.json"))
    if meta is None:
        return None
    if os.path.join(_ROOT, "tools") not in sys.path:
        sys.path.insert(0, os.path.join(_ROOT, "tools"))
    import build_timeline as bt  # noqa: E402
    try:
        return bt.build_timeline(meta)
    except ValueError:
        return None


def _build_conversation(base: str) -> Optional[dict]:
    conv = _load_json(os.path.join(base, "conversation.json"))
    if conv is not None:
        return conv
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    try:
        from conversation import load_conversation
        return load_conversation(base, write=False).to_dict()
    except (FileNotFoundError, ValueError):
        return None


def load_session(experiment_dir: Optional[str] = None) -> Session:
    """Load a Session from an experiment dir. No write side effects.

    Uses saved artifacts when present; builds timeline/conversation in
    memory otherwise. Does not persist anything.
    """
    base = experiment_dir or _latest_timeline_dir()
    metadata = _load_json(os.path.join(base, "metadata.json"))
    timeline = _build_timeline(base)
    conversation = _build_conversation(base)
    return Session(base_dir=base, metadata=metadata, timeline=timeline,
                   conversation=conversation)


def save_session(session: Session, path: Optional[str] = None) -> str:
    """Write session.json atomically. Returns the path. Explicit only."""
    if path is None:
        if not session.base_dir:
            raise ValueError("no base_dir and no explicit path to save to")
        path = os.path.join(session.base_dir, "session.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(session.to_dict(), f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path


def load_session_file(path: str) -> Session:
    """Restore a Session from a saved session.json (round-trip)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return Session.from_dict(data, base_dir=os.path.dirname(path))

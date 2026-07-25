"""Sprint 10 — Integration Harness (engineering tool, NOT product).

Runs the whole PsychAI pipeline over ONE experiment directory and prints
a single Integration Report with PASS / WARNING / FAIL per stage plus a
summary. Uses ONLY existing APIs; never modifies existing artifacts; adds
no product logic.

Stages: Audio Capture, Metadata, Timeline, Conversation, Session,
Orchestrator.

Usage:
    python tools/run_integration_validation.py                 # newest run
    python tools/run_integration_validation.py <experiment_dir>
"""

from __future__ import annotations

import glob
import json
import os
import sys
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

PASS = "PASS"
WARNING = "WARNING"
FAIL = "FAIL"


class StageReport:
    """Accumulates notes for one stage and resolves an overall status."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.status = PASS
        self.notes: list = []

    def ok(self, msg: str) -> None:
        self.notes.append(("PASS", msg))

    def warn(self, msg: str) -> None:
        self.notes.append(("WARNING", msg))
        if self.status == PASS:
            self.status = WARNING

    def fail(self, msg: str) -> None:
        self.notes.append(("FAIL", msg))
        self.status = FAIL


def _latest_timeline_dir() -> str:
    dirs = sorted(glob.glob(os.path.join(ROOT, "experiments", "*_timeline")))
    if not dirs:
        print("FAIL: no *_timeline experiment directory found")
        sys.exit(2)
    return dirs[-1]


def _load_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------- #
# Stage 1: Audio Capture
# --------------------------------------------------------------------- #

def stage_audio(base: str, meta: dict) -> StageReport:
    r = StageReport("Audio Capture")
    if meta is None:
        r.fail("metadata.json missing — cannot check audio streams")
        return r
    uf = meta.get("unified_format", {})
    for stream in ("microphone", "loopback"):
        s = meta.get(stream, {})
        wav = os.path.join(base, s.get("wav", f"{stream}.wav"))
        if not (os.path.exists(wav) and os.path.getsize(wav) > 0):
            r.fail(f"{stream}: WAV missing/empty ({os.path.basename(wav)})")
            continue
        try:
            wf = wave.open(wav, "rb")
            rate, ch, width = (wf.getframerate(), wf.getnchannels(),
                               wf.getsampwidth())
            frames = wf.getnframes()
            wf.close()
        except (wave.Error, OSError) as exc:
            r.fail(f"{stream}: WAV not readable ({exc!r})")
            continue
        r.ok(f"{stream}: WAV reads ({rate}Hz {ch}ch {width}B, {frames} frames)")
        if uf and not (rate == uf.get("sample_rate") and ch == uf.get("channels")
                       and width == uf.get("sample_width_bytes")):
            r.fail(f"{stream}: format {rate}Hz {ch}ch {width}B != unified {uf}")
        if s.get("errors"):
            r.warn(f"{stream}: device errors reported: {s['errors']}")
    return r


# --------------------------------------------------------------------- #
# Stage 2: Metadata
# --------------------------------------------------------------------- #

def stage_metadata(base: str, meta: dict) -> StageReport:
    r = StageReport("Metadata")
    if meta is None:
        r.fail("metadata.json missing or unparseable")
        return r
    for key in ("session_id", "created_at", "unified_format",
                "microphone", "loopback"):
        if key in meta:
            r.ok(f"has '{key}'")
        else:
            r.fail(f"missing '{key}'")
    # Per-stream required fields.
    for stream in ("microphone", "loopback"):
        s = meta.get(stream, {})
        for key in ("device", "record_start", "first_frame_at",
                    "duration_sec", "wav"):
            if key not in s:
                r.fail(f"{stream}: missing '{key}'")
    return r


# --------------------------------------------------------------------- #
# Stage 3: Timeline
# --------------------------------------------------------------------- #

def stage_timeline(base: str, meta: dict) -> StageReport:
    r = StageReport("Timeline")
    try:
        import build_timeline as bt
    except Exception as exc:  # noqa: BLE001
        r.fail(f"cannot import build_timeline: {exc!r}")
        return r
    tl_path = os.path.join(base, "timeline.json")
    try:
        timeline = _load_json(tl_path) if os.path.exists(tl_path) else \
            bt.build_timeline(meta)
    except Exception as exc:  # noqa: BLE001
        r.fail(f"timeline could not be built/loaded: {exc!r}")
        return r

    for key in ("session_id", "timeline_start", "timeline_end", "offsets",
                "tracks"):
        if key in timeline:
            r.ok(f"has '{key}'")
        else:
            r.fail(f"missing '{key}'")

    # Consistency checks via existing validator.
    if meta is not None:
        try:
            failures = bt.validate_timeline(timeline, meta)
            if failures:
                for f in failures:
                    r.fail(f"consistency: {f}")
            else:
                r.ok("timeline consistent with metadata (offsets, ids, formats)")
        except Exception as exc:  # noqa: BLE001
            r.fail(f"validate_timeline error: {exc!r}")
    return r


# --------------------------------------------------------------------- #
# Stage 4: Conversation
# --------------------------------------------------------------------- #

def stage_conversation(base: str) -> StageReport:
    r = StageReport("Conversation")
    try:
        from conversation import (load_conversation, validate_conversation)
    except Exception as exc:  # noqa: BLE001
        r.fail(f"cannot import conversation API: {exc!r}")
        return r
    try:
        conv = load_conversation(base, write=False)
    except Exception as exc:  # noqa: BLE001
        r.fail(f"conversation could not be built: {exc!r}")
        return r

    utts = conv.utterances
    if not utts:
        r.warn("conversation has no utterances")
    else:
        r.ok(f"{len(utts)} utterances built")
        starts = [u.start_time for u in utts]
        if starts == sorted(starts):
            r.ok("utterances ordered by start_time")
        else:
            r.fail("utterances not ordered by start_time")
        if all(u.speaker for u in utts):
            r.ok("every utterance has a speaker")
        else:
            r.fail("some utterance missing speaker")
        if all(u.text and u.text.strip() for u in utts):
            r.ok("every utterance has text")
        else:
            r.fail("some utterance missing text")

    # Consistency with timeline via existing validator.
    try:
        import build_timeline as bt
        tl_path = os.path.join(base, "timeline.json")
        meta_path = os.path.join(base, "metadata.json")
        timeline = _load_json(tl_path) if os.path.exists(tl_path) else \
            bt.build_timeline(_load_json(meta_path))
        failures = validate_conversation(conv, timeline)
        if failures:
            for f in failures:
                r.fail(f"consistency: {f}")
        else:
            r.ok("conversation consistent with timeline")
    except Exception as exc:  # noqa: BLE001
        r.warn(f"could not cross-check with timeline: {exc!r}")
    return r


# --------------------------------------------------------------------- #
# Stage 5: Session
# --------------------------------------------------------------------- #

def stage_session(base: str) -> StageReport:
    r = StageReport("Session")
    try:
        from session import load_session, save_session, load_session_file
    except Exception as exc:  # noqa: BLE001
        r.fail(f"cannot import session API: {exc!r}")
        return r
    try:
        s = load_session(base)
    except Exception as exc:  # noqa: BLE001
        r.fail(f"load_session failed: {exc!r}")
        return r
    r.ok(f"Session loaded (id={s.session_id})")

    v = s.validate()
    if v.status == FAIL:
        r.fail(f"validate() FAIL: {v.reasons}")
    elif v.status == WARNING:
        r.warn(f"validate() WARNING: {v.reasons}")
    else:
        r.ok("validate() PASS")

    st = s.statistics
    r.ok(f"statistics: utt={st.utterance_count} psy={st.psychologist_utterances} "
         f"cli={st.client_utterances} words={st.total_words} "
         f"dur={st.duration_sec}")

    # Serialization round-trip into a TEMP file (does not touch artifacts).
    import tempfile
    try:
        tmp = os.path.join(tempfile.gettempdir(),
                           f"psychai_session_{s.session_id or 'x'}.json")
        save_session(s, tmp)
        s2 = load_session_file(tmp)
        os.remove(tmp)
        if s2.session_id == s.session_id:
            r.ok("serialization round-trip OK (temp file)")
        else:
            r.fail("serialization round-trip mismatch")
    except Exception as exc:  # noqa: BLE001
        r.fail(f"serialization failed: {exc!r}")
    return r


# --------------------------------------------------------------------- #
# Stage 6: Orchestrator
# --------------------------------------------------------------------- #

def stage_orchestrator(base: str) -> StageReport:
    r = StageReport("Orchestrator")
    try:
        from orchestrator.orchestrator import Orchestrator
    except Exception as exc:  # noqa: BLE001
        r.fail(f"cannot import Orchestrator: {exc!r}")
        return r
    try:
        result = Orchestrator().run(base)
    except Exception as exc:  # noqa: BLE001
        r.fail(f"pipeline raised (should never happen): {exc!r}")
        return r

    if result.status == FAIL:
        r.fail(f"PipelineResult FAIL: {result.errors}")
    elif result.status == WARNING:
        r.warn(f"PipelineResult WARNING: {result.warnings}")
    else:
        r.ok("PipelineResult PASS")
    r.ok(f"stages completed: {result.stages_completed}")
    if result.errors:
        r.fail(f"internal errors: {result.errors}")
    return r


# --------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------- #

def run_report(base: str) -> int:
    meta_path = os.path.join(base, "metadata.json")
    meta = None
    if os.path.exists(meta_path) and os.path.getsize(meta_path) > 0:
        try:
            meta = _load_json(meta_path)
        except (ValueError, OSError):
            meta = None

    stages = [
        stage_audio(base, meta),
        stage_metadata(base, meta),
        stage_timeline(base, meta),
        stage_conversation(base),
        stage_session(base),
        stage_orchestrator(base),
    ]

    print("=" * 60)
    print("PsychAI Integration Report")
    print(f"experiment: {base}")
    print("=" * 60)
    for st in stages:
        print(f"\n[{st.status}] {st.name}")
        for level, msg in st.notes:
            print(f"    {level}: {msg}")

    n_pass = sum(1 for s in stages if s.status == PASS)
    n_warn = sum(1 for s in stages if s.status == WARNING)
    n_fail = sum(1 for s in stages if s.status == FAIL)
    overall = FAIL if n_fail else (WARNING if n_warn else PASS)

    print("\n" + "=" * 60)
    print("Summary")
    print(f"  PASS:    {n_pass}")
    print(f"  WARNING: {n_warn}")
    print(f"  FAIL:    {n_fail}")
    print(f"  Overall Result: {overall}")
    print("=" * 60)

    return 0 if overall != FAIL else 1


def main() -> None:
    base = sys.argv[1] if len(sys.argv) > 1 else _latest_timeline_dir()
    sys.exit(run_report(base))


if __name__ == "__main__":
    main()

"""Sprint 12 integration test: build Dialogue from existing Session 1.

Runs against a COPY of the real DB (./data/psychai.db) so the production
artifact is never mutated. Requires the real session #1 to exist with
status 'transcribed' and 4 mic TranscriptSegments (0 loopback) as produced
by the Sprint 11 post-stop run.

Marked slow: it touches SQLite and exercises the full Orchestrator path
(record load -> builder -> persistence), not just the pure function.
"""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest

DB_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "data", "psychai.db")

pytestmark = pytest.mark.slow


def _copy_db() -> str:
    if not os.path.exists(DB_SRC):
        pytest.skip(f"real DB not found at {DB_SRC}")
    tmp = tempfile.mkdtemp()
    dst = os.path.join(tmp, "psychai.db")
    shutil.copyfile(DB_SRC, dst)
    return dst


def _dangling_fk(db_path: str) -> int:
    """Count dialogue_utterances whose original_segment_id points nowhere."""
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        # utterance -> junction -> transcript_segment existence
        cur.execute(
            "SELECT COUNT(*) FROM dialogue_utterance_segments ds "
            "LEFT JOIN transcript_segments ts ON ds.transcript_segment_id = ts.id "
            "WHERE ts.id IS NULL"
        )
        n = cur.fetchone()[0]
        return int(n)
    finally:
        conn.close()


def test_build_dialogue_on_session_1(tmp_path_factory):
    db_path = _copy_db()
    from orchestrator.orchestrator import Orchestrator

    orch = Orchestrator(db_path=db_path)
    result = orch.build_dialogue(1)

    # R1/R4: status accepted, utterances built.
    assert result["status"] == "dialogued", result
    # Real Session 1 produced 4 mic segments, 0 loopback.
    assert result["utterances"] == 4, result

    # dangling FK must be zero.
    assert _dangling_fk(db_path) == 0

    # Dialogue rows must link back to real transcript segments.
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT u.speaker, u.source, ds.transcript_segment_id "
            "FROM dialogue_utterances u "
            "JOIN dialogue_utterance_segments ds ON ds.utterance_id = u.id "
            "ORDER BY u.id"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 4
    # All from microphone source -> psychologist speaker.
    assert all(r[0] == "psychologist" and r[1] == "microphone" for r in rows)


def test_build_dialogue_idempotent(tmp_path_factory):
    db_path = _copy_db()
    from orchestrator.orchestrator import Orchestrator

    orch = Orchestrator(db_path=db_path)
    r1 = orch.build_dialogue(1)
    r2 = orch.build_dialogue(1)  # re-run must NOT duplicate

    assert r1["status"] == "dialogued"
    assert r2["status"] == "dialogued"
    assert r1["utterances"] == r2["utterances"] == 4

    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        n = conn.execute("SELECT COUNT(*) FROM dialogue_utterances").fetchone()[0]
    finally:
        conn.close()
    # Idempotent: derived layer rebuilt, not appended.
    assert n == 4
    assert _dangling_fk(db_path) == 0


def test_build_dialogue_rejects_untranscribed(tmp_path_factory):
    db_path = _copy_db()
    from orchestrator.orchestrator import Orchestrator

    orch = Orchestrator(db_path=db_path)
    # Force status away from 'transcribed' to verify the guard.
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE sessions SET status='completed' WHERE id=1")
    conn.commit()
    conn.close()

    result = orch.build_dialogue(1)
    assert result["status"] == "completed"
    assert result["error"] is not None

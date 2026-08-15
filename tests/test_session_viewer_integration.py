"""Sprint 13/14 integration tests: viewer + automatic processing over a
real DB copy.

Runs against a COPY of ./data/psychai.db so the production artifact is never
mutated. Verifies the Orchestrator viewer delegates return plain dicts (no
ORM objects leak to the UI), that list/detail/Dialogue work, and that
process_session (Sprint 14) runs transcribe -> build automatically and
recovers a stuck 'transcribing' state.
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


def _orch(db_path):
    from orchestrator.orchestrator import Orchestrator
    return Orchestrator(db_path=db_path)


def _store(db_path):
    from db.session_store import SessionStore
    return SessionStore(db_path)


def test_list_sessions_returns_session_1():
    db_path = _copy_db()
    sessions = _orch(db_path).list_sessions()
    ids = [s["id"] for s in sessions]
    assert 1 in ids
    s1 = next(s for s in sessions if s["id"] == 1)
    assert isinstance(s1["status"], str)
    assert "started_at" in s1 and "ended_at" in s1


def test_get_session_returns_dict_with_tracks():
    db_path = _copy_db()
    sess = _orch(db_path).get_session(1)
    assert sess is not None
    assert sess["id"] == 1
    assert "audio_tracks" in sess
    # status is a plain string; depends on current DB state.
    assert isinstance(sess["status"], str)


def test_get_dialogue_returns_list():
    db_path = _copy_db()
    utts = _orch(db_path).get_dialogue(1)
    assert isinstance(utts, list)  # may be empty if Dialogue not built yet
    for u in utts:
        assert set(u.keys()) >= {"speaker", "start", "end", "text", "source"}


def test_get_dialogue_empty_for_unknown_session():
    db_path = _copy_db()
    orch = _orch(db_path)
    assert orch.get_dialogue(999) == []
    assert orch.get_session(999) is None


def test_multiple_sessions_listed():
    db_path = _copy_db()
    orch = _orch(db_path)
    before = len(orch.list_sessions())
    store = _store(db_path)
    with store._factory() as db:
        from db.repositories import SessionRepository
        SessionRepository(db).create(source="live", status="completed")
        db.commit()
    after = orch.list_sessions()
    assert len(after) == before + 1


def test_process_session_runs_transcribe_and_build():
    db_path = _copy_db()
    orch = _orch(db_path)
    # Force back to 'completed' so the full pipeline runs (WAV on disk intact).
    _store(db_path).set_session_status(1, "completed")
    result = orch.process_session(1)
    assert result["status"] == "dialogued", result
    assert result["utterances"] == 4
    assert len(orch.get_dialogue(1)) == 4


def test_process_session_does_not_reset_failed_status():
    db_path = _copy_db()
    orch = _orch(db_path)
    # Simulate a session that previously failed transcription.
    _store(db_path).set_session_status(1, "transcription_failed")
    result = orch.process_session(1)
    # No recovery: status stays 'transcription_failed', not silently reset.
    assert orch._store.get_session_status(1) == "transcription_failed"
    assert result["status"] == "transcription_failed"

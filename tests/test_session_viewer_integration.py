"""Sprint 13 integration tests: viewer over a real DB copy.

Runs against a COPY of ./data/psychai.db so the production artifact is never
mutated. Verifies the Orchestrator viewer delegates return plain dicts (no
ORM objects leak to the UI) and the existing recording session is visible.
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


def test_list_sessions_returns_session_1():
    db_path = _copy_db()
    from orchestrator.orchestrator import Orchestrator

    orch = Orchestrator(db_path=db_path)
    sessions = orch.list_sessions()
    ids = [s["id"] for s in sessions]
    assert 1 in ids
    # Plain dicts, not ORM objects.
    s1 = next(s for s in sessions if s["id"] == 1)
    assert isinstance(s1["status"], str)
    assert "started_at" in s1 and "ended_at" in s1


def test_get_session_returns_dict_with_tracks():
    db_path = _copy_db()
    from orchestrator.orchestrator import Orchestrator

    orch = Orchestrator(db_path=db_path)
    sess = orch.get_session(1)
    assert sess is not None
    assert sess["id"] == 1
    assert "audio_tracks" in sess
    assert sess["status"] == "dialogued"


def test_get_dialogue_returns_utterances():
    db_path = _copy_db()
    from orchestrator.orchestrator import Orchestrator

    orch = Orchestrator(db_path=db_path)
    utts = orch.get_dialogue(1)
    assert len(utts) == 4  # real Session 1 produced 4 mic utterances
    for u in utts:
        assert set(u.keys()) >= {"speaker", "start", "end", "text", "source"}
        assert u["speaker"] == "psychologist"
        assert u["source"] == "microphone"


def test_get_dialogue_empty_for_unknown_session():
    db_path = _copy_db()
    from orchestrator.orchestrator import Orchestrator

    orch = Orchestrator(db_path=db_path)
    # Session 999 does not exist -> no Dialogue, must not raise.
    assert orch.get_dialogue(999) == []
    assert orch.get_session(999) is None


def test_multiple_sessions_listed():
    db_path = _copy_db()
    from orchestrator.orchestrator import Orchestrator
    from db.session_store import SessionStore

    orch = Orchestrator(db_path=db_path)
    before = len(orch.list_sessions())
    # Add a second fake session directly through the store port.
    store = SessionStore(db_path)
    store._factory()  # ensure init
    with store._factory() as db:
        from db.repositories import SessionRepository
        SessionRepository(db).create(source="live", status="completed")
        db.commit()
    after = orch.list_sessions()
    assert len(after) == before + 1

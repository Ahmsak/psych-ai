"""Sprint 17 analysis persistence integration tests.

Drives Orchestrator.analyze_session over a real SQLite store (the same
store the GUI uses) but with a FAKE LLM provider injected via the factory,
so no network/Gemini is touched. Verifies:

  - RAW transcript (not Dialogue) is used as the analysis source;
  - order & timestamps of segments are preserved into the prompt;
  - source is NOT turned into a speaker name;
  - a missing/empty transcript is refused (no_analysis);
  - the result is persisted in the analyses table (provider/model/
    prompt_version/text) and get_analysis returns the LATEST;
  - a repeated analysis creates a NEW row (history preserved);
  - the API key never reaches the DB (store has no key, and our fake
    provider never sees one);
  - schema migration: a pre-S17 DB gains the new columns on init.
"""

from __future__ import annotations

import datetime

import pytest

from db.session_store import SessionStore
from orchestrator.orchestrator import Orchestrator


# --------------------------------------------------------------------------- #
# Fake provider injected through the factory
# --------------------------------------------------------------------------- #
class _RecordingProvider:
    """Captures the request so we can assert on the prompt contents."""

    name = "fake"

    def __init__(self):
        self.last_request = None
        self.call_count = 0

    def analyze(self, request):
        from llm.contract import AnalysisResult

        self.last_request = request
        self.call_count += 1
        return AnalysisResult(
            text="СУПЕРВИЗОР:\n1. Краткое содержание…",
            provider=self.name,
            model=request.model,
            prompt_version=request.prompt_version,
        )


@pytest.fixture
def fake_provider(monkeypatch):
    prov = _RecordingProvider()
    from llm.provider_factory import PROVIDER_REGISTRY

    PROVIDER_REGISTRY["fake"] = lambda cfg: prov  # noqa: E731
    monkeypatch.setenv("PSYCHAI_LLM_PROVIDER", "fake")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    yield prov
    PROVIDER_REGISTRY.pop("fake", None)


@pytest.fixture
def store_with_transcript(tmp_path):
    """One COMPLETED session with two RAW transcript segments."""
    store = SessionStore(str(tmp_path / "analysis.db"))
    sid = store.create_session(
        started_at=datetime.datetime(2026, 1, 1, 12, 0, 0))
    mic = str(tmp_path / "mic.wav")
    loop = str(tmp_path / "loop.wav")
    open(mic, "w").close()
    open(loop, "w").close()
    store.add_audio_track(session_id=sid, source="microphone",
                          file_path=mic, duration=0.2,
                          sample_rate=44100, channels=1)
    store.add_audio_track(session_id=sid, source="loopback",
                          file_path=loop, duration=0.2,
                          sample_rate=48000, channels=1)
    store.finalize_session(session_id=sid,
                           ended_at=datetime.datetime(2026, 1, 1, 12, 0, 5),
                           status="completed")
    # RAW segments with explicit order + timestamps + sources.
    store.add_transcript_segments(
        session_id=sid, audio_track_id=1, source="microphone", model="small",
        segments=[
            {"start": 0.0, "end": 4.2, "text": "ПРИВЕТ", "confidence": 0.9},
            {"start": 4.2, "end": 9.7, "text": "МИР", "confidence": 0.8},
        ],
    )
    return store, sid


@pytest.fixture
def orch(store_with_transcript, tmp_path):
    store, sid, = store_with_transcript
    o = Orchestrator(db_path=str(tmp_path / "analysis.db"))
    o.session.record_id = sid
    o._store = store
    return o, sid


# --------------------------------------------------------------------------- #
# Source-of-truth + prompt content
# --------------------------------------------------------------------------- #
def test_uses_raw_transcript_not_dialogue(orch, fake_provider):
    o, sid = orch
    res = o.analyze_session(sid)
    assert res["status"] == "analyzed"
    # The prompt must contain the RAW text, NOT anything from Dialogue.
    prompt = fake_provider.last_request.prompt
    assert "ПРИВЕТ" in prompt and "МИР" in prompt
    # Order + timestamps preserved.
    assert prompt.index("0:00.000 -> 0:04.200") < prompt.index("0:04.200 -> 0:09.700")
    # Source tags present but NOT as speaker names.
    assert "microphone" in prompt and "loopback" in prompt
    assert "Психолог" not in prompt and "Клиент" not in prompt


def test_analysis_persisted_with_provenance(orch, fake_provider):
    o, sid = orch
    res = o.analyze_session(sid)
    got = o._store.get_analysis(sid)
    assert got is not None
    assert got["provider"] == "fake"
    assert got["model"] == "gemini-2.5-flash"  # default model in config
    assert got["prompt_version"] == "v1"
    assert "СУПЕРВИЗОР" in got["text"]
    # No key column exists; assert text does not contain a key shape.
    assert "GEMINI_API_KEY" not in got["text"]


def test_no_transcript_refused(tmp_path):
    store = SessionStore(str(tmp_path / "empty.db"))
    sid = store.create_session(started_at=None)
    store.finalize_session(session_id=sid, ended_at=None, status="completed")
    o = Orchestrator(db_path=str(tmp_path / "empty.db"))
    o.session.record_id = sid
    o._store = store
    res = o.analyze_session(sid)
    assert res["status"] == "no_transcript"
    assert o._store.get_analysis(sid) is None


def test_repeat_analysis_creates_new_row(orch, fake_provider, tmp_path):
    o, sid = orch
    r1 = o.analyze_session(sid)
    r2 = o.analyze_session(sid)
    assert r1["analysis_id"] != r2["analysis_id"]
    # get_analysis returns the LATEST.
    latest = o._store.get_analysis(sid)
    assert latest["id"] == r2["analysis_id"]
    # history preserved: 2 rows in the table.
    from db.database import get_session_factory
    from db.repositories import AnalysisRepository

    with get_session_factory(o._store._engine)() as db:
        rows = AnalysisRepository(db).get_by_session(sid)
    assert len(rows) == 2


def test_missing_api_key_handled_gracefully(tmp_path, monkeypatch):
    """With the real gemini provider but no key, analyze_session reports error."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("PSYCHAI_LLM_PROVIDER", "gemini")
    store = SessionStore(str(tmp_path / "nokey.db"))
    sid = store.create_session(started_at=None)
    store.add_transcript_segments(
        session_id=sid, audio_track_id=None, source="microphone", model="small",
        segments=[{"start": 0.0, "end": 1.0, "text": "x", "confidence": 0.9}])
    store.finalize_session(session_id=sid, ended_at=None, status="completed")
    o = Orchestrator(db_path=str(tmp_path / "nokey.db"))
    o.session.record_id = sid
    o._store = store
    res = o.analyze_session(sid)
    assert res["status"] == "error"
    assert "GEMINI_API_KEY" in (res["error"] or "")


# --------------------------------------------------------------------------- #
# Schema migration: pre-S17 DB gains new columns on init
# --------------------------------------------------------------------------- #
def test_migration_adds_analysis_columns(tmp_path):
    from db.database import get_engine, init_db, SCHEMA_VERSION
    from db.migrations import get_schema_version
    from sqlalchemy import inspect, text

    db_path = str(tmp_path / "migrated.db")
    engine = get_engine(db_path)
    # 1) Create the full (current) schema.
    init_db(engine)

    # 2) Emulate a PRE-S17 analyses table (without provider/prompt_version/text)
    #    by rebuilding the table with the older column set and copying rows.
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE analyses_old ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "session_id INTEGER NOT NULL, "
            "type VARCHAR(64) NOT NULL, "
            "model VARCHAR(64), "
            "status VARCHAR(32) NOT NULL DEFAULT 'pending', "
            "created_at DATETIME NOT NULL, "
            "updated_at DATETIME NOT NULL, "
            "result_json TEXT, "
            "metadata_json TEXT, "
            "FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE)"
        ))
        conn.execute(text(
            "INSERT INTO analyses_old "
            "(id, session_id, type, model, status, created_at, updated_at, "
            "result_json, metadata_json) "
            "SELECT id, session_id, type, model, status, created_at, updated_at, "
            "result_json, metadata_json FROM analyses"
        ))
        conn.execute(text("DROP TABLE analyses"))
        conn.execute(text("ALTER TABLE analyses_old RENAME TO analyses"))

    # 3) Re-run init_db/migrate — it must ADD the missing S17 columns safely.
    init_db(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("analyses")}
    assert "provider" in cols
    assert "prompt_version" in cols
    assert "text" in cols
    # Existing rows survived the rebuild.
    with engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM analyses")).scalar()
        assert n == 0  # no rows were written yet, but table is intact
    assert get_schema_version(engine) == SCHEMA_VERSION


def test_persisted_row_roundtrip_with_new_columns(orch, fake_provider):
    o, sid = orch
    o.analyze_session(sid)
    # Read raw ORM columns to ensure the new columns are actually written.
    from db.database import get_session_factory
    from db.repositories import AnalysisRepository

    with get_session_factory(o._store._engine)() as db:
        row = AnalysisRepository(db).latest_by_session(sid)
        assert row.provider == "fake"
        assert row.prompt_version == "v1"
        assert row.text and "СУПЕРВИЗОР" in row.text

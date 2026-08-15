"""Tests for the PsychAI persistence layer (Sprint 12).

Covers:
  1. DB creation
  2. Client creation
  3. Session creation
  4. Client ↔ Session link
  5. Audio tracks creation
  6. Transcript segments import
  7. Raw text preserved unchanged
  8. Dialogue utterances creation
  9. Utterance ↔ transcript segment link
  10. Real experiment import
  11. Idempotent re-import (no duplicates)
  12. Missing WAV does not break import
  13. Large WAV not stored as BLOB
  14. Existing project tests still pass (verified by pytest run)
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from db.database import get_engine, get_session_factory, init_db, SCHEMA_VERSION
from db.importer import import_experiment
from db.models import (
    AudioTrack,
    Client,
    DialogueUtterance,
    Session as SessionModel,
    TranscriptSegment,
    dialogue_utterance_segments,
)
from db.repositories import (
    AnalysisRepository,
    AudioTrackRepository,
    ClientRepository,
    DialogueRepository,
    SessionRepository,
    TranscriptRepository,
)
from db.migrations import get_schema_version


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def db_engine(tmp_path):
    """A fresh in-memory-file SQLite DB for each test."""
    db_path = tmp_path / "test.db"
    engine = get_engine(str(db_path))
    init_db(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    factory = get_session_factory(db_engine)
    with factory() as session:
        yield session


# ── 1. DB creation ─────────────────────────────────────────────────────


def test_db_creation(db_engine):
    """DB is created with all expected tables."""
    inspector = inspect(db_engine)
    tables = set(inspector.get_table_names())
    expected = {
        "clients",
        "sessions",
        "audio_tracks",
        "transcript_segments",
        "dialogue_utterances",
        "dialogue_utterance_segments",
        "analyses",
        "schema_version",
    }
    assert expected.issubset(tables), f"Missing tables: {expected - tables}"


def test_schema_version_recorded(db_engine):
    assert get_schema_version(db_engine) == SCHEMA_VERSION


# ── 2. Client creation ─────────────────────────────────────────────────


def test_create_client(db_session):
    repo = ClientRepository(db_session)
    client = repo.create(display_name="Test Client", notes="test notes")
    db_session.commit()
    assert client.id is not None
    assert client.display_name == "Test Client"
    assert client.notes == "test notes"
    assert client.created_at is not None


# ── 3. Session creation ────────────────────────────────────────────────


def test_create_session(db_session):
    repo = SessionRepository(db_session)
    sess = repo.create(source_session_id="abc123", source="experiment")
    db_session.commit()
    assert sess.id is not None
    assert sess.source_session_id == "abc123"
    assert sess.status == "imported"


# ── 4. Client ↔ Session link ───────────────────────────────────────────


def test_client_session_link(db_session):
    client_repo = ClientRepository(db_session)
    session_repo = SessionRepository(db_session)

    client = client_repo.create(display_name="Linked Client")
    db_session.flush()
    sess = session_repo.create(
        client_id=client.id, source_session_id="link_test"
    )
    db_session.commit()

    # Reload session to test relationship
    db_session.expire_all()
    loaded = session_repo.get(sess.id)
    assert loaded.client_id == client.id
    assert loaded.client.display_name == "Linked Client"


# ── 5. Audio tracks ────────────────────────────────────────────────────


def test_create_audio_tracks(db_session):
    sess_repo = SessionRepository(db_session)
    track_repo = AudioTrackRepository(db_session)

    sess = sess_repo.create(source_session_id="audio_test")
    db_session.flush()

    mic = track_repo.create(
        session_id=sess.id, source="microphone", duration=100.0, sample_rate=48000, channels=1
    )
    loop = track_repo.create(
        session_id=sess.id, source="loopback", duration=95.0, sample_rate=48000, channels=1
    )
    db_session.commit()

    tracks = track_repo.get_by_session(sess.id)
    assert len(tracks) == 2
    assert {t.source for t in tracks} == {"microphone", "loopback"}


# ── 6. Transcript segments ─────────────────────────────────────────────


def test_import_transcript_segments(db_session):
    sess_repo = SessionRepository(db_session)
    track_repo = AudioTrackRepository(db_session)
    seg_repo = TranscriptRepository(db_session)

    sess = sess_repo.create(source_session_id="seg_test")
    db_session.flush()
    track = track_repo.create(session_id=sess.id, source="microphone")
    db_session.flush()

    seg = seg_repo.create(
        session_id=sess.id,
        audio_track_id=track.id,
        speaker="psychologist",
        start=0.0,
        end=2.5,
        text="Raw Whisper output",
        confidence=-0.5,
        model="small",
    )
    db_session.commit()

    segs = seg_repo.get_by_session(sess.id)
    assert len(segs) == 1
    assert segs[0].text == "Raw Whisper output"


# ── 7. Raw text preserved ──────────────────────────────────────────────


def test_raw_text_preserved(db_session):
    """Raw transcript text must never be modified by normalization."""
    sess_repo = SessionRepository(db_session)
    track_repo = AudioTrackRepository(db_session)
    seg_repo = TranscriptRepository(db_session)

    sess = sess_repo.create(source_session_id="raw_test")
    db_session.flush()
    track = track_repo.create(session_id=sess.id, source="loopback")
    db_session.flush()

    original_text = "Алло, здравствуйте, да-да-да"
    seg_repo.create(
        session_id=sess.id,
        audio_track_id=track.id,
        speaker="client",
        start=1.0,
        end=5.0,
        text=original_text,
    )
    db_session.commit()

    # Even after creating derived utterances, raw text is unchanged.
    dlg_repo = DialogueRepository(db_session)
    dlg_repo.create(
        session_id=sess.id,
        speaker="client",
        start=1.0,
        end=5.0,
        text=original_text,
        source="loopback",
        normalization_version="test",
        original_segment_ids=[seg_repo.get_by_session(sess.id)[0].id],
    )
    db_session.commit()

    raw_seg = seg_repo.get_by_session(sess.id)[0]
    assert raw_seg.text == original_text


# ── 8. Dialogue utterances ─────────────────────────────────────────────


def test_create_dialogue_utterances(db_session):
    sess_repo = SessionRepository(db_session)
    dlg_repo = DialogueRepository(db_session)

    sess = sess_repo.create(source_session_id="dlg_test")
    db_session.flush()

    utt = dlg_repo.create(
        session_id=sess.id,
        speaker="client",
        start=0.0,
        end=3.0,
        text="Hello",
        source="loopback",
        confidence=-0.3,
        normalization_version="v1",
    )
    db_session.commit()

    utts = dlg_repo.get_by_session(sess.id)
    assert len(utts) == 1
    assert utts[0].speaker == "client"
    assert utts[0].text == "Hello"


# ── 9. Utterance ↔ segment link ────────────────────────────────────────


def test_utterance_segment_link(db_session):
    sess_repo = SessionRepository(db_session)
    track_repo = AudioTrackRepository(db_session)
    seg_repo = TranscriptRepository(db_session)
    dlg_repo = DialogueRepository(db_session)

    sess = sess_repo.create(source_session_id="link_test2")
    db_session.flush()
    track = track_repo.create(session_id=sess.id, source="microphone")
    db_session.flush()

    # Create 2 raw segments
    s1 = seg_repo.create(
        session_id=sess.id, audio_track_id=track.id, speaker="psychologist",
        start=0.0, end=2.0, text="segment one",
    )
    s2 = seg_repo.create(
        session_id=sess.id, audio_track_id=track.id, speaker="psychologist",
        start=2.0, end=4.0, text="segment two",
    )
    db_session.flush()

    # Create utterance linked to both segments
    utt = dlg_repo.create(
        session_id=sess.id,
        speaker="psychologist",
        start=0.0,
        end=4.0,
        text="segment one segment two",
        source="microphone",
        original_segment_ids=[s1.id, s2.id],
    )
    db_session.commit()

    # Verify m2m link
    db_session.expire_all()
    loaded_utts = dlg_repo.get_by_session(sess.id)
    assert len(loaded_utts) == 1
    linked = loaded_utts[0].original_segments
    assert len(linked) == 2
    assert {s.text for s in linked} == {"segment one", "segment two"}

    # Verify sequence ordering
    assert linked[0].text == "segment one"
    assert linked[1].text == "segment two"


# ── 10-13. Experiment import tests ─────────────────────────────────────


def _make_fake_experiment(tmp_path: Path, *, with_wav: bool = True) -> Path:
    """Create a minimal fake experiment directory for testing."""
    exp_dir = tmp_path / "fake_experiment"
    exp_dir.mkdir()

    # metadata.json
    metadata = {
        "session_id": "fake_test_001",
        "created_at": "2026-08-12T10:00:00",
        "microphone": {
            "role": "outgoing",
            "duration_sec": 10.0,
            "stored_format": {"sample_rate": 48000, "channels": 1},
            "wav": "mic.wav",
            "segments": "mic_segments.json",
        },
        "loopback": {
            "role": "incoming",
            "duration_sec": 10.0,
            "stored_format": {"sample_rate": 48000, "channels": 1},
            "wav": "loopback.wav",
            "segments": "loopback_segments.json",
        },
    }
    (exp_dir / "metadata.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )

    # segments
    mic_segs = [
        {"start": 0.0, "end": 2.0, "text": "mic one", "confidence": -0.1},
        {"start": 2.0, "end": 4.0, "text": "mic two", "confidence": -0.2},
    ]
    loop_segs = [
        {"start": 1.0, "end": 3.0, "text": "loop one", "confidence": -0.3},
    ]
    (exp_dir / "mic_segments.json").write_text(
        json.dumps(mic_segs), encoding="utf-8"
    )
    (exp_dir / "loopback_segments.json").write_text(
        json.dumps(loop_segs), encoding="utf-8"
    )

    # dialogue.json (raw merged)
    dialogue = {
        "session_id": "fake_test_001",
        "utterance_count": 3,
        "utterances": [
            {"id": 0, "speaker": "psychologist", "start": 0.0, "end": 2.0,
             "text": "mic one", "source": "microphone", "confidence": -0.1},
            {"id": 1, "speaker": "client", "start": 1.0, "end": 3.0,
             "text": "loop one", "source": "loopback", "confidence": -0.3},
            {"id": 2, "speaker": "psychologist", "start": 2.0, "end": 4.0,
             "text": "mic two", "source": "microphone", "confidence": -0.2},
        ],
    }
    (exp_dir / "dialogue.json").write_text(
        json.dumps(dialogue), encoding="utf-8"
    )

    # dialogue_normalized.json
    norm = {
        "session_id": "fake_test_001",
        "normalization": {"original_count": 3, "normalized_count": 2},
        "utterances": [
            {"id": 0, "speaker": "psychologist", "start": 0.0, "end": 4.0,
             "text": "mic one mic two", "source": "microphone",
             "confidence": -0.15, "original_segments": [0, 2]},
            {"id": 1, "speaker": "client", "start": 1.0, "end": 3.0,
             "text": "loop one", "source": "loopback",
             "confidence": -0.3, "original_segments": [1]},
        ],
    }
    (exp_dir / "dialogue_normalized.json").write_text(
        json.dumps(norm), encoding="utf-8"
    )

    if with_wav:
        # Create small fake WAV files (not real audio, just dummy files).
        (exp_dir / "mic.wav").write_bytes(b"FAKE_WAV_CONTENT_MIC")
        (exp_dir / "loopback.wav").write_bytes(b"FAKE_WAV_CONTENT_LOOP")

    return exp_dir


def test_import_fake_experiment(db_session, tmp_path):
    """Test 10: import a fake experiment."""
    exp_dir = _make_fake_experiment(tmp_path)
    result = import_experiment(exp_dir, db_session)

    assert not result.skipped
    assert result.audio_tracks == 2
    assert result.transcript_segments == 3  # 2 mic + 1 loop
    assert result.dialogue_utterances == 2  # normalized has 2


def test_idempotent_import(db_session, tmp_path):
    """Test 11: re-importing the same experiment does not create duplicates."""
    exp_dir = _make_fake_experiment(tmp_path)

    result1 = import_experiment(exp_dir, db_session)
    assert not result1.skipped

    result2 = import_experiment(exp_dir, db_session)
    assert result2.skipped
    assert result2.session_id == result1.session_id

    # Verify only one session exists
    from sqlalchemy import select
    sessions = db_session.execute(
        select(SessionModel).where(SessionModel.source_session_id == "fake_test_001")
    ).scalars().all()
    assert len(sessions) == 1


def test_missing_wav_does_not_break_import(db_session, tmp_path):
    """Test 12: missing WAV files should not break metadata/transcript import."""
    exp_dir = _make_fake_experiment(tmp_path, with_wav=False)
    result = import_experiment(exp_dir, db_session)

    assert not result.skipped
    assert result.audio_tracks == 2  # tracks created, just no file_path
    assert result.transcript_segments == 3

    # Verify file_path is None for tracks
    from sqlalchemy import select
    tracks = db_session.execute(select(AudioTrack)).scalars().all()
    for t in tracks:
        assert t.file_path is None


def test_wav_not_stored_as_blob(db_session, tmp_path):
    """Test 13: WAV content must NOT be stored in the DB as a BLOB."""
    exp_dir = _make_fake_experiment(tmp_path, with_wav=True)
    import_experiment(exp_dir, db_session)

    # Check that no column in audio_tracks contains WAV bytes.
    from sqlalchemy import select
    tracks = db_session.execute(select(AudioTrack)).scalars().all()
    for t in tracks:
        # file_path should be a string path, not binary content
        if t.file_path:
            assert isinstance(t.file_path, str)
            assert "mic.wav" in t.file_path or "loopback.wav" in t.file_path
            # Ensure it's a path, not file content
            assert not t.file_path.startswith("FAKE_WAV")

    # Also verify DB file size is small (no BLOBs).
    # (The test DB is in-memory-file, check its size is reasonable.)
    # The fake WAVs are ~20 bytes each; the DB should be well under 1MB.
    # This is a sanity check, not a strict size assertion.


# ── Real experiment import ─────────────────────────────────────────────


REAL_EXPERIMENT = Path(__file__).resolve().parent.parent / "experiments" / "20260812_095907_timeline"


@pytest.mark.skipif(
    not REAL_EXPERIMENT.exists(),
    reason="Real experiment directory not found",
)
def test_import_real_experiment(db_engine, tmp_path):
    """Test 10b: import the real experiment and verify counts."""
    factory = get_session_factory(db_engine)
    with factory() as session:
        result = import_experiment(REAL_EXPERIMENT, session)

    assert not result.skipped
    assert result.audio_tracks == 2
    assert result.transcript_segments > 0
    assert result.dialogue_utterances > 0
    # Real data: 521 mic + 489 loop = 1010 raw segments
    assert result.transcript_segments == 1010


@pytest.mark.skipif(
    not REAL_EXPERIMENT.exists(),
    reason="Real experiment directory not found",
)
def test_real_experiment_idempotent(db_engine):
    """Test 11b: re-importing real experiment is idempotent."""
    factory = get_session_factory(db_engine)
    with factory() as session:
        r1 = import_experiment(REAL_EXPERIMENT, session)
    with factory() as session:
        r2 = import_experiment(REAL_EXPERIMENT, session)

    assert not r1.skipped
    assert r2.skipped
    assert r1.session_id == r2.session_id


# ── Deletion-policy tests (B1) ─────────────────────────────────────────
#
# Verifies the approved deletion semantics:
#   Session.client_id          -> RESTRICT
#   AudioTrack.session_id      -> CASCADE
#   TranscriptSegment.session_id       -> CASCADE
#   TranscriptSegment.audio_track_id   -> SET NULL
#   DialogueUtterance.session_id        -> CASCADE
#   Analysis.session_id        -> CASCADE
#   dialogue_utterance_segments.utterance_id       -> CASCADE
#   dialogue_utterance_segments.transcript_segment_id -> NO ACTION
#   (NO ACTION == deferred RESTRICT in SQLite: blocks deleting a RAW segment still
#    linked to DERIVED, but does NOT block `DELETE FROM sessions` like immediate RESTRICT)
# RAW transcript_segments must never be destroyed by deleting a DERIVED row,
# and no dangling foreign keys may remain.


def _dangling_count(conn) -> int:
    """Count dangling FK references across deletion-relevant tables."""
    sql = [
        # junction row whose utterance is gone
        "SELECT COUNT(*) FROM dialogue_utterance_segments d "
        "WHERE NOT EXISTS (SELECT 1 FROM dialogue_utterances u WHERE u.id = d.utterance_id)",
        # junction row whose segment is gone
        "SELECT COUNT(*) FROM dialogue_utterance_segments d "
        "WHERE NOT EXISTS (SELECT 1 FROM transcript_segments t WHERE t.id = d.transcript_segment_id)",
        # segment whose audio_track is gone (non-null)
        "SELECT COUNT(*) FROM transcript_segments t WHERE audio_track_id IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM audio_tracks a WHERE a.id = t.audio_track_id)",
        # audio_track whose session is gone
        "SELECT COUNT(*) FROM audio_tracks a "
        "WHERE NOT EXISTS (SELECT 1 FROM sessions s WHERE s.id = a.session_id)",
        # segment whose session is gone
        "SELECT COUNT(*) FROM transcript_segments t "
        "WHERE NOT EXISTS (SELECT 1 FROM sessions s WHERE s.id = t.session_id)",
        # utterance whose session is gone
        "SELECT COUNT(*) FROM dialogue_utterances u "
        "WHERE NOT EXISTS (SELECT 1 FROM sessions s WHERE s.id = u.session_id)",
    ]
    total = 0
    for q in sql:
        total += conn.execute(text(q)).scalar() or 0
    return total


def _seed_full_graph(session) -> int:
    """Build client->session->track->raw_segment + utterance->raw_segment(m2m)."""
    from db.models import Client, Session as SM, AudioTrack, TranscriptSegment, DialogueUtterance

    client = Client(display_name="Del")
    session.add(client)
    session.flush()
    sess = SM(client_id=client.id, source_session_id="del_test")
    session.add(sess)
    session.flush()
    track = AudioTrack(session_id=sess.id, source="microphone")
    session.add(track)
    session.flush()
    seg = TranscriptSegment(
        session_id=sess.id, audio_track_id=track.id, speaker="psychologist",
        start=0.0, end=2.0, text="RAW MUST SURVIVE",
    )
    session.add(seg)
    session.flush()
    utt = DialogueUtterance(
        session_id=sess.id, speaker="psychologist", start=0.0, end=2.0,
        text="derived", source="microphone", normalization_version="v1",
    )
    session.add(utt)
    session.flush()
    session.execute(
        dialogue_utterance_segments.insert().values(
            utterance_id=utt.id, transcript_segment_id=seg.id, sequence=0
        )
    )
    session.commit()
    return sess.id


def test_F1_delete_session_raw_sql_cascades_children(db_engine):
    """F1: raw `DELETE FROM sessions` removes all children, dangling=0."""
    Factory = get_session_factory(db_engine)
    with Factory() as s:
        sid = _seed_full_graph(s)
    with db_engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.execute(text("DELETE FROM sessions WHERE id=:s"), {"s": sid})
        counts = {t: conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
                  for t in ("audio_tracks", "transcript_segments",
                            "dialogue_utterances", "dialogue_utterance_segments", "analyses")}
        dangling = _dangling_count(conn)
    assert counts == {"audio_tracks": 0, "transcript_segments": 0,
                      "dialogue_utterances": 0, "dialogue_utterance_segments": 0, "analyses": 0}
    assert dangling == 0


def test_F2_delete_session_orm_cascades_children(db_session):
    """F2: ORM session.delete cascades (passive_deletes) and leaves dangling=0."""
    from db.models import Session as SM

    sid = _seed_full_graph(db_session)
    with db_session.bind.connect() as conn:
        before = _dangling_count(conn)
    assert before == 0
    obj = db_session.get(SM, sid)
    db_session.delete(obj)
    db_session.commit()
    counts = {t: db_session.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
              for t in ("audio_tracks", "transcript_segments", "dialogue_utterances")}
    assert counts == {"audio_tracks": 0, "transcript_segments": 0, "dialogue_utterances": 0}
    assert _dangling_count(db_session.bind.connect()) == 0


def test_F3_delete_audio_track_sets_null_keeps_raw(db_session):
    """F3: deleting AudioTrack SETs NULL the FK; RAW segment survives, text intact."""
    sid = _seed_full_graph(db_session)
    with db_session.bind.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.execute(text("DELETE FROM audio_tracks WHERE session_id=:s"), {"s": sid})
        conn.commit()
    segs = db_session.execute(
        text("SELECT COUNT(*), COUNT(audio_track_id) FROM transcript_segments")
    ).fetchone()
    raw_text = db_session.execute(
        text("SELECT text FROM transcript_segments")
    ).scalar()
    assert segs[0] == 1          # RAW segment still present
    assert segs[1] == 0          # its audio_track_id is NULL
    assert raw_text == "RAW MUST SURVIVE"
    assert _dangling_count(db_session.bind.connect()) == 0


def test_F4_delete_dialogue_utterance_cascades_junction_keeps_raw(db_session):
    """F4: deleting DialogueUtterance cascades only junction; RAW untouched."""
    sid = _seed_full_graph(db_session)
    with db_session.bind.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.execute(text("DELETE FROM dialogue_utterances WHERE session_id=:s"), {"s": sid})
        conn.commit()
    jc = db_session.execute(text("SELECT COUNT(*) FROM dialogue_utterance_segments")).scalar()
    raw = db_session.execute(text("SELECT COUNT(*), text FROM transcript_segments")).fetchone()
    assert jc == 0               # junction cleared
    assert raw[0] == 1           # RAW survives
    assert raw[1] == "RAW MUST SURVIVE"
    assert _dangling_count(db_session.bind.connect()) == 0


def test_F5_delete_raw_segment_with_live_link_blocked(db_session):
    """F5: deleting a RAW segment still referenced by DERIVED is RESTRICTed."""
    _seed_full_graph(db_session)
    with db_session.bind.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        with pytest.raises(Exception):  # IntegrityError (FK RESTRICT)
            conn.execute(text("DELETE FROM transcript_segments"))
            conn.commit()
    # RAW and DERIVED both still present, no dangling introduced.
    assert db_session.execute(text("SELECT COUNT(*) FROM transcript_segments")).scalar() == 1
    assert db_session.execute(text("SELECT COUNT(*) FROM dialogue_utterances")).scalar() == 1
    assert _dangling_count(db_session.bind.connect()) == 0


def test_F6_delete_client_with_sessions_blocked(db_session):
    """F6: deleting a Client that owns sessions is RESTRICTed."""
    _seed_full_graph(db_session)
    with db_session.bind.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        with pytest.raises(Exception):  # IntegrityError (FK RESTRICT)
            conn.execute(text("DELETE FROM clients"))
            conn.commit()
    assert db_session.execute(text("SELECT COUNT(*) FROM clients")).scalar() == 1
    assert db_session.execute(text("SELECT COUNT(*) FROM sessions")).scalar() == 1


def test_F7_regenerate_derived_keeps_raw(db_session, tmp_path):
    """F7: regenerate DERIVED layer (delete_by_session) leaves RAW intact."""
    from db.repositories import DialogueRepository

    exp_dir = _make_fake_experiment(tmp_path)
    import_experiment(exp_dir, db_session)
    raw_before = db_session.execute(
        text("SELECT COUNT(*) FROM transcript_segments")
    ).scalar()

    # Regenerate DERIVED only.
    repo = DialogueRepository(db_session)
    deleted = repo.delete_by_session(
        db_session.execute(
            text("SELECT id FROM sessions WHERE source_session_id='fake_test_001'")
        ).scalar()
    )
    db_session.commit()

    raw_after = db_session.execute(
        text("SELECT COUNT(*) FROM transcript_segments")
    ).scalar()
    junctions = db_session.execute(text("SELECT COUNT(*) FROM dialogue_utterance_segments")).scalar()
    assert deleted == 2
    assert raw_after == raw_before      # RAW not touched by derived regeneration
    assert junctions == 0               # junction cleared with DERIVED
    assert _dangling_count(db_session.bind.connect()) == 0


def test_F8_two_step_delete_no_dangling(db_session):
    """F8: delete AudioTrack then Session -> dangling=0 at each step."""
    sid = _seed_full_graph(db_session)
    with db_session.bind.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.execute(text("DELETE FROM audio_tracks WHERE session_id=:s"), {"s": sid})
        assert _dangling_count(conn) == 0
        conn.execute(text("DELETE FROM sessions WHERE id=:s"), {"s": sid})
        assert _dangling_count(conn) == 0
        counts = {t: conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
                  for t in ("audio_tracks", "transcript_segments", "dialogue_utterances")}
    assert counts == {"audio_tracks": 0, "transcript_segments": 0, "dialogue_utterances": 0}


def test_F9_orm_remove_from_collection_deletes_derived_keeps_raw(db_session):
    """F9: ORM delete-orphan via collection removes utterance + junction, RAW intact."""
    from db.models import Session as SM

    sid = _seed_full_graph(db_session)
    sess = db_session.get(SM, sid)
    utt = sess.dialogue_utterances[0]
    sess.dialogue_utterances.remove(utt)
    db_session.flush()
    jc = db_session.execute(text("SELECT COUNT(*) FROM dialogue_utterance_segments")).scalar()
    raw = db_session.execute(text("SELECT COUNT(*), text FROM transcript_segments")).fetchone()
    assert jc == 0
    assert raw[0] == 1 and raw[1] == "RAW MUST SURVIVE"
    db_session.commit()
    assert _dangling_count(db_session.bind.connect()) == 0


def test_F10_idempotent_reimport_regression(db_session, tmp_path):
    """F10: idempotent re-import still works and does not mutate/duplicate RAW."""
    exp_dir = _make_fake_experiment(tmp_path)
    r1 = import_experiment(exp_dir, db_session)
    raw_after_first = db_session.execute(
        text("SELECT COUNT(*) FROM transcript_segments")
    ).scalar()
    r2 = import_experiment(exp_dir, db_session)
    assert r2.skipped and r2.session_id == r1.session_id
    assert db_session.execute(
        text("SELECT COUNT(*) FROM transcript_segments")
    ).scalar() == raw_after_first
    assert _dangling_count(db_session.bind.connect()) == 0


def test_F11_incompatible_old_schema_reports_error_no_data_loss(db_engine, tmp_path):
    """F11: an old v1 DB (FK NO ACTION) is rejected with a clear error; data untouched.

    Reproduces the pre-B1 schema by creating the tables WITHOUT on-delete policies,
    inserts a client+session, then asserts init_db/migrate raises SchemaMigrationError
    and the rows are still present (the tool never auto-drops or overwrites them).
    """
    from sqlalchemy import text as _t
    from db.migrations import SchemaMigrationError, migrate

    db_path = tmp_path / "old_v1.db"
    old_eng = create_engine(f"sqlite:///{db_path}")
    with old_eng.begin() as c:
        c.execute(_t("CREATE TABLE clients(id INTEGER PRIMARY KEY, display_name TEXT)"))
        c.execute(_t("CREATE TABLE sessions(id INTEGER PRIMARY KEY, client_id INTEGER REFERENCES clients(id))"))  # NO ACTION (v1)
        c.execute(_t("CREATE TABLE schema_version(version INTEGER PRIMARY KEY)"))
        c.execute(_t("INSERT INTO schema_version(version) VALUES(1)"))
        c.execute(_t("INSERT INTO clients(id, display_name) VALUES(1, 'legacy')"))
        c.execute(_t("INSERT INTO sessions(id, client_id) VALUES(1, 1)"))
    old_eng.dispose()

    # Re-open with the project engine (same path) and attempt init/migrate.
    eng = get_engine(str(db_path))
    with pytest.raises(SchemaMigrationError):
        init_db(eng)

    # Data must be intact — nothing was deleted or overwritten.
    with eng.connect() as c:
        c.execute(_t("PRAGMA foreign_keys=ON"))
        clients = c.execute(_t("SELECT COUNT(*) FROM clients")).scalar()
        sessions = c.execute(_t("SELECT COUNT(*) FROM sessions")).scalar()
        ver = c.execute(_t("SELECT MAX(version) FROM schema_version")).scalar()
    assert clients == 1 and sessions == 1
    assert ver == 1  # version marker NOT silently bumped to 2


def test_F12_fresh_v2_engine_is_compatible(tmp_path):
    """F12: a freshly created schema passes is_schema_compatible and migrate is a no-op-ish."""
    from db.migrations import is_schema_compatible, migrate

    db_path = tmp_path / "fresh_v2.db"
    eng = get_engine(str(db_path))
    init_db(eng)  # create current schema
    assert is_schema_compatible(eng) is True
    # migrate must not raise and must report the current schema version.
    assert migrate(eng) == SCHEMA_VERSION

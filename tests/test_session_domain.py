"""Sprint 8 tests: Session domain model, statistics, validation, I/O.

Offline and deterministic: synthetic metadata/timeline/conversation
dicts and temp dirs. No audio device, no model.
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from session import (Session, load_session, save_session, load_session_file,
                     PASS, WARNING, FAIL)
from session.statistics import compute_statistics


def _meta():
    return {"session_id": "s1", "created_at": "2026-01-01T00:00:00"}


def _timeline():
    return {"session_id": "s1", "duration_sec": 20.0,
            "offsets": {"per_track_sec": {"microphone": 0.0, "loopback": 1.0}}}


def _conversation():
    return {
        "session_id": "s1",
        "utterances": [
            {"id": 0, "speaker": "psychologist", "start_time": 0.0,
             "end_time": 2.0, "text": "Здравствуйте как дела",
             "source": "microphone", "confidence": -0.2},
            {"id": 1, "speaker": "client", "start_time": 2.0,
             "end_time": 6.0, "text": "Всё хорошо спасибо большое",
             "source": "loopback", "confidence": -0.1},
        ],
    }


def _session():
    return Session(base_dir=None, metadata=_meta(), timeline=_timeline(),
                   conversation=_conversation())


# ------------------------------- statistics ---------------------------- #

def test_statistics_counts_and_words():
    st = compute_statistics(_conversation(), _timeline())
    assert st.utterance_count == 2
    assert st.psychologist_utterances == 1
    assert st.client_utterances == 1
    assert st.total_words == 3 + 4
    assert st.duration_sec == 20.0


def test_statistics_time_percent():
    st = compute_statistics(_conversation(), _timeline())
    # psych spoke 2s, client 4s -> 33.3 / 66.7
    assert st.psychologist_time_pct == 33.3
    assert st.client_time_pct == 66.7


def test_statistics_no_time_when_no_bounds():
    conv = {"utterances": [
        {"speaker": "psychologist", "start_time": 0.0, "text": "hi"}]}
    st = compute_statistics(conv, None)
    assert st.psychologist_time_pct is None


# ------------------------------- domain API ---------------------------- #

def test_session_accessors():
    s = _session()
    assert s.session_id == "s1"
    assert s.duration == 20.0
    assert s.client_name is None
    assert s.metadata["session_id"] == "s1"
    assert s.timeline["duration_sec"] == 20.0
    assert len(s.conversation["utterances"]) == 2
    assert s.statistics.total_words == 7


# ------------------------------- validation ---------------------------- #

def test_validate_pass():
    assert _session().validate().status == PASS


def test_validate_fail_missing_timeline():
    s = Session(metadata=_meta(), timeline=None, conversation=_conversation())
    v = s.validate()
    assert v.status == FAIL
    assert any("timeline" in r for r in v.reasons)


def test_validate_fail_session_id_mismatch():
    tl = _timeline(); tl["session_id"] = "other"
    s = Session(metadata=_meta(), timeline=tl, conversation=_conversation())
    v = s.validate()
    assert v.status == FAIL
    assert any("session_id" in r for r in v.reasons)


def test_validate_warning_empty_conversation():
    s = Session(metadata=_meta(), timeline=_timeline(),
                conversation={"session_id": "s1", "utterances": []})
    v = s.validate()
    assert v.status == WARNING
    assert any("no utterances" in r for r in v.reasons)


def test_validate_warning_one_sided():
    conv = {"session_id": "s1", "utterances": [
        {"id": 0, "speaker": "psychologist", "start_time": 0.0,
         "end_time": 1.0, "text": "hi", "source": "microphone"}]}
    v = Session(metadata=_meta(), timeline=_timeline(),
                conversation=conv).validate()
    assert v.status == WARNING
    assert any("client" in r for r in v.reasons)


# ------------------------------- serialization ------------------------- #

def test_save_load_roundtrip(tmp_path):
    base = str(tmp_path / "20260101_000000_timeline")
    os.makedirs(base)
    s = Session(base_dir=base, metadata=_meta(), timeline=_timeline(),
                conversation=_conversation())
    path = save_session(s)
    assert os.path.exists(path)
    s2 = load_session_file(path)
    assert s2.session_id == s.session_id
    assert s2.statistics.total_words == s.statistics.total_words
    assert s2.validate().status == PASS


def test_load_session_no_write_side_effects(tmp_path):
    base = str(tmp_path / "20260101_000001_timeline")
    os.makedirs(base)
    with open(os.path.join(base, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(_meta(), f)
    with open(os.path.join(base, "timeline.json"), "w", encoding="utf-8") as f:
        json.dump(_timeline(), f)
    with open(os.path.join(base, "conversation.json"), "w",
              encoding="utf-8") as f:
        json.dump(_conversation(), f)
    load_session(base)
    # loader must not write session.json
    assert not os.path.exists(os.path.join(base, "session.json"))

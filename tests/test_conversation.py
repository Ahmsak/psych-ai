"""Sprint 7 tests: Conversation model, builder, checks, API.

Offline and deterministic: synthetic timeline + segment dicts, temp dirs.
No audio device, no model. Exercises the product module conversation/.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from conversation import (Conversation, Utterance, build_conversation,
                          validate_conversation, load_conversation)


def _timeline():
    return {
        "session_id": "s1",
        "duration_sec": 20.0,
        "offsets": {"per_track_sec": {"microphone": 0.0, "loopback": 1.0}},
        "tracks": {
            "microphone": {"segments": "mic_segments.json"},
            "loopback": {"segments": "loopback_segments.json"},
        },
    }


def _segments():
    return {
        "microphone": [
            {"start": 0.0, "end": 2.0, "text": "Здравствуйте", "confidence": -0.2},
            {"start": 5.0, "end": 6.0, "text": "Как вы себя чувствуете",
             "confidence": -0.3},
        ],
        "loopback": [
            {"start": 1.0, "end": 3.0, "text": "Добрый день", "confidence": -0.1},
        ],
    }


# ------------------------------- model --------------------------------- #

def test_utterance_roundtrip():
    u = Utterance(id=1, speaker="client", start_time=2.0, text="hi",
                  source="loopback", end_time=3.0, confidence=-0.1)
    assert Utterance.from_dict(u.to_dict()) == u


# ------------------------------- builder ------------------------------- #

def test_build_orders_by_time_and_maps_speakers():
    conv = build_conversation(_timeline(), _segments())
    # mic@0.0, loopback@1.0+1.0=2.0, mic@5.0 -> ordered
    times = [u.start_time for u in conv.utterances]
    assert times == sorted(times)
    assert times[0] == 0.0
    # loopback offset applied: seg start 1.0 + offset 1.0 = 2.0
    loop = [u for u in conv.utterances if u.source == "loopback"][0]
    assert loop.start_time == 2.0
    assert loop.speaker == "client"
    mic = [u for u in conv.utterances if u.source == "microphone"][0]
    assert mic.speaker == "psychologist"
    # ids are sequential after sort
    assert [u.id for u in conv.utterances] == [0, 1, 2]


def test_build_does_not_modify_text():
    conv = build_conversation(_timeline(), _segments())
    texts = {u.text for u in conv.utterances}
    assert "Здравствуйте" in texts  # verbatim, unchanged


def test_build_skips_empty_text():
    segs = {"microphone": [{"start": 0.0, "end": 1.0, "text": "  "}],
            "loopback": []}
    conv = build_conversation(_timeline(), segs)
    assert conv.utterances == []


# ------------------------------- checks -------------------------------- #

def test_validate_passes_on_good_conversation():
    conv = build_conversation(_timeline(), _segments())
    assert validate_conversation(conv, _timeline()) == []


def test_validate_fails_on_missing_speaker():
    conv = build_conversation(_timeline(), _segments())
    conv.utterances[0].speaker = ""
    assert any("speaker" in f for f in validate_conversation(conv, _timeline()))


def test_validate_fails_on_missing_text():
    conv = build_conversation(_timeline(), _segments())
    conv.utterances[0].text = ""
    assert any("text" in f for f in validate_conversation(conv, _timeline()))


def test_validate_fails_on_out_of_order():
    conv = build_conversation(_timeline(), _segments())
    conv.utterances[0].start_time = 999.0  # break ordering
    assert any("ordered" in f for f in validate_conversation(conv, _timeline()))


def test_validate_fails_on_timeline_contradiction():
    conv = build_conversation(_timeline(), _segments())
    conv.session_id = "other"
    assert any("session_id" in f
               for f in validate_conversation(conv, _timeline()))


# ------------------------------- API ----------------------------------- #

def _write_run(base):
    os.makedirs(base, exist_ok=True)
    with open(os.path.join(base, "timeline.json"), "w", encoding="utf-8") as f:
        json.dump(_timeline(), f)
    segs = _segments()
    with open(os.path.join(base, "mic_segments.json"), "w", encoding="utf-8") as f:
        json.dump(segs["microphone"], f)
    with open(os.path.join(base, "loopback_segments.json"), "w",
              encoding="utf-8") as f:
        json.dump(segs["loopback"], f)


def test_load_conversation_writes_json(tmp_path):
    base = str(tmp_path / "20260101_000000_timeline")
    _write_run(base)
    conv = load_conversation(base)
    assert conv.session_id == "s1"
    assert len(conv.utterances) == 3
    out = os.path.join(base, "conversation.json")
    assert os.path.exists(out)
    data = json.load(open(out, encoding="utf-8"))
    assert data["utterance_count"] == 3
    assert data["utterances"][0]["start_time"] == 0.0


def test_load_conversation_no_write(tmp_path):
    base = str(tmp_path / "20260101_000001_timeline")
    _write_run(base)
    load_conversation(base, write=False)
    assert not os.path.exists(os.path.join(base, "conversation.json"))

"""Sprint 12 unit tests: dialogue builder (offline, deterministic).

No audio, no model, no DB. Exercises the pure build_dialogue / validate
logic over synthetic RAW segment dicts shaped like TranscriptSegment rows.
"""

from __future__ import annotations

import pytest

from dialogue.builder import build_dialogue, validate_dialogue


# Simulate RAW TranscriptSegment rows as plain dicts.
def _seg(id=0, source="microphone", start=0.0, end=2.0, text="Hello",
         confidence=-0.2):
    return {
        "id": id, "audio_track_id": 1, "source": source,
        "speaker": "psychologist" if source == "microphone" else "client",
        "start": start, "end": end, "text": text, "confidence": confidence,
    }


def _group(*segs):
    by_source = {}
    for s in segs:
        by_source.setdefault(s["source"], []).append(s)
    return by_source


# ------------------------- build_dialogue ------------------------------ #

def test_several_same_source_ordered():
    segs = [
        _seg(id=0, source="microphone", start=5.0, end=6.0, text="Третья"),
        _seg(id=1, source="microphone", start=1.0, end=2.0, text="Первая"),
        _seg(id=2, source="microphone", start=3.0, end=4.0, text="Вторая"),
    ]
    d = build_dialogue(_group(*segs))
    texts = [u.text for u in d.utterances]
    assert texts == ["Первая", "Вторая", "Третья"]
    assert [u.id for u in d.utterances] == [0, 1, 2]


def test_mic_and_loopback_two_speakers():
    segs = [
        _seg(id=0, source="microphone", start=2.0, end=3.0, text="Психолог"),
        _seg(id=1, source="loopback", start=1.0, end=2.0, text="Клиент"),
    ]
    d = build_dialogue(_group(*segs))
    assert len(d.utterances) == 2
    # loopback (client) starts earlier -> first
    assert d.utterances[0].source == "loopback"
    assert d.utterances[0].speaker == "client"
    assert d.utterances[1].source == "microphone"
    assert d.utterances[1].speaker == "psychologist"


def test_empty_track_yields_no_utterance():
    segs = [_seg(id=0, source="loopback", start=0.0, end=1.0, text="   ")]
    d = build_dialogue(_group(*segs))
    assert d.utterances == []


def test_stable_sort_on_equal_starts():
    segs = [
        _seg(id=0, source="microphone", start=10.0, end=11.0, text="Mic"),
        _seg(id=1, source="loopback", start=10.0, end=11.0, text="Loop"),
    ]
    d = build_dialogue(_group(*segs))
    assert len(d.utterances) == 2
    # microphone inserted first -> stays first on tie (stable sort)
    assert d.utterances[0].source == "microphone"
    assert d.utterances[1].source == "loopback"


def test_timestamps_preserved_track_relative():
    segs = [_seg(id=0, source="loopback", start=3.5, end=5.25, text="X")]
    d = build_dialogue(_group(*segs))
    assert d.utterances[0].start == 3.5
    assert d.utterances[0].end == 5.25


def test_original_segment_id_linked():
    segs = [
        _seg(id=7, source="microphone", start=1.0, end=2.0, text="A"),
        _seg(id=8, source="loopback", start=0.5, end=1.5, text="B"),
    ]
    d = build_dialogue(_group(*segs))
    by_id = {u.source: u for u in d.utterances}
    assert by_id["microphone"].original_segment_id == 7
    assert by_id["loopback"].original_segment_id == 8


def test_overlapping_segments_preserved():
    segs = [
        _seg(id=0, source="microphone", start=10.0, end=15.0, text="Психолог"),
        _seg(id=1, source="loopback", start=12.0, end=14.0, text="Клиент"),
    ]
    d = build_dialogue(_group(*segs))
    assert len(d.utterances) == 2  # both kept despite overlap


# ------------------------- validate_dialogue -------------------------- #

def test_validate_passes_on_good():
    segs = [
        _seg(id=0, source="microphone", start=0.0, end=2.0, text="Привет"),
        _seg(id=1, source="loopback", start=1.0, end=3.0, text="Здравствуй"),
    ]
    d = build_dialogue(_group(*segs))
    assert validate_dialogue(d) == []


def test_validate_fails_on_no_utterances():
    d = build_dialogue({})
    assert any("no utterances" in f for f in validate_dialogue(d))


def test_validate_fails_on_inverted_time():
    segs = [_seg(id=0, source="microphone", start=10.0, end=1.0, text="X")]
    d = build_dialogue(_group(*segs))
    assert any("time range" in f for f in validate_dialogue(d))


def test_validate_fails_on_missing_link():
    # Simulate a broken builder that drops the link.
    d = build_dialogue(_group(*[]))
    # empty dialogue -> no utterances failure, not missing-link
    assert validate_dialogue(d) != []
    # Build a dialogue and strip one link to test the check.
    segs = [_seg(id=0, source="microphone", start=0.0, end=1.0, text="X")]
    dd = build_dialogue(_group(*segs))
    dd.utterances[0].original_segment_id = None
    assert any("original_segment_id" in f for f in validate_dialogue(dd))


def test_validate_fails_on_out_of_order():
    segs = [
        _seg(id=0, source="microphone", start=9.0, end=10.0, text="Позже"),
        _seg(id=1, source="loopback", start=1.0, end=2.0, text="Раньше"),
    ]
    d = build_dialogue(_group(*segs))
    # After stable sort by start, order is correct; force disorder to test:
    d.utterances[0], d.utterances[1] = d.utterances[1], d.utterances[0]
    assert any("ordered by start" in f for f in validate_dialogue(d))

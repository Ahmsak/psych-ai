"""Sprint 13 unit tests: ui/state formatting helpers (no Qt, no DB)."""

from __future__ import annotations

from datetime import datetime, timezone

from ui.state import (
    dialogue_text,
    format_elapsed,
    session_detail_text,
    session_row_text,
)


def _session(**kw):
    base = {
        "id": 1,
        "source": "live",
        "status": "dialogued",
        "started_at": datetime(2026, 8, 14, 14, 3, 20),
        "ended_at": datetime(2026, 8, 14, 14, 3, 24),
        "audio_tracks": [
            {"source": "microphone", "duration": 4.09},
            {"source": "loopback", "duration": 4.01},
        ],
    }
    base.update(kw)
    return base


def test_session_row_text_fields():
    row = session_row_text(_session(id=7, status="completed"))
    # id · дата · duration · status
    assert row.startswith("7 · ")
    assert "2026-08-14 14:03:20" in row
    assert "00:00:04" in row
    assert row.endswith("completed")


def test_session_detail_text_contains_blocks():
    detail = session_detail_text(_session())
    assert "Сессия: 1" in detail
    assert "Статус: dialogued" in detail
    assert "Длительность: 00:00:04" in detail
    assert "microphone" in detail and "loopback" in detail


def test_session_detail_handles_missing_times():
    detail = session_detail_text(_session(started_at=None, ended_at=None))
    assert "—" in detail


def test_dialogue_text_empty():
    assert dialogue_text([]) == "Dialogue ещё не построен"


def test_dialogue_text_labels_and_track_relative_marker():
    utts = [
        {"speaker": "psychologist", "start": 2.1, "end": 6.8,
         "text": "Здравствуйте"},
        {"speaker": "client", "start": 7.0, "end": 9.0,
         "text": "Добрый день"},
    ]
    out = dialogue_text(utts)
    assert "Психолог: Здравствуйте" in out
    assert "Клиент: Добрый день" in out
    # R4: timestamps must be explicitly marked track-relative.
    assert "отн. трека" in out
    assert "0:02.1 → 0:06.8" in out


def test_format_elapsed_reused():
    assert format_elapsed(4) == "00:00:04"
    assert format_elapsed(197) == "00:03:17"

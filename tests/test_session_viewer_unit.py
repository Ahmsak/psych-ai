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
    # The stored value is naive UTC; _fmt_dt must convert it to LOCAL time,
    # so the rendered wall-clock must differ from the raw UTC input.
    assert "2026-08-14" in row
    assert "14:03:20" not in row  # raw UTC must NOT be shown verbatim
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


# ---------------------------------------------------------------------------
# _fmt_dt: naive UTC must be shown as LOCAL wall-clock time.
# These tests are deterministic: they do not rely on the test machine's
# timezone. The local conversion is pinned to a fixed +6h offset via a
# FakeDatetime subclass (production code is untouched).
# ---------------------------------------------------------------------------
from datetime import timedelta
from unittest.mock import patch


class FakeDatetime(datetime):
    def astimezone(self, tz=None):
        # Emulate a machine whose local zone is UTC+6.
        return (self + timedelta(hours=6)).replace(tzinfo=None)


def test_fmt_dt_converts_naive_utc_to_local():
    from ui.state import _fmt_dt

    naive_utc = FakeDatetime(2026, 8, 14, 16, 2, 55)  # what SessionStore returns
    out = _fmt_dt(naive_utc)
    # 16:02:55 UTC + 6h = 22:02:55 local
    assert out == "2026-08-14 22:02:55"


def test_fmt_dt_format_is_ymd_hms():
    from ui.state import _fmt_dt

    naive_utc = FakeDatetime(2026, 8, 14, 16, 2, 55)
    out = _fmt_dt(naive_utc)
    assert out == "2026-08-14 22:02:55"
    assert "UTC" not in out
    assert len(out) == 19


def test_fmt_dt_none_yields_dash():
    from ui.state import _fmt_dt

    assert _fmt_dt(None) == "—"


def test_duration_elapsed_untouched_by_timefix():
    # _fmt_span derives from (ended-started); both UTC -> delta is correct and
    # must NOT be shifted by the local-time conversion.
    from ui.state import _fmt_span, format_elapsed

    started = datetime(2026, 8, 14, 16, 0, 0)
    ended = datetime(2026, 8, 14, 16, 0, 4)
    assert _fmt_span(started, ended) == "00:00:04"
    assert format_elapsed(4) == "00:00:04"
"""Presentation helpers for the recording state (no Qt, no domain logic).

Kept apart from ``ui.window`` only so the formatting is importable and
testable without PySide6 installed. Pure functions over the state dict
returned by ``Orchestrator.session_state()``.
"""

from __future__ import annotations

# Source/speaker role labels (source-based, NOT diarization). Mirrors the
# product mapping in conversation.builder.SPEAKER_BY_SOURCE; kept local so
# ui/state stays dependency-free (no Qt, no db, no domain import).
SPEAKER_LABEL = {
    "psychologist": "Психолог",
    "client": "Клиент",
}


def format_elapsed(seconds: float) -> str:
    """Format seconds as HH:MM:SS."""
    total = int(max(0.0, seconds))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def state_text(state: dict) -> str:
    """Human-readable status line for a state dict from the Orchestrator."""
    if state.get("is_recording"):
        return f"ЗАПИСЬ ИДЁТ\n{format_elapsed(state.get('elapsed_sec', 0.0))}"
    if state.get("error"):
        return f"Ошибка: {state['error']}"
    if state.get("state") == "completed":
        return "Сессия завершена"
    return "Готов к записи"


def button_text(state: dict) -> str:
    return "Остановить" if state.get("is_recording") else "Начать запись"


def _fmt_dt(value) -> str:
    """Render a datetime (naive UTC) as YYYY-MM-DD HH:MM:SS, or '—' if None."""
    if value is None:
        return "—"
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _fmt_span(started, ended) -> str:
    """Duration string from two datetimes, or '—' if incomplete."""
    if started is None:
        return "—"
    end = ended or started
    return format_elapsed((end - started).total_seconds())


def session_row_text(session: dict) -> str:
    """One-line list entry: 'id · дата · duration · status'."""
    return (
        f"{session.get('id')} · "
        f"{_fmt_dt(session.get('started_at'))} · "
        f"{_fmt_span(session.get('started_at'), session.get('ended_at'))} · "
        f"{session.get('status', '?')}"
    )


def session_detail_text(session: dict) -> str:
    """Multi-line detail block for the selected session."""
    lines = [
        f"Сессия: {session.get('id')}",
        f"Источник: {session.get('source')}",
        f"Статус: {session.get('status')}",
        f"Начало: {_fmt_dt(session.get('started_at'))}",
        f"Конец: {_fmt_dt(session.get('ended_at'))}",
        f"Длительность: {_fmt_span(session.get('started_at'), session.get('ended_at'))}",
    ]
    tracks = session.get("audio_tracks") or []
    if tracks:
        lines.append("Дорожки:")
        for t in tracks:
            dur = t.get("duration")
            lines.append(
                f"  - {t.get('source')}: "
                f"{format_elapsed(dur) if dur is not None else '—'}"
            )
    return "\n".join(lines)


def _fmt_time_frac(seconds: float) -> str:
    """Format seconds as M:SS.s (e.g. '0:02.1'), preserving sub-second
    precision needed for track-relative utterance timestamps."""
    if seconds is None:
        return "?"
    m = int(seconds // 60)
    s = seconds - m * 60
    return f"{m}:{s:04.1f}"


def dialogue_text(utterances: list[dict]) -> str:
    """Read-only Dialogue rendering. Timestamps are TRACK-RELATIVE (see
    Sprint 12 R1) — labelled 'отн. трека' so the UI never implies a shared
    session timeline. Returns a placeholder when no Dialogue exists yet."""
    if not utterances:
        return "Dialogue ещё не построен"
    lines = []
    for u in utterances:
        label = SPEAKER_LABEL.get(u.get("speaker"), u.get("speaker", "?"))
        start = u.get("start")
        end = u.get("end")
        time = ""
        if start is not None:
            time = f"[{_fmt_time_frac(start)} → {_fmt_time_frac(end) if end is not None else '?'}] "
        lines.append(f"{time}{label}: {u.get('text', '')}  (отн. трека)")
    return "\n".join(lines)


__all__ = [
    "SPEAKER_LABEL",
    "button_text",
    "dialogue_text",
    "format_elapsed",
    "session_detail_text",
    "session_row_text",
    "state_text",
]

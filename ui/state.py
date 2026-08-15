"""Presentation helpers for the recording state (no Qt, no domain logic).

Kept apart from ``ui.window`` only so the formatting is importable and
testable without PySide6 installed. Pure functions over the state dict
returned by ``Orchestrator.session_state()``.
"""

from __future__ import annotations

from datetime import datetime, timezone

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
    """Render a datetime as LOCAL time. The stored value is naive UTC
    (see SessionStore._naive); interpret it as UTC and convert to the
    machine's local timezone before formatting, so the viewer shows local
    wall-clock time rather than raw UTC figures.

    Returns '—' if value is None.
    """
    if value is None:
        return "—"
    return value.replace(tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


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


def client_label(client: dict) -> str:
    """Render a client as 'Тест 001' from display_name + client_number.

    ``display_name`` stores the base name only; ``client_number`` is the
    stable global visual id. Falls back to 'Клиент N' if name missing.
    """
    number = client.get("client_number")
    name = (client.get("display_name") or "").strip()
    if number is None:
        return name or "Без имени"
    if not name:
        return f"Клиент {number:03d}"
    return f"{name} {number:03d}"


def analysis_status_text(state: dict) -> str:
    """Human-readable status for an analysis state dict from the Orchestrator.

    States: analyzing (UI sets this before the background call),
    analyzed, no_transcript, no_session, error.
    """
    status = state.get("status")
    if status == "analyzed":
        prov = state.get("provider")
        model = state.get("model")
        pv = state.get("prompt_version")
        meta = " ".join(p for p in (prov, model, pv) if p)
        return f"Анализ готов ({meta})" if meta else "Анализ готов"
    if status == "no_transcript":
        return "Нет RAW-транскрипта для анализа"
    if status == "no_session":
        return "Нет выбранной сессии"
    if status == "error":
        err = state.get("error") or "неизвестная ошибка"
        return f"Ошибка анализа: {err}"
    # "analyzing" or any other in-flight marker
    return "Анализ…"


def analysis_text(result: dict) -> str:
    """Render a completed analysis result dict (or empty placeholder)."""
    if not result or not (result.get("text") or "").strip():
        return "Результат анализа пуст"
    return result.get("text")


def client_session_groups(sessions: list[dict]) -> list[dict]:
    """Group sessions by client for the viewer.

    Returns a list of groups in display order:
      - normal clients (by client_number, None-last), each with their sessions;
      - a trailing "Без клиента" group for sessions with client_id NULL.
    Each group: {"label", "client_id" (int or None), "sessions": [session dicts]}.
    """
    normal: dict[int, dict] = {}
    legacy_sessions: list[dict] = []
    for s in sessions:
        cid = s.get("client_id")
        if cid is None:
            legacy_sessions.append(s)
            continue
        grp = normal.setdefault(cid, {
            "client_id": cid,
            "display_name": s.get("client_name"),
            "client_number": s.get("client_number"),
            "sessions": [],
        })
        grp["sessions"].append(s)

    groups = []
    for cid in sorted(normal.keys(), key=lambda k: (normal[k]["client_number"] is None, normal[k]["client_number"] or 0, cid)):
        g = normal[cid]
        g["label"] = client_label(g)
        groups.append(g)
    if legacy_sessions:
        groups.append({
            "label": "Без клиента",
            "client_id": None,
            "sessions": legacy_sessions,
        })
    return groups


__all__ = [
    "SPEAKER_LABEL",
    "button_text",
    "client_label",
    "client_session_groups",
    "dialogue_text",
    "format_elapsed",
    "session_detail_text",
    "session_row_text",
    "state_text",
    "analysis_status_text",
    "analysis_text",
]

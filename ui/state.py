"""Presentation helpers for the recording state (no Qt, no domain logic).

Kept apart from ``ui.window`` only so the formatting is importable and
testable without PySide6 installed. Pure functions over the state dict
returned by ``Orchestrator.session_state()``.
"""

from __future__ import annotations


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


__all__ = ["button_text", "format_elapsed", "state_text"]

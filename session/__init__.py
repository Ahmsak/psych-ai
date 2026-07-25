"""Session package — the main domain object of PsychAI.

Public API:
    from session import Session, load_session, save_session
    from session import SessionStatistics, ValidationResult

Session unifies metadata + timeline + conversation + artifacts +
statistics + validation for one consultation, and is the single entry
point for the Orchestrator. No LLM, no analysis.
"""

from __future__ import annotations

from session.model import (Session, ValidationResult, PASS, WARNING, FAIL)
from session.statistics import SessionStatistics, compute_statistics
from session.loader import (load_session, save_session, load_session_file)

__all__ = [
    "Session", "ValidationResult", "PASS", "WARNING", "FAIL",
    "SessionStatistics", "compute_statistics",
    "load_session", "save_session", "load_session_file",
]

"""Backward-compatible entry point.

The Session domain model now lives in ``session.model``. This module
re-exports it so existing imports (``from session.session import
Session``) keep working. Session is the single entry point for the
Orchestrator.
"""

from session.model import Session

__all__ = ["Session"]

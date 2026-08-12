"""Persistence layer for PsychAI.

SQLite + SQLAlchemy 2.x.  Business logic talks to repositories, never to
raw SQL.  Physical audio files stay on disk; the DB stores metadata and
structured data only.

Layering principle preserved:
    RAW          audio_tracks, transcript_segments
    DERIVED      dialogue_utterances (+ utterance_segments link)
    ANALYSIS     analyses
"""

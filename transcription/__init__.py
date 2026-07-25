"""Transcription module: streaming Speech-to-Text via faster-whisper.

Public surface: TranscriptionConfig, StreamingTranscriber.
"""

from transcription.transcriber import StreamingTranscriber, TranscriptionConfig

__all__ = ["StreamingTranscriber", "TranscriptionConfig"]

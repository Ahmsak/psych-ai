"""Transcription module: Speech-to-Text via faster-whisper.

Public surface:
- StreamingTranscriber / TranscriptionConfig: live PCM chunk streaming.
- transcribe_file: post-hoc transcription of a finished WAV file.
"""

from transcription.file_transcriber import transcribe_file
from transcription.transcriber import StreamingTranscriber, TranscriptionConfig

__all__ = [
    "StreamingTranscriber",
    "TranscriptionConfig",
    "transcribe_file",
]

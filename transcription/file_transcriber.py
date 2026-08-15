"""Post-hoc transcription of a finished WAV file with faster-whisper.

This is the file-based counterpart to ``transcriber.StreamingTranscriber``:
where the streaming transcriber consumes a live PCM chunk source, this
function takes an already-recorded WAV (as produced by the live recording
slice) and returns RAW transcript segments WITH timestamps.

Responsibility (single): Speech-to-Text for a finished file. It knows
nothing about the Session, the database, the UI, or audio devices. The
caller (Orchestrator) decides what to do with the returned segments.

Output contract
---------------
Returns a list of dicts with the RAW fields Whisper produced — text is
NOT modified, timestamps are relative to the START of the given file
(see ADR/Sprint 11: per-track timeline, no cross-track alignment yet):

    {"start": float, "end": float, "text": str, "confidence": float}

Only one Whisper model entrypoint exists in the project (faster-whisper).
This is not a second transcription backend — it is a second INPUT path to
the same model, mirroring the existing ``_transcribe_segments`` helper that
lived in tools/run_timeline_experiment.py (now reused from here).
"""

from __future__ import annotations

import wave
from typing import List, Optional

import numpy as np

WHISPER_SAMPLE_RATE = 16000


def transcribe_file(
    path: str,
    model_size: str = "small",
    language: Optional[str] = None,
    device: str = "cpu",
    compute_type: str = "int8",
    vad_filter: bool = True,
) -> List[dict]:
    """Transcribe a WAV file and keep per-segment timing.

    Reads the file at ``path`` as 16-bit PCM, resamples to 16 kHz mono
    (what Whisper expects), and runs faster-whisper with ``vad_filter``
    enabled to suppress hallucinations on near-silence.

    Returns a list of ``{"start", "end", "text", "confidence"}`` using
    faster-whisper's native segment timestamps. Text is NOT modified.
    This is the data layer for RAW transcript persistence (per-track).

    Args:
        path: path to a WAV file (any sample rate; mono or multi-channel).
        model_size: faster-whisper model size (default ``"small"``).
        language: optional language hint (e.g. ``"ru"``); None = autodetect.
        device: inference device (default ``"cpu"``).
        compute_type: compute type (default ``"int8"``).
    """
    from faster_whisper import WhisperModel  # heavy dep, local import

    wf = wave.open(path, "rb")
    try:
        raw = wf.readframes(wf.getnframes())
        rate = wf.getframerate()
    finally:
        wf.close()

    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if rate != WHISPER_SAMPLE_RATE and audio.size:
        dst = int(round(audio.size * WHISPER_SAMPLE_RATE / rate))
        audio = np.interp(
            np.linspace(0, audio.size - 1, dst),
            np.arange(audio.size),
            audio,
        ).astype(np.float32)

    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments, _info = model.transcribe(
        audio,
        language=language,
        beam_size=1,
        vad_filter=vad_filter,
    )
    out: List[dict] = []
    for s in segments:
        text = s.text.strip()
        if not text:
            continue
        out.append(
            {
                "start": round(float(s.start), 3),
                "end": round(float(s.end), 3),
                "text": text,  # unchanged Whisper text (RAW)
                "confidence": round(float(getattr(s, "avg_logprob", 0.0)), 4),
            }
        )
    return out


__all__ = ["transcribe_file"]

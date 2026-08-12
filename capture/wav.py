"""WAV writing helper for captured PCM (audio I/O only).

Extracted from the duplicated ``_write_wav`` / ``_write_unified_wav``
helpers in ``tools/run_dual_experiment.py`` and
``tools/run_timeline_experiment.py``. Same formula, one implementation.
"""

from __future__ import annotations

import wave
from typing import Iterable, List

SAMPLE_WIDTH = 2  # bytes, PCM int16


def write_wav(
    path: str,
    frames: Iterable[bytes],
    rate: int,
    channels: int,
    *,
    ndigits: int = 1,
) -> float:
    """Write int16 PCM ``frames`` to ``path``; return duration in seconds.

    ``ndigits`` controls the rounding of the returned duration (the dual
    experiment used 1 decimal, the timeline experiment 2).
    """
    materialised: List[bytes] = list(frames)
    wf = wave.open(path, "wb")
    try:
        wf.setnchannels(channels)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(rate)
        for chunk in materialised:
            wf.writeframes(chunk)
    finally:
        wf.close()
    total = sum(len(chunk) for chunk in materialised)
    return round(total / (rate * SAMPLE_WIDTH * channels), ndigits)


__all__ = ["SAMPLE_WIDTH", "write_wav"]

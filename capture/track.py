"""A named audio track being recorded to a WAV file (audio I/O only).

Pairs a capturer (``MicrophoneCapture`` or ``SystemAudioCapture``) with a
track name and a destination file. Knows nothing about Session,
Orchestrator, persistence or the UI — it starts/stops the device and
writes the captured PCM to disk, reporting the resulting file metrics.
"""

from __future__ import annotations

import threading
from typing import List, Optional

from capture.wav import write_wav


class RecordedTrack:
    """One recorded audio track: capture -> frames -> WAV file."""

    def __init__(self, source: str, capturer, file_path: str) -> None:
        #: Track name; the project convention is "microphone" / "loopback".
        self.source = source
        self.file_path = file_path
        self._capturer = capturer
        self._frames: List[bytes] = []
        self._thread: Optional[threading.Thread] = None
        self._own_frames = not hasattr(capturer, "frames")

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """Start the device and begin collecting PCM."""
        self._capturer.start()
        if self._own_frames:
            # Pull-mode capturer (loopback): drain chunks in a thread.
            self._thread = threading.Thread(
                target=self._drain, name=f"RecordedTrack-{self.source}",
                daemon=True,
            )
            self._thread.start()

    def _drain(self) -> None:
        for pcm in self._capturer.iter_chunks(timeout=0.5):
            self._frames.append(pcm)

    def stop(self) -> None:
        """Stop the device and join the drain thread. Idempotent."""
        self._capturer.stop()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

    # ------------------------------------------------------------------ #
    # Result
    # ------------------------------------------------------------------ #
    @property
    def frames(self) -> List[bytes]:
        if self._own_frames:
            return self._frames
        return self._capturer.frames

    def save(self) -> dict:
        """Write the WAV file and return its metrics.

        Returns ``{"file_path", "duration", "sample_rate", "channels",
        "errors"}``. Never raises on an empty track: a zero-length WAV is
        still written so the caller can record the fact honestly.
        """
        rate = int(getattr(self._capturer, "sample_rate", 0) or 0)
        channels = int(getattr(self._capturer, "output_channels", 0) or 0)
        if rate <= 0 or channels <= 0:
            # Device never delivered a usable format (failed start).
            return {
                "file_path": None,
                "duration": 0.0,
                "sample_rate": rate or None,
                "channels": channels or None,
                "errors": list(getattr(self._capturer, "errors", [])),
            }
        duration = write_wav(self.file_path, self.frames, rate, channels,
                             ndigits=2)
        return {
            "file_path": self.file_path,
            "duration": duration,
            "sample_rate": rate,
            "channels": channels,
            "errors": list(getattr(self._capturer, "errors", [])),
        }


__all__ = ["RecordedTrack"]

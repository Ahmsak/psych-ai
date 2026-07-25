"""Streaming transcription of raw PCM audio with faster-whisper.

Responsibility (single): Speech-to-Text. This module
- accepts raw int16 PCM chunks (as produced by capture/),
- buffers them into windows of ``window_duration_sec`` seconds,
- resamples the window to 16 kHz mono float32 (what Whisper expects),
- runs faster-whisper and returns recognized text segments.

It knows NOTHING about audio devices (capture/) or the UI. The
Orchestrator feeds chunks in and receives text out.

Example
-------
    tr = StreamingTranscriber(TranscriptionConfig(), input_sample_rate=48000)
    tr.load_model()
    for pcm in some_chunk_source:
        for text in tr.feed(pcm):
            print(text)
    for text in tr.flush():   # transcribe the incomplete last window
        print(text)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional

import numpy as np

WHISPER_SAMPLE_RATE = 16000


@dataclass
class TranscriptionConfig:
    """Tunables for a :class:`StreamingTranscriber`."""

    #: Whisper model size ("tiny", "base", "small", ...). Same as the
    #: validated sandbox prototype (sandbox/whisper_test.py).
    model_size: str = "small"
    device: str = "cpu"
    compute_type: str = "int8"
    #: Window length in seconds. Audio is accumulated into windows of this
    #: size before each transcription pass. Configurable, not hard-coded.
    window_duration_sec: float = 5.0
    #: Optional language hint (e.g. "ru"). None = autodetect per window.
    language: Optional[str] = None
    #: Windows quieter than this RMS (int16 scale) are skipped as silence
    #: to avoid Whisper hallucinating text on empty audio.
    silence_rms_threshold: float = 30.0


class StreamingTranscriber:
    """Accumulate PCM chunks into windows and transcribe them."""

    def __init__(
        self,
        config: Optional[TranscriptionConfig] = None,
        input_sample_rate: int = 48000,
        input_channels: int = 1,
    ) -> None:
        self.config = config or TranscriptionConfig()
        self.input_sample_rate = int(input_sample_rate)
        self.input_channels = int(input_channels)
        self._model = None
        self._buffer = bytearray()
        self._window_bytes = 0
        self.recompute_window()

    def recompute_window(self) -> None:
        """Recompute window size in bytes from current rate/channels.

        Call after changing ``input_sample_rate`` / ``input_channels``
        (e.g. once the capture device's real parameters are known).
        """
        # Bytes per window: rate * seconds * 2 bytes/sample * channels.
        self._window_bytes = int(
            self.input_sample_rate
            * self.config.window_duration_sec
            * 2
            * self.input_channels
        )

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def load_model(self) -> None:
        """Load the faster-whisper model (slow; call once, up front)."""
        if self._model is not None:
            return
        from faster_whisper import WhisperModel  # import here: heavy dep

        self._model = WhisperModel(
            self.config.model_size,
            device=self.config.device,
            compute_type=self.config.compute_type,
        )

    def close(self) -> None:
        """Release the model and clear buffers. Idempotent."""
        self._model = None
        self._buffer.clear()

    # ------------------------------------------------------------------ #
    # Streaming API
    # ------------------------------------------------------------------ #
    def feed(self, pcm: bytes) -> List[str]:
        """Add a PCM chunk; return texts for every completed window."""
        self._buffer.extend(pcm)
        texts: List[str] = []
        while len(self._buffer) >= self._window_bytes:
            window = bytes(self._buffer[: self._window_bytes])
            del self._buffer[: self._window_bytes]
            texts.extend(self._transcribe_window(window))
        return texts

    def flush(self) -> List[str]:
        """Transcribe whatever is left in the buffer (< one window)."""
        if not self._buffer:
            return []
        window = bytes(self._buffer)
        self._buffer.clear()
        # Skip fragments too short to be meaningful speech (< 0.5 s).
        min_bytes = int(self.input_sample_rate * 0.5 * 2 * self.input_channels)
        if len(window) < min_bytes:
            return []
        return self._transcribe_window(window)

    def run(
        self,
        chunks: Iterable[bytes],
        on_text: Callable[[str], None],
    ) -> None:
        """Consume a PCM chunk source directly and emit text to a sink.

        This is the direct capture -> transcriber data path: the caller
        (Orchestrator) only wires the components together; raw PCM never
        passes through it. Blocks until the source is exhausted (i.e. the
        capturer is stopped) or the thread is interrupted; the remaining
        buffer is flushed at the end in both cases.
        """
        try:
            for pcm in chunks:
                for text in self.feed(pcm):
                    on_text(text)
        finally:
            for text in self.flush():
                on_text(text)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _transcribe_window(self, window: bytes) -> List[str]:
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load_model() first.")

        audio = np.frombuffer(window, dtype=np.int16)

        if self.input_channels > 1:
            audio = audio.reshape(-1, self.input_channels).mean(axis=1)

        audio = audio.astype(np.float32)

        # Silence gate: Whisper hallucinates on near-silent windows.
        rms = float(np.sqrt(np.mean(audio ** 2))) if audio.size else 0.0
        if rms < self.config.silence_rms_threshold:
            return []

        audio /= 32768.0

        if self.input_sample_rate != WHISPER_SAMPLE_RATE:
            audio = self._resample(audio, self.input_sample_rate,
                                   WHISPER_SAMPLE_RATE)

        segments, _info = self._model.transcribe(
            audio,
            language=self.config.language,
            beam_size=1,          # fastest; fine for streaming MVP
            vad_filter=True,      # extra protection against silence
        )
        texts = [seg.text.strip() for seg in segments]
        return [t for t in texts if t]

    @staticmethod
    def _resample(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
        """Linear-interpolation resample (good enough for speech STT)."""
        if src_rate == dst_rate or audio.size == 0:
            return audio
        dst_len = int(round(audio.size * dst_rate / src_rate))
        src_idx = np.linspace(0.0, audio.size - 1, num=dst_len)
        return np.interp(src_idx, np.arange(audio.size),
                         audio).astype(np.float32)

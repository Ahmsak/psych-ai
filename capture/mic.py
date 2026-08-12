"""Default-microphone capture (Windows / PortAudio).

Product counterpart of :mod:`capture.capturer` (WASAPI loopback) for the
LOCAL user's voice. Like the rest of the ``capture`` package this module
is dependency-isolated: it knows nothing about Session, Orchestrator,
persistence, SQLAlchemy or the UI. Audio I/O only.

Origin
------
Extracted from ``tools/run_dual_experiment.py`` (``MicRecorder``) and
``tools/run_timeline_experiment.py`` (``TimedMicRecorder``); both scripts
now use this single implementation. Behaviour is preserved:

* blocking ``stream.read(chunk_size, exception_on_overflow=False)`` in a
  dedicated daemon thread;
* frames accumulated in ``frames`` (list of PCM byte chunks);
* ``rms_max`` peak level and ``errors`` collected for the run manifest;
* mono int16 at the device's native sample rate, NO resampling here --
  unless a ``transform`` callable is supplied (the timeline experiment
  passes its "unified format" converter, which used to live inside
  ``TimedMicRecorder``).

The device is *resolved* in ``__init__`` (so callers can print
``device_name`` / ``native_rate`` before recording) but the stream is
opened in ``start()``, matching :class:`SystemAudioCapture`. ``stop()``
is idempotent and safe to call from a ``finally`` block even if
``start()`` was never called.
"""

from __future__ import annotations

import queue
import struct
import threading
import time
from typing import Callable, Iterator, List, Optional

import pyaudiowpatch as pyaudio

from capture.capturer import CaptureError

_SENTINEL = object()

DEFAULT_CHUNK = 4096


class MicrophoneDeviceNotFoundError(CaptureError):
    """Raised when no default input (microphone) device is available."""


def rms(pcm: bytes) -> float:
    """Root-mean-square level of int16 little-endian PCM bytes."""
    n = len(pcm) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack("<%dh" % n, pcm[: n * 2])
    return (sum(x * x for x in samples) / n) ** 0.5


class MicrophoneCapture:
    """Capture raw PCM from the default input device.

    ``transform(pcm, src_rate, src_channels) -> bytes`` is applied to each
    chunk before it is stored/yielded. When omitted the native bytes are
    passed through unchanged.
    """

    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK,
        *,
        transform: Optional[Callable[[bytes, int, int], bytes]] = None,
    ) -> None:
        self._chunk_size = chunk_size
        self._transform = transform

        self._pa: Optional[pyaudio.PyAudio] = pyaudio.PyAudio()
        try:
            info = self._pa.get_default_input_device_info()
        except Exception as exc:  # no input device / no host API
            try:
                self._pa.terminate()
            finally:
                self._pa = None
            raise MicrophoneDeviceNotFoundError(
                f"No default input (microphone) device available: {exc!r}"
            ) from exc

        self.device_name: str = info["name"]
        self._device_index = int(info["index"])
        #: Device-native capture parameters.
        self.native_rate: int = int(info["defaultSampleRate"])
        self.native_channels: int = 1

        self._stream = None
        self._running = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._queue: "queue.Queue[object]" = queue.Queue(maxsize=60)

        #: Accumulated PCM chunks (post-transform), for WAV writing.
        self.frames: List[bytes] = []
        self.rms_max: float = 0.0
        self.errors: List[str] = []
        self.record_start: Optional[float] = None
        self.first_frame_at: Optional[float] = None

        self._started_once = False
        self._out_rate = 0
        self._out_channels = 0

    # ------------------------------------------------------------------ #
    # Format exposed to consumers (mirrors SystemAudioCapture)
    # ------------------------------------------------------------------ #
    @property
    def sample_rate(self) -> int:
        """Sample rate of the delivered bytes (0 before ``start()``)."""
        if not self._started_once:
            return 0
        return self._out_rate

    @property
    def output_channels(self) -> int:
        if not self._started_once:
            return 0
        return self._out_channels

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """Open the input stream and begin capturing. Idempotent."""
        if self._running:
            return
        if self._pa is None:
            raise CaptureError("MicrophoneCapture was stopped and cannot restart")

        self._stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=self.native_channels,
            rate=self.native_rate,
            frames_per_buffer=self._chunk_size,
            input=True,
            input_device_index=self._device_index,
        )
        # A transform may change the delivered format; the timeline
        # converter targets 48 kHz mono. Consumers read sample_rate /
        # output_channels, so report what the transform produced.
        self._out_rate = self.native_rate
        self._out_channels = self.native_channels
        self._started_once = True

        self._running = True
        self._stop_event.clear()
        self.record_start = time.time()
        self._thread = threading.Thread(
            target=self._loop, name="MicrophoneCapture", daemon=True
        )
        self._thread.start()

    def set_output_format(self, sample_rate: int, channels: int) -> None:
        """Declare the format produced by ``transform`` (audio I/O only)."""
        self._out_rate = sample_rate
        self._out_channels = channels

    def _loop(self) -> None:
        assert self._stream is not None
        while not self._stop_event.is_set():
            try:
                data = self._stream.read(
                    self._chunk_size, exception_on_overflow=False
                )
            except Exception as exc:
                # Never raise out of the audio thread: record and stop.
                self.errors.append(f"mic read failed: {exc!r}")
                break
            if self.first_frame_at is None:
                self.first_frame_at = time.time()
            if self._transform is not None:
                data = self._transform(data, self.native_rate,
                                       self.native_channels)
            self.frames.append(data)
            level = rms(data)
            if level > self.rms_max:
                self.rms_max = level
            try:
                self._queue.put_nowait(data)
            except queue.Full:
                # Bounded queue: drop the oldest chunk to bound latency.
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._queue.put_nowait(data)
                except queue.Full:
                    pass

    def stop(self) -> None:
        """Stop capturing and release the device. Idempotent."""
        if not self._running and self._stream is None and self._pa is None:
            return

        self._running = False
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

        if self._stream is not None:
            try:
                try:
                    self._stream.stop_stream()
                except Exception:
                    pass
                self._stream.close()
            finally:
                self._stream = None

        # Unblock any iter_chunks() consumer.
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self._queue.put_nowait(_SENTINEL)
        except queue.Full:
            pass

        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None

    def __enter__(self) -> "MicrophoneCapture":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.stop()
        return False

    # ------------------------------------------------------------------ #
    # Consumption API
    # ------------------------------------------------------------------ #
    def iter_chunks(self, timeout: float = 1.0) -> Iterator[bytes]:
        """Pull mode: yield PCM chunks until ``stop()`` is called."""
        while True:
            if not self._running and self._queue.empty():
                return
            try:
                item = self._queue.get(timeout=timeout)
            except queue.Empty:
                if not self._running:
                    return
                continue
            if item is _SENTINEL:
                return
            yield item  # type: ignore[misc]


__all__ = [
    "DEFAULT_CHUNK",
    "MicrophoneCapture",
    "MicrophoneDeviceNotFoundError",
    "rms",
]

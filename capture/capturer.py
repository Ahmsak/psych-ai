"""WASAPI loopback capture implementation (Windows only).

Public surface
--------------
``CaptureConfig``        -- tunables for a capture session.
``SystemAudioCapture``   -- the capturer. start()/stop() control the stream;
                            consume via ``iter_chunks()`` (pull) or
                            ``register_callback()`` (push).
Exceptions               -- CaptureError, WASAPINotAvailableError,
                            LoopbackDeviceNotFoundError.

Design notes
------------
* The module depends only on ``pyaudiowpatch`` and the standard library.
* Audio is read in PortAudio's callback thread and pushed into a bounded
  ``queue.Queue``. A consumer (the Orchestrator, later) pulls chunks without
  ever touching the audio backend directly.
* Captured PCM is returned as-is in the device's native sample rate
  (usually 48000 Hz). Resampling is explicitly NOT done here -- that belongs
  to the Transcription module. ``sample_rate`` / ``output_channels`` are
  exposed so the consumer knows how to handle the bytes.
* ``mono_mix`` averages stereo -> mono cheaply, which is what most speech
  models expect. When the device is already mono, it is a no-op.
* Per-application (per-process) capture is a documented future extension
  point (``process_id``). WASAPI process-loopback requires native ctypes/
  comtypes code (Windows 10 1903+) and is NOT implemented; setting
  ``process_id`` raises ``NotImplementedError`` rather than silently failing.

Example
-------
    from capture import SystemAudioCapture, CaptureConfig

    cap = SystemAudioCapture(CaptureConfig(chunk_size=4096, mono_mix=True))
    cap.start()
    try:
        for pcm in cap.iter_chunks(timeout=1.0):
            # hand pcm (bytes, int16) to Transcription / Whisper
            ...
    finally:
        cap.stop()
"""

from __future__ import annotations

import queue
import struct
import threading
from dataclasses import dataclass
from typing import Callable, Iterator, Optional

import pyaudiowpatch as pyaudio


_SENTINEL = object()


@dataclass
class CaptureConfig:
    """Tunables for a :class:`SystemAudioCapture` session."""

    #: Frames per PortAudio buffer. Lower = lower latency, higher CPU.
    chunk_size: int = 4096
    #: Substring filter for the loopback device name. ``None`` = default
    #: output device's loopback.
    device_name: Optional[str] = None
    #: Average stereo -> mono. Speech models want mono; this is cheap.
    mono_mix: bool = True
    #: Future extension: capture only this process's audio via native WASAPI
    #: process-loopback (Win10 1903+). NOT implemented -> raises
    #: NotImplementedError if set.
    process_id: Optional[int] = None
    #: Optional auto-stop after this many seconds (wall-clock). Guarantees
    #: the stream ends even when no audio is playing (some WASAPI loopback
    #: endpoints emit no frames during silence), so consumers waiting on
    #: ``iter_chunks()`` always unblock.
    auto_stop_seconds: Optional[float] = None


class CaptureError(Exception):
    """Base error for the capture module."""


class WASAPINotAvailableError(CaptureError):
    """Raised when WASAPI is not available on the host system."""


class LoopbackDeviceNotFoundError(CaptureError):
    """Raised when no WASAPI loopback device could be resolved."""


class SystemAudioCapture:
    """Capture raw PCM system audio via WASAPI loopback (Windows only)."""

    def __init__(self, config: Optional[CaptureConfig] = None) -> None:
        self._config = config or CaptureConfig()
        if self._config.process_id is not None:
            raise NotImplementedError(
                "Per-process (per-application) loopback capture is not "
                "implemented yet. It requires native WASAPI process-loopback "
                "via ctypes/comtypes (Windows 10 1903+)."
            )

        self._pa: Optional[pyaudio.PyAudio] = None
        self._stream: Optional[pyaudio.Stream] = None
        self._queue: "queue.Queue[object]" = queue.Queue(maxsize=60)
        self._user_callback: Optional[Callable[[bytes, dict], None]] = None
        self._running = False
        self._lock = threading.Lock()

        self._device_info: Optional[dict] = None
        self.sample_rate: int = 0
        self.output_channels: int = 0

    # ------------------------------------------------------------------ #
    # Device discovery
    # ------------------------------------------------------------------ #
    def list_loopback_devices(self) -> list[dict]:
        """Return all available WASAPI loopback devices (for future UI)."""
        self._ensure_pa()
        assert self._pa is not None
        return list(self._pa.get_loopback_device_info_generator())

    def diagnose(self) -> dict:
        """Collect a diagnostic snapshot of the audio environment.

        Returns a dict with playback devices, loopback devices, the
        default loopback device that would be used, plus its sample rate
        and channel count. Prints a human-readable report to stdout.
        Useful for Sprint 2 validation on a real Windows machine.
        """
        self._ensure_pa()
        assert self._pa is not None

        playback = []
        try:
            wasapi_info = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_idx = wasapi_info["defaultOutputDevice"]
        except OSError:
            print("WASAPI is NOT available on this system.")
            return {"wasapi_available": False}

        for i in range(self._pa.get_device_count()):
            info = self._pa.get_device_info_by_index(i)
            if info.get("maxOutputChannels", 0) > 0:
                playback.append({
                    "index": info["index"],
                    "name": info["name"],
                    "defaultSampleRate": int(info["defaultSampleRate"]),
                    "maxOutputChannels": int(info["maxOutputChannels"]),
                    "isDefault": info["index"] == default_idx,
                })

        loopbacks = []
        for lb in self._pa.get_loopback_device_info_generator():
            loopbacks.append({
                "index": lb["index"],
                "name": lb["name"],
                "defaultSampleRate": int(lb["defaultSampleRate"]),
                "maxInputChannels": int(lb["maxInputChannels"]),
            })

        chosen = None
        try:
            chosen = self._resolve_loopback_device()
        except CaptureError as exc:
            print(f"Default loopback resolution failed: {exc}")

        print("=" * 60)
        print("AUDIO DIAGNOSTIC (WASAPI loopback)")
        print("=" * 60)
        print(f"WASAPI available: True")
        print(f"\nPlayback devices ({len(playback)}):")
        for d in playback:
            mark = " [DEFAULT]" if d["isDefault"] else ""
            print(f"  [{d['index']}] {d['name']}{mark}")
            print(f"        rate={d['defaultSampleRate']}Hz "
                  f"out_ch={d['maxOutputChannels']}")
        print(f"\nLoopback devices ({len(loopbacks)}):")
        for d in loopbacks:
            print(f"  [{d['index']}] {d['name']}")
            print(f"        rate={d['defaultSampleRate']}Hz "
                  f"in_ch={d['maxInputChannels']}")
        print("\nDefault capture target:")
        if chosen is not None:
            print(f"  [{chosen['index']}] {chosen['name']}")
            print(f"        rate={int(chosen['defaultSampleRate'])}Hz "
                  f"in_ch={int(chosen['maxInputChannels'])}")
        else:
            print("  (none resolved)")
        print("=" * 60)

        return {
            "wasapi_available": True,
            "playback_devices": playback,
            "loopback_devices": loopbacks,
            "default_loopback": chosen,
        }

    def _resolve_loopback_device(self) -> dict:
        assert self._pa is not None
        try:
            wasapi_info = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError as exc:
            raise WASAPINotAvailableError(
                "WASAPI is not available on this system. "
                "Capture requires Windows with a WASAPI audio stack."
            ) from exc

        default_speakers = self._pa.get_device_info_by_index(
            wasapi_info["defaultOutputDevice"]
        )

        name_filter = self._config.device_name
        if name_filter:
            candidate = None
            for loopback in self._pa.get_loopback_device_info_generator():
                if name_filter.lower() in loopback["name"].lower():
                    candidate = loopback
                    break
        elif default_speakers.get("isLoopbackDevice"):
            candidate = default_speakers
        else:
            candidate = None
            for loopback in self._pa.get_loopback_device_info_generator():
                if default_speakers["name"] in loopback["name"]:
                    candidate = loopback
                    break

        if candidate is None:
            raise LoopbackDeviceNotFoundError(
                "No WASAPI loopback device found. Run "
                "`python -m pyaudiowpatch` to inspect available devices."
            )
        return candidate

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """Open the loopback stream and begin capturing."""
        if self._running:
            return

        self._ensure_pa()
        device = self._resolve_loopback_device()
        self._device_info = device

        native_rate = int(device["defaultSampleRate"])
        native_channels = int(device["maxInputChannels"])
        self.sample_rate = native_rate
        self.output_channels = (
            1 if (self._config.mono_mix and native_channels == 2) else native_channels
        )

        def callback(in_data, frame_count, time_info, status):
            data: bytes = in_data
            if self._config.mono_mix and native_channels == 2:
                data = self._downmix_mono(in_data)
            if self._user_callback is not None:
                try:
                    self._user_callback(data, time_info)
                except Exception:
                    # Never let a consumer error kill the audio thread.
                    pass
            # Bounded queue: drop oldest chunk on overflow to bound latency.
            try:
                self._queue.put_nowait(data)
            except queue.Full:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._queue.put_nowait(data)
                except queue.Full:
                    pass
            return (in_data, pyaudio.paContinue)

        self._stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=native_channels,
            rate=native_rate,
            frames_per_buffer=self._config.chunk_size,
            input=True,
            input_device_index=device["index"],
            stream_callback=callback,
        )
        self._stream.start_stream()
        self._running = True

        # Auto-stop timer (best-effort). Ensures shutdown even during
        # silence when the loopback endpoint yields no frames.
        self._auto_stop_timer: Optional[threading.Timer] = None
        if self._config.auto_stop_seconds:
            self._auto_stop_timer = threading.Timer(
                self._config.auto_stop_seconds, self.stop
            )
            self._auto_stop_timer.daemon = True
            self._auto_stop_timer.start()

    def __enter__(self) -> "SystemAudioCapture":
        """Context-manager entry: start capturing.

        Use as::

            with SystemAudioCapture(cfg) as cap:
                for pcm in cap.iter_chunks():
                    ...
            # stop() is guaranteed to run on exit, even on exception.
        """
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Context-manager exit: always stop and release the device."""
        self.stop()
        return False  # do not suppress exceptions

    def stop(self) -> None:
        """Stop capturing and release the audio device.

        Idempotent: safe to call multiple times and from finally blocks.
        Always terminates the stream, signals generation consumers to exit,
        and releases the underlying PortAudio handle.
        """
        if not self._running and self._stream is None and self._pa is None:
            return
        with self._lock:
            self._running = False

        if self._auto_stop_timer is not None:
            try:
                self._auto_stop_timer.cancel()
            except Exception:
                pass
            self._auto_stop_timer = None

        if self._stream is not None:
            try:
                # abort() stops the stream immediately (does not wait for
                # buffered frames to drain), which avoids hanging when the
                # audio callback thread is still active.
                try:
                    self._stream.abort()
                except Exception:
                    pass
                self._stream.close()
            finally:
                self._stream = None

        # Drain the queue so a blocked iter_chunks() consumer cannot hang,
        # then signal it to terminate with the sentinel.
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
                # Never let teardown errors block shutdown.
                pass
            self._pa = None

    # ------------------------------------------------------------------ #
    # Consumption API
    # ------------------------------------------------------------------ #
    def register_callback(self, cb: Callable[[bytes, dict], None]) -> None:
        """Push mode: ``cb(pcm_bytes, time_info)`` is called per chunk."""
        self._user_callback = cb

    def iter_chunks(self, timeout: float = 1.0) -> Iterator[bytes]:
        """Pull mode: yield captured PCM chunks until ``stop()`` is called."""
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

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _ensure_pa(self) -> None:
        if self._pa is None:
            self._pa = pyaudio.PyAudio()

    @staticmethod
    def _downmix_mono(stereo_bytes: bytes) -> bytes:
        """Average interleaved int16 stereo -> int16 mono."""
        frame_count = len(stereo_bytes) // 4  # 2 channels * 2 bytes/sample
        samples = struct.unpack(f"<{frame_count * 2}h", stereo_bytes)
        mono = bytearray(frame_count * 2)
        for i in range(frame_count):
            left = samples[2 * i]
            right = samples[2 * i + 1]
            struct.pack_into("<h", mono, i * 2, (left + right) // 2)
        return bytes(mono)

    @property
    def is_running(self) -> bool:
        return self._running

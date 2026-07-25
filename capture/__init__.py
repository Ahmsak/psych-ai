"""Windows system audio capture module for PsychAI.

This module is intentionally dependency-isolated: it imports NOTHING from the
rest of the project (no UI, Orchestrator, Session, Memory, Validator, LLM).
Its single responsibility is to obtain raw PCM audio from the Windows audio
engine via WASAPI loopback.

Capture engine: ``pyaudiowpatch`` -- a PortAudio fork with WASAPI loopback
support. It records "what you hear" (the render endpoint mix) without
requiring a stereo-mix / "what you hear" virtual device.

The captured bytes are raw signed 16-bit little-endian PCM. Downstream
modules (Transcription) are responsible for resampling to the rate expected
by the speech model (e.g. 16 kHz mono for faster-whisper).
"""

from .capturer import (
    CaptureConfig,
    CaptureError,
    LoopbackDeviceNotFoundError,
    SystemAudioCapture,
    WASAPINotAvailableError,
)

__all__ = [
    "CaptureConfig",
    "CaptureError",
    "LoopbackDeviceNotFoundError",
    "SystemAudioCapture",
    "WASAPINotAvailableError",
]

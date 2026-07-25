"""Sprint 5 — Unified Audio Timeline experiment (mic + loopback).

Builds on Sprint 4 dual capture, adding:
  - a single unified audio format for BOTH streams (48 kHz, mono, PCM16);
  - per-stream timing (record start, first-frame time, duration);
  - metadata.json describing the run, ready for FUTURE track merging.

It does NOT merge/mix/synchronize tracks and does NOT analyze the dialog
(see SPEC-001, "Constraints"). Streams stay independent WAV files.

Why 48 kHz / mono / PCM16 as the unified format:
  - WASAPI loopback already delivers 48 kHz natively (no resampling of the
    remote party -> no quality loss on that side);
  - mono: speech is single-channel; halves data, matches Whisper input;
  - PCM16: lossless for our purposes, native output of both devices,
    directly writable to WAV; 16 kHz downsampling is left to the
    transcriber (Whisper) so the stored master keeps full 48 kHz.

Usage:
    python tools/run_timeline_experiment.py --language ru
    python tools/run_timeline_experiment.py --duration 60 --model small

Artifacts in experiments/<ts>_timeline/ (gitignored):
    mic.wav loopback.wav mic_transcription.txt loopback_transcription.txt
    metadata.json log.txt
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import threading
import time
import uuid
import wave
from datetime import datetime
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pyaudiowpatch as pyaudio

from capture import CaptureConfig, SystemAudioCapture
from transcription import StreamingTranscriber, TranscriptionConfig

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHUNK = 4096

# Unified target format (see module docstring for rationale).
UNIFIED_RATE = 48000
UNIFIED_CHANNELS = 1
UNIFIED_SAMPWIDTH = 2  # bytes (PCM int16)


def _rms(b: bytes) -> float:
    n = len(b) // 2
    if n == 0:
        return 0.0
    s = struct.unpack("<%dh" % n, b[: n * 2])
    return (sum(x * x for x in s) / n) ** 0.5


def to_unified(pcm: bytes, src_rate: int, src_channels: int) -> bytes:
    """Convert int16 PCM to UNIFIED format (48 kHz mono int16).

    Reuses linear resampling; downmix by averaging channels. Returns raw
    int16 little-endian bytes at UNIFIED_RATE, mono.
    """
    if not pcm:
        return b""
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if src_channels > 1:
        audio = audio.reshape(-1, src_channels).mean(axis=1)
    if src_rate != UNIFIED_RATE and audio.size:
        dst_len = int(round(audio.size * UNIFIED_RATE / src_rate))
        src_idx = np.linspace(0.0, audio.size - 1, num=dst_len)
        audio = np.interp(src_idx, np.arange(audio.size), audio)
    return np.clip(audio, -32768, 32767).astype(np.int16).tobytes()


class TimedMicRecorder:
    """Default-microphone recorder with timing, converts to unified format."""

    def __init__(self) -> None:
        self.pa = pyaudio.PyAudio()
        info = self.pa.get_default_input_device_info()
        self.device_name = info["name"]
        self.native_rate = int(info["defaultSampleRate"])
        self.native_channels = 1
        self.stream = self.pa.open(
            format=pyaudio.paInt16, channels=self.native_channels,
            rate=self.native_rate, frames_per_buffer=CHUNK, input=True,
            input_device_index=int(info["index"]))
        self.frames: List[bytes] = []          # unified-format frames
        self.rms_max = 0.0
        self.errors: List[str] = []
        self.record_start: Optional[float] = None
        self.first_frame_at: Optional[float] = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self.record_start = time.time()
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                data = self.stream.read(CHUNK, exception_on_overflow=False)
            except Exception as exc:
                self.errors.append(f"mic read failed: {exc!r}")
                break
            if self.first_frame_at is None:
                self.first_frame_at = time.time()
            unified = to_unified(data, self.native_rate, self.native_channels)
            self.frames.append(unified)
            r = _rms(unified)
            if r > self.rms_max:
                self.rms_max = r

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=3.0)
        try:
            self.stream.stop_stream()
            self.stream.close()
        finally:
            self.pa.terminate()


def _write_unified_wav(path: str, frames: List[bytes]) -> float:
    wf = wave.open(path, "wb")
    wf.setnchannels(UNIFIED_CHANNELS)
    wf.setsampwidth(UNIFIED_SAMPWIDTH)
    wf.setframerate(UNIFIED_RATE)
    for f in frames:
        wf.writeframes(f)
    wf.close()
    total = sum(len(f) for f in frames)
    return round(total / (UNIFIED_RATE * UNIFIED_SAMPWIDTH * UNIFIED_CHANNELS), 2)


def _transcribe_wav(path: str, model: str, language: Optional[str]) -> str:
    """Transcribe a unified WAV via the existing StreamingTranscriber."""
    tr = StreamingTranscriber(
        TranscriptionConfig(window_duration_sec=10.0, model_size=model,
                            language=language),
        input_sample_rate=UNIFIED_RATE, input_channels=UNIFIED_CHANNELS)
    tr.load_model()
    texts: List[str] = []
    wf = wave.open(path, "rb")
    try:
        while True:
            data = wf.readframes(UNIFIED_RATE)
            if not data:
                break
            texts += tr.feed(data)
    finally:
        wf.close()
        texts += tr.flush()
        tr.close()
    return "\n".join(texts)


def _iso(ts: Optional[float]) -> Optional[str]:
    return datetime.fromtimestamp(ts).isoformat() if ts else None


def main() -> None:
    p = argparse.ArgumentParser(description="Sprint 5 unified audio timeline")
    p.add_argument("--model", default="small")
    p.add_argument("--language", default=None)
    p.add_argument("--duration", type=float, default=None,
                   help="auto-stop after N seconds (default: until Ctrl+C)")
    args = p.parse_args()

    session_id = uuid.uuid4().hex[:12]
    created_at = datetime.now()
    base = os.path.join(ROOT, "experiments",
                        f"{created_at:%Y%m%d_%H%M%S}_timeline")
    os.makedirs(base, exist_ok=True)

    # Loopback (existing capture module, unchanged) -> unified frames.
    loop = SystemAudioCapture(CaptureConfig(mono_mix=True,
                                            auto_stop_seconds=args.duration))
    loop.start()
    loop_native_rate = loop.sample_rate
    loop_native_ch = loop.output_channels
    loop_frames: List[bytes] = []
    loop_state = {"rms_max": 0.0, "start": time.time(),
                  "first": None, "err": []}

    def loop_consumer():
        for pcm in loop.iter_chunks(timeout=0.5):
            if loop_state["first"] is None:
                loop_state["first"] = time.time()
            unified = to_unified(pcm, loop_native_rate, loop_native_ch)
            loop_frames.append(unified)
            r = _rms(unified)
            if r > loop_state["rms_max"]:
                loop_state["rms_max"] = r

    mic = TimedMicRecorder()

    print(f"[timeline] session={session_id} -> {base}")
    print(f"[timeline] unified format: {UNIFIED_RATE} Hz mono PCM16")
    print(f"[timeline] loopback native: {loop_native_rate} Hz {loop_native_ch}ch"
          f" '{loop._device_info['name']}'")
    print(f"[timeline] mic native:      {mic.native_rate} Hz"
          f" '{mic.device_name}'")

    t = threading.Thread(target=loop_consumer, daemon=True)
    mic.start()
    t.start()
    try:
        while t.is_alive():
            t.join(timeout=0.5)
    except KeyboardInterrupt:
        print("\n[timeline] Ctrl+C — stopping")
    finally:
        loop.stop()
        t.join(timeout=3.0)
        mic.stop()

    mic_wav = os.path.join(base, "mic.wav")
    loop_wav = os.path.join(base, "loopback.wav")
    mic_dur = _write_unified_wav(mic_wav, mic.frames)
    loop_dur = _write_unified_wav(loop_wav, loop_frames)

    print(f"[timeline] transcribing mic.wav ({mic_dur}s)...")
    mic_text = _transcribe_wav(mic_wav, args.model, args.language)
    print(f"[timeline] transcribing loopback.wav ({loop_dur}s)...")
    loop_text = _transcribe_wav(loop_wav, args.model, args.language)
    for name, text in (("mic_transcription.txt", mic_text),
                       ("loopback_transcription.txt", loop_text)):
        with open(os.path.join(base, name), "w", encoding="utf-8") as f:
            f.write(text)

    unified = {"sample_rate": UNIFIED_RATE, "channels": UNIFIED_CHANNELS,
               "sample_width_bytes": UNIFIED_SAMPWIDTH, "encoding": "pcm_s16le"}
    metadata = {
        "session_id": session_id,
        "created_at": created_at.isoformat(),
        "sprint": "5.0-unified-audio-timeline",
        "unified_format": unified,
        "note": "tracks are independent; NOT merged/synchronized/diarized",
        "microphone": {
            "role": "outgoing: local user's voice",
            "device": mic.device_name,
            "native_sample_rate": mic.native_rate,
            "native_channels": mic.native_channels,
            "stored_format": unified,
            "record_start": _iso(mic.record_start),
            "first_frame_at": _iso(mic.first_frame_at),
            "duration_sec": mic_dur,
            "rms_max": round(mic.rms_max, 1),
            "audio_captured": mic.rms_max > 1.0,
            "wav": "mic.wav",
            "transcription": "mic_transcription.txt",
            "errors": mic.errors,
        },
        "loopback": {
            "role": "incoming: remote party + system sounds",
            "device": loop._device_info["name"],
            "native_sample_rate": loop_native_rate,
            "native_channels": loop_native_ch,
            "stored_format": unified,
            "record_start": _iso(loop_state["start"]),
            "first_frame_at": _iso(loop_state["first"]),
            "duration_sec": loop_dur,
            "rms_max": round(loop_state["rms_max"], 1),
            "audio_captured": loop_state["rms_max"] > 1.0,
            "wav": "loopback.wav",
            "transcription": "loopback_transcription.txt",
            "errors": loop_state["err"],
        },
    }
    # Atomic write so a partial file never passes as valid metadata.
    tmp = os.path.join(base, "metadata.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    os.replace(tmp, os.path.join(base, "metadata.json"))

    log = (
        "=== Unified Audio Timeline ===\n"
        f"session:  {session_id}\n"
        f"unified:  {UNIFIED_RATE} Hz mono PCM16\n"
        f"MIC       dev='{mic.device_name}' native={mic.native_rate}Hz "
        f"dur={mic_dur}s rms={mic.rms_max:.1f} "
        f"captured={'YES' if mic.rms_max > 1.0 else 'NO'} "
        f"first_frame={_iso(mic.first_frame_at)}\n"
        f"LOOPBACK  dev='{loop._device_info['name']}' "
        f"native={loop_native_rate}Hz dur={loop_dur}s "
        f"rms={loop_state['rms_max']:.1f} "
        f"captured={'YES' if loop_state['rms_max'] > 1.0 else 'NO'} "
        f"first_frame={_iso(loop_state['first'])}\n"
        f"MIC transcription:      {len(mic_text)} chars\n"
        f"LOOPBACK transcription: {len(loop_text)} chars\n"
        f"Errors: mic={mic.errors or 'none'} loop={loop_state['err'] or 'none'}\n"
        f"Artifacts: {base}\n"
    )
    with open(os.path.join(base, "log.txt"), "w", encoding="utf-8") as f:
        f.write(log)
    print(log)


if __name__ == "__main__":
    main()

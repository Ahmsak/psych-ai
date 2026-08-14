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
import logging
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

from capture import (
    CaptureConfig,
    MicrophoneCapture,
    SystemAudioCapture,
    write_wav,
)
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


def _diag(thread_name: str, func: str, msg: str) -> None:
    ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    logging.debug(f"{ts} {thread_name} {func} {msg}")


def _make_unified_mic() -> MicrophoneCapture:
    """Microphone capture that stores frames in the UNIFIED format.

    The conversion that used to live inside ``TimedMicRecorder`` is now a
    ``transform`` passed to the product component (capture/mic.py).
    """
    mic = MicrophoneCapture(chunk_size=CHUNK, transform=to_unified)
    mic.set_output_format(UNIFIED_RATE, UNIFIED_CHANNELS)
    return mic


def _write_unified_wav(path: str, frames: List[bytes]) -> float:
    return write_wav(path, frames, UNIFIED_RATE, UNIFIED_CHANNELS, ndigits=2)


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


def _transcribe_segments(path: str, model: str, language: Optional[str]) -> list:
    """Transcribe a unified WAV and keep per-segment timing.

    Reuses the product file-transcriber so there is a single Whisper
    entrypoint. Returns a list of {start, end, text, confidence} using
    faster-whisper's native segment timestamps. Text is NOT modified.
    This is the data layer for the Conversation Builder (Sprint 7):
    timing is preserved, no analysis is performed.
    """
    from transcription import transcribe_file

    return transcribe_file(path, model_size=model, language=language)


def _iso(ts: Optional[float]) -> Optional[str]:
    return datetime.fromtimestamp(ts).isoformat() if ts else None


def main() -> None:
    _diag(threading.current_thread().name, "main", "entering")
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
        _diag(threading.current_thread().name, "loop_consumer", "entering")
        for pcm in loop.iter_chunks(timeout=0.5):
            if loop_state["first"] is None:
                loop_state["first"] = time.time()
            unified = to_unified(pcm, loop_native_rate, loop_native_ch)
            loop_frames.append(unified)
            r = _rms(unified)
            if r > loop_state["rms_max"]:
                loop_state["rms_max"] = r
        _diag(threading.current_thread().name, "loop_consumer", "exiting")

    mic = _make_unified_mic()

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
            _diag(threading.current_thread().name, "main", f"loop iter t.alive={t.is_alive()} running={loop._running} qsize={loop._queue.qsize()}")
            t.join(timeout=0.5)
            _diag(threading.current_thread().name, "main", f"after t.join t.alive={t.is_alive()}")
    except KeyboardInterrupt:
        print("\n[timeline] Ctrl+C — stopping")
    finally:
        _diag(threading.current_thread().name, "main", "entering finally")
        loop.stop()
        t.join(timeout=3.0)
        mic.stop()

    mic_wav = os.path.join(base, "mic.wav")
    loop_wav = os.path.join(base, "loopback.wav")
    mic_dur = _write_unified_wav(mic_wav, mic.frames)
    loop_dur = _write_unified_wav(loop_wav, loop_frames)

    print(f"[timeline] transcribing mic.wav ({mic_dur}s)...")
    mic_segs = _transcribe_segments(mic_wav, args.model, args.language)
    print(f"[timeline] transcribing loopback.wav ({loop_dur}s)...")
    loop_segs = _transcribe_segments(loop_wav, args.model, args.language)
    # INV-001 fix: derive transcription text from the SAME segment path so
    # the .txt and *_segments.json never disagree. The old StreamingTranscriber
    # path hallucinated text on near-silence, masking empty-segment tracks.
    mic_text = "\n".join(s["text"] for s in mic_segs)
    loop_text = "\n".join(s["text"] for s in loop_segs)
    for name, text in (("mic_transcription.txt", mic_text),
                       ("loopback_transcription.txt", loop_text)):
        with open(os.path.join(base, name), "w", encoding="utf-8") as f:
            f.write(text)
    # Per-segment timing (data layer for Conversation Builder, Sprint 7).
    for name, segs in (("mic_segments.json", mic_segs),
                       ("loopback_segments.json", loop_segs)):
        with open(os.path.join(base, name), "w", encoding="utf-8") as f:
            json.dump(segs, f, ensure_ascii=False, indent=2)

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
            "segments": "mic_segments.json",
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
            "segments": "loopback_segments.json",
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
    _diag(threading.current_thread().name, "main", "pre-enter finally=False")
    main()
    _diag(threading.current_thread().name, "main", "exited")

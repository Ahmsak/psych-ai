"""Sprint 4.0 — Step 2: dual capture experiment (mic + WASAPI loopback).

Captures BOTH streams simultaneously during one run:
  - default microphone        -> mic.wav        (local user's voice)
  - WASAPI loopback (output)  -> loopback.wav   (remote party)

After recording, each file is transcribed separately with the existing
faster-whisper pipeline:
  mic.wav      -> mic_transcription.txt
  loopback.wav -> loopback_transcription.txt

Usage:
    python tools/run_dual_experiment.py --language ru
    python tools/run_dual_experiment.py --duration 60 --model small

Stop with Ctrl+C (or automatically after --duration seconds).
Artifacts land in experiments/<ts>_dual/ (gitignored).
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import threading
import time
import wave
from datetime import datetime
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capture import (
    CaptureConfig,
    MicrophoneCapture,
    SystemAudioCapture,
    write_wav,
)
from transcription import StreamingTranscriber, TranscriptionConfig

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHUNK = 4096


def _rms(b: bytes) -> float:
    n = len(b) // 2
    if n == 0:
        return 0.0
    s = struct.unpack("<%dh" % n, b[: n * 2])
    return (sum(x * x for x in s) / n) ** 0.5


def _transcribe_wav(path: str, rate: int, model: str,
                    language: Optional[str]) -> str:
    """Transcribe a whole WAV via the existing StreamingTranscriber."""
    tr = StreamingTranscriber(
        TranscriptionConfig(window_duration_sec=10.0, model_size=model,
                            language=language),
        input_sample_rate=rate, input_channels=1)
    tr.load_model()
    texts: List[str] = []
    wf = wave.open(path, "rb")
    try:
        while True:
            data = wf.readframes(48000)
            if not data:
                break
            texts += tr.feed(data)
    finally:
        wf.close()
        texts += tr.flush()
        tr.close()
    return "\n".join(texts)


def main() -> None:
    p = argparse.ArgumentParser(description="Sprint 4.0 dual capture experiment")
    p.add_argument("--model", default="small")
    p.add_argument("--language", default=None)
    p.add_argument("--duration", type=float, default=None,
                   help="auto-stop after N seconds (default: until Ctrl+C)")
    args = p.parse_args()

    base = os.path.join(ROOT, "experiments", f"{datetime.now():%Y%m%d_%H%M%S}_dual")
    os.makedirs(base, exist_ok=True)

    # Loopback stream (existing capture module, unchanged).
    loop = SystemAudioCapture(CaptureConfig(mono_mix=True,
                                            auto_stop_seconds=args.duration))
    loop.start()
    loop_frames: List[bytes] = []
    loop_rms = {"max": 0.0}

    def loop_consumer():
        for pcm in loop.iter_chunks(timeout=0.5):
            loop_frames.append(pcm)
            r = _rms(pcm)
            if r > loop_rms["max"]:
                loop_rms["max"] = r

    # Microphone stream (product component, capture/mic.py).
    mic = MicrophoneCapture(chunk_size=CHUNK)

    print("[dual] loopback device:", loop._device_info["name"])
    print(f"[dual]   sr={loop.sample_rate} ch={loop.output_channels}")
    print("[dual] mic device:     ", mic.device_name)
    print(f"[dual]   sr={mic.native_rate} ch={mic.native_channels}")
    print(f"[dual] recording to {base}")
    print("[dual] speak AND play remote audio; Ctrl+C to stop"
          + (f" (auto-stop {args.duration}s)" if args.duration else ""))

    t = threading.Thread(target=loop_consumer, daemon=True)
    started = time.time()
    mic.start()
    t.start()
    try:
        while t.is_alive():
            t.join(timeout=0.5)  # ends when loopback auto-stops
    except KeyboardInterrupt:
        print("\n[dual] Ctrl+C — stopping")
    finally:
        loop.stop()
        t.join(timeout=3.0)
        mic.stop()
    wall = round(time.time() - started, 1)

    mic_wav = os.path.join(base, "mic.wav")
    loop_wav = os.path.join(base, "loopback.wav")
    mic_dur = write_wav(mic_wav, mic.frames, mic.native_rate,
                        mic.native_channels)
    loop_dur = write_wav(loop_wav, loop_frames, loop.sample_rate,
                         loop.output_channels)

    print(f"[dual] transcribing mic.wav ({mic_dur}s)...")
    mic_text = _transcribe_wav(mic_wav, mic.native_rate, args.model,
                               args.language)
    print(f"[dual] transcribing loopback.wav ({loop_dur}s)...")
    loop_text = _transcribe_wav(loop_wav, loop.sample_rate, args.model,
                                args.language)

    for name, text in (("mic_transcription.txt", mic_text),
                       ("loopback_transcription.txt", loop_text)):
        with open(os.path.join(base, name), "w", encoding="utf-8") as f:
            f.write(text)

    manifest = {
        "mode": "dual",
        "wall_duration_sec": wall,
        "mic": {"device": mic.device_name, "sample_rate": mic.native_rate,
                "channels": mic.native_channels, "duration_sec": mic_dur,
                "rms_max": round(mic.rms_max, 1),
                "audio_captured": mic.rms_max > 1.0,
                "errors": mic.errors,
                "role": "outgoing: local user's voice"},
        "loopback": {"device": loop._device_info["name"],
                     "sample_rate": loop.sample_rate,
                     "channels": loop.output_channels,
                     "duration_sec": loop_dur,
                     "rms_max": round(loop_rms["max"], 1),
                     "audio_captured": loop_rms["max"] > 1.0,
                     "errors": [],
                     "role": "incoming: remote party + system sounds"},
    }
    with open(os.path.join(base, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    log_lines = [
        "=== Dual Capture Summary ===",
        f"Wall duration: {wall}s",
        f"MIC      dev='{mic.device_name}' sr={mic.native_rate} "
        f"ch={mic.native_channels} dur={mic_dur}s rms_max={mic.rms_max:.1f} "
        f"captured={'YES' if mic.rms_max > 1.0 else 'NO'}",
        f"LOOPBACK dev='{loop._device_info['name']}' sr={loop.sample_rate} "
        f"ch={loop.output_channels} dur={loop_dur}s "
        f"rms_max={loop_rms['max']:.1f} "
        f"captured={'YES' if loop_rms['max'] > 1.0 else 'NO'}",
        f"MIC transcription:      {len(mic_text)} chars",
        f"LOOPBACK transcription: {len(loop_text)} chars",
        f"Errors: {mic.errors or 'none'}",
        f"Artifacts: {base}",
    ]
    log = "\n".join(log_lines) + "\n"
    with open(os.path.join(base, "log.txt"), "w", encoding="utf-8") as f:
        f.write(log)
    print(log)


if __name__ == "__main__":
    main()

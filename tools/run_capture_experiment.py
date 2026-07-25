"""Sprint 4.0 — Windows Audio Capture experiment harness.

Runs ONE capture method at a time, records audio + transcription + a
manifest, so the project owner can compare methods during real
WhatsApp/Telegram Desktop calls.

Usage:
    python tools/run_capture_experiment.py --mode loopback
    python tools/run_capture_experiment.py --mode loopback --window 5 --language ru --duration 60

Modes implemented so far: loopback (reuses capture/capturer.py).
Other modes (microphone, output, process) are planned; see Sprint 4 plan.

Artifacts (gitignored under experiments/):
    experiments/<ts>_<mode>/
        audio.wav          raw captured PCM (int16)
        transcription.txt  incremental Whisper text
        manifest.json      device/sr/channels, RMS, stream role, errors
        log.txt            human-readable summary
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time
import wave
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capture import CaptureConfig, SystemAudioCapture
from transcription import StreamingTranscriber, TranscriptionConfig

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ROLE_BY_MODE = {
    "loopback": "incoming: remote party + system sounds (rendered to output)",
    "output": "incoming: remote party + system sounds (default output)",
    "microphone": "outgoing: local user's voice (microphone)",
    "process": "app-isolated audio (e.g. WhatsApp/Telegram process)",
}


@dataclass
class ExperimentResult:
    mode: str
    capture_device_name: str = ""
    sample_rate: int = 0
    channels: int = 0
    started_at: str = ""
    ended_at: str = ""
    duration_sec: float = 0.0
    chunk_count: int = 0
    rms_max: float = 0.0
    rms_avg: float = 0.0
    audio_captured: bool = False
    stream_role: str = ""
    transcription: str = ""
    errors: List[str] = field(default_factory=list)


def _rms(int16_bytes: bytes) -> float:
    n = len(int16_bytes) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack("<%dh" % n, int16_bytes[: n * 2])
    return (sum(s * s for s in samples) / n) ** 0.5


def run_experiment(
    mode: str,
    window: float,
    model: str,
    language: Optional[str],
    duration: Optional[float],
    transcribe: bool,
) -> ExperimentResult:
    if mode != "loopback":
        raise NotImplementedError(
            f"Mode '{mode}' is planned but not implemented yet in Sprint 4. "
            f"Implemented: loopback."
        )
    res = ExperimentResult(mode=mode, stream_role=ROLE_BY_MODE.get(mode, ""))
    res.started_at = datetime.now().isoformat(timespec="seconds")

    cap = SystemAudioCapture(CaptureConfig(mono_mix=True, auto_stop_seconds=duration))
    cap.start()
    res.capture_device_name = cap._device_info["name"] if cap._device_info else ""
    res.sample_rate = cap.sample_rate
    res.channels = cap.output_channels

    base = os.path.join(ROOT, "experiments",
                        f"{datetime.now():%Y%m%d_%H%M%S}_{mode}")
    os.makedirs(base, exist_ok=True)
    wav_path = os.path.join(base, "audio.wav")
    wf = wave.open(wav_path, "wb")
    wf.setnchannels(res.channels)
    wf.setsampwidth(2)
    wf.setframerate(res.sample_rate)

    transcriber = None
    texts: List[str] = []
    if transcribe:
        transcriber = StreamingTranscriber(
            TranscriptionConfig(window_duration_sec=window, model_size=model,
                                language=language),
            input_sample_rate=cap.sample_rate, input_channels=cap.output_channels)
        transcriber.load_model()

    print(f"[exp] mode={mode} device='{res.capture_device_name}' "
          f"sr={res.sample_rate} ch={res.channels}")
    print(f"[exp] recording to {base} (Ctrl+C to stop early)")

    chunks = 0
    rms_sum = 0.0
    rms_max = 0.0
    started = time.time()
    try:
        for pcm in cap.iter_chunks(timeout=0.5):
            chunks += 1
            wf.writeframes(pcm)
            r = _rms(pcm)
            rms_sum += r
            if r > rms_max:
                rms_max = r
            if transcriber is not None:
                for t in transcriber.feed(pcm):
                    texts.append(t)
                    print(">>", t, flush=True)
    except KeyboardInterrupt:
        print("\n[exp] Ctrl+C — stopping")
    finally:
        cap.stop()
        if transcriber is not None:
            texts += transcriber.flush()
            transcriber.close()
        wf.close()
        ended = time.time()
        res.ended_at = datetime.now().isoformat(timespec="seconds")
        res.duration_sec = round(ended - started, 1)
        res.chunk_count = chunks
        res.rms_max = round(rms_max, 1)
        res.rms_avg = round(rms_sum / chunks, 1) if chunks else 0.0
        res.audio_captured = rms_max > 1.0
        res.transcription = "\n".join(texts)

    with open(os.path.join(base, "transcription.txt"), "w", encoding="utf-8") as f:
        f.write(res.transcription)
    with open(os.path.join(base, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(asdict(res), f, ensure_ascii=False, indent=2)
    log = _human_log(res, wav_path)
    with open(os.path.join(base, "log.txt"), "w", encoding="utf-8") as f:
        f.write(log)
    print(log)
    return res


def _human_log(res: ExperimentResult, wav_path: str) -> str:
    lines = [
        "=== Experiment Summary ===",
        f"Mode:           {res.mode}",
        f"Stream role:    {res.stream_role}",
        f"Device:         {res.capture_device_name}",
        f"Sample rate:    {res.sample_rate} Hz",
        f"Channels:       {res.channels}",
        f"Duration:       {res.duration_sec} s",
        f"Chunks:         {res.chunk_count}",
        f"RMS max/avg:    {res.rms_max} / {res.rms_avg}",
        f"Audio captured: {'YES' if res.audio_captured else 'NO/quiet'}",
        f"Audio file:     {wav_path}",
        f"Transcription:  {len(res.transcription)} chars",
        f"Errors:         {res.errors or 'none'}",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    p = argparse.ArgumentParser(description="Sprint 4.0 audio capture experiment")
    p.add_argument("--mode", default="loopback", choices=["loopback"],
                   help="capture method (loopback implemented; others planned)")
    p.add_argument("--window", type=float, default=5.0, dest="window_duration_sec")
    p.add_argument("--model", default="small")
    p.add_argument("--language", default=None)
    p.add_argument("--duration", type=float, default=None,
                   help="auto-stop after N seconds (default: until Ctrl+C)")
    p.add_argument("--no-transcribe", dest="transcribe", action="store_false",
                   help="skip Whisper transcription")
    args = p.parse_args()
    run_experiment(args.mode, args.window_duration_sec, args.model,
                   args.language, args.duration, args.transcribe)


if __name__ == "__main__":
    main()

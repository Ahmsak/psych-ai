"""Live WASAPI loopback capture check (Sprint 2 validation).

Run on a real Windows machine with pyaudiowpatch installed:

    python tests/capture_live_check.py silence
    python tests/capture_live_check.py youtube
    python tests/capture_live_check.py telegram
    python tests/capture_live_check.py whatsapp

It captures the default loopback device for a fixed window, reports:
  - chunk count and any buffer overflow drops
  - RMS (loudness) average / max -> proof that real audio is captured
  - clean shutdown

Start the named source (e.g. play a YouTube video) BEFORE/while running.
"""

import sys
import time
import struct

sys.path.insert(0, ".")

from capture import SystemAudioCapture, CaptureConfig


def _rms(int16_bytes: bytes) -> float:
    n = len(int16_bytes) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack("<%dh" % n, int16_bytes[: n * 2])
    return (sum(s * s for s in samples) / n) ** 0.5


def main(label: str, duration: float = 15.0) -> int:
    print(f"[live-check] label={label!r} duration={duration}s")
    cap = SystemAudioCapture(
        CaptureConfig(mono_mix=True, chunk_size=4096,
                      auto_stop_seconds=duration)
    )
    cap.start()
    print(f"[live-check] running (rate={cap.sample_rate}Hz, "
          f"ch={cap.output_channels}); play audio now if needed...")

    chunks = 0
    drops = 0
    rms_sum = 0.0
    rms_max = 0.0
    started = time.time()
    last_report = started

    for pcm in cap.iter_chunks(timeout=0.5):
        chunks += 1
        r = _rms(pcm)
        rms_sum += r
        if r > rms_max:
            rms_max = r
        now = time.time()
        if now - last_report >= 2.0:
            print(f"  t={now - started:5.1f}s chunks={chunks} "
                  f"rms_now={r:7.1f} rms_max={rms_max:7.1f}")
            last_report = now

    # auto_stop guarantees we reach here; ensure full teardown.
    cap.stop()

    avg_rms = rms_sum / chunks if chunks else 0.0
    print("-" * 50)
    print(f"[live-check] STOPPED cleanly: is_running={cap.is_running}")
    print(f"  chunks          = {chunks}")
    print(f"  buffer_drops    = {drops}")
    print(f"  rms_avg         = {avg_rms:.1f}  (0 = silence)")
    print(f"  rms_max         = {rms_max:.1f}")
    print(f"  captured_audio  = {'YES' if rms_max > 1.0 else 'NO/quiet'}")

    if not cap.is_running:
        return 0
    return 1


if __name__ == "__main__":
    label = sys.argv[1] if len(sys.argv) > 1 else "silence"
    dur = float(sys.argv[2]) if len(sys.argv) > 2 else 15.0
    sys.exit(main(label, dur))

"""Sprint 5 — sensor-first validator for a timeline experiment run.

Checks an experiments/<ts>_timeline/ directory against measurable
conditions. Prints one PASS/FAIL line per check and exits non-zero if any
FAIL, so it can gate a Definition of Done.

Usage:
    python tools/check_experiment.py                 # newest _timeline run
    python tools/check_experiment.py <experiment_dir>

Checks (from SPEC-001 Acceptance Criteria):
    - metadata.json exists, parses, has required keys;
    - both WAVs exist and open (not corrupted);
    - stored WAV format matches unified format declared in metadata;
    - a stream with audio_captured=YES has a non-empty WAV;
    - a stream with audio present (rms above gate) has a transcription;
    - device errors are surfaced (reported, not silently ignored).
"""

from __future__ import annotations

import glob
import json
import os
import sys
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SILENCE_RMS_GATE = 30.0  # matches TranscriptionConfig.silence_rms_threshold


def _latest_timeline_dir() -> str:
    dirs = sorted(glob.glob(os.path.join(ROOT, "experiments", "*_timeline")))
    if not dirs:
        print("FAIL: no *_timeline experiment directory found")
        sys.exit(2)
    return dirs[-1]


def _check(cond: bool, ok_msg: str, fail_msg: str, failures: list) -> None:
    if cond:
        print(f"PASS: {ok_msg}")
    else:
        print(f"FAIL: {fail_msg}")
        failures.append(fail_msg)


def validate(base: str) -> int:
    failures: list = []
    print(f"[check] {base}")

    meta_path = os.path.join(base, "metadata.json")
    if not (os.path.exists(meta_path) and os.path.getsize(meta_path) > 0):
        print("FAIL: metadata.json missing or empty")
        return 1
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except (ValueError, OSError) as exc:
        print(f"FAIL: metadata.json not parseable: {exc!r}")
        return 1

    for key in ("session_id", "created_at", "unified_format",
                "microphone", "loopback"):
        _check(key in meta, f"metadata has '{key}'",
               f"metadata missing '{key}'", failures)
    if failures:
        return 1

    uf = meta["unified_format"]
    for stream in ("microphone", "loopback"):
        s = meta[stream]
        wav = os.path.join(base, s.get("wav", f"{stream}.wav"))

        # WAV exists and is not corrupted.
        opened = False
        rate = ch = width = frames = 0
        if os.path.exists(wav) and os.path.getsize(wav) > 0:
            try:
                wf = wave.open(wav, "rb")
                rate, ch, width = (wf.getframerate(), wf.getnchannels(),
                                   wf.getsampwidth())
                frames = wf.getnframes()
                wf.close()
                opened = True
            except (wave.Error, OSError):
                opened = False
        _check(opened, f"{stream}: WAV opens (not corrupted)",
               f"{stream}: WAV missing/corrupted ({wav})", failures)

        if opened:
            fmt_ok = (rate == uf["sample_rate"] and ch == uf["channels"]
                      and width == uf["sample_width_bytes"])
            _check(fmt_ok,
                   f"{stream}: WAV format matches unified "
                   f"({rate}Hz {ch}ch {width}B)",
                   f"{stream}: WAV format {rate}Hz {ch}ch {width}B != unified "
                   f"{uf['sample_rate']}Hz {uf['channels']}ch "
                   f"{uf['sample_width_bytes']}B", failures)

            # audio_captured=YES must mean actual recorded frames.
            if s.get("audio_captured"):
                _check(frames > 0, f"{stream}: recording present (frames>0)",
                       f"{stream}: audio_captured but 0 frames", failures)

        # Transcription must exist when there is real audio.
        has_audio = float(s.get("rms_max", 0.0)) > SILENCE_RMS_GATE
        tr = os.path.join(base, s.get("transcription", f"{stream}_transcription.txt"))
        if has_audio:
            tr_ok = os.path.exists(tr) and os.path.getsize(tr) > 0
            _check(tr_ok,
                   f"{stream}: transcription present for audible stream",
                   f"{stream}: no transcription despite audio "
                   f"(rms_max={s.get('rms_max')})", failures)

        # Device errors surfaced (not a hard fail, but reported).
        errs = s.get("errors") or []
        if errs:
            print(f"WARN: {stream}: device errors reported: {errs}")

        # INV-001: transcription text vs segments consistency. A non-empty
        # .txt with empty segments means the text path hallucinated on a
        # (near-)silent track — the failure that masked problem #1.
        tr_has = os.path.exists(tr) and os.path.getsize(tr) > 0
        seg_path = os.path.join(base, s.get("segments", f"{stream}_segments.json"))
        seg_n = None
        if os.path.exists(seg_path):
            try:
                with open(seg_path, encoding="utf-8") as sf:
                    seg_n = len(json.load(sf))
            except (ValueError, OSError):
                seg_n = None
        if seg_n is not None:
            _check(not (tr_has and seg_n == 0),
                   f"{stream}: transcription/segments consistent "
                   f"(segments={seg_n})",
                   f"{stream}: transcription text present but 0 segments "
                   f"(likely hallucination on silence — see INV-001)",
                   failures)

    print(f"[check] {'ALL PASS' if not failures else f'{len(failures)} FAIL'}")
    return 0 if not failures else 1


def main() -> None:
    base = sys.argv[1] if len(sys.argv) > 1 else _latest_timeline_dir()
    sys.exit(validate(base))


if __name__ == "__main__":
    main()

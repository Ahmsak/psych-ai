"""PsychAI environment verification.

Run after environment setup, before development, and after any
dependency change:

    python tools/verify_environment.py

Checks Python, ffmpeg, Visual C++ runtime, PyAudioWPatch, ctranslate2,
faster-whisper, NumPy, PySide6, Hermes CLI and WASAPI availability,
then prints a summary report. Exit code 0 = all CORE checks passed.

Read-only: this script NEVER installs or modifies anything.
"""

from __future__ import annotations

import importlib
import platform
import shutil
import subprocess
import sys

OK, WARN, FAIL = "OK", "WARN", "FAIL"

# (name, required) — required=True means the MVP pipeline needs it.
results: list[tuple[str, str, str]] = []  # (name, status, details)


def record(name: str, status: str, details: str) -> None:
    results.append((name, status, details))


def check_python() -> None:
    v = sys.version_info
    detail = f"{platform.python_version()} at {sys.executable}"
    if v.major == 3 and v.minor == 12:
        record("Python 3.12", OK, detail)
    else:
        record("Python 3.12", WARN,
               f"{detail} (project targets 3.12; see docs/ENVIRONMENT.md)")


def check_import(mod: str, label: str, required: bool = True) -> bool:
    try:
        m = importlib.import_module(mod)
        ver = getattr(m, "__version__", "unknown version")
        record(label, OK, f"import ok ({ver})")
        return True
    except Exception as exc:  # noqa: BLE001 - report anything
        record(label, FAIL if required else WARN,
               f"import failed: {exc.__class__.__name__}: {exc}")
        return False


def check_command(cmd: str, label: str, args: list[str],
                  required: bool = True) -> None:
    path = shutil.which(cmd)
    if not path:
        record(label, FAIL if required else WARN, "not found in PATH")
        return
    try:
        out = subprocess.run([cmd, *args], capture_output=True, text=True,
                             timeout=30)
        first = (out.stdout or out.stderr).strip().splitlines()
        record(label, OK, first[0] if first else path)
    except Exception as exc:  # noqa: BLE001
        record(label, WARN, f"found at {path} but failed to run: {exc}")


def check_vcpp(ct2_ok: bool) -> None:
    # ctranslate2 links against the VC++ runtime; a successful import is
    # the practical proof that the runtime is present.
    if ct2_ok:
        record("Visual C++ runtime", OK,
               "implied by successful ctranslate2 import")
    else:
        record("Visual C++ runtime", WARN,
               "cannot confirm (ctranslate2 import failed)")


def check_wasapi(paw_ok: bool) -> None:
    if not paw_ok:
        record("WASAPI loopback", FAIL, "pyaudiowpatch not importable")
        return
    try:
        import pyaudiowpatch as pyaudio

        pa = pyaudio.PyAudio()
        try:
            pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            loopbacks = list(pa.get_loopback_device_info_generator())
            if loopbacks:
                record("WASAPI loopback", OK,
                       f"{len(loopbacks)} loopback device(s); "
                       f"e.g. {loopbacks[0]['name']}")
            else:
                record("WASAPI loopback", FAIL, "no loopback devices found")
        finally:
            pa.terminate()
    except Exception as exc:  # noqa: BLE001
        record("WASAPI loopback", FAIL, f"{exc.__class__.__name__}: {exc}")


def main() -> int:
    print("PsychAI environment verification")
    print(f"OS: {platform.platform()}")
    print("-" * 64)

    check_python()
    paw_ok = check_import("pyaudiowpatch", "PyAudioWPatch")
    ct2_ok = check_import("ctranslate2", "ctranslate2")
    check_import("faster_whisper", "faster-whisper")
    check_import("numpy", "NumPy")
    # GUI-only: MVP (run_stream.py) works without it.
    check_import("PySide6", "PySide6 (GUI only)", required=False)
    check_vcpp(ct2_ok)
    # faster-whisper uses the 'av' package, so system ffmpeg is optional.
    check_command("ffmpeg", "ffmpeg (optional)", ["-version"],
                  required=False)
    check_command("hermes", "Hermes CLI (dev tool)", ["--version"],
                  required=False)
    check_wasapi(paw_ok)

    print()
    width = max(len(n) for n, _, _ in results)
    fails = warns = 0
    for name, status, details in results:
        print(f"  [{status:^4}] {name:<{width}}  {details}")
        fails += status == FAIL
        warns += status == WARN

    print("-" * 64)
    if fails:
        print(f"RESULT: FAIL — {fails} critical problem(s), {warns} warning(s).")
        print("Do NOT auto-fix: report to the project owner first")
        print("(see docs/ENVIRONMENT.md, section 'Правила').")
        return 1
    if warns:
        print(f"RESULT: OK with {warns} warning(s) — MVP pipeline is usable.")
        print("Details for known warnings: docs/ENVIRONMENT.md.")
        return 0
    print("RESULT: OK — environment fully operational.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

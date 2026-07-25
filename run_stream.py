"""Sprint 3 MVP entry point: streaming system-audio transcription.

Pipeline: Windows loopback -> capture/ -> transcription/ -> console,
coordinated by the Orchestrator (no direct module-to-module links).

Usage:
    python run_stream.py                 # window 5s, model small, autodetect
    python run_stream.py --window 3
    python run_stream.py --model tiny --language ru

Stop with Ctrl+C: capture and transcription are shut down cleanly.
"""

import argparse

from orchestrator.orchestrator import Orchestrator


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PsychAI streaming transcription MVP (Sprint 3)")
    parser.add_argument("--window", type=float, default=5.0,
                        dest="window_duration_sec", metavar="SEC",
                        help="transcription window in seconds (default: 5)")
    parser.add_argument("--model", default="small",
                        help="faster-whisper model size (default: small)")
    parser.add_argument("--language", default=None,
                        help="language hint, e.g. 'ru' (default: autodetect)")
    args = parser.parse_args()

    orchestrator = Orchestrator()
    orchestrator.run_transcription_stream(
        window_duration_sec=args.window_duration_sec,
        model_size=args.model,
        language=args.language,
    )


if __name__ == "__main__":
    main()

"""Manual error-path check for the recording slice (real Orchestrator).

Exercises the failure scenarios end-to-end against the real
Orchestrator/Session/store, forcing the capture failure by monkeypatching
the capturer factory. Not a pytest test -- run it by hand:

    python tools/check_recording_errors.py --db data/errors_check.db
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator.orchestrator import Orchestrator

OK = "OK  "
BAD = "FAIL"


def _counts(db_path: str) -> tuple[int, int]:
    if not os.path.exists(db_path):
        return (0, 0)
    c = sqlite3.connect(db_path)
    try:
        s = c.execute("select count(*) from sessions").fetchone()[0]
        t = c.execute("select count(*) from audio_tracks").fetchone()[0]
    except sqlite3.OperationalError:
        return (0, 0)
    finally:
        c.close()
    return (s, t)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="data/errors_check.db")
    p.add_argument("--recordings", default="recordings/_errcheck")
    args = p.parse_args()
    db = os.path.abspath(args.db)
    failures = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        print(f"[{OK if cond else BAD}] {name}" + (f" -- {detail}" if detail else ""))
        if not cond:
            failures.append(name)

    # 1. Stop before any Start.
    orch = Orchestrator(recordings_dir=args.recordings, db_path=db)
    st = orch.stop_recording()
    check("Stop before Start is safe",
          st["is_recording"] is False and st["state"] == "idle", str(st))
    check("Stop before Start wrote nothing", _counts(db) == (0, 0),
          f"rows={_counts(db)}")

    # 2. Capture that fails to start (real Orchestrator path).
    import capture

    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("simulated device failure")

    orig_mic = capture.MicrophoneCapture
    capture.MicrophoneCapture = Boom
    try:
        st = orch.start_recording()
    finally:
        capture.MicrophoneCapture = orig_mic
    check("Capture start failure -> not recording",
          st["is_recording"] is False, str(st))
    check("Capture start failure -> state failed",
          st["state"] == "failed", str(st))
    check("Capture start failure -> no DB rows", _counts(db) == (0, 0),
          f"rows={_counts(db)}")

    # 3. Stop right after the failed Start.
    st = orch.stop_recording()
    check("Stop after failed Start is safe",
          st["is_recording"] is False, str(st))

    # 4. Successful Start after a failure (next run not broken).
    st = orch.start_recording()
    started_ok = st["is_recording"] is True
    check("Start works after a failure", started_ok, str(st))

    # 5. Second Start while recording.
    if started_ok:
        st2 = orch.start_recording()
        check("Second Start refused",
              st2["error"] == "session is already recording"
              and st2["is_recording"] is True, str(st2))
        sessions_before = _counts(db)[0]
        check("Second Start created no extra session row",
              sessions_before == 1, f"sessions={sessions_before}")

        # 6. Stop -> completed + 2 tracks; second Stop is a no-op.
        st3 = orch.stop_recording()
        check("Stop completes the session", st3["state"] == "completed", str(st3))
        check("Stop persisted 1 session + 2 tracks", _counts(db) == (1, 2),
              f"rows={_counts(db)}")
        st4 = orch.stop_recording()
        check("Second Stop is a no-op", st4["is_recording"] is False
              and _counts(db) == (1, 2), f"rows={_counts(db)}")

    print()
    print("RESULT:", "ALL CHECKS PASSED" if not failures
          else f"FAILURES: {failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

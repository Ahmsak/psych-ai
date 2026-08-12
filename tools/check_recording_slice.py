"""Manual end-to-end check of the recording slice (real devices).

Not a pytest test: it opens the real microphone and WASAPI loopback for a
few seconds, exactly like the UI buttons do, and prints what landed in
SQLite. Run it on the target Windows machine:

    python tools/check_recording_slice.py --seconds 3
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import get_engine, get_session_factory
from db.repositories import AudioTrackRepository, SessionRepository
from orchestrator.orchestrator import Orchestrator


def main() -> int:
    p = argparse.ArgumentParser(description="Recording slice smoke check")
    p.add_argument("--seconds", type=float, default=3.0)
    p.add_argument("--db", default=None, help="DB path (default data/psychai.db)")
    p.add_argument("--recordings", default=None)
    args = p.parse_args()

    orch = Orchestrator(recordings_dir=args.recordings, db_path=args.db)

    print("[check] START ->", orch.start_recording())
    if not orch.session_state()["is_recording"]:
        print("[check] FAILED to start:", orch.session_state()["error"])
        return 1

    time.sleep(args.seconds)
    print(f"[check] elapsed from Session: "
          f"{orch.session_state()['elapsed_sec']:.1f}s")

    state = orch.stop_recording()
    print("[check] STOP  ->", state)

    engine = get_engine(args.db)
    with get_session_factory(engine)() as db:
        row = SessionRepository(db).get(state["session_id"])
        tracks = AudioTrackRepository(db).get_by_session(row.id)
        print(f"[check] session #{row.id} status={row.status} "
              f"started={row.started_at} ended={row.ended_at}")
        for t in tracks:
            exists = os.path.exists(t.file_path) if t.file_path else False
            size = os.path.getsize(t.file_path) if exists else 0
            print(f"[check]   track {t.source:<10} dur={t.duration}s "
                  f"sr={t.sample_rate} ch={t.channels} "
                  f"wav_exists={exists} bytes={size}")
        ok = (row.status == "completed"
              and {t.source for t in tracks} == {"microphone", "loopback"})
    print("[check] RESULT:", "OK" if ok else "PROBLEM")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

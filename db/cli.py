"""CLI for the PsychAI persistence layer.

Usage:
    python -m db.cli init
    python -m db.cli import experiments/20260812_095907_timeline
    python -m db.cli stats
    python -m db.cli show <session_id>
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from db.database import get_db_path, get_engine, get_session_factory, init_db
from db.importer import import_experiment
from db.migrations import get_schema_version


def _cmd_init(args: argparse.Namespace) -> int:
    engine = get_engine(args.db)
    init_db(engine)
    path = get_db_path(args.db)
    ver = get_schema_version(engine)
    print(f"DB initialized: {path}")
    print(f"Schema version: {ver}")
    return 0


def _cmd_import(args: argparse.Namespace) -> int:
    engine = get_engine(args.db)
    init_db(engine)  # ensure tables exist
    factory = get_session_factory(engine)

    whisper_model = args.model or None

    with factory() as session:
        result = import_experiment(
            args.experiment_dir, session, whisper_model=whisper_model
        )
        if result.skipped:
            print(
                f"SKIP: experiment already imported "
                f"(session_id={result.session_id}, "
                f"source={result.source_session_id})"
            )
        else:
            print(
                f"IMPORT OK: session_id={result.session_id} "
                f"source={result.source_session_id}"
            )
            print(f"  audio_tracks:       {result.audio_tracks}")
            print(f"  transcript_segments: {result.transcript_segments}")
            print(f"  dialogue_utterances: {result.dialogue_utterances}")
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    from sqlalchemy import text

    engine = get_engine(args.db)
    if not get_db_path(args.db).exists():
        print("DB not found. Run 'init' first.")
        return 1

    with engine.connect() as conn:
        ver = get_schema_version(engine)
        print(f"DB: {get_db_path(args.db)}")
        print(f"Schema version: {ver}")
        print()

        tables = [
            "clients",
            "sessions",
            "audio_tracks",
            "transcript_segments",
            "dialogue_utterances",
            "dialogue_utterance_segments",
            "analyses",
        ]
        for t in tables:
            try:
                count = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
                print(f"  {t:30s} {count}")
            except Exception:
                print(f"  {t:30s} (table not found)")

        db_size = get_db_path(args.db).stat().st_size
        print(f"\n  DB file size: {db_size:,} bytes ({db_size / 1024 / 1024:.2f} MB)")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    from db.repositories import (
        AudioTrackRepository,
        DialogueRepository,
        SessionRepository,
        TranscriptRepository,
    )

    engine = get_engine(args.db)
    factory = get_session_factory(engine)
    with factory() as session:
        sess_repo = SessionRepository(session)
        sess = sess_repo.get(args.session_id)
        if not sess:
            print(f"Session id={args.session_id} not found")
            return 1

        print(f"Session id={sess.id}")
        print(f"  source_session_id: {sess.source_session_id}")
        print(f"  source:            {sess.source}")
        print(f"  status:            {sess.status}")
        print(f"  started_at:        {sess.started_at}")
        print(f"  client_id:         {sess.client_id}")

        tracks = AudioTrackRepository(session).get_by_session(sess.id)
        print(f"\n  Audio tracks ({len(tracks)}):")
        for t in tracks:
            print(
                f"    [{t.id}] {t.source:12s} "
                f"dur={t.duration}s sr={t.sample_rate} "
                f"path={'<set>' if t.file_path else '<none>'}"
            )

        segs = TranscriptRepository(session).get_by_session(sess.id)
        print(f"\n  Transcript segments ({len(segs)}):")
        if segs:
            s0 = segs[0]
            print(f"    first: [{s0.id}] {s0.speaker} {s0.start}-{s0.end} "
                  f"conf={s0.confidence}")
            sN = segs[-1]
            print(f"    last:  [{sN.id}] {sN.speaker} {sN.start}-{sN.end} "
                  f"conf={sN.confidence}")

        utts = DialogueRepository(session).get_by_session(sess.id)
        print(f"\n  Dialogue utterances ({len(utts)}):")
        if utts:
            u0 = utts[0]
            print(f"    first: [{u0.id}] {u0.speaker} {u0.start}-{u0.end}")
            uN = utts[-1]
            print(f"    last:  [{uN.id}] {uN.speaker} {uN.start}-{uN.end}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m db.cli",
        description="PsychAI persistence CLI",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Path to SQLite DB (default: data/psychai.db)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Initialize the database")
    p_init.set_defaults(func=_cmd_init)

    p_import = sub.add_parser("import", help="Import an experiment directory")
    p_import.add_argument("experiment_dir", help="Path to experiment directory")
    p_import.add_argument(
        "--model",
        default=None,
        help="Whisper model name to stamp on segments",
    )
    p_import.set_defaults(func=_cmd_import)

    p_stats = sub.add_parser("stats", help="Show database statistics")
    p_stats.set_defaults(func=_cmd_stats)

    p_show = sub.add_parser("show", help="Show session details")
    p_show.add_argument("session_id", type=int)
    p_show.set_defaults(func=_cmd_show)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

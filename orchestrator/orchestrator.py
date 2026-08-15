import os
from datetime import datetime
from typing import Optional

from session.session import Session


class Orchestrator:
    def __init__(self, recordings_dir: Optional[str] = None,
                 db_path: Optional[str] = None):
        self.session = Session()
        self._recordings_dir = recordings_dir
        self._db_path = db_path
        self._store = None

    def start_session(self):
        print("Orchestrator: starting session")
        self.session.start()

    # ------------------------------------------------------------------ #
    # Sprint 10: live recording lifecycle (UI -> Orchestrator -> Session
    # -> Capture / Persistence). The Orchestrator only coordinates: it
    # creates the capturers and the store, hands them to the Session and
    # translates failures into a state the UI can render. No business
    # logic, no PCM, no SQL.
    # ------------------------------------------------------------------ #
    def start_recording(self, client_id: Optional[int] = None) -> dict:
        """Start a live recording session. Returns the new state.

        ``client_id`` optionally binds the new session to a Client (Sprint 16).
        """
        if self.session.is_recording:
            return self._state(error="session is already recording")

        # Heavy / platform imports kept local so GUI startup stays fast.
        from capture import (
            CaptureConfig,
            MicrophoneCapture,
            RecordedTrack,
            SystemAudioCapture,
        )
        from db.session_store import SessionStore

        base = self._new_recording_dir()
        mic = None
        loop = None
        try:
            mic = MicrophoneCapture()
            loop = SystemAudioCapture(CaptureConfig(mono_mix=True))
            tracks = [
                RecordedTrack("microphone", mic,
                              os.path.join(base, "mic.wav")),
                RecordedTrack("loopback", loop,
                              os.path.join(base, "loopback.wav")),
            ]
            if self._store is None:
                self._store = SessionStore(self._db_path)
            self.session = Session()
            self.session.start_recording(tracks, self._store, client_id=client_id)
        except Exception as exc:
            # Coordination duty: release whatever was created.
            for cap in (mic, loop):
                if cap is not None:
                    try:
                        cap.stop()
                    except Exception:
                        pass
            return self._state(error=str(exc), failed=True)
        return self._state()

    def stop_recording(self) -> dict:
        """Stop the live session (safe when nothing is recording)."""
        try:
            self.session.stop_recording()
        except Exception as exc:
            return self._state(error=str(exc), failed=True)
        return self._state()

    def session_state(self) -> dict:
        """Current state for the UI (single source of truth: the Session)."""
        return self._state()

    # -- internals ------------------------------------------------------ #
    def _state(self, error: Optional[str] = None,
               failed: bool = False) -> dict:
        s = self.session
        return {
            "state": "failed" if failed else s.state,
            "is_recording": s.is_recording,
            "elapsed_sec": s.elapsed_sec,
            "session_id": s.record_id,
            "error": error or s.error,
        }

    def transcribe_session(
        self,
        session_id: Optional[int] = None,
        model: str = "small",
        language: Optional[str] = None,
    ) -> dict:
        """Post-stop transcription of a completed live session.

        The recording must be finished (status == "completed"). The
        Orchestrator coordinates: read the session's audio tracks from the
        store, run the file transcriber per track, persist RAW
        TranscriptSegments, and update the session status. It holds no
        transcription logic and never touches PCM or SQL directly (both
        stay behind the transcription module and the persistence port).

        Args:
            session_id: live session id. Defaults to the current session.
            model: faster-whisper model size (default "small").
            language: optional language hint (default None = autodetect).

        Returns a state dict:
            {"session_id", "status", "tracks", "error"}
        where ``tracks`` is a list of
            {"source", "segments", "skipped", "error"}.
        """
        if session_id is None:
            session_id = self.session.record_id
        if session_id is None:
            return self._transcribe_state(
                session_id=None,
                status="no_session",
                tracks=[],
                error="no session id available",
            )

        from db.session_store import SessionStore

        if self._store is None:
            self._store = SessionStore(self._db_path)

        status = self._store.get_session_status(session_id)
        # Transcription is only valid for a finished recording. A
        # partially-transcribed session (re-run) is allowed: existing
        # tracks keep their segments; only empty tracks are filled.
        if status not in ("completed", "transcribed_partial"):
            return self._transcribe_state(
                session_id=session_id,
                status=status,
                tracks=[],
                error=f"session is not ready for transcription "
                      f"(status={status})",
            )

        from transcription import transcribe_file

        tracks = self._store.get_tracks(session_id)
        self._store.set_session_status(session_id, "transcribing")

        results = []
        any_ok = False
        any_err = False
        for trk in tracks:
            src = trk["source"]
            path = trk["file_path"]
            if not path or not os.path.exists(path):
                results.append(
                    {"source": src, "segments": 0, "skipped": 0,
                     "error": "audio file missing"})
                any_err = True
                continue
            try:
                segs = transcribe_file(
                    path,
                    model_size=model,
                    language=language,
                    vad_filter=(src != "loopback"),
                )
                written = self._store.add_transcript_segments(
                    session_id=session_id,
                    audio_track_id=trk["id"],
                    source=src,
                    model=model,
                    segments=segs,
                )
                skipped = 1 if written == 0 else 0
                results.append(
                    {"source": src, "segments": written, "skipped": skipped,
                     "error": None})
                if written or skipped:
                    any_ok = True
            except Exception as exc:
                results.append(
                    {"source": src, "segments": 0, "skipped": 0,
                     "error": str(exc)})
                any_err = True

        if any_err and not any_ok:
            self._store.set_session_status(session_id, "transcription_failed")
            final_status = "transcription_failed"
        elif any_err:
            self._store.set_session_status(session_id, "transcribed_partial")
            final_status = "transcribed_partial"
        else:
            self._store.set_session_status(session_id, "transcribed")
            final_status = "transcribed"

        return self._transcribe_state(
            session_id=session_id, status=final_status, tracks=results)

    def build_dialogue(
        self,
        session_id: Optional[int] = None,
    ) -> dict:
        """Build a structured Dialogue from the session's TranscriptSegments.

        Requires status == "transcribed" (post-stop transcription finished).
        The Orchestrator coordinates: read RAW TranscriptSegments from the
        store, run the dialogue builder (pure, no DB), persist
        DialogueUtterances through the store port, and update the session
        status. It holds no dialogue-building logic and never touches SQL
        directly (stays behind the persistence port).

        Speaker is assigned by source track (microphone->psychologist,
        loopback->client) inside the builder -- NOT diarization. Timestamps
        are track-relative (verbatim from TranscriptSegment), NOT a
        cross-track aligned session timeline (ADR-007 alignment is future).

        Returns a state dict:
            {"session_id", "status", "utterances", "error"}
        """
        if session_id is None:
            session_id = self.session.record_id
        if session_id is None:
            return self._dialogue_state(
                session_id=None, status="no_session", utterances=0,
                error="no session id available",
            )

        from db.session_store import SessionStore

        if self._store is None:
            self._store = SessionStore(self._db_path)

        status = self._store.get_session_status(session_id)
        if status != "transcribed":
            return self._dialogue_state(
                session_id=session_id, status=status, utterances=0,
                error=f"session is not ready for dialogue building "
                      f"(status={status})",
            )

        from dialogue.builder import build_dialogue, validate_dialogue
        from dialogue.model import Dialogue

        # Group RAW segments by source track (microphone / loopback).
        segs = self._store.get_transcript_segments(session_id)
        by_source: dict = {}
        for s in segs:
            by_source.setdefault(s["source"] or s["speaker"], []).append(s)

        dialogue: Dialogue = build_dialogue(by_source)
        failures = validate_dialogue(dialogue)
        if failures:
            self._store.set_session_status(session_id, "dialogue_failed")
            return self._dialogue_state(
                session_id=session_id, status="dialogue_failed",
                utterances=0, error="; ".join(failures),
            )

        written = self._store.add_dialogue_utterances(
            session_id=session_id,
            utterances=[u.to_dict() for u in dialogue.utterances],
        )
        self._store.set_session_status(session_id, "dialogued")
        return self._dialogue_state(
            session_id=session_id, status="dialogued", utterances=written)

    # ------------------------------------------------------------------ #
    # Sprint 13: session viewer (read-only). Thin delegates to the store
    # port. The Orchestrator holds no viewing logic and never touches the
    # DB directly — it only forwards to SessionStore (which returns plain
    # dicts, never ORM objects).
    # ------------------------------------------------------------------ #
    def list_sessions(self) -> list[dict]:
        """List existing sessions for the viewer UI."""
        if self._store is None:
            from db.session_store import SessionStore
            self._store = SessionStore(self._db_path)
        return self._store.list_sessions()

    def get_session(self, session_id: int) -> Optional[dict]:
        """Return one session (details + track summary) for the viewer, or None."""
        if self._store is None:
            from db.session_store import SessionStore
            self._store = SessionStore(self._db_path)
        return self._store.get_session(session_id)

    def get_dialogue(self, session_id: int) -> list[dict]:
        """Return the built Dialogue of a session for the viewer, or None."""
        if self._store is None:
            from db.session_store import SessionStore
            self._store = SessionStore(self._db_path)
        return self._store.get_dialogue(session_id)

    # ------------------------------------------------------------------ #
    # Sprint 16: client layer (grouping sessions by client). Thin delegates
    # to the store port; the Orchestrator stays the single coordination
    # point and the UI never imports db/SQLAlchemy directly.
    # ------------------------------------------------------------------ #
    def list_clients(self) -> list[dict]:
        """List clients for the viewer UI."""
        if self._store is None:
            from db.session_store import SessionStore
            self._store = SessionStore(self._db_path)
        return self._store.list_clients()

    def create_client(self, name: str) -> dict:
        """Create a client with a stable global sequential number; return it."""
        if self._store is None:
            from db.session_store import SessionStore
            self._store = SessionStore(self._db_path)
        client = self._store.create_client(name)
        return {
            "id": int(client.id),
            "display_name": client.display_name,
            "client_number": client.client_number,
        }

    def get_client(self, client_id: int) -> Optional[dict]:
        """Return one client as a plain dict, or None."""
        if self._store is None:
            from db.session_store import SessionStore
            self._store = SessionStore(self._db_path)
        from db.repositories import ClientRepository
        with self._store._factory() as db:
            c = ClientRepository(db).get(client_id)
            if c is None:
                return None
            return {
                "id": int(c.id),
                "display_name": c.display_name,
                "client_number": c.client_number,
            }

    def list_client_sessions(self, client_id: int) -> list[dict]:
        """List sessions of one client (excludes others)."""
        if self._store is None:
            from db.session_store import SessionStore
            self._store = SessionStore(self._db_path)
        return self._store.list_client_sessions(client_id)

    # ------------------------------------------------------------------ #
    # Sprint 17: LLM analysis vertical slice (delegates to the store port).
    # ------------------------------------------------------------------ #
    def get_analysis(self, session_id: int) -> Optional[dict]:
        """Return the latest Analysis of a session, or None (read-only)."""
        if self._store is None:
            from db.session_store import SessionStore
            self._store = SessionStore(self._db_path)
        return self._store.get_analysis(session_id)

    def analyze_session(
        self,
        session_id: Optional[int] = None,
        prompt_version: Optional[str] = None,
    ) -> dict:
        """Run the supervisor analysis for a session and persist the result.

        Args:
            session_id: target session id. Defaults to the current session.
            prompt_version: override the prompt version (default PROMPT_VERSION).

        Returns a state dict:
            {"session_id", "status", "provider", "model",
             "prompt_version", "created_at", "text", "error"}
        where ``status`` is one of: "analyzed", "no_transcript", "error".
        """
        if session_id is None:
            session_id = self.session.record_id
        if session_id is None:
            return self._analysis_state(
                session_id=None, status="no_session",
                error="no session id available")
        if self._store is None:
            from db.session_store import SessionStore
            self._store = SessionStore(self._db_path)

        from llm.transcript_format import format_raw_transcript
        from llm.prompt import PROMPT_VERSION, build_analysis_prompt

        # RAW transcript is the sole source of truth (not Dialogue).
        segments = self._store.get_transcript_segments(session_id)
        raw_text = format_raw_transcript(segments)
        if not raw_text.strip():
            return self._analysis_state(
                session_id=session_id, status="no_transcript",
                error="session has no RAW transcript to analyze")

        prompt = build_analysis_prompt(raw_text)
        pv = prompt_version or PROMPT_VERSION

        try:
            from llm.config import load_llm_config
            from llm.contract import AnalysisRequest
            from llm.provider_factory import get_provider

            config = load_llm_config()
            provider = get_provider(config)
            request = AnalysisRequest(
                prompt=prompt, model=config.model, prompt_version=pv)
            result = provider.analyze(request)
        except Exception as exc:
            return self._analysis_state(
                session_id=session_id, status="error", error=str(exc))

        row_id = self._store.save_analysis(
            session_id=session_id,
            provider=result.provider,
            model=result.model,
            prompt_version=result.prompt_version,
            text=result.text,
        )
        return self._analysis_state(
            session_id=session_id,
            status="analyzed",
            provider=result.provider,
            model=result.model,
            prompt_version=result.prompt_version,
            created_at=result.created_at,
            text=result.text,
            analysis_id=row_id,
        )

    def _analysis_state(
        self,
        *,
        session_id: Optional[int],
        status: Optional[str],
        provider: Optional[str] = None,
        model: Optional[str] = None,
        prompt_version: Optional[str] = None,
        created_at=None,
        text: Optional[str] = None,
        analysis_id: Optional[int] = None,
        error: Optional[str] = None,
    ) -> dict:
        return {
            "session_id": session_id,
            "status": status,
            "provider": provider,
            "model": model,
            "prompt_version": prompt_version,
            "created_at": created_at,
            "text": text,
            "analysis_id": analysis_id,
            "error": error,
        }

    # ------------------------------------------------------------------ #
    # Sprint 14: automatic post-stop processing (single entry point).
    # Thin composition of transcribe_session + build_dialogue. No recovery
    # logic: a session left in a transient/failed state stays as-is and is
    # reported honestly by the existing transcribe/build guards (a full
    # crash-recovery mechanism is a separate future task).
    # ------------------------------------------------------------------ #
    def process_session(
        self,
        session_id: Optional[int] = None,
        on_stage: Optional[callable] = None,
    ) -> dict:
        """Run transcription then dialogue-building for a completed session.

        Intended to be called automatically after Stop. Thin composition of the
        two existing operations; no recovery logic: a session left in a
        transient/failed state stays as-is and is reported honestly by the
        existing transcribe/build guards (a full crash-recovery mechanism is a
        separate future task).

        ``on_stage`` is an optional callback(str) invoked with the stage name
        ("transcribing" / "building_dialogue") so a UI can reflect progress
        without polling the DB. It is a pure hook: no business logic depends
        on it.

        Returns the final state dict from build_dialogue (or transcribe if
        dialogue was skipped due to a non-transcribed result).
        """
        if session_id is None:
            session_id = self.session.record_id
        if session_id is None:
            return self._dialogue_state(
                session_id=None, status="no_session", utterances=0,
                error="no session id available",
            )

        if self._store is None:
            from db.session_store import SessionStore
            self._store = SessionStore(self._db_path)

        if on_stage is not None:
            on_stage("transcribing")
        transcribe_result = self.transcribe_session(session_id)
        if transcribe_result.get("status") != "transcribed":
            # Non-transcribed result (failed / partial / wrong state) — return
            # it unchanged; do NOT mutate the session status.
            return transcribe_result

        if on_stage is not None:
            on_stage("building_dialogue")
        return self.build_dialogue(session_id)

    def _dialogue_state(
        self,
        *,
        session_id: Optional[int],
        status: Optional[str],
        utterances: int,
        error: Optional[str] = None,
    ) -> dict:
        return {
            "session_id": session_id,
            "status": status,
            "utterances": utterances,
            "error": error,
        }

    def _new_recording_dir(self) -> str:
        """Create and return a fresh per-session recordings directory."""
        root = self._recordings_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "recordings",
        )
        base = os.path.join(root, f"{datetime.now():%Y%m%d_%H%M%S}_session")
        os.makedirs(base, exist_ok=True)
        return base

    def _transcribe_state(
        self,
        *,
        session_id: Optional[int],
        status: Optional[str],
        tracks: list,
        error: Optional[str] = None,
    ) -> dict:
        return {
            "session_id": session_id,
            "status": status,
            "tracks": tracks,
            "error": error,
        }

    # ------------------------------------------------------------------ #
    # Sprint 9: Session processing pipeline.
    # The Orchestrator is the single point that manages Session
    # processing. It holds NO business logic — it only runs the pipeline
    # stages (each stage delegates to the domain Session). No LLM, no
    # memory, no analysis.
    # ------------------------------------------------------------------ #
    def run(self, session=None):
        """Run the Session processing pipeline. Returns a PipelineResult.

        ``session`` may be a Session, an experiment directory path, or
        None (uses the latest experiment). Never raises on pipeline
        failure — errors are captured in the result.
        """
        from orchestrator.pipeline import Pipeline
        source = session if session is not None else self.session
        return Pipeline().run(source)

    # ------------------------------------------------------------------ #
    # Sprint 3: streaming transcription pipeline.
    # The Orchestrator ONLY coordinates: it creates Capture and
    # Transcriber, wires them together, starts and stops them. Raw PCM
    # flows DIRECTLY capture -> transcriber (transcriber.run consumes
    # capture.iter_chunks()); it never passes through the Orchestrator.
    # ------------------------------------------------------------------ #
    def run_transcription_stream(
        self,
        window_duration_sec: float = 5.0,
        model_size: str = "small",
        language: Optional[str] = None,
    ) -> None:
        """Run the streaming STT pipeline until Ctrl+C.

        Blocks the calling thread. Guarantees that capture and
        transcription are stopped and resources released on exit
        (including KeyboardInterrupt).
        """
        # Heavy imports kept local so GUI startup stays fast.
        from capture import CaptureConfig, SystemAudioCapture
        from transcription import StreamingTranscriber, TranscriptionConfig

        print("Orchestrator: loading Whisper model "
              f"({model_size})... this may take a while")
        capture = SystemAudioCapture(CaptureConfig(mono_mix=True))
        transcriber = None
        try:
            # Load the model BEFORE starting capture: first run may
            # download the model, and audio captured meanwhile would be
            # silently dropped by the bounded queue.
            transcriber = StreamingTranscriber(
                TranscriptionConfig(
                    model_size=model_size,
                    window_duration_sec=window_duration_sec,
                    language=language,
                ),
            )
            transcriber.load_model()
            capture.start()
            transcriber.input_sample_rate = capture.sample_rate
            transcriber.input_channels = capture.output_channels
            transcriber.recompute_window()
            print(f"Orchestrator: capturing at {capture.sample_rate} Hz, "
                  f"window={window_duration_sec}s. Press Ctrl+C to stop.")

            # Wire the components: PCM flows capture -> transcriber
            # directly; text flows transcriber -> console sink. The
            # Orchestrator does not touch the data itself.
            transcriber.run(
                chunks=capture.iter_chunks(timeout=0.5),
                on_text=lambda text: print(f">> {text}", flush=True),
            )
        except KeyboardInterrupt:
            print("\nOrchestrator: Ctrl+C received, shutting down...")
        finally:
            # Coordination only: stop the source, release the components.
            # (transcriber.run() already flushed its remaining buffer.)
            capture.stop()
            if transcriber is not None:
                transcriber.close()
            print("Orchestrator: transcription stream stopped cleanly.")
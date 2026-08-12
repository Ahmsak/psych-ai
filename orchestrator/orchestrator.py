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
    def start_recording(self) -> dict:
        """Start a live recording session. Returns the new state."""
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
            self.session.start_recording(tracks, self._store)
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

    def _new_recording_dir(self) -> str:
        root = self._recordings_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "recordings",
        )
        base = os.path.join(root, f"{datetime.now():%Y%m%d_%H%M%S}_session")
        os.makedirs(base, exist_ok=True)
        return base

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
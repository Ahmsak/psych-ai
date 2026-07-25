from typing import Optional

from session.session import Session


class Orchestrator:
    def __init__(self):
        self.session = Session()

    def start_session(self):
        print("Orchestrator: starting session")
        self.session.start()

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
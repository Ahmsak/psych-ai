# Psych AI Architecture

## MISSION
- The system assists the psychologist, not replaces the psychologist.

## Core components

- App
- UI (PySide6; GUI-скелет, пока не запускается в активном интерпретаторе)
- Orchestrator. The Orchestrator is the only component that coordinates other modules.
  Modules never communicate directly with each other.
- capture/ — audio I/O: WASAPI loopback (SystemAudioCapture) + microphone
  (MicrophoneCapture), written to separate WAV files (RecordedTrack, write_wav).
- transcription/ — Speech-to-Text via faster-whisper. Two input paths to the
  same backend: StreamingTranscriber (live PCM chunks) and file_transcriber
  (post-stop WAV → RAW TranscriptSegments).
- db/ — SQLite persistence (SQLAlchemy). SessionStore is the persistence port
  hiding SQLAlchemy from the domain Session (AudioTracks, TranscriptSegments).
- session/ — Session: the domain object and single entry point for Orchestrator
  (metadata/timeline/statistics/validation; no LLM).
- conversation/ — assembles a structured dialogue from experiment artifacts
  (used by the experiment/loader path, not by the live post-stop product path).

## Future (architecture concepts, NOT implemented yet)

- Memory (facts, not conclusions)
- Agents / multi-agent system
- Validator
- LLM analysis
- Episode model
- Constitution DSL
- Narrative agent

## Principles

- One responsibility per module.
- Agents never communicate directly.
- All communication goes through the Orchestrator.
- Ethics are centralized.
- The Constitution is independent from the LLM.
- Memory stores facts, not conclusions.
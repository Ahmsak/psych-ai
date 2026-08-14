# SPEC-007: Post-stop Transcription (транскрипция записанных дорожек)

## Purpose
После завершения live-сессии (status=`completed`/`transcribed_partial`)
транскрибировать её сохранённые WAV-дорожки и записать RAW сегменты в
SQLite. Дополнение к потоковой транскрипции (SPEC/ADR-012: тот же
backend, другой input-path).

## Requirements
- `Orchestrator.transcribe_session(session_id, model="small", language=None)`
  допускается только для status `completed`/`transcribed_partial`; иначе
  возвращает ошибку без транскрипции.
- Для каждого AudioTrack: прочитать WAV (wave.open), ресемплить к 16 кГц
  mono float32, вызвать `transcribe_file(path, model_size, language)`
  (faster-whisper, device=cpu, compute_type=int8, vad_filter=True).
- `transcribe_file` возвращает RAW [{start,end,text,confidence}] —
  текст не модифицируется, тайминги относительно НАЧАЛА файла (per-track,
  без cross-track alignment).
- `SessionStore.add_transcript_segments` пишет TranscriptSegment на трек;
  idempotent: уже записанные сегменты трека не дублируются (повторный
  прогон → skipped=1, written=0). Пустой трек (0 кадров) → 0 сегментов,
  skipped=1, текст не порождается.
- `set_session_status`: transcribing → transcribed (все ок) /
  transcribed_partial (были ошибки, но часть записана) /
  transcription_failed (все треки с ошибкой).

## Constraints
- Один faster-whisper backend (ADR-012). НЕ второй STT-движок.
- НЕ diarization/LLM/анализ. speaker берётся из источника трека
  (microphone→psychologist, loopback→client) в SessionStore.SPEAKER_MAP.
- НЕ cross-track alignment таймингов (отложено, ADR-007).
- Orchestrator не трогает PCM и SQL напрямую — только через transcription
  и SessionStore.
- Фикс. стек: Python 3.12, faster-whisper small/cpu/int8.

## Acceptance Criteria (sensor-first, PASS/FAIL)
- FAIL, если transcribe_session вызван для status != completed/
  transcribed_partial.
- FAIL, если существующий WAV не читается (audio file missing → error на
  треке, но не краш всего прогона).
- OK, если status сессии переведён в transcribed/transcribed_partial/
  transcription_failed корректно по результату.
- OK, если microphone-трек с речью дал >0 сегментов, loopback-трек без
  звука дал 0 сегментов, WAV на диске не изменён, dangling FK=0.
- Реальный прогон Session 1: status=transcribed, 4 mic-сегмента, 0
  loopback, WAV SHA256 unchanged, dangling FK=0 (проведено).

## Definition of Done
См. docs/DEFINITION_OF_DONE.md. Специфично: pytest test_post_stop_transcription
зелёный (12); штатный прогон transcribe_session(1) без monkey-patch
завершается и пишет сегменты.

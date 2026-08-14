# SPEC-006: Live Recording Vertical Slice (захват → WAV → SQLite)

## Purpose
Снять вертикальный срез записи консультации: по команде пользователя
захватить одновременно микрофон (психолог) и системный звук (loopback,
собеседник) в два независимых WAV, зафиксировать сессию и треки в SQLite.
Это продуктовый путь (не tools/), управляемый Orchestrator.

## Requirements
- `Orchestrator.start_recording()` создаёт MicrophoneCapture + SystemAudioCapture
  (CaptureConfig mono_mix=True), оборачивает каждый в RecordedTrack
  ("microphone"→mic.wav, "loopback"→loopback.wav) в каталоге recordings/.
- `session.start_recording(tracks, store)` ведёт жизненный цикл: создаёт
  Session (status=`recording`) + 2 AudioTrack через SessionStore.
- `Orchestrator.stop_recording()` останавливает захват, пишет WAV
  (RecordedTrack.save → write_wav), finalize_session (status=`completed`).
- Пустой трек не падает: write_wav пишет валидный WAV (0 кадров), трек
  фиксируется с duration=0.0; caller честно записывает отсутствие звука.
- Ctrl+C / исключение в capture → Orchestrator возвращает state с error,
  ресурсы устройств освобождаются (idempotent stop в finally).
- Idempotency: stop до start — безопасно (no-op); повторный start при
  записи — отказ ("session is already recording").

## Constraints
- НЕ объединять/микшировать/синхронизировать дорожки (ADR-006).
- НЕ транскрибировать внутри среза (транскрипция — отдельный post-stop
  путь, SPEC-007). НЕ LLM/анализ.
- capture/ изолирован (audio I/O only); Session не видит SQLAlchemy
  (ADR-011); связь модулей только через Orchestrator (ADR-001).
- Фикс. стек: Python 3.12, faster-whisper, PyAudioWPatch.

## Acceptance Criteria (sensor-first, PASS/FAIL)
- FAIL, если start_recording не создал сессию в БД (SessionStore).
- FAIL, если после stop нет двух AudioTrack (microphone, loopback) с
  file_path, указывающим на существующий WAV.
- FAIL, если WAV не открывается wave-модулем (повреждён).
- FAIL, если stop до start или повторный start при записи НЕ обработаны
  без краша (проверка error-path).
- OK, если status сессии recording→completed, обе дорожки на диске,
  размеры >0 при наличии звука.

## Definition of Done
См. docs/DEFINITION_OF_DONE.md. Специфично для среза: проверки
tools/check_recording_slice.py (real-device smoke) и
tools/check_recording_errors.py (error-path) проходят; pytest
test_ui_recording_slice/test_capture_unit/test_db зелёные.

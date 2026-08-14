# PROJECT_STATE — PsychAI

Обновляется после завершения каждого Sprint.

## Completed

- Sprint 0: скелет проекта — main.py → app.py → Orchestrator → Session,
  GUI-окно (PySide6, кнопка Start Session).
- Sprint 1: capture/ — WASAPI loopback захват системного звука
  (PyAudioWPatch): pull (iter_chunks) и push (register_callback) режимы,
  mono-микс, bounded queue, auto_stop, идемпотентный stop(), diagnose().
- Sprint 2: валидация capture на реальной машине
  (tests/capture_live_check.py), прототип Whisper (sandbox/whisper_test.py).
- Sprint 3: MVP потоковой транскрипции.
  Конвейер: Windows Loopback → capture → transcription → консоль.
  Новый модуль transcription/ (StreamingTranscriber, окна
  window_duration_sec=5.0 по умолчанию, ресемплинг 48к→16к, RMS-гейт
  тишины), Orchestrator.run_transcription_stream() (только координация,
  PCM напрямую capture → transcriber), run_stream.py, Ctrl+C — чистое
  завершение. Проверено e2e на реальной машине.
- Sprint 3.5: система знаний проекта (docs/, START_HERE.md,
  tools/verify_environment.py).
- Sprint 3.6: аудит и укрепление системы знаний: DEVELOPMENT_WORKFLOW,
  DEFINITION_OF_DONE, DISASTER_RECOVERY, BACKUP_STRATEGY, VERSIONING
  (предложение), GLOSSARY, OWNER_DECISIONS, расширенный .gitignore;
  вся работа Sprint 1–3.6 закоммичена и запушена в GitHub.
- Architectural Improvements (harness, по мотивам habr/1062822):
  AGENTS.md (карта для агентов), единый Definition of Done (чек-лист в
  docs/DEFINITION_OF_DONE.md), docs/specs/ (шаблон спецификаций),
  минимальный pytest-набор (smoke, логика capture/transcription,
  валидность JSON; маркеры hardware/slow), docs/adr/ (короткие ADR;
  ADR-006 — два независимых аудиопотока mic+loopback). Не внедрено по
  решению владельца: R2 (CONVENTIONS), R6 (check_done); R7 — после MVP.

## Current Sprint

Sprint 11 — Post-stop Transcription — завершён.
Sprint 10 — Live Recording Vertical Slice — завершён.
Sprint 9 — Orchestrator Pipeline — завершён.
Sprint 8 — Session Domain Model — завершён.
Sprint 7 — Conversation Builder — завершён.
Sprint 6 — Session Alignment — завершён.
Sprint 5 — единый формат аудио, metadata.json — завершён.
Sprint 4.0 — двухпотоковый захват (ADR-006) — завершён.

### Sprint 11 — Post-stop Transcription (2026-08-14)
- `Orchestrator.transcribe_session(session_id)` — пост-фактум
  транскрипция завершённой live-сессии (status=`completed`/`transcribed_partial`).
- `transcription/file_transcriber.py::transcribe_file(path)` — тот же
  faster-whisper backend, что у StreamingTranscriber, но input-путь из
  готового WAV (ADR-012: НЕ второй backend). Возвращает RAW сегменты
  {start,end,text,confidence} с таймингами относительно начала файла.
- `db/session_store.py::SessionStore.add_transcript_segments` — персистит
  RAW TranscriptSegment на трек (idempotent: пустой трек → skipped,
  повторный прогон не дублирует). `set_session_status` переводит сессию в
  `transcribing`→`transcribed`/`transcribed_partial`/`transcription_failed`.
- Два AudioTrack (microphone, loopback) транскрибируются по отдельности;
  пустой loopback (0 кадров) корректно даёт 0 сегментов, текст не порождает.
- fix (9e15683): добавлен локальный импорт `SessionStore` в
  `transcribe_session` (было NameError).
- Реальный прогон Session 1: status=`transcribed`, 4 microphone-сегмента,
  0 loopback-сегментов, WAV SHA256 не изменились, dangling FK=0.
- Тесты: `tests/test_post_stop_transcription.py` (12). Всего в репозитории
  215 тестов pytest; из них 12 относятся к Sprint 11, остальные — вне
  Sprint 10/11 (см. незакоммиченные файлы в рабочем дереве).

### Sprint 10 — Live Recording Vertical Slice (2026-08-14)
- `Orchestrator.start_recording()/stop_recording()` — полный вертикальный
  срез: capture (mic + loopback) → RecordedTrack → WAV → SessionStore.
- `capture/mic.py` (MicrophoneCapture) — продуктовый захват микрофона,
  извлечён из tools/ (ADR-010). `capture/track.py` (RecordedTrack),
  `capture/wav.py` (write_wav) — audio I/O, без знания о Session/UI/БД.
- `session/session.py` — ре-экспорт доменной Session (model.py), НЕ
  заглушка (ADR-009). `session.start_recording(tracks, store)` ведёт
  жизненный цикл записи.
- `db/session_store.py` (SessionStore) — порт персистентности: создаёт
  сессию + 2 AudioTrack, прячет SQLAlchemy от Session (ADR-011).
- Служебные проверки (tools/, НЕ продукт): `check_recording_slice.py`
  (real-device smoke), `check_recording_errors.py` (error-path checks).
- Тесты: `tests/test_ui_recording_slice.py` (15), `tests/test_capture_unit.py`
  (6), `tests/test_db.py` (28).

## Current Goal

Валидация интеграции на реальном звонке + расследование найденных
проблем. Memory/LLM НЕ начаты.

## Next Goal

Memory и LLM-анализ — будущие спринты. Пока НЕ начаты. Перед ними —
новый реальный e2e с исправным микрофоном (проверить, что №1 даёт PASS,
а №2 устранена настройками записи).



## Known Issues

- PySide6 не импортируется текущим интерпретатором Python 3.12
  (ModuleNotFoundError), хотя указан в requirements.txt; в __pycache__
  есть артефакты cpython-313 — вероятно, GUI-зависимости ставились в
  Python 3.13. MVP (run_stream.py) не затронут; main.py (GUI) не
  запустится, пока PySide6 не установлен в активный интерпретатор.
- ffmpeg отсутствует в PATH. faster-whisper работает без него
  (декодирование через пакет av), но заявленная в окружении утилита
  недоступна из shell.
- Внутри faster-whisper включён vad_filter=True (встроенный Silero-фильтр
  против галлюцинаций на тишине). Не отдельный VAD-модуль; решение об
  отключении за владельцем проекта.
- Слово на границе окна транскрипции может распознаться неточно
  (следствие ADR-004, ждёт Overlap-спринта).
- post-stop транскрипция на CPU/int8 (small) ~6–9с инференса на ~3–5с
  аудио; полная session 13.9с занимает ~25–30с. Без progress-вывода это
  читается как «зависание». Функционально завершается (проверено на
  Session 1).

## Technical Debt

- ROADMAP.md — крупноблочный, без привязки к спринтам.
- tests/ — автоматических e2e-тестов транскрипции на реальном устройстве
  нет (hardware/slow помечены в pytest.ini; покрыты unit-тесты формата,
  ресемпла, silence-gate, persistence, post-stop оркестрации).
- Незакоммиченные в рабочем дереве файлы (benchmark/dialogue/normalize
  утилиты и тесты, capture/capturer.py modified, docs/investigations/
  INV-001-model-selection.md) — вне Sprint 10/11, в эту документацию не
  включены.

## Deferred (отдельные будущие спринты — сейчас НЕ реализовывать)

- VAD, Speaker Diarization, Endpoint Detection
- Partial Results, Streaming Decoder, Overlap, Buffer Optimization
- LLM-анализ, память, агенты, рекомендации, Validator
- Pub/sub-модель capture (register_callback уже есть как основа)
- Per-application захват звука (WASAPI process-loopback, ctypes)
- Индекс знаний (SQLite FTS5 / векторный) — см. MEMORY_ARCHITECTURE.md

## Last Update

2026-08-14 — Sprint 11 (post-stop transcription) + Sprint 10 (live
recording slice) завершены; документация приведена к фактическому коду.

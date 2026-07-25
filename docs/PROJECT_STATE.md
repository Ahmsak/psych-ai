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

Sprint 5 — Unified Audio Timeline. Реализована временная основа для
будущего объединения двух потоков: единый формат аудио (48к/mono/PCM16),
временная шкала на каждый поток, metadata.json, sensor-first проверки
(tools/check_experiment.py), pytest (25 passed). Объединение/синхро/
диаризация/LLM НЕ выполняются (вне спринта). Артефакты — см.
docs/EXPERIMENTS.md. Ожидается подтверждение владельцем на реальном
звонке (run_timeline_experiment.py).

Sprint 4.0 — двухпотоковый захват (mic + loopback) реализован
экспериментально; принят как архитектурное решение (ADR-006).

## Current Goal

Качественная временная основа для объединения потоков: единый формат,
временные метки, metadata, измеримые проверки. Без анализа диалога.

## Next Goal

Объединение дорожек в единый диалог по общей временной шкале (будущий
спринт) — на основе metadata.json и единого формата.



## Known Issues

- PySide6 не импортируется текущим интерпретатором Python 3.12
  (ModuleNotFoundError), хотя указан в requirements.txt; в __pycache__
  есть артефакты cpython-313 — вероятно, GUI-зависимости ставились в
  Python 3.13. MVP (run_stream.py) не затронут; main.py (GUI) не
  запустится, пока PySide6 не установлен в активный интерпретатор.
- ffmpeg отсутствует в PATH. faster-whisper работает без него
  (декодирование через пакет av), но заявленная в окружении утилита
  недоступна из shell.
- Слово на границе окна транскрипции может распознаться неточно
  (следствие ADR-004, ждёт Overlap-спринта).

## Technical Debt

- session/session.py — заглушка (флаг active), не связана с конвейером STT.
- ROADMAP.md — крупноблочный, без привязки к спринтам.
- Внутри faster-whisper включён vad_filter=True (встроенный Silero-фильтр
  против галлюцинаций на тишине). Не отдельный VAD-модуль; решение об
  отключении за владельцем проекта.
- tests/ — только ручные проверки capture; автоматических тестов
  transcription/orchestrator нет.

## Deferred (отдельные будущие спринты — сейчас НЕ реализовывать)

- VAD, Speaker Diarization, Endpoint Detection
- Partial Results, Streaming Decoder, Overlap, Buffer Optimization
- LLM-анализ, память, агенты, рекомендации, Validator
- Pub/sub-модель capture (register_callback уже есть как основа)
- Per-application захват звука (WASAPI process-loopback, ctypes)
- Индекс знаний (SQLite FTS5 / векторный) — см. MEMORY_ARCHITECTURE.md

## Last Update

2026-07-25 — Sprint 4.0 шаг 1 (харнесс экспериментов захвата, loopback).

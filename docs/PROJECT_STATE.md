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

## Current Sprint

Sprint 4.0 — Исследование захвата аудио Windows (WhatsApp/Telegram
Desktop). Шаг 1 (харнесс + режим loopback) выполнен; ожидаются
результаты эксперимента №1 от владельца (реальный звонок).

## Current Goal

Обоснованно ответить: доступен ли голос пользователя, голос
собеседника, оба одновременно; какой механизм Windows подходит лучше;
какие ограничения накладывают WhatsApp/Telegram Desktop.
Рабочая гипотеза: двухпотоковая схема loopback + microphone.

Sprint 4.0 НЕ завершён, пока одновременно не выполнены ВСЕ условия:
1. проведён хотя бы один реальный звонок Telegram Desktop;
2. проведён хотя бы один реальный звонок WhatsApp Desktop;
3. выполнена транскрипция обоих тестов;
4. результаты задокументированы;
5. код проверен реальным запуском;
6. документация обновлена;
7. изменения зафиксированы в Git;
8. изменения отправлены в GitHub (DEFINITION_OF_DONE п.8).
Звонки выполняет владелец проекта; агент ждёт результатов и не
меняет стратегию исследования самостоятельно.

## Next Goal

По завершении Sprint 4.0 — решение владельца на основе результатов
экспериментов (вероятно: dual-режим захвата в продукте, либо LLM).

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

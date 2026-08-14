# ADR-012: Post-stop transcription — второй input-path к тому же backend

## Status
Accepted

## Context
Sprint 11 добавляет пост-фактум транскрипцию УЖЕ записанных WAV
(завершённая live-сессия), в дополнение к потоковой транскрипции
(StreamingTranscriber, Sprint 3). Искушение — сделать отдельный
«file-transcriber backend» со своей моделью/конфигом. Это продублировало
бы faster-whisper-логику (загрузка модели, vad_filter, resample,
segment-тайминги) и рассогласовало бы поведение двух путей.

## Decision
1. Один faster-whisper backend в проекте. file_transcriber.transcribe_file
   — НЕ второй backend, а второй INPUT-path к той же модели: читает WAV,
   ресемплит к 16 кГц mono, вызывает WhisperModel.transcribe(...) с теми же
   параметрами (model_size, device=cpu, compute_type=int8, vad_filter=True).
2. Разница только в источнике аудио: поток (StreamingTranscriber) vs
   готовый файл (transcribe_file). Оба возвращают RAW-сегменты;
   file_transcriber дополнительно сохраняет нативные тайминги Whisper
   (start/end) относительно начала файла.
3. Оркестрация (чтение треков, запись RAW TranscriptSegment, смена
   статуса) — в Orchestrator.transcribe_session, а не в транскрайбере.

## Consequences
- (+) Один источник истины по STT; поведение потокового и post-stop путей
  согласовано (та же модель, те же фильтры).
- (+) file_transcriber переиспользует логику resample/vad без дублирования.
- (+) Тайминги per-track (без cross-track alignment) — явное ограничение
  Sprint 11 (общая таймлайна отложена, см. ADR-007).
- (−) Post-stop на CPU/int8 small медленнее реального времени (~6–9с
  инференса на ~3–5с аудио); без progress-вывода читается как «зависание»,
  но завершается (проверено на Session 1).
- Пустой/тихий WAV (0 кадров) даёт 0 сегментов без падения — корректно.

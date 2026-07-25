# SPEC-002: Session Alignment (единая временная модель разговора)

## Purpose
Объединить два независимых аудиопотока (mic + loopback) в единую
ВРЕМЕННУЮ модель разговора (Timeline) на основе объективных меток из
metadata.json. Только временная модель: без микса аудио, диаризации,
LLM и анализа речи.

## Requirements
- Построить Session Timeline из metadata.json (Sprint 5):
  - timeline_start = min(record_start обоих потоков);
  - timeline_end = max(record_start + duration) обоих потоков;
  - offset потока = first_frame_at − timeline_start;
  - межпотоковый offset = loopback.first_frame_at − mic.first_frame_at;
  - интервалы записи и появления первого аудио на каждый поток.
- Сохранить timeline.json — будущий источник истины для Session:
  session_id, timeline_start, timeline_end, tracks, offsets, artifacts.
- Проверки согласованности (Sensor-first, PASS/FAIL).
- API загрузки: load_timeline()/load_session() возвращает структуру,
  пригодную для дальнейшей работы.

## Constraints
- НЕ объединять/микшировать WAV, НЕ синхронизировать физически.
- НЕ диаризация, НЕ исправление Whisper, НЕ LLM, НЕ анализ.
- НЕ менять архитектуру: ось GUI→Orchestrator→Session→Audio→Memory→LLM
  неизменна. Timeline строится из экспериментальных артефактов —
  код в tools/ (исследовательский слой), модули продукта не трогаем.
- Offset — только объективные данные (ADR-007), без эвристик/сигналов.

## Acceptance Criteria (sensor-first, PASS/FAIL)
- FAIL, если offset невозможно определить (нет first_frame_at потока).
- FAIL, если timeline противоречит metadata (session_id/длительности/
  имена артефактов не совпадают).
- FAIL, если дорожки имеют несовместимый формат (stored_format различны
  или != unified_format).
- FAIL, если timeline.json повреждён (не парсится / нет ключей).
- Проверки в детекторе + pytest на синтетике.

## Definition of Done
См. docs/DEFINITION_OF_DONE.md. Дополнительно Sprint 6: timeline.json
создаётся; offsets вычисляются; Timeline проходит проверки; есть API
загрузки Timeline.

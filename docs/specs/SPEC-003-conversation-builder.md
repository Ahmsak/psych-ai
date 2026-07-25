# SPEC-003: Conversation Builder (первый продуктовый модуль)

## Purpose
Преобразовать два независимых результата транскрипции в единый
структурированный диалог (Conversation) — упорядоченный по времени
список реплик. Это НЕ анализ, НЕ диаризация, НЕ LLM. Только сборка.
Первый ПРОДУКТОВЫЙ модуль: код в архитектуре проекта (conversation/),
не в tools/.

## Requirements
- Модель Conversation: реплика (Utterance) минимум с полями id, speaker,
  start_time, end_time (если возможно), text, source, confidence (если
  доступно).
- Построение из: timeline.json (offsets), metadata.json (роли),
  двух транскрипций c таймингами сегментов.
- Абсолютное время реплики = offset[track] + seg.start (объективно,
  из Timeline; ADR-007/008). Список сортируется по start_time.
- speaker назначается по источнику дорожки (mic → psychologist,
  loopback → client) — source-based, НЕ диаризация.
- conversation.json — главный источник данных для будущего анализа.
- API: conversation.load_conversation([dir]) → Conversation; а также
  Session.conversation (через session_manager) для удобства.
- Текст Whisper НЕ изменяется.

## Constraints
- НЕ GPT/LLM, НЕ анализ эмоций/искажений, НЕ психологические выводы.
- НЕ менять текст Whisper, НЕ диаризация, НЕ смысловая обработка.
- Новый код — продуктовый пакет conversation/ (единая ответственность:
  сборка диалога). Экспериментальный слой (tools/) только поставляет
  артефакты с таймингами сегментов.
- Архитектура (ось GUI→Orchestrator→Session→Audio→Memory→LLM) не
  меняется; conversation/ — часть Session-слоя данных.

## Acceptance Criteria (sensor-first, PASS/FAIL)
- FAIL, если реплики идут не по возрастанию start_time.
- FAIL, если у реплики отсутствует speaker.
- FAIL, если у реплики отсутствует text.
- FAIL, если conversation повреждён (не парсится / нет ключей).
- FAIL, если conversation противоречит timeline (session_id;
  start_time вне [0, timeline duration]).
- Проверки в модуле + pytest на синтетике.

## Definition of Done
См. docs/DEFINITION_OF_DONE.md. Дополнительно Sprint 7: conversation.json
создаётся; Conversation API существует; реплики упорядочены по времени;
проверки работают.

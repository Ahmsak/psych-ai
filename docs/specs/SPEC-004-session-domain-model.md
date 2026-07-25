# SPEC-004: Session Domain Model (главный объект консультации)

## Purpose
Превратить Session из набора загрузчиков (tools/session_manager) в
главный объект предметной области PsychAI — единственную точку входа
для Orchestrator. Session объединяет все артефакты одной консультации:
metadata, timeline, conversation, artifacts, statistics, validation.
Без LLM и без анализа Conversation.

## Requirements
- Доменная Session в ПРОДУКТОВОМ пакете session/ (не tools/).
- API: session.metadata, session.timeline, session.conversation,
  session.artifacts, session.statistics, session.duration,
  session.client_name (задел, пока None).
- Statistics (автоматически, только метаданные, без интерпретации):
  длительность консультации; число реплик; число реплик психолога;
  число реплик клиента; % времени каждой стороны (если возможно);
  общее число слов.
- Validation: session.validate() → результат PASS/WARNING/FAIL с
  причинами.
- Serialization: load_session()/save_session() без побочных эффектов
  (load не пишет; save пишет только по явному вызову).
- Orchestrator использует Session как единую точку входа.

## Constraints
- НЕ GPT/LLM, НЕ анализ Conversation, НЕ эмоции/искажения/выводы.
- НЕ менять текст Whisper.
- Session — доменный объект в оси GUI→Orchestrator→Session→Audio→
  Memory→LLM. Не должно быть ДВУХ конкурирующих Session: доменная
  модель живёт в session/, tools/session_manager остаётся тонкой
  совместимой обёрткой (переадресация), чтобы Sprint 6/7 не сломались.
- Переиспользовать существующие сборщики: timeline (tools/build_timeline)
  и conversation (пакет conversation/), не дублируя логику.

## Acceptance Criteria (sensor-first, PASS/WARNING/FAIL)
- FAIL, если нет metadata или timeline (консультацию не собрать).
- FAIL, если conversation противоречит timeline (session_id).
- WARNING, если conversation пуст (нет реплик) или у стороны нет реплик.
- PASS, если metadata+timeline+conversation согласованы и статистика
  вычислима.
- save_session→load_session даёт эквивалентный объект (round-trip).
- Проверки покрыты pytest на синтетике.

## Definition of Done
См. docs/DEFINITION_OF_DONE.md. Дополнительно Sprint 8: Session —
главный объект; объединяет metadata/timeline/conversation; statistics
автоматически; validate() работает; сериализация есть.

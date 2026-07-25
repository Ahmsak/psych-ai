# SPEC-005: Orchestrator Pipeline (единый конвейер обработки Session)

## Purpose
Подключить существующие продуктовые модули через единый расширяемый
конвейер обработки Session. Orchestrator — единственная точка управления
этапами; бизнес-логики он не содержит. Без GPT/LLM, без памяти, без
анализа консультации.

## Requirements
- Минимальный конвейер: Load Session → Validate Session → Build
  Statistics → Finalize. Каждый этап — отдельный шаг; Pipeline
  расширяем (добавление шага без переписывания).
- PipelineResult: status, warnings, errors, statistics, duration.
- Логирование по одному сообщению на этап (Session Loaded, Validation
  Passed, Statistics Built, Pipeline Finished), без избыточности.
- API: orchestrator.run(session) → PipelineResult (принимает Session или
  путь к каталогу эксперимента).
- Orchestrator только оркеструет; validate()/statistics берутся из
  доменной Session (Sprint 8), не дублируются.

## Constraints
- НЕ GPT/LLM, НЕ Memory / долгосрочная память, НЕ анализ консультации.
- НЕ менять архитектуру Session (Sprint 8) и существующий STT-конвейер
  Orchestrator (run_transcription_stream не трогать — новый путь run()).
- Ось GUI→Orchestrator→Session→Audio→Memory→LLM не меняется.

## Acceptance Criteria (sensor-first, PASS/FAIL)
- FAIL, если Session невалидна (validate() → FAIL).
- FAIL, если Conversation отсутствует.
- FAIL, если Pipeline прерван (этап не завершился).
- FAIL при неожиданном исключении на любом этапе (перехват → errors).
- PASS, если все этапы прошли; WARNING пробрасывается из Session.validate.
- Проверки покрыты pytest на синтетике.

## Definition of Done
См. docs/DEFINITION_OF_DONE.md. Дополнительно Sprint 9: Pipeline
существует; Orchestrator управляет Session; PipelineResult существует;
логирование работает; проверки работают.

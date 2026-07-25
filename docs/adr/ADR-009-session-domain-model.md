# ADR-009: Session как главный доменный объект (единая точка входа)

## Status
Accepted

## Context
До Sprint 8 «Session» существовал в двух местах: заглушка
session/session.py (active/start(), её использует Orchestrator) и
рабочий загрузчик tools/session_manager.py (dataclass с timeline/
conversation в исследовательском слое). Две конкурирующие сущности с
одним именем — риск расхождения и нарушение оси
GUI→Orchestrator→Session→Audio→Memory→LLM.

Sprint 8 требует, чтобы Session стал главным объектом предметной области
и ЕДИНСТВЕННОЙ точкой входа для Orchestrator, объединяя metadata,
timeline, conversation, artifacts, statistics, validation. Без LLM и без
анализа Conversation.

## Decision
1. Доменная модель Session живёт в ПРОДУКТОВОМ пакете session/
   (model.py + statistics.py + loader.py + __init__.py). Это
   единственный класс Session.
2. session/session.py сохранён как тонкий ре-экспорт
   (`from session.model import Session`) — старый импорт Orchestrator
   продолжает работать, но получает доменный объект.
3. Runtime-lifecycle (start()/active) слит в доменную Session, чтобы у
   Orchestrator был один тип Session и для live-, и для загруженной
   работы.
4. tools/session_manager.py остаётся тонкой совместимой обёрткой для
   Sprint 6/7 (не удалён, чтобы не ломать существующий код и тесты).
5. Statistics — только объективные метаданные (счётчики/длительность/
   проценты времени), без интерпретации. Validation → PASS/WARNING/FAIL.
6. Сериализация без побочных эффектов: load_session не пишет;
   save_session пишет session.json только по явному вызову.

## Consequences
- (+) Один источник истины: Session — главный объект продукта и единая
  точка входа Orchestrator.
- (+) Обратная совместимость: старые импорты и tools/ не сломаны.
- (+) Переиспользование существующих сборщиков (timeline, conversation),
  без дублирования логики.
- (−) Временно два пути загрузки (session/ и tools/session_manager);
  session_manager помечен как совместимый слой и может быть свёрнут
  позже.
- Аудио/текст Whisper не трогаются; анализа/LLM нет.

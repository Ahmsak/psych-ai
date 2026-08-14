# docs/specs — спецификации функций

Короткие спецификации отдельных функций, пишутся ДО реализации.
Одна спецификация = один файл SPEC-NNN-<краткое-имя>.md.

Назначение: зафиксировать контракт функции (что и как проверить) до
кода, чтобы требования не приходили частями. Слой между ROADMAP (план)
и ADR (принятые архитектурные решения).

Формат — см. SPEC-000-template.md. Нумерация сквозная (SPEC-001, 002...).
Definition of Done не дублируется — ссылка на docs/DEFINITION_OF_DONE.md.

Сквозной список SPEC:
- SPEC-001 — Unified Audio Timeline (SPEC-001-unified-audio-timeline.md).
- SPEC-002 — Session Alignment (SPEC-002-session-alignment.md).
- SPEC-003 — Conversation Builder (SPEC-003-conversation-builder.md).
- SPEC-004 — Session Domain Model (SPEC-004-session-domain-model.md).
- SPEC-005 — Orchestrator Pipeline (SPEC-005-orchestrator-pipeline.md).
- SPEC-006 — Live Recording Vertical Slice (SPEC-006-live-recording-slice.md).
- SPEC-007 — Post-stop Transcription (SPEC-007-post-stop-transcription.md).

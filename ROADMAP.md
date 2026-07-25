# ROADMAP — PsychAI

Обновляется при завершении Sprint или изменении плана.

## Завершено

- ✔ Sprint 0 — структура проекта, GUI-скелет, Session
- ✔ Sprint 1 — capture/ (WASAPI loopback, PyAudioWPatch)
- ✔ Sprint 2 — валидация capture на реальной машине; прототип Whisper
- ✔ Sprint 3 — MVP потоковой транскрипции
  (loopback → capture → transcription → консоль, run_stream.py)
- ✔ Sprint 3.5 — система знаний проекта (docs/, START_HERE.md,
  tools/verify_environment.py)
- ✔ Sprint 3.6 — аудит системы знаний (DEVELOPMENT_WORKFLOW,
  DEFINITION_OF_DONE, git/GitHub-правила)

## Дальше (порядок не зафиксирован — решение владельца проекта)

- ⬜ LLM connection (llm/ пуст) + test prompt
- ⬜ Улучшения STT-конвейера (отдельные спринты):
  Overlap, Partial Results, Streaming Decoder, Buffer Optimization,
  VAD, Endpoint Detection, Speaker Diarization
- ⬜ Memory (факты, не выводы)
- ⬜ Validator
- ⬜ Session Widget / Workspace (GUI; требует починки PySide6 в 3.12)
- ⬜ Агенты / мультиагентная система
- ⬜ Per-application захват звука (WASAPI process-loopback)

Текущее состояние и известные проблемы: docs/PROJECT_STATE.md.

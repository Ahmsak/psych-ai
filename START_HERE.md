# START_HERE — PsychAI

Точка входа для любого нового разработчика или ИИ-агента.
Прочитай эту страницу, затем документы в указанном порядке — и можно работать.

## Что это

PsychAI — Windows-десктоп ИИ-ассистент для психологов.
Ассистирует психологу, НЕ заменяет его.
Стек: Python 3.12, PySide6 (GUI), PyAudioWPatch (WASAPI loopback),
faster-whisper + ctranslate2 (STT).

## Состояние

- Завершено: Sprint 3 — рабочий MVP потоковой транскрипции системного
  звука (loopback → capture → transcription → консоль).
- Текущий Sprint: 3.5 — инфраструктура знаний проекта (этот документ).
- Следующий этап: см. docs/PROJECT_STATE.md → Next Goal.

## Ключевое архитектурное правило

Orchestrator управляет жизненным циклом компонентов и соединяет их,
но НИКОГДА не транспортирует потоковые данные (сырой PCM идёт напрямую
capture → transcription). Полные правила: docs/CONSTITUTION.md.

## Проверка среды

    cd C:\works\psych-ai
    python tools/verify_environment.py

## Запуск

    python run_stream.py                      # MVP: потоковая транскрипция
    python run_stream.py --window 3 --language ru
    python main.py                            # GUI-скелет (требует PySide6)

## Порядок чтения документов

1. START_HERE.md          — этот файл
2. docs/CONSTITUTION.md   — миссия, философия, незыблемые принципы
3. docs/PROJECT_STATE.md  — что сделано / текущая и следующая цель
4. docs/SESSION.md        — последняя рабочая сессия, следующий шаг
5. docs/ARCHITECTURAL_DECISIONS.md — почему всё устроено именно так
6. docs/ENVIRONMENT.md    — окружение и его проверка

Перед работой: docs/DEVELOPMENT_WORKFLOW.md (цикл разработки, git).
Перед завершением Sprint: docs/DEFINITION_OF_DONE.md (чек-лист).
Дальше — по необходимости: docs/DEPENDENCIES.md, README модулей
(capture/, transcription/), исходники. Не читай весь проект без нужды.

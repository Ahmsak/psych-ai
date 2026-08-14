# SESSION — оперативная память разработки

Обновляется после каждой рабочей сессии. Новая запись — сверху.

---

## 2026-08-14 — Sprint 11: Post-stop Transcription (fix 9e15683)

### Что сделано
- `Orchestrator.transcribe_session(session_id)` — пост-фактум транскрипция
  завершённой live-сессии (status=`completed`/`transcribed_partial`).
- `transcription/file_transcriber.py::transcribe_file(path)` — тот же
  faster-whisper backend (small, cpu, int8), что у StreamingTranscriber, но
  input-путь из готового WAV. Возвращает RAW сегменты
  {start,end,text,confidence} с таймингами относительно начала файла.
- `db/session_store.py::SessionStore.add_transcript_segments` — персистит
  RAW TranscriptSegment на трек; idempotent (пустой трек → skipped, повтор
  не дублирует). `set_session_status` ведёт
  `transcribing`→`transcribed`/`transcribed_partial`/`transcription_failed`.
- Два AudioTrack (microphone, loopback) транскрибируются по отдельности;
  пустой loopback (0 кадров) даёт 0 сегментов, текст не порождает.
- fix 9e15683: добавлен локальный импорт `SessionStore` в
  `transcribe_session` (было `NameError: name 'SessionStore' is not defined`).

### Проверки, реально прошедшие
- `tests/test_post_stop_transcription.py` — 12 passed.
- Полный штатный прогон `Orchestrator.transcribe_session(session_id=1)`
  на реальной Session 1 (без runtime-подмен): завершился за ~26с,
  status=`transcribed`.
- Результат прогона Session 1:
  - microphone: 4 TranscriptSegment
    (2.00–6.88 «1 2 3 1 2»; 6.88–8.68 «тесто от запись»;
     8.68–11.58 «мы делаем тестовую запись»; 11.58–13.58 «останавливаю»);
  - loopback: 0 сегментов (файл 44 байта, 0 кадров — тишина);
  - WAV SHA256 mic и loopback ДО/ПОСЛЕ идентичны (файлы не изменены);
  - dangling FK = 0 (seg→track, seg→session, track→session).
- pytest -q по репозиторию: 215 tests (из них 12 — Sprint 11).

### Commit hashes
- ef8a843 feat: add post-stop transcription (Sprint 11)
- 9e15683 fix: import SessionStore in post-stop transcription (Sprint 11 fix)

### Важные дефекты и исправления
- Дефект: `transcribe_session` падал с NameError (SessionStore не
  импортирован). Исправлен 9e15683 (локальный импорт, как в
  start_recording). Подтверждено штатным прогоном без monkey-patch.

---

## 2026-08-14 — Sprint 10: Live Recording Vertical Slice

### Что сделано
- `Orchestrator.start_recording()/stop_recording()` — полный вертикальный
  срез: capture (mic + loopback) → RecordedTrack → WAV → SessionStore.
- `capture/mic.py` (MicrophoneCapture) — продуктовый захват микрофона,
  извлечён из tools/ (был MicRecorder/TimedMicRecorder).
- `capture/track.py` (RecordedTrack), `capture/wav.py` (write_wav) — audio
  I/O, без знания о Session/UI/БД.
- `session/session.py` — ре-экспорт доменной Session (model.py), НЕ
  заглушка (ADR-009). `session.start_recording(tracks, store)`.
- `db/session_store.py` (SessionStore) — порт персистентности: создаёт
  сессию + 2 AudioTrack, прячет SQLAlchemy от Session (ADR-011).
- Служебные проверки (tools/, НЕ продукт):
  `check_recording_slice.py` (real-device smoke),
  `check_recording_errors.py` (error-path: stop-before-start, capture
  failure, second start, no-op stop).

### Проверки, реально прошедшие
- `tests/test_ui_recording_slice.py` (15), `tests/test_capture_unit.py` (6),
  `tests/test_db.py` (28).
- `python tools/check_recording_slice.py --seconds 3` — сессия completed,
  2 трека (microphone + loopback) записаны, WAV на диске.
- `python tools/check_recording_errors.py` — ALL CHECKS PASSED.

### Commit hash
- bc30317 feat: add live recording vertical slice (Sprint 10)

---

## 2026-07-25 — Sprint 10.1: Integration Investigation (INV-001)

### Расследование (эксперимент 20260725_181758_timeline)
- Первый реальный e2e: Overall WARNING, 0 FAIL. Архитектура работоспособна.
- Проблема №1 (psychologist=0): причина — почти пустой сигнал микрофона
  (peak 3.6%) → Whisper 0 сегментов. НЕ баг конвейера. Маскировалась
  расхождением двух путей транскрипции (StreamingTranscriber галлюцинировал
  текст на тишине, сегментный путь давал 0).
- Проблема №2 (обе стороны на MIC): смешивание ДО PsychAI (corr огибающих
  0.952 по offset; в коде микса нет). Аудио-тракт Windows/Realtek/акустика.
  По правилу — не исправляем, только документируем.
- Отчёты: docs/investigations/INV-001-*.md (part1/part2/part3-fix).

### Исправлено (только №1, минимально, без рефакторинга/смены архитектуры)
- tools/run_timeline_experiment.py: текст транскрипции берётся из того же
  сегментного пути, что и *_segments.json (устранены галлюцинации-фантомы).
- tools/check_experiment.py + run_integration_validation.py: sensor
  «transcription/segments mismatch» (непустой .txt при 0 сегментов → FAIL).
- tests/test_integration_harness.py: тест на этот рассинхрон. pytest 70 passed.
- Артефакты эксперимента перегенерированы из имеющихся сегментов (без
  повторного Whisper, без фабрикации): mic .txt пуст (честно),
  conversation.json/Session/Statistics перестроены; harness Overall WARNING.

### Архитектура Audio Capture НЕ менялась
Оба дефекта во входном аудио (до PsychAI); захват отработал корректно.

---


## 2026-07-25 — Sprint 10: Integration Harness (инженерный инструмент)

### Что сделано
- tools/run_integration_validation.py — прогоняет весь конвейер над
  каталогом эксперимента, печатает Integration Report (PASS/WARNING/FAIL
  по 6 этапам) + сводку и Overall Result.
- Этапы: Audio Capture, Metadata, Timeline, Conversation, Session,
  Orchestrator. Используются только существующие API; артефакты не
  изменяются (round-trip сериализации во временный файл); новая
  продуктовая логика не добавлена. Harness — НЕ часть продукта.
- pytest: tests/test_integration_harness.py (4 теста, включая проверку
  неизменности артефактов и FAIL на пустом каталоге). Итого 69 passed.
- Smoke на существующем эксперименте: Overall Result PASS (6/0/0).
- docs: EXPERIMENTS.md (раздел Integration Harness).

### Ограничения соблюдены
- Без GPT/LLM, без Memory, без изменения архитектуры и новой
  функциональности; артефакты не менялись.

### Следующий шаг
- Ожидание указаний. Реальный e2e-прогон на звонке WhatsApp Desktop —
  по готовности владельца: `python tools/run_timeline_experiment.py
  --language ru`, затем `python tools/run_integration_validation.py`.

---


## 2026-07-25 — Sprint 9: Orchestrator Pipeline

### Что сделано
- SPEC-005. Orchestrator стал единственной точкой управления обработкой
  Session, без бизнес-логики.
- orchestrator/pipeline.py: расширяемый конвейер (Load → Validate →
  Build Statistics → Finalize), каждый этап — отдельный PipelineStage;
  делегирует доменной Session (Sprint 8).
- PipelineResult (status/warnings/errors/statistics/duration/
  stages_completed); PipelineAbort для управляемого FAIL.
- Логирование logger psychai.pipeline: по одному сообщению на этап.
- Orchestrator.run(session) → PipelineResult (Session | путь | None);
  никогда не бросает — ошибки в result. STT-конвейер
  (run_transcription_stream) не тронут.
- Sensor-first: FAIL при невалидной Session / отсутствии Conversation /
  прерывании / неожиданном исключении; WARNING из Session.validate.
- pytest: tests/test_pipeline.py (12 тестов). Итого 65 passed.
- Реальный e2e: Orchestrator.run(load_session()) → PASS, 4 этапа
  залогированы, статистика построена.
- docs: EXPERIMENTS.md (раздел Orchestrator Pipeline).

### Ограничения соблюдены
- Без GPT/LLM, без Memory/долгосрочной памяти, без анализа консультации;
  архитектура Session не менялась; текст Whisper не трогался.

### Следующий шаг
- Ожидание задания. Memory/LLM — будущие спринты.

---


## 2026-07-25 — Sprint 8: Session Domain Model (главный объект)

### Что сделано
- SPEC-004 + ADR-009 (Session — главный доменный объект и единая точка
  входа Orchestrator; устранены две конкурирующие Session).
- Продуктовый пакет session/:
  - model.py — класс Session (metadata/timeline/conversation/artifacts/
    statistics/validation, duration, client_name-задел) + runtime
    lifecycle start()/active;
  - statistics.py — compute_statistics (длительность, число реплик,
    реплики психолога/клиента, % времени сторон, число слов; без
    интерпретации);
  - loader.py — load_session (без записи), save_session/load_session_file
    (session.json, явно);
  - __init__.py — публичный API.
- session/session.py → ре-экспорт доменной Session (совместимость
  Orchestrator). tools/session_manager.py оставлен тонким слоем Sprint 6/7.
- Orchestrator теперь получает доменную Session (проверено).
- pytest: tests/test_session_domain.py (11 тестов). Итого 55 passed.
- Реальный e2e: load_session → statistics (2 реплики, 50/50 время,
  18 слов), validate PASS, save/load round-trip PASS.
- docs: EXPERIMENTS.md (раздел Session Domain Model), ADR-009.

### Ограничения соблюдены
- Без LLM/GPT, без анализа Conversation, эмоций, искажений; текст
  Whisper не менялся; архитектура (ось Session) укреплена, не изменена.

### Следующий шаг
- Ожидание задания. Анализ (llm/) — будущий спринт.

---


## 2026-07-25 — Sprint 7: Conversation Builder (первый продуктовый модуль)

### Что сделано
- SPEC-003 + ADR-008 (speaker по источнику; сегментные тайминги Whisper).
- Data-слой: run_timeline_experiment.py дополнительно сохраняет
  mic_segments.json / loopback_segments.json (нативные сегменты Whisper
  start/end/text/confidence; текст не меняется); segments добавлен в
  metadata и timeline tracks.
- Продуктовый пакет conversation/ (НЕ tools/):
  - model.py — Utterance (id, speaker, start_time, end_time, text,
    source, confidence) + Conversation;
  - builder.py — build_conversation (offset дорожки + seg.start,
    сортировка по времени, speaker mic→psychologist/loopback→client) +
    validate_conversation (проверки Задачи 5);
  - __init__.py — API load_conversation()/write_conversation();
  - conversation.json (атомарная запись) — источник данных для анализа.
- Session.conversation (session_manager) — ленивая сборка без записи.
- pytest: tests/test_conversation.py (14 тестов, вкл. negative). Итого
  44 passed, 2 deselected.
- Реальный e2e: прогон → segments → timeline → conversation.json;
  2 реплики упорядочены, speaker по источнику, текст Whisper дословно,
  confidence сохранён; Session.conversation OK.
- docs: EXPERIMENTS.md (раздел Conversation), AGENTS.md (пакет
  conversation/), ADR-008.

### Ограничения соблюдены
- Без LLM/GPT, эмоций, искажений, психологических выводов; текст Whisper
  не изменялся; не диаризация (speaker по источнику); архитектура не
  менялась (новый продуктовый модуль в оси Session).

### Следующий шаг
- Ожидание задания. Анализ разговора — будущий спринт (llm/).

---


## 2026-07-25 — Sprint 6: Session Alignment (Timeline)

### Что сделано
- SPEC-002 (docs/specs/) + ADR-007 (offset по first_frame_at).
- tools/build_timeline.py — строит timeline.json из metadata.json:
  timeline_start=min(record_start), timeline_end=max(record_start+dur),
  offset потока=first_frame_at−timeline_start, межпотоковый
  loopback−mic. Запись атомарна (tmp+os.replace).
- Проверки согласованности (Задача 4): FAIL если offset неопределим,
  timeline противоречит metadata, форматы дорожек несовместимы,
  timeline повреждён.
- tools/session_manager.py — API load_timeline()/load_session()
  (Session с accessors: offsets, wav_path, transcription_text и т.д.);
  строит из metadata в памяти, если timeline.json нет.
- pytest: tests/test_session_alignment.py (10 тестов, вкл. negative).
  Итого 33 passed, 2 deselected.
- docs/EXPERIMENTS.md — разделы Session Timeline и Session API.
- Реальный прогон на артефактах Sprint 5: timeline.json построен,
  offsets mic=0.188s loop=1.353s (loop−mic=1.165s), API грузит OK.

### Ограничения соблюдены
- Аудио НЕ объединялось/не микшировалось/не синхронизировалось;
  диаризации/LLM/анализа нет; архитектура не менялась (код в tools/).

### Следующий шаг
- Ожидание задания. Физическое объединение дорожек — будущий спринт.

---


## 2026-07-25 — Sprint 5: Unified Audio Timeline

### Что сделано
- SPEC-001 (docs/specs/) — контракт до реализации.
- Единый формат аудио 48000 Гц / mono / PCM16 для ОБОИХ потоков
  (loopback нативно 48к; mic ресемплится 44100→48000). Функция
  to_unified() переиспользует линейный ресемпл/даунмикс.
- tools/run_timeline_experiment.py — mic + loopback в едином формате,
  временная шкала (record_start, first_frame_at, duration) на каждый
  поток, metadata.json (session_id, created_at, unified_format, блоки
  microphone/loopback). Запись metadata атомарна (tmp+os.replace).
- Дорожки НЕ объединяются/не синхронизируются/не диаризуются (только
  подготовка данных, см. ADR-006).
- Sensor-first: tools/check_experiment.py — PASS/FAIL по измеримым
  условиям (metadata, WAV-целостность, соответствие формату, наличие
  записи, транскрипция при звуке). exit!=0 при FAIL.
- pytest: tests/test_timeline.py (8 тестов: конверсия формата +
  negative-кейсы детектора). Итого 25 passed, 2 deselected.
- docs/EXPERIMENTS.md — формат хранения, metadata, единый формат,
  подготовка к Timeline.
- Реальный прогон (tone-probe): оба потока в 48к mono, обе транскрипции,
  timing зафиксирован; check_experiment.py → ALL PASS (exit 0).

### Что осталось
- Владелец: реальный звонок (Telegram/WhatsApp) с
  run_timeline_experiment.py для подтверждения на живом диалоге.

### Следующий шаг
- Ожидание указаний владельца. Объединение дорожек — будущий спринт.

---


## 2026-07-25 — Architectural Improvements: R1, R3, R4, R5 (одобрено)

### Что сделано
- R1: создан AGENTS.md (корень) — краткая карта проекта для агентов.
- R3: единый Definition of Done (8-пунктовый чек-лист) интегрирован в
  docs/DEFINITION_OF_DONE.md; расширенный спринтовый чек-лист сохранён.
- R4: каталог docs/specs/ — README + SPEC-000-template.md
  (Purpose / Requirements / Constraints / Acceptance Criteria /
  Definition of Done).
- R5: минимальный набор pytest (offline по умолчанию):
  tests/test_smoke.py (импорты, конфиги, process_id NotImplementedError),
  tests/test_transcription.py (окно, resample, silence-gate, ошибка без
  модели; реальный декод @slow, skip без фикстуры),
  tests/test_capture.py (downmix, idempotent stop; открытие устройства
  @hardware), tests/test_artifacts.py (валидность manifest.json).
  pytest.ini с маркерами hardware/slow (opt-in); pytest в requirements.
- Проверено: 17 passed, 2 deselected (0.6s); hardware-тест реально
  открывает WASAPI-устройство и проходит; slow корректно gated.

### Что осталось
- R2, R6 — по решению владельца НЕ внедрять сейчас.
- R7 — после MVP.
- speech.wav фикстура для @slow — добавить при необходимости.

### Следующий шаг
- Ожидание указаний владельца.

---


## 2026-07-25 — Sprint 4.0, шаг 2: dual capture (mic + loopback)

### Что сделано
- Результат эксперимента №1 (владелец): loopback пишет собеседника,
  голос пользователя в loopback ОТСУТСТВУЕТ — нужен второй поток.
- tools/run_dual_experiment.py — одновременный захват микрофона
  (MicRecorder внутри скрипта) и loopback (существующий capture/ без
  изменений); артефакты: mic.wav, loopback.wav, mic_transcription.txt,
  loopback_transcription.txt, manifest.json, log.txt; диагностика
  обоих потоков (устройство, sr, каналы, длительность, RMS).
- Смок-тест: оба потока записаны ОДНОВРЕМЕННО (mic 44100 Гц,
  loopback 48000 Гц), конфликтов нет; loopback транскрибирован.

### Что осталось
- Владелец: эксперимент №2 — реальные звонки Telegram и WhatsApp
  с dual-записью; сообщить содержимое обеих транскрипций.

### Следующий шаг
- Ожидание результатов эксперимента №2; архитектурное решение о
  dual-захвате не принимается до подтверждения.

### Риски
- Эхо собеседника в микрофоне при работе без наушников.

---

## 2026-07-25 — Sprint 4.0, шаг 1: харнесс экспериментов, режим loopback

### Что сделано
- tools/run_capture_experiment.py — экспериментальный харнесс захвата:
  один запуск = один метод; артефакты в experiments/<ts>_<mode>/
  (audio.wav, transcription.txt, manifest.json, log.txt), живая
  диагностика (устройство, sr, каналы, RMS, транскрипция).
- Реализован режим loopback (переиспользует capture/ и transcription/
  без изменений). experiments/ добавлен в .gitignore (приватность).
- Проверено tone-probe (test.wav → loopback → Whisper → артефакты OK).
- Анализ: ни один одиночный механизм Windows не даёт оба голоса;
  рекомендация для MVP — двухпотоковая схема loopback (собеседник) +
  microphone (пользователь); бонус — естественная диаризация по потокам.

### Что осталось
- Владелец: провести эксперимент №1 (реальный звонок WhatsApp/Telegram
  с --mode loopback) и сообщить результат.
- По подтверждению: реализовать режим microphone, затем dual.
- Process Loopback — отложен в конец спринта (нативный ctypes, дорого).

### Следующий шаг
- Ожидание результатов эксперимента №1 от владельца (по правилам
  Sprint 4.0 стратегия не меняется без его результатов).

### Риски
- Эхо собеседника в микрофонном потоке при работе без наушников;
  оценить в эксперименте.

---

## 2026-07-25 — Sprint 3.6 (продолжение): пункты 6–12, финализация

### Что сделано
- DISASTER_RECOVERY.md (восстановление после потери машины).
- BACKUP_STRATEGY.md (источник истины, производные артефакты).
- VERSIONING.md (предложение 0.x-схемы; реализация тегов не требовалась).
- GLOSSARY.md (краткие однозначные определения).
- OWNER_DECISIONS.md (журнал решений владельца, OD-001..009).
- Аудит и расширение .gitignore (секреты, кэши, логи, индексы);
  проверено: канонические знания не исключаются, отслеживаемые файлы
  не затенены.
- Финальный аудит системы знаний: риски, годовые проблемы, кандидаты
  на объединение, будущие документы (создаются только по триггеру —
  правило добавлено в DOCUMENTATION_LIFECYCLE).
- Все коммиты запушены в GitHub по ходу работы.

### Что осталось
- OD-008 (vad_filter) и OD-009 (Next Goal) — открытые решения владельца.

### Следующий шаг
- Новый Sprint по решению владельца.

### Риски
- Дисциплина обновления доков; один remote (GitHub) без зеркала.

---

## 2026-07-25 — Sprint 3.6: аудит и укрепление системы знаний

### Что сделано
- Аудит docs/: существующие документы покрывают знания «что и почему»,
  но не покрывали ПРОЦЕСС (как работать) и КРИТЕРИИ (когда готово).
- Созданы docs/DEVELOPMENT_WORKFLOW.md (полный цикл сессии, git-правила,
  роль GitHub) и docs/DEFINITION_OF_DONE.md (чек-лист завершения Sprint).
- START_HERE.md и DOCUMENTATION_LIFECYCLE.md дополнены ссылками на них.

### Что осталось
- Владелец: подтвердить Next Goal.

### Следующий шаг
- Начать следующий Sprint по решению владельца (docs/PROJECT_STATE.md → Next Goal).

### Риски
- (git-риск снят: вся работа Sprint 1–3.6 закоммичена и запушена,
  origin/main = 32032ab; правило проекта — каждый завершённый Sprint
  отправляется в GitHub.)

---

## 2026-07-25 — Sprint 3.5: система знаний

### Что сделано
- Создана структура знаний: START_HERE.md (корень) + docs/
  (CONSTITUTION, PROJECT_STATE, SESSION, ARCHITECTURAL_DECISIONS,
  ENVIRONMENT, DEPENDENCIES, MEMORY_ARCHITECTURE,
  DOCUMENTATION_LIFECYCLE).
- PROJECT_STATE.md переработан по новой структуре и перенесён из корня
  в docs/.
- Создан tools/verify_environment.py — автопроверка среды с итоговым
  отчётом.
- Зафиксированы ADR-001..006.

### Что осталось
- Владелец: подтвердить Next Goal (LLM-подключение или улучшение STT).
- Известная проблема среды: PySide6 не импортируется в Python 3.12
  (GUI main.py не запустится) — среду НЕ чинил по правилам проекта,
  только сообщил.

### Следующий шаг
- Новый агент: прочитать документы по порядку из START_HERE.md,
  запустить python tools/verify_environment.py, затем run_stream.py.

### Риски
- Документация актуальна только при соблюдении
  DOCUMENTATION_LIFECYCLE.md (человеческий фактор).

---

## 2026-07-25 — Sprint 3: MVP потоковой транскрипции

### Что сделано
- transcription/ (StreamingTranscriber, TranscriptionConfig, README).
- Orchestrator.run_transcription_stream(): только координация; PCM
  напрямую capture → transcriber (ADR-005).
- run_stream.py; Ctrl+C — чистое завершение без зависших потоков.
- e2e проверка на реальной машине: loopback + test.wav → корректные
  RU/EN сегменты, чистый останов.

### Что осталось
- Запрещённое в спринте отложено: VAD, diarization, endpoint detection,
  partial results, streaming decoder, overlap, buffer optimization, LLM.

### Следующий шаг
- Sprint 3.5 (инфраструктура знаний) — выполнен, см. запись выше.

### Риски
- CPU-инференс модели small может отставать от реального времени на
  слабых машинах; окна без overlap рвут слова на границах.

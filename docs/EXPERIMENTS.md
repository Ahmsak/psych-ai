# EXPERIMENTS — формат хранения аудиоэкспериментов

Описывает артефакты экспериментов захвата (Sprint 4–5). Все прогоны
пишутся в `experiments/<ts>_<mode>/` (каталог в .gitignore — аудио
разговоров не попадает в репозиторий).

## Единый формат аудио (Sprint 5)
Оба потока приводятся к единому формату при записи:
- sample rate: 48000 Гц
- channels: 1 (mono)
- sample width: 2 байта (PCM int16, little-endian)

Обоснование: WASAPI loopback отдаёт 48 кГц нативно (собеседник без
ресемпла и потери качества); речь одноканальна (mono вдвое меньше и
совпадает со входом Whisper); PCM16 без потерь и пишется прямо в WAV.
Понижение до 16 кГц для распознавания делает транскрайбер (Whisper),
хранимый мастер остаётся в 48 кГц.

## Режимы (скрипты в tools/)
- `run_capture_experiment.py` — одиночный loopback (Sprint 4, шаг 1).
- `run_dual_experiment.py` — mic + loopback (Sprint 4, шаг 2).
- `run_timeline_experiment.py` — mic + loopback в едином формате с
  временной шкалой и metadata.json (Sprint 5).

## Артефакты timeline-прогона
`experiments/<ts>_timeline/`:
- `mic.wav`, `loopback.wav` — независимые дорожки в едином формате;
- `mic_transcription.txt`, `loopback_transcription.txt` — раздельные
  транскрипции (faster-whisper);
- `metadata.json` — описание прогона (см. ниже);
- `log.txt` — человекочитаемая сводка.

Дорожки НЕ объединяются, НЕ синхронизируются, НЕ диаризуются — это
подготовка к будущему объединению (см. docs/adr/ADR-006).

## metadata.json
Пригоден для будущего объединения потоков. Ключи:
- `session_id`, `created_at`, `sprint`;
- `unified_format`: {sample_rate, channels, sample_width_bytes, encoding};
- `note`: явно фиксирует, что дорожки независимы;
- `microphone` и `loopback`, каждый:
  - `role`, `device`, `native_sample_rate`, `native_channels`,
    `stored_format`;
  - `record_start` — время старта записи (ISO-8601);
  - `first_frame_at` — время первого аудиокадра;
  - `duration_sec` — длительность;
  - `rms_max`, `audio_captured` — наличие звука;
  - `wav`, `transcription` — имена артефактов;
  - `errors` — ошибки устройства (пусто, если нет).

Запись атомарна (tmp + os.replace): повреждённый/частичный файл не
пройдёт как валидный metadata.

## Подготовка к Timeline (что уже есть для объединения)
Единый формат + `record_start`/`first_frame_at` на каждый поток дают
общую временную опору: в будущем дорожки можно выровнять по времени
первого кадра без пересчёта форматов. Само объединение — вне Sprint 5.

## Session Timeline (Sprint 6)
`timeline.json` — единая временная модель разговора, строится из
`metadata.json` (без микса аудио, без LLM, см. ADR-007).

Построение: `python tools/build_timeline.py [<dir>]` — пишет
timeline.json (атомарно) и проверяет согласованность; exit!=0 при FAIL.

Ключи timeline.json:
- `session_id`, `created_at`, `sprint`, `source_metadata`;
- `timeline_start` = min(record_start обоих потоков);
- `timeline_end` = max(record_start + duration);
- `duration_sec`;
- `unified_format`;
- `tracks`: {microphone, loopback} с role/wav/transcription/
  stored_format/record_start/first_frame_at/duration_sec/audio_captured;
- `offsets`: {per_track_sec, loopback_minus_mic_sec, method}
  (offset = first_frame_at − timeline_start, ADR-007);
- `artifacts`: имена wav/transcription на поток;
- `note`: дорожки НЕ объединены/не синхронизированы/не диаризованы.

Проверки согласованности (Задача 4, sensor-first): FAIL если offset
невозможно определить; timeline противоречит metadata (session_id,
длительности, имена артефактов); дорожки имеют несовместимый формат;
timeline повреждён (нет ключей / не парсится).

## Orchestrator Pipeline (Sprint 9)
`orchestrator/pipeline.py` — единый расширяемый конвейер обработки
Session. Orchestrator — единственная точка управления этапами, без
бизнес-логики (каждый этап делегирует доменной Session). Без LLM,
памяти, анализа.

Этапы: Load Session → Validate Session → Build Statistics → Finalize.
Расширение — добавлением PipelineStage в Pipeline.stages.

API:
- `Orchestrator().run(session)` → PipelineResult (принимает Session,
  путь к каталогу эксперимента или None → последний эксперимент);
  никогда не бросает исключение — ошибки в result.errors.
- `Pipeline([stages]).run(source)` напрямую.

PipelineResult: status (PASS/WARNING/FAIL), warnings, errors, statistics,
duration, stages_completed.

Логирование (logger `psychai.pipeline`, по одному сообщению на этап):
Session Loaded, Validation Passed, Statistics Built, Pipeline Finished.

Проверки (sensor-first): FAIL если Session невалидна (validate FAIL);
нет Conversation; Pipeline прерван (PipelineAbort); неожиданное
исключение (перехват → errors). WARNING пробрасывается из
Session.validate.

## Session Domain Model (Sprint 8, главный объект продукта)
Пакет `session/` — главный объект предметной области и единственная
точка входа для Orchestrator (ADR-009). Объединяет все артефакты одной
консультации: metadata, timeline, conversation, artifacts, statistics,
validation. Без анализа/LLM; текст Whisper не меняется.

API:
- `from session import Session, load_session, save_session`;
- `load_session([dir])` — собирает Session из артефактов (строит
  timeline/conversation в памяти, если файлов нет); БЕЗ записи;
- `save_session(session[, path])` — пишет session.json (атомарно)
  только по явному вызову;
- `load_session_file(path)` — восстановление из session.json;
- аксессоры: `session.metadata`, `.timeline`, `.conversation`,
  `.artifacts`, `.statistics`, `.duration`, `.client_name` (задел),
  `.session_id`.

Statistics (объективные метаданные, без интерпретации): длительность,
число реплик, реплики психолога/клиента, % времени каждой стороны
(если есть тайминги), общее число слов.

Validation: `session.validate()` → PASS / WARNING / FAIL с причинами.
FAIL: нет metadata/timeline или рассинхрон session_id. WARNING: пустой
conversation или нет реплик одной из сторон.

`session.json` — сериализованный снимок консультации (session_id,
metadata, timeline, conversation, statistics, validation).

Совместимость: `tools/session_manager.py` остаётся тонкой обёрткой для
Sprint 6/7; `session/session.py` — ре-экспорт доменной Session.

## Session API (Sprint 6, загрузчики — совместимый слой)
`tools/session_manager.py` — единый интерфейс загрузки:
- `load_timeline([dir])` → dict Timeline (строит из metadata в памяти,
  если timeline.json нет; без сайд-эффектов записи);
- `load_session([dir])` → объект Session с доступом к session_id,
  timeline_start/end, tracks, offsets, offset_of(), wav_path(),
  transcription_path()/text(), conversation. Это структура для
  дальнейшей работы (будущее объединение/UI/анализ) — источник истины
  для Session.

## Conversation (Sprint 7, продуктовый модуль)
Пакет `conversation/` (НЕ tools/ — первый продуктовый модуль) собирает
из двух транскрипций единый упорядоченный по времени диалог. Без
анализа/диаризации/LLM; текст Whisper не меняется (ADR-008).

Данные о таймингах: `run_timeline_experiment.py` дополнительно сохраняет
`mic_segments.json` / `loopback_segments.json` — нативные сегменты
Whisper {start, end, text, confidence}.

`conversation.json` — главный источник данных для будущего анализа:
- `session_id`, `sprint`, `note`, `utterance_count`;
- `utterances`: список реплик, каждая с id, speaker, start_time,
  end_time, text, source, confidence. Отсортированы по start_time.
- speaker по источнику: microphone → psychologist, loopback → client.
- время реплики = offset дорожки (timeline) + seg.start.

API:
- `from conversation import load_conversation` →
  `load_conversation([dir], write=True)` строит, проверяет и пишет
  conversation.json;
- `Session.conversation` (session_manager) — ленивая сборка без записи.

Проверки (Задача 5, sensor-first): FAIL если реплики не по времени;
нет speaker; нет text; conversation повреждён; conversation
противоречит timeline (session_id / время вне границ).

## Sensor-first проверка
`python tools/check_experiment.py [<dir>]` — измеримые PASS/FAIL:
metadata есть/парсится/полон; WAV открывается и совпадает с единым
форматом; audio_captured=YES ⇒ кадры есть; при наличии звука есть
транскрипция; ошибки устройства сообщаются. exit!=0 при любом FAIL.

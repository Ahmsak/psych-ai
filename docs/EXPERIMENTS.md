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

## Session API (Sprint 6)
`tools/session_manager.py` — единый интерфейс загрузки:
- `load_timeline([dir])` → dict Timeline (строит из metadata в памяти,
  если timeline.json нет; без сайд-эффектов записи);
- `load_session([dir])` → объект Session с доступом к session_id,
  timeline_start/end, tracks, offsets, offset_of(), wav_path(),
  transcription_path()/text(). Это структура для дальнейшей работы
  (будущее объединение/UI/анализ) — источник истины для Session.

## Sensor-first проверка
`python tools/check_experiment.py [<dir>]` — измеримые PASS/FAIL:
metadata есть/парсится/полон; WAV открывается и совпадает с единым
форматом; audio_captured=YES ⇒ кадры есть; при наличии звука есть
транскрипция; ошибки устройства сообщаются. exit!=0 при любом FAIL.

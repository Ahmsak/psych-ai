# DEPENDENCIES — зависимости PsychAI

Обновляется при добавлении, удалении или замене библиотек.
Критичность: CORE (без неё MVP не работает) / GUI / TRANSITIVE (тянется
автоматически) / DEV.

## Прямые зависимости

### pyaudiowpatch 0.2.12.8
- Назначение: захват системного звука через WASAPI loopback (форк
  PyAudio/PortAudio с готовым wheel).
- Используется: capture/
- Критичность: CORE
- Альтернативы: soundcard (баги, хобби-проект), sounddevice (нет loopback
  без пересборки PortAudio), нативный WASAPI через ctypes (много работы).
  Выбор обоснован в ADR-002.

### faster-whisper 1.2.1
- Назначение: локальная транскрипция речи (Whisper на ctranslate2).
- Используется: transcription/
- Критичность: CORE
- Альтернативы: openai-whisper (медленнее на CPU), whisper.cpp (C++,
  биндинги), облачные STT (исключены: конфиденциальность сессий).

### ctranslate2 4.8.1
- Назначение: инференс-движок для faster-whisper (int8 на CPU).
- Используется: transcription/ (через faster-whisper)
- Критичность: CORE
- Альтернативы: нет в рамках faster-whisper (его рантайм).

### numpy 2.5.1
- Назначение: ресемплинг 48к→16к, RMS, преобразование int16→float32.
- Используется: transcription/
- Критичность: CORE
- Альтернативы: scipy.signal (лишняя тяжёлая зависимость), pure-python
  (медленно).

### PySide6 6.11.1 (+ Addons, Essentials, shiboken6)
- Назначение: GUI (главное окно).
- Используется: ui/, app.py
- Критичность: GUI (MVP-конвейер run_stream.py не зависит).
- Состояние: НЕ импортируется в активном Python 3.12 — см. ENVIRONMENT.md.
- Альтернативы: PyQt6 (лицензия GPL/коммерческая), tkinter (беднее).

### av 18.0.0
- Назначение: декодирование аудиофайлов для faster-whisper (вместо
  системного ffmpeg).
- Используется: transcription/ (через faster-whisper, файловый путь)
- Критичность: CORE (транзитивно обязательна для faster-whisper)

### onnxruntime 1.27.0
- Назначение: рантайм Silero VAD внутри faster-whisper (vad_filter=True).
- Используется: transcription/ (через faster-whisper)
- Критичность: CORE (пока включён vad_filter)

### huggingface_hub 1.23.0 (+ tokenizers, hf-xet)
- Назначение: скачивание весов Whisper при первом запуске.
- Используется: transcription/ (через faster-whisper)
- Критичность: CORE при первом запуске; после кэширования модели —
  офлайн-работа.

## Остальное в requirements.txt

anyio, certifi, click, colorama, filelock, flatbuffers, fsspec, h11,
httpcore, httpx, idna, packaging, protobuf, PyYAML, setuptools, tqdm,
typing_extensions — TRANSITIVE: тянутся указанными выше пакетами,
напрямую кодом проекта не используются. Не удалять и не обновлять
отдельно.

## Инструменты вне requirements.txt

- Hermes Agent v0.19.0 — ИИ-агент разработки (CLI hermes). DEV.
- ffmpeg — заявлен в окружении, но в PATH отсутствует; кодом проекта
  напрямую не используется (см. ENVIRONMENT.md).

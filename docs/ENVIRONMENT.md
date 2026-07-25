# ENVIRONMENT — рабочее окружение PsychAI

Обновляется после изменения окружения или зависимостей.
Снимок сделан 2026-07-25 (Sprint 3.5) реальными командами на машине.

## ОС

- Windows 10 22H2 (Version 10.0.19045)
- Проект: C:\works\psych-ai
- Shell агента: git-bash/MSYS (POSIX-синтаксис; PowerShell-команды не работают)

## Python

- Python 3.12.9 — C:\Program Files\Python312\python.exe (активный, py -3.12 = default)
- pip ставит пользовательские пакеты в
  C:\Users\lenin126\AppData\Roaming\Python\Python312\site-packages
- Виртуальное окружение НЕ используется (системный интерпретатор).
- ВНИМАНИЕ: в __pycache__ встречаются артефакты cpython-313 — раньше
  запускался и Python 3.13. Рабочий интерпретатор проекта — 3.12.

## Ключевые пакеты (проверено импортом, 2026-07-25)

- pyaudiowpatch 0.2.12.8 — импортируется, WASAPI loopback работает
- ctranslate2 4.8.1 — импортируется
- faster-whisper 1.2.1 — импортируется; модель small скачана в
  C:\Users\lenin126\.cache\huggingface\hub\models--Systran--faster-whisper-small
- numpy 2.5.1 — импортируется
- av (18.0.0 в requirements) — декодер аудио для faster-whisper
- PySide6 6.11.1 — в requirements.txt, но НЕ импортируется в Python 3.12
  (ModuleNotFoundError). GUI (main.py) не запустится до установки.
  MVP run_stream.py от PySide6 не зависит.

## Visual C++

- VC++ Runtime необходим для ctranslate2/onnxruntime; косвенно проверен:
  ctranslate2 импортируется и работает → runtime присутствует.

## ffmpeg

- НЕ найден в PATH (bash: ffmpeg: command not found).
- faster-whisper работает без системного ffmpeg (использует пакет av),
  транскрипция подтверждена. Если появится код, зовущий ffmpeg напрямую —
  его нужно установить и добавить в PATH.

## Hermes

- Hermes Agent v0.19.0 (CLI `hermes` в PATH), установлен через uv/pip:
  C:\Users\lenin126\AppData\Roaming\uv\tools\hermes-agent

## WASAPI / аудио

- WASAPI доступен; loopback-захват дефолтного устройства вывода работает
  на 48000 Гц (проверено tests/capture_live_check.py и e2e Sprint 3).
- Во время тишины loopback НЕ выдаёт фреймы — используйте
  auto_stop_seconds в CaptureConfig для гарантированного завершения.

## Verification

Автоматически (рекомендуется):

    python tools/verify_environment.py

Вручную:

    python --version                    # ожидается 3.12.x
    python -c "import pyaudiowpatch"    # без ошибок
    python -c "import ctranslate2, faster_whisper, numpy"
    python -c "import PySide6"          # сейчас FAIL — известная проблема
    ffmpeg -version                     # сейчас FAIL — нет в PATH
    hermes --version
    python tests/capture_live_check.py silence 5   # WASAPI loopback
    python run_stream.py                # полный конвейер (Ctrl+C для выхода)

## Правила

- Ничего не переустанавливать и не менять версии без необходимости.
- Проблемы среды сначала СООБЩАЮТСЯ владельцу, не чинятся автоматически.

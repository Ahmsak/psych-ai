# Psych AI

AI-ассистент для психологов (ассистирует, НЕ заменяет). MVP-стадия.

Сейчас работает: потоковая транскрипция системного звука Windows
(WASAPI loopback → faster-whisper → консоль).

    python tools/verify_environment.py   # проверка среды
    python run_stream.py                 # запуск MVP (Ctrl+C — выход)

Новому разработчику или ИИ-агенту: начни с **START_HERE.md**.
Знания проекта: каталог **docs/**.

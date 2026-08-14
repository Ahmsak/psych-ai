# Psych AI

AI-ассистент для психологов (ассистирует, НЕ заменяет). MVP-стадия.

Сейчас работает:
- потоковая транскрипция системного звука Windows (WASAPI loopback →
  faster-whisper → консоль);
- live-запись сессии: микрофон + loopback одновременно пишутся в два
  отдельных WAV и сохраняются в SQLite (Sprint 10);
- post-stop транскрипция записанных WAV: RAW TranscriptSegments в SQLite
  (Sprint 11).

    python tools/verify_environment.py   # проверка среды
    python run_stream.py                 # запуск MVP (Ctrl+C — выход)

Новому разработчику или ИИ-агенту: начни с **START_HERE.md**.
Знания проекта: каталог **docs/**.

# ADR-011: Порт персистентности Session → SessionStore

## Status
Accepted

## Context
До Sprint 10 доменная Session (session/model.py) не имела точки записи в
БД; эксперименты сохраняли артефакты как файлы (metadata.json,
session.json). Live recording vertical slice требует, чтобы завершённая
запись попадала в SQLite (Session + AudioTrack), а позже — RAW
TranscriptSegment. Прямая зависимость домена от SQLAlchemy нарушила бы
разделение ответственности и усложнила бы тестирование Session в изоляции.

## Decision
1. Доменная Session НЕ импортирует SQLAlchemy и не пишет в БД. Вся
   персистентность спрятана за портом SessionStore (db/session_store.py).
2. SessionStore — единственное место в live/post-stop пути, видящее
   SQLAlchemy (engine/session/repositories/models). Методы порта:
   create_session, add_audio_track, finalize_session, get_tracks,
   get_session_status, set_session_status, add_transcript_segments.
3. Orchestrator владеет экземпляром SessionStore и передаёт его в
   session.start_recording(tracks, store); transcribe_session читает треки
   и пишет сегменты только через порт.
4. FK-политика (CASCADE/RESTRICT/SET NULL) определена в db/models.py и
   проверена миграцией; порт не дублирует её.

## Consequences
- (+) Session тестируется без БД; персистентность изолирована и заменима.
- (+) Один узкий порт между доменом и SQLAlchemy (соответствует
  правилу владельца «Session→persistence so Session avoids SQLAlchemy»).
- (+) Post-stop transcription и live slice делят один порт — нет второго
  слоя доступа к данным.
- (−) Порт дублирует часть полей модели (SPEAKER_MAP и т.п. живёт в
  session_store.py, не в домене) — осознанный компромисс изоляции.
- Схема версионируется (SCHEMA_VERSION, db/migrations.py); несовместимая
  старая схема поднимает SchemaMigrationError, а не перезаписывается.

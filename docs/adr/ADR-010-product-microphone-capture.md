# ADR-010: Продуктовый захват микрофона (capture/mic.py)

## Status
Accepted

## Context
До Sprint 10 захват микрофона жил только внутри экспериментальных
скриптов tools/ (MicRecorder в run_dual_experiment.py, TimedMicRecorder в
run_timeline_experiment.py). Loopback уже был продуктовым модулем
capture/capturer.py (ADR-002), а микрофон — нет. Дублирование логики
захвата в tools/ нарушает принцип «одна ответственность на модуль» и
мешает live-recording вертикальному срезу (Orchestrator должен
координировать оба потока через единый capture-API).

## Decision
1. Захват микрофона вынесен в продуктовый модуль capture/mic.py
   (MicrophoneCapture) — тот же audio-I/O контракт, что у
   SystemAudioCapture: блокирующее чтение в daemon-потоке, накопление
   кадров, rms_max/errors, sample_rate/output_channels, idempotent stop(),
   iter_chunks(timeout).
2. capture/mic.py изолирует зависимости: не импортирует Session,
   Orchestrator, persistence, UI, SQLAlchemy.
3. Оба экспериментальных скрипта переведены на capture.MicrophoneCapture;
   поведение сохранено (включая опциональный transform для единого формата).
4. Live slice использует MicrophoneCapture + SystemAudioCapture через
   RecordedTrack (capture/track.py) — оба потока пишутся в WAV.

## Consequences
- (+) Единый продуктовый capture-API для обоих источников; Orchestrator
  координирует mic и loopback симметрично.
- (+) Дублирование захвата в tools/ устранено; эксперименты тоньше.
- (+) capture/ остаётся изолированным (audio I/O only), ось
  Orchestrator→Session→Audio не нарушена.
- (−) tools/run_*_experiment.py теперь зависят от продуктового capture/
  (допустимо: эксперименты — не продукт, но переиспользуют продукт).
- Ресемпл/downmix — вне mic.py (как и в loopback); при необходимости
  задаётся transform (единый формат) или делается транскрайбером.

"""Sprint 9 tests: Orchestrator pipeline, result, logging, sensor-first.

Offline and deterministic: synthetic Session objects, no audio, no model.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from session import Session
from orchestrator.pipeline import (Pipeline, PipelineResult, PipelineStage,
                                   default_stages, PASS, WARNING, FAIL)
from orchestrator.orchestrator import Orchestrator


def _meta():
    return {"session_id": "s1"}


def _timeline():
    return {"session_id": "s1", "duration_sec": 20.0}


def _conversation(one_sided=False):
    utts = [{"id": 0, "speaker": "psychologist", "start_time": 0.0,
             "end_time": 2.0, "text": "Здравствуйте как дела",
             "source": "microphone"}]
    if not one_sided:
        utts.append({"id": 1, "speaker": "client", "start_time": 2.0,
                     "end_time": 6.0, "text": "Всё хорошо спасибо",
                     "source": "loopback"})
    return {"session_id": "s1", "utterances": utts}


def _good_session():
    return Session(metadata=_meta(), timeline=_timeline(),
                   conversation=_conversation())


# ------------------------------- happy path ---------------------------- #

def test_pipeline_pass_runs_all_stages():
    r = Pipeline().run(_good_session())
    assert r.status == PASS
    assert r.errors == []
    assert r.stages_completed == [
        "Load Session", "Validate Session", "Build Statistics", "Finalize"]
    assert r.statistics["total_words"] == 6
    assert r.duration is not None


def test_result_to_dict():
    r = Pipeline().run(_good_session())
    d = r.to_dict()
    assert set(d) >= {"status", "warnings", "errors", "statistics",
                      "duration", "stages_completed"}


def test_logging_one_message_per_stage(caplog):
    import logging
    with caplog.at_level(logging.INFO, logger="psychai.pipeline"):
        Pipeline().run(_good_session())
    msgs = [r.message for r in caplog.records]
    assert "Session Loaded" in msgs
    assert "Validation Passed" in msgs
    assert "Statistics Built" in msgs
    assert "Pipeline Finished" in msgs


# ------------------------------- sensor-first -------------------------- #

def test_fail_when_session_invalid():
    # missing timeline -> Session.validate() FAIL
    s = Session(metadata=_meta(), timeline=None, conversation=_conversation())
    r = Pipeline().run(s)
    assert r.status == FAIL
    assert any("invalid" in e for e in r.errors)
    assert "Validate Session" not in r.stages_completed


def test_fail_when_conversation_missing():
    s = Session(metadata=_meta(), timeline=_timeline(), conversation=None)
    r = Pipeline().run(s)
    assert r.status == FAIL
    assert any("conversation" in e for e in r.errors)


def test_fail_on_bad_source_type():
    r = Pipeline().run(12345)  # not a Session or path
    assert r.status == FAIL
    assert any("neither a Session" in e for e in r.errors)


def test_fail_on_unexpected_exception():
    def boom(ctx):
        raise RuntimeError("kaboom")
    stages = default_stages()
    stages.insert(0, PipelineStage("Boom", boom))
    r = Pipeline(stages).run(_good_session())
    assert r.status == FAIL
    assert any("unexpected error" in e for e in r.errors)


def test_warning_propagates_from_session():
    s = Session(metadata=_meta(), timeline=_timeline(),
                conversation=_conversation(one_sided=True))
    r = Pipeline().run(s)
    assert r.status == WARNING
    assert any("client" in w for w in r.warnings)


# ------------------------------- extensibility ------------------------- #

def test_pipeline_is_extensible():
    marker = {}
    def extra(ctx):
        marker["ran"] = True
    stages = default_stages() + [PipelineStage("Extra", extra)]
    r = Pipeline(stages).run(_good_session())
    assert marker.get("ran") is True
    assert "Extra" in r.stages_completed


# ------------------------------- orchestrator API ---------------------- #

def test_orchestrator_run_returns_result():
    o = Orchestrator()
    r = o.run(_good_session())
    assert isinstance(r, PipelineResult)
    assert r.status == PASS

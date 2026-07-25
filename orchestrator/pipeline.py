"""Session processing pipeline (Sprint 9).

A minimal, extensible pipeline that wires existing product modules
together for post-capture Session processing. NO business logic lives
here — each stage delegates to the domain Session (Sprint 8). No LLM, no
memory, no analysis.

Stages: Load Session -> Validate Session -> Build Statistics -> Finalize.
Extend by appending PipelineStage entries to Pipeline.stages.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

logger = logging.getLogger("psychai.pipeline")

# Result status levels.
PASS = "PASS"
WARNING = "WARNING"
FAIL = "FAIL"


@dataclass
class PipelineResult:
    """Outcome of a pipeline run."""

    status: str = PASS
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    statistics: Optional[dict] = None
    duration: Optional[float] = None      # wall-clock of the run, seconds
    stages_completed: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "warnings": self.warnings,
            "errors": self.errors,
            "statistics": self.statistics,
            "duration": self.duration,
            "stages_completed": self.stages_completed,
        }


@dataclass
class PipelineContext:
    """Mutable state passed between stages."""

    source: object                       # Session or experiment dir (str)
    session: object = None
    result: PipelineResult = field(default_factory=PipelineResult)


@dataclass
class PipelineStage:
    """One named processing step."""

    name: str
    run: Callable[["PipelineContext"], None]


class PipelineAbort(Exception):
    """Raised by a stage to stop the pipeline with a FAIL result."""


# --------------------------------------------------------------------- #
# Default stages (delegate to the domain Session; no business logic here)
# --------------------------------------------------------------------- #

def _stage_load(ctx: PipelineContext) -> None:
    from session import Session, load_session
    src = ctx.source
    if isinstance(src, Session):
        ctx.session = src
    elif isinstance(src, str):
        ctx.session = load_session(src)
    else:
        raise PipelineAbort("source is neither a Session nor a directory path")
    if ctx.session is None:
        raise PipelineAbort("session could not be loaded")
    logger.info("Session Loaded")


def _stage_validate(ctx: PipelineContext) -> None:
    v = ctx.session.validate()
    if v.status == FAIL:
        raise PipelineAbort(f"session invalid: {v.reasons}")
    if ctx.session.conversation is None:
        raise PipelineAbort("conversation is missing")
    if v.status == WARNING:
        ctx.result.warnings.extend(v.reasons)
        logger.info("Validation Passed (with warnings)")
    else:
        logger.info("Validation Passed")


def _stage_statistics(ctx: PipelineContext) -> None:
    ctx.result.statistics = ctx.session.statistics.to_dict()
    logger.info("Statistics Built")


def _stage_finalize(ctx: PipelineContext) -> None:
    if ctx.result.status != FAIL:
        ctx.result.status = WARNING if ctx.result.warnings else PASS
    logger.info("Pipeline Finished")


def default_stages() -> List[PipelineStage]:
    return [
        PipelineStage("Load Session", _stage_load),
        PipelineStage("Validate Session", _stage_validate),
        PipelineStage("Build Statistics", _stage_statistics),
        PipelineStage("Finalize", _stage_finalize),
    ]


class Pipeline:
    """Extensible sequence of stages producing a PipelineResult."""

    def __init__(self, stages: Optional[List[PipelineStage]] = None) -> None:
        self.stages = stages if stages is not None else default_stages()

    def run(self, source) -> PipelineResult:
        ctx = PipelineContext(source=source)
        start = time.monotonic()
        try:
            for stage in self.stages:
                stage.run(ctx)
                ctx.result.stages_completed.append(stage.name)
        except PipelineAbort as exc:
            ctx.result.status = FAIL
            ctx.result.errors.append(str(exc))
            logger.error("Pipeline aborted: %s", exc)
        except Exception as exc:  # unexpected -> FAIL, never crash the caller
            ctx.result.status = FAIL
            ctx.result.errors.append(f"unexpected error: {exc!r}")
            logger.error("Pipeline error: %r", exc)
        finally:
            ctx.result.duration = round(time.monotonic() - start, 4)
        return ctx.result

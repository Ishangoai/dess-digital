"""The minuting pipeline: one structured LLM call per stage."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from app.llm import LLMClient, LLMError, LLMOutputValidationError, Usage
from app.minutes import prompts
from app.minutes.checks import LintIssue, lint_draft
from app.minutes.llm_schemas import (
    DraftMinutes,
    EvidenceAnalysis,
    EvidenceMap,
    PolicySelection,
    Reconsideration,
    ValidationReport,
)
from app.minutes.prompts import PromptContext, render_mapping


class PipelineStage(StrEnum):
    EVIDENCE = "evidence"
    POLICY = "policy"
    STYLE = "style"
    VALIDATION = "validation"
    RECONSIDERATION = "reconsideration"


@dataclass(frozen=True)
class StageResult[T]:
    stage: PipelineStage
    output: T
    usage: Usage
    provider: str
    model: str
    latency_ms: float


class StageError(Exception):
    def __init__(self, stage: PipelineStage, cause: LLMError) -> None:
        super().__init__(f"{stage} stage failed: {cause}")
        self.stage = stage
        self.cause = cause
        self.raw_text = cause.raw_text if isinstance(cause, LLMOutputValidationError) else None


@dataclass
class DraftingResult:
    selection: PolicySelection
    draft_initial: DraftMinutes
    validation: ValidationReport
    reconsideration: Reconsideration | None
    draft: DraftMinutes
    lint: list[LintIssue] = field(default_factory=list)


OnStage = Callable[[StageResult[Any]], None]


class Pipeline:
    def __init__(self, llm: LLMClient, ctx: PromptContext, max_tokens: int) -> None:
        self.llm = llm
        self.ctx = ctx
        self.max_tokens = max_tokens

    def _call[T: BaseModel](
        self, stage: PipelineStage, schema: type[T], message: str
    ) -> StageResult[T]:
        try:
            r = self.llm.generate_structured(
                message, schema=schema, system=self.ctx.system(), max_tokens=self.max_tokens
            )
        except LLMError as e:
            raise StageError(stage, e) from e
        return StageResult(stage, r.output, r.usage, r.provider, r.model, r.latency_ms)

    def analyse_evidence(self) -> StageResult[EvidenceAnalysis]:
        guidance = self.ctx.profile.operational_instructions.stages.evidence
        message = self.ctx.message(prompts.TASK_EVIDENCE, guidance)
        return self._call(PipelineStage.EVIDENCE, EvidenceAnalysis, message)

    def select_content(
        self, mapping: EvidenceMap, analysis: EvidenceAnalysis
    ) -> StageResult[PolicySelection]:
        stages = self.ctx.profile.operational_instructions.stages
        message = self.ctx.message(
            prompts.TASK_POLICY,
            stages.policy,
            confirmed_evidence_map=render_mapping(mapping),
            evidence_notes=_analysis_notes(analysis),
        )
        return self._call(PipelineStage.POLICY, PolicySelection, message)

    def write_minutes(
        self, mapping: EvidenceMap, selection: PolicySelection
    ) -> StageResult[DraftMinutes]:
        stages = self.ctx.profile.operational_instructions.stages
        guidance = "\n\n".join(g for g in (stages.style, stages.questions) if g)
        message = self.ctx.message(
            prompts.TASK_STYLE,
            guidance or None,
            confirmed_evidence_map=render_mapping(mapping),
            selection=selection,
        )
        return self._call(PipelineStage.STYLE, DraftMinutes, message)

    def validate(
        self,
        mapping: EvidenceMap,
        selection: PolicySelection,
        draft: DraftMinutes,
        lint: list[LintIssue],
    ) -> StageResult[ValidationReport]:
        message = self.ctx.message(
            prompts.TASK_VALIDATION,
            self.ctx.profile.operational_instructions.stages.validation,
            confirmed_evidence_map=render_mapping(mapping),
            selection=selection,
            draft=draft,
            automated_checks=[str(i) for i in lint],
        )
        return self._call(PipelineStage.VALIDATION, ValidationReport, message)

    def reconsider(
        self, selection: PolicySelection, draft: DraftMinutes, report: ValidationReport
    ) -> StageResult[Reconsideration]:
        message = self.ctx.message(
            prompts.TASK_RECONSIDER, selection=selection, draft=draft, findings=report
        )
        return self._call(PipelineStage.RECONSIDERATION, Reconsideration, message)

    def run_drafting(
        self,
        mapping: EvidenceMap,
        analysis: EvidenceAnalysis,
        on_stage: OnStage | None = None,
    ) -> DraftingResult:
        def done[T: BaseModel](result: StageResult[T]) -> T:
            if on_stage:
                on_stage(result)
            return result.output

        selection = done(self.select_content(mapping, analysis))
        draft = done(self.write_minutes(mapping, selection))
        lint = lint_draft(draft, mapping, selection)
        report = done(self.validate(mapping, selection, draft, lint))

        reconsideration = None
        final = draft
        if report.findings:  # one reconsideration, never a second validation loop
            reconsideration = done(self.reconsider(selection, draft, report))
            final = reconsideration.revised_minutes

        return DraftingResult(
            selection=selection,
            draft_initial=draft,
            validation=report,
            reconsideration=reconsideration,
            draft=final,
            lint=lint_draft(final, mapping, selection),
        )


def _analysis_notes(analysis: EvidenceAnalysis) -> str:
    """Source limitations and uncertainties from stage 1, as context for later stages."""
    payload = {
        "sources": [s.model_dump() for s in analysis.sources],
        "particulars": analysis.particulars.model_dump(),
        "cross_item_links": [c.model_dump() for c in analysis.cross_item_links],
        "uncertainties": [u.model_dump() for u in analysis.uncertainties],
    }
    return json.dumps(payload, indent=1)

"""The minuting pipeline. Stage 1 and validation see the whole meeting; policy, writing and
reconsideration run once per agenda item, in parallel, and code assembles the results."""

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from app.llm import LLMClient, LLMError, LLMOutputValidationError, Usage
from app.minutes import prompts
from app.minutes.checks import LintIssue, lint_draft
from app.minutes.llm_schemas import (
    ActionEntry,
    AnchorKind,
    DraftMinutes,
    EvidenceAnalysis,
    EvidenceMap,
    Finding,
    FindingDecision,
    HeaderReconsideration,
    ItemDraft,
    ItemReconsideration,
    ItemSelection,
    ItemSelectionResult,
    MeetingHeaderDraft,
    PolicySelection,
    Reconsideration,
    ValidationReport,
)
from app.minutes.prompts import PromptContext, Unit, item_context, render_mapping, units


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
    system: str = ""  # instructions sent with the call
    message: str = ""  # evidence, guidance, earlier outputs and task
    item_ref: str | None = None  # set for per-item calls; "header" for the header

    @property
    def label(self) -> str:
        return f"{self.stage}:{self.item_ref}" if self.item_ref else str(self.stage)


class StageError(Exception):
    def __init__(
        self,
        stage: PipelineStage,
        cause: LLMError,
        system: str = "",
        message: str = "",
        item_ref: str | None = None,
    ) -> None:
        where = f" (item {item_ref})" if item_ref and item_ref != HEADER else ""
        super().__init__(f"{stage} stage failed{where}: {cause}")
        self.stage = stage
        self.label = f"{stage}:{item_ref}" if item_ref else str(stage)
        self.cause = cause
        self.raw_text = cause.raw_text if isinstance(cause, LLMOutputValidationError) else None
        self.system = system
        self.message = message


@dataclass
class DraftingResult:
    selection: PolicySelection
    draft_initial: DraftMinutes
    validation: ValidationReport
    reconsideration: Reconsideration | None
    draft: DraftMinutes
    lint: list[LintIssue] = field(default_factory=list)


OnCall = Callable[[StageResult[Any]], None]  # every LLM call, in a stable order
OnOutput = Callable[[PipelineStage, BaseModel], None]  # each stage's assembled output

HEADER = "header"


class Pipeline:
    def __init__(self, llm: LLMClient, ctx: PromptContext, max_tokens: int, workers: int = 4):
        self.llm = llm
        self.ctx = ctx
        self.max_tokens = max_tokens
        self.workers = workers

    def _call[T: BaseModel](
        self, stage: PipelineStage, schema: type[T], message: str, item_ref: str | None = None
    ) -> StageResult[T]:
        system = self.ctx.system()
        try:
            r = self.llm.generate_structured(
                message, schema=schema, system=system, max_tokens=self.max_tokens
            )
        except LLMError as e:
            raise StageError(stage, e, system, message, item_ref) from e
        return StageResult(
            stage, r.output, r.usage, r.provider, r.model, r.latency_ms, system, message, item_ref
        )

    def _each[T: BaseModel](
        self,
        stage: PipelineStage,
        schema: type[T],
        jobs: list[tuple[str, str]],
        on_call: OnCall | None,
    ) -> list[T]:
        """One call per (item_ref, message) in parallel; a failed call is retried once."""

        def run(job: tuple[str, str]) -> StageResult[T]:
            ref, message = job
            try:
                return self._call(stage, schema, message, ref)
            except StageError:
                return self._call(stage, schema, message, ref)

        with ThreadPoolExecutor(max(1, self.workers)) as pool:
            futures = [pool.submit(run, job) for job in jobs]
        outputs = []
        for f in futures:  # report in item order; the first failure stops the stage
            result = f.result()
            if on_call:
                on_call(result)
            outputs.append(result.output)
        return outputs

    def analyse_evidence(self) -> StageResult[EvidenceAnalysis]:
        message = self.ctx.message(prompts.TASK_EVIDENCE)
        return self._call(PipelineStage.EVIDENCE, EvidenceAnalysis, message)

    def select_content(
        self, mapping: EvidenceMap, analysis: EvidenceAnalysis, on_call: OnCall | None = None
    ) -> PolicySelection:
        shared = {
            "confirmed_evidence_map": render_mapping(mapping),
            "evidence_notes": _analysis_notes(analysis),
        }
        todo = units(mapping)
        jobs = [
            (
                u.ref,
                self.ctx.message(
                    prompts.TASK_ITEM_POLICY, **shared, **item_context(self.ctx, mapping, u)
                ),
            )
            for u in todo
        ]
        results = self._each(PipelineStage.POLICY, ItemSelectionResult, jobs, on_call)
        return assemble_selection(analysis, todo, results)

    def write_minutes(
        self, mapping: EvidenceMap, selection: PolicySelection, on_call: OnCall | None = None
    ) -> DraftMinutes:
        shared = {"confirmed_evidence_map": render_mapping(mapping)}
        chosen = {s.item_ref: s for s in selection.items}
        todo = [u for u in units(mapping) if u.ref in chosen and _worth_writing(u, chosen[u.ref])]
        jobs = []
        for u in todo:
            mine = ItemSelectionResult(
                selection=chosen[u.ref],
                clarifications=[c for c in selection.clarifications if c.item_ref == u.ref],
            )
            context = item_context(self.ctx, mapping, u)
            context = {"this_item": context.pop("this_item"), "selection": mine, **context}
            jobs.append((u.ref, self.ctx.message(prompts.TASK_ITEM_STYLE, **shared, **context)))
        header_message = self.ctx.message(
            prompts.TASK_HEADER,
            particulars=selection.particulars,
            clarifications=[
                c.model_dump_json() for c in selection.clarifications if c.item_ref is None
            ],
        )
        jobs_header = [(HEADER, header_message)]
        header = self._each(PipelineStage.STYLE, MeetingHeaderDraft, jobs_header, on_call)[0]
        items = self._each(PipelineStage.STYLE, ItemDraft, jobs, on_call)
        return assemble_draft(header, [(u.ref, d) for u, d in zip(todo, items, strict=True)])

    def validate(
        self,
        mapping: EvidenceMap,
        selection: PolicySelection,
        draft: DraftMinutes,
        lint: list[LintIssue],
    ) -> StageResult[ValidationReport]:
        message = self.ctx.message(
            prompts.TASK_VALIDATION,
            confirmed_evidence_map=render_mapping(mapping),
            selection=selection,
            draft=draft,
            automated_checks=[str(i) for i in lint],
        )
        return self._call(PipelineStage.VALIDATION, ValidationReport, message)

    def reconsider(
        self,
        selection: PolicySelection,
        draft: DraftMinutes,
        report: ValidationReport,
        on_call: OnCall | None = None,
    ) -> Reconsideration:
        """Re-run only the items (and header) that have findings."""
        header, parts, loose = split_draft(draft)
        by_ref = findings_by_item(report.findings, draft)
        chosen = {s.item_ref: s for s in selection.items}

        jobs = []
        for ref, item in parts:
            if ref not in by_ref:
                continue
            context: dict[str, Any] = {"this_item": f"Item {ref}: {item.item.heading}"}
            if ref in chosen:
                context["selection"] = chosen[ref]
            context |= {"draft": item, "findings": _findings(by_ref[ref])}
            jobs.append((ref, self.ctx.message(prompts.TASK_ITEM_RECONSIDER, **context)))
        revised = self._each(PipelineStage.RECONSIDERATION, ItemReconsideration, jobs, on_call)
        decisions: list[FindingDecision] = []
        new_items = {ref: r.revised for (ref, _), r in zip(jobs, revised, strict=True)}
        for r in revised:
            decisions += r.decisions

        if HEADER in by_ref:
            message = self.ctx.message(
                prompts.TASK_HEADER_RECONSIDER, draft=header, findings=_findings(by_ref[HEADER])
            )
            done = self._each(
                PipelineStage.RECONSIDERATION, HeaderReconsideration, [(HEADER, message)], on_call
            )[0]
            header = done.revised
            decisions += done.decisions

        merged = [(ref, new_items.get(ref, item)) for ref, item in parts]
        return Reconsideration(
            decisions=decisions, revised_minutes=assemble_draft(header, merged, loose)
        )

    def run_drafting(
        self,
        mapping: EvidenceMap,
        analysis: EvidenceAnalysis,
        on_call: OnCall | None = None,
        on_output: OnOutput | None = None,
    ) -> DraftingResult:
        def done[T: BaseModel](stage: PipelineStage, output: T) -> T:
            if on_output:
                on_output(stage, output)
            return output

        selection = done(PipelineStage.POLICY, self.select_content(mapping, analysis, on_call))
        draft = done(PipelineStage.STYLE, self.write_minutes(mapping, selection, on_call))
        lint = lint_draft(draft, mapping, selection)
        validation = self.validate(mapping, selection, draft, lint)
        if on_call:
            on_call(validation)
        report = done(PipelineStage.VALIDATION, validation.output)

        reconsideration = None
        final = draft
        if report.findings:  # one reconsideration, never a second validation loop
            reconsideration = done(
                PipelineStage.RECONSIDERATION, self.reconsider(selection, draft, report, on_call)
            )
            final = reconsideration.revised_minutes

        return DraftingResult(
            selection=selection,
            draft_initial=draft,
            validation=report,
            reconsideration=reconsideration,
            draft=final,
            lint=lint_draft(final, mapping, selection),
        )


# Assembly: per-item outputs into the whole-meeting shapes the rest of the app uses.


def _scoped(ref: str, ident: str) -> str:
    """Ids are only unique within an item, so prefix them with the item ref."""
    return ident if ident.startswith(f"{ref}.") else f"{ref}.{ident}"


def assemble_selection(
    analysis: EvidenceAnalysis, todo: list[Unit], results: list[ItemSelectionResult]
) -> PolicySelection:
    items, clarifications = [], []
    for unit, r in zip(todo, results, strict=True):
        s = r.selection
        s.item_ref, ref = unit.ref, unit.ref
        renamed: dict[str, str] = {}
        for entries, attr in (
            (s.outcomes, "outcome_id"),
            (s.points, "point_id"),
            (s.actions, "action_id"),
            (s.delegations, "delegation_id"),
        ):
            for e in entries:
                old = getattr(e, attr)
                renamed[old] = _scoped(ref, old)
                setattr(e, attr, renamed[old])
        for c in r.clarifications:
            c.requirement_id = _scoped(ref, c.requirement_id)
            c.item_ref = ref
            c.concerns = renamed.get(c.concerns, c.concerns)
        items.append(s)
        clarifications += r.clarifications
    return PolicySelection(
        particulars=analysis.particulars, items=items, clarifications=clarifications
    )


def _worth_writing(unit: Unit, s: ItemSelection) -> bool:
    """Additional business the policy stage selected nothing for gets no minute."""
    return not unit.additional or bool(s.outcomes or s.points or s.actions or s.delegations)


def assemble_draft(
    header: MeetingHeaderDraft,
    parts: list[tuple[str, ItemDraft]],
    loose_actions: list[ActionEntry] | None = None,
) -> DraftMinutes:
    items, actions, notes = [], [], []
    questions = [
        q.model_copy(
            update={
                "anchor_kind": AnchorKind.MEETING_HEADING,
                "item_ref": None,
                "paragraph_id": None,
            }
        )
        for q in header.questions
    ]
    for ref, part in parts:
        item = part.item.model_copy(update={"item_ref": ref}, deep=True)
        ids: dict[str, str] = {}
        for n, p in enumerate(item.paragraphs, 1):
            new = p.paragraph_id if p.paragraph_id.startswith(f"{ref}.p") else f"{ref}.p{n}"
            ids[p.paragraph_id] = new
            p.paragraph_id = new
        items.append(item)
        for a in part.actions:
            actions.append(
                a.model_copy(
                    update={
                        "action_id": _scoped(ref, a.action_id),
                        "paragraph_id": ids.get(a.paragraph_id, a.paragraph_id),
                    }
                )
            )
        for q in part.questions:
            pid = ids.get(q.paragraph_id or "", q.paragraph_id)
            questions.append(q.model_copy(update={"item_ref": ref, "paragraph_id": pid}))
        notes += [f"{ref}: {note}" for note in part.drafting_notes]
    for n, q in enumerate(questions, 1):
        q.question_id = f"Q{n}"
    return DraftMinutes(
        header=header.header,
        items=items,
        actions=actions + list(loose_actions or []),
        questions=questions,
        drafting_notes=notes,
    )


def split_draft(
    draft: DraftMinutes,
) -> tuple[MeetingHeaderDraft, list[tuple[str, ItemDraft]], list[ActionEntry]]:
    """The inverse of assemble_draft: header, per-item parts, and actions no item owns."""
    owner = {p.paragraph_id: i.item_ref for i in draft.items for p in i.paragraphs}
    header = MeetingHeaderDraft(
        header=draft.header,
        questions=[q for q in draft.questions if q.anchor_kind == AnchorKind.MEETING_HEADING],
    )
    parts = []
    for item in draft.items:
        ref = item.item_ref
        parts.append(
            (
                ref,
                ItemDraft(
                    item=item,
                    actions=[a for a in draft.actions if owner.get(a.paragraph_id) == ref],
                    questions=[
                        q
                        for q in draft.questions
                        if q.anchor_kind != AnchorKind.MEETING_HEADING and q.item_ref == ref
                    ],
                    drafting_notes=[
                        n.removeprefix(f"{ref}: ")
                        for n in draft.drafting_notes
                        if n.startswith(f"{ref}: ")
                    ],
                ),
            )
        )
    loose = [a for a in draft.actions if a.paragraph_id not in owner]
    return header, parts, loose


def findings_by_item(findings: list[Finding], draft: DraftMinutes) -> dict[str, list[Finding]]:
    """Route each finding to its item; anything meeting-wide goes to the header."""
    refs = {i.item_ref for i in draft.items}
    owner = {p.paragraph_id: i.item_ref for i in draft.items for p in i.paragraphs}
    asked = {q.question_id: q.item_ref for q in draft.questions}
    out: dict[str, list[Finding]] = {}
    for f in findings:
        ref = (
            (f.item_ref if f.item_ref in refs else None)
            or owner.get(f.paragraph_id or "")
            or asked.get(f.question_id or "")
            or HEADER
        )
        out.setdefault(ref, []).append(f)
    return out


def _findings(findings: list[Finding]) -> ValidationReport:
    return ValidationReport(findings=findings, summary="")


def _analysis_notes(analysis: EvidenceAnalysis) -> str:
    """Source limitations and uncertainties from stage 1, as context for later stages."""
    payload = {
        "sources": [s.model_dump() for s in analysis.sources],
        "particulars": analysis.particulars.model_dump(),
        "cross_item_links": [c.model_dump() for c in analysis.cross_item_links],
        "uncertainties": [u.model_dump() for u in analysis.uncertainties],
    }
    return json.dumps(payload, indent=1)

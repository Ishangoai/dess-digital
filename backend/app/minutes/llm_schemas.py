"""Structured outputs for each pipeline stage.

Kept simple for Gemini structured output: every field required (nullable where optional),
no free-form dicts, shallow nesting.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class LineRef(BaseModel):
    source_id: str = Field(description="Source id, e.g. A (agenda), T (transcript), N (notes).")
    start: int = Field(description="First line number (inclusive).")
    end: int = Field(description="Last line number (inclusive).")


# Stage 1: understand the evidence


class PurposeKind(StrEnum):
    DECISION = "decision"
    APPROVAL = "approval"
    RECOMMENDATION = "recommendation"
    DISCUSSION = "discussion"
    NOTING = "noting"
    INFORMATION = "information"
    PROCEDURAL = "procedural"
    UNSPECIFIED = "unspecified"


class AgendaItem(BaseModel):
    ref: str = Field(description="Item number exactly as on the agenda, e.g. '4' or '4.1'.")
    heading: str
    stated_purpose: str | None = Field(description="Purpose as worded on the agenda, if any.")
    purpose_kind: PurposeKind = Field(description="An expectation only, not evidence of outcome.")
    linked_papers: list[str]


class AdditionalBusiness(BaseModel):
    key: str = Field(description="AB1, AB2 ... Never invent agenda numbers.")
    heading: str


class Association(StrEnum):
    PRIMARY = "primary"
    RELATED = "related"
    ADDITIONAL_BUSINESS = "additional_business"
    PROCEDURAL = "procedural"
    UNCERTAIN = "uncertain"


class EvidenceSegment(BaseModel):
    segment_id: str = Field(description="S1, S2 ...")
    source: LineRef
    item_ref: str | None = Field(description="Agenda ref or AB key; null if unassigned.")
    association: Association
    summary: str = Field(description="One neutral sentence on what the passage covers.")
    apparent_outcome: str | None = Field(description="Outcome this passage appears to reach.")


class SourceAssessment(BaseModel):
    source_id: str
    description: str
    limitations: list[str] = Field(description="Gaps, unclear speakers, partial coverage etc.")


class InputProblemKind(StrEnum):
    AGENDA_UNUSABLE = "agenda_unusable"
    PROCEEDINGS_UNUSABLE = "proceedings_unusable"
    DIFFERENT_MEETING = "different_meeting"


class InputProblem(BaseModel):
    kind: InputProblemKind
    description: str


class Particulars(BaseModel):
    organisation: str | None
    body: str | None
    meeting_date: str | None
    start_time: str | None
    venue_or_mode: str | None
    chair: str | None
    secretary: str | None
    present: list[str]
    in_attendance: list[str]
    apologies: list[str]
    refs: list[LineRef]


class FactualUncertainty(BaseModel):
    uncertainty_id: str = Field(description="U1, U2 ...")
    item_ref: str | None
    description: str
    competing_readings: list[str]
    refs: list[LineRef]


class CrossItemLink(BaseModel):
    from_ref: str
    to_ref: str
    note: str


class EvidenceMap(BaseModel):
    """The part of stage 1 the user reviews and corrects."""

    agenda_items: list[AgendaItem]
    additional_business: list[AdditionalBusiness]
    segments: list[EvidenceSegment]


class EvidenceAnalysis(EvidenceMap):
    sources: list[SourceAssessment]
    essential_input_problems: list[InputProblem] = Field(
        description="Only problems that make drafting impossible. Usually empty."
    )
    particulars: Particulars
    cross_item_links: list[CrossItemLink]
    uncertainties: list[FactualUncertainty]

    def evidence_map(self) -> EvidenceMap:
        return EvidenceMap(
            agenda_items=self.agenda_items,
            additional_business=self.additional_business,
            segments=self.segments,
        )


# Stage 2: apply the Minuting Policy


class OutcomeType(StrEnum):
    RECEIVED = "received"
    NOTED = "noted"
    DISCUSSED_WITHOUT_CONCLUSION = "discussed_without_conclusion"
    ENDORSED = "endorsed"
    RECOMMENDED = "recommended"
    APPROVED = "approved"
    RESOLVED = "resolved"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    REFERRED = "referred"
    WITHDRAWN = "withdrawn"
    NOT_TAKEN = "not_taken"


class Treatment(StrEnum):
    FULL = "full"
    CONDENSED = "condensed"
    BRIEF = "brief"


class PointFunction(StrEnum):
    CONTEXT = "context"
    EVIDENCE_RELIED_ON = "evidence_relied_on"
    REASONING = "reasoning"
    ALTERNATIVE = "alternative"
    RISK = "risk"
    CHALLENGE = "challenge"
    RESPONSE = "response"
    UNRESOLVED_CONCERN = "unresolved_concern"
    DISSENT = "dissent"
    CONDITION = "condition"
    PROCEDURE = "procedure"
    CONFLICT_OF_INTEREST = "conflict_of_interest"
    STAKEHOLDER_EFFECT = "stakeholder_effect"


class SelectedOutcome(BaseModel):
    outcome_id: str = Field(description="O1, O2 ...")
    outcome_type: OutcomeType
    deciding_body: str | None
    proposition: str = Field(description="What was decided, with its exact scope.")
    limits: list[str]
    conditions: list[str]
    vote_detail: str | None
    refs: list[LineRef]


class SelectedPoint(BaseModel):
    point_id: str = Field(description="P1, P2 ...")
    function: PointFunction
    substance: str
    attribution: str | None = Field(description="Only where attribution is material.")
    refs: list[LineRef]


class SelectedAction(BaseModel):
    action_id: str = Field(description="AC1, AC2 ...")
    task: str
    owner: str | None = Field(description="Null unless agreed in the meeting.")
    due: str | None = Field(description="Null unless agreed in the meeting.")
    refs: list[LineRef]


class SelectedDelegation(BaseModel):
    delegation_id: str = Field(description="D1, D2 ...")
    delegate: str
    authority: str
    limits: list[str]
    conditions: list[str]
    report_back: str | None
    refs: list[LineRef]


class ItemSelection(BaseModel):
    item_ref: str
    heading: str
    treatment: Treatment
    outcomes: list[SelectedOutcome]
    points: list[SelectedPoint]
    actions: list[SelectedAction]
    delegations: list[SelectedDelegation]
    drafting_boundary: list[str] = Field(description="Wording that would overstate the evidence.")
    omitted_summary: str | None = Field(description="What was left out and why, briefly.")


class ClarificationRequirement(BaseModel):
    requirement_id: str = Field(description="R1, R2 ...")
    item_ref: str | None = Field(description="Null for meeting-level particulars.")
    concerns: str = Field(description="Id of the outcome/action/point affected, or 'particulars'.")
    known: str = Field(description="What the evidence does establish.")
    unresolved: str
    why_it_matters: str = Field(description="How the answer would change the record.")
    refs: list[LineRef]


class PolicySelection(BaseModel):
    particulars: Particulars
    items: list[ItemSelection]
    clarifications: list[ClarificationRequirement]


# Stage 3: apply the Writing Style


class ParagraphKind(StrEnum):
    NARRATIVE = "narrative"
    OUTCOME = "outcome"
    ACTION = "action"
    DELEGATION = "delegation"
    PROCEDURAL = "procedural"


class MinuteParagraph(BaseModel):
    paragraph_id: str = Field(description="Item ref plus .p and a number, e.g. '4.p2'.")
    kind: ParagraphKind
    outcome_type: OutcomeType | None = Field(description="Set when the paragraph records one.")
    text: str
    based_on: list[str] = Field(description="Selection ids this paragraph expresses.")


class MinuteItem(BaseModel):
    item_ref: str
    heading: str
    paragraphs: list[MinuteParagraph]


class MeetingHeader(BaseModel):
    title: str
    meeting_date: str | None
    time_and_place: str | None
    present: list[str]
    in_attendance: list[str]
    apologies: list[str]


class ActionEntry(BaseModel):
    action_id: str
    text: str
    owner: str | None
    due: str | None
    paragraph_id: str


class AnchorKind(StrEnum):
    PARAGRAPH = "paragraph"
    ITEM_HEADING = "item_heading"
    MEETING_HEADING = "meeting_heading"


class ClarificationQuestion(BaseModel):
    question_id: str = Field(description="Q1, Q2 ...")
    requirement_ids: list[str]
    anchor_kind: AnchorKind
    item_ref: str | None
    paragraph_id: str | None
    anchor_text: str | None = Field(
        description="Exact substring of the paragraph the question is about."
    )
    question: str


class DraftMinutes(BaseModel):
    header: MeetingHeader
    items: list[MinuteItem]
    actions: list[ActionEntry]
    questions: list[ClarificationQuestion]
    drafting_notes: list[str] = Field(description="Notes for the reviewer; never exported.")


# Stage 4: validate once, then reconsider once


class FindingCategory(StrEnum):
    FACTUAL_ACCURACY = "factual_accuracy"
    COMPLETENESS = "completeness"
    MINUTING_POLICY = "minuting_policy"
    WRITING_STYLE = "writing_style"
    CONSISTENCY = "consistency"
    QUESTION_QUALITY = "question_quality"


class ResponsibleStage(StrEnum):
    EVIDENCE = "evidence"
    POLICY = "policy"
    STYLE = "style"


class Significance(StrEnum):
    MATERIAL = "material"
    MINOR = "minor"


class Finding(BaseModel):
    finding_id: str = Field(description="F1, F2 ...")
    category: FindingCategory
    responsible_stage: ResponsibleStage
    significance: Significance
    item_ref: str | None
    paragraph_id: str | None
    question_id: str | None
    issue: str
    suggested_change: str | None
    refs: list[LineRef]


class ValidationReport(BaseModel):
    findings: list[Finding]
    summary: str


class Disposition(StrEnum):
    ACCEPT = "accept"
    ACCEPT_IN_PART = "accept_in_part"
    RETAIN = "retain"


class FindingDecision(BaseModel):
    finding_id: str
    decision: Disposition
    reason: str


class Reconsideration(BaseModel):
    decisions: list[FindingDecision]
    revised_minutes: DraftMinutes

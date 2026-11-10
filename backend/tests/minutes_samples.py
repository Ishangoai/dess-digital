"""Stage outputs for the invented Northbridge meeting in fixtures/minutes."""

from app.minutes.llm_schemas import (
    AgendaItem,
    AnchorKind,
    Association,
    ClarificationQuestion,
    ClarificationRequirement,
    Disposition,
    DraftMinutes,
    EvidenceAnalysis,
    EvidenceSegment,
    Finding,
    FindingCategory,
    FindingDecision,
    InputProblem,
    InputProblemKind,
    ItemSelection,
    LineRef,
    MeetingHeader,
    MinuteItem,
    MinuteParagraph,
    OutcomeType,
    ParagraphKind,
    Particulars,
    PolicySelection,
    PurposeKind,
    Reconsideration,
    ResponsibleStage,
    SelectedOutcome,
    Significance,
    SourceAssessment,
    Treatment,
    ValidationReport,
)


def ref(start: int, end: int, source: str = "T") -> LineRef:
    return LineRef(source_id=source, start=start, end=end)


def particulars() -> Particulars:
    return Particulars(
        organisation="Northbridge Housing Trust",
        body="Board of Trustees",
        meeting_date="12 March 2026",
        start_time="10:00",
        venue_or_mode="Head Office",
        chair="Ruth Okafor",
        secretary=None,
        present=[],
        in_attendance=["Amaka Bello", "Sam Hale"],
        apologies=["Daniel"],
        refs=[ref(1, 2, "A"), ref(1, 1)],
    )


def agenda_items() -> list[AgendaItem]:
    def item(r: str, heading: str, kind: PurposeKind) -> AgendaItem:
        return AgendaItem(
            ref=r, heading=heading, stated_purpose=None, purpose_kind=kind, linked_papers=[]
        )

    return [
        item("1", "Apologies and declarations of interest", PurposeKind.PROCEDURAL),
        item("2", "Minutes of the previous meeting", PurposeKind.APPROVAL),
        item("3", "Chief Executive's report", PurposeKind.NOTING),
        item("4", "Roof replacement programme: contract award", PurposeKind.APPROVAL),
        item("5", "Any other business", PurposeKind.UNSPECIFIED),
    ]


def segment(sid: str, start: int, end: int, item: str | None, summary: str) -> EvidenceSegment:
    return EvidenceSegment(
        segment_id=sid,
        source=ref(start, end),
        item_ref=item,
        association=Association.PRIMARY if item else Association.UNCERTAIN,
        summary=summary,
        apparent_outcome=None,
    )


def analysis(problems: bool = False) -> EvidenceAnalysis:
    return EvidenceAnalysis(
        agenda_items=agenda_items(),
        additional_business=[],
        segments=[
            segment("S1", 1, 2, "1", "Apologies and Tom Reid's declared interest."),
            segment("S2", 3, 3, "2", "Previous minutes agreed."),
            segment("S3", 4, 4, "3", "Chief Executive's update."),
            segment("S4", 6, 13, "4", "Roof contract discussion and approval of phase one."),
            segment("S5", 14, 14, "5", "No other business."),
        ],
        sources=[SourceAssessment(source_id="T", description="Transcript", limitations=[])],
        essential_input_problems=(
            [InputProblem(kind=InputProblemKind.PROCEEDINGS_UNUSABLE, description="Empty.")]
            if problems
            else []
        ),
        particulars=particulars(),
        cross_item_links=[],
        uncertainties=[],
    )


def selection() -> PolicySelection:
    def brief(r: str, heading: str) -> ItemSelection:
        return ItemSelection(
            item_ref=r,
            heading=heading,
            treatment=Treatment.BRIEF,
            outcomes=[],
            points=[],
            actions=[],
            delegations=[],
            drafting_boundary=[],
            omitted_summary=None,
        )

    minutes = brief("2", "Minutes of the previous meeting")
    minutes.outcomes = [
        SelectedOutcome(
            outcome_id="O0",
            outcome_type=OutcomeType.APPROVED,
            deciding_body="Board",
            proposition="Minutes of the previous meeting",
            limits=[],
            conditions=[],
            vote_detail=None,
            refs=[ref(3, 3)],
        )
    ]
    roof = brief("4", "Roof replacement programme: contract award")
    roof.treatment = Treatment.FULL
    roof.outcomes = [
        SelectedOutcome(
            outcome_id="O1",
            outcome_type=OutcomeType.APPROVED,
            deciding_body="Board",
            proposition="Award of the phase one roof contract to Kestrel Roofing",
            limits=["Phase one only", "Capped at £1.2 million"],
            conditions=[],
            vote_detail=None,
            refs=[ref(11, 12)],
        )
    ]
    return PolicySelection(
        particulars=particulars(),
        items=[
            brief("1", "Apologies and declarations of interest"),
            minutes,
            brief("3", "Chief Executive's report"),
            roof,
            brief("5", "Any other business"),
        ],
        clarifications=[
            ClarificationRequirement(
                requirement_id="R1",
                item_ref="4",
                concerns="O1",
                known="Tenants are to be written to about the works.",
                unresolved="No owner was agreed for the tenant letter.",
                why_it_matters="An action needs an owner.",
                refs=[ref(13, 13)],
            )
        ],
    )


def paragraph(pid: str, text: str, outcome: OutcomeType | None = None) -> MinuteParagraph:
    return MinuteParagraph(
        paragraph_id=pid,
        kind=ParagraphKind.OUTCOME if outcome else ParagraphKind.NARRATIVE,
        outcome_type=outcome,
        text=text,
        based_on=[],
    )


def draft(
    roof_text: str = "The Board approved phase one only, capped at £1.2 million.",
) -> DraftMinutes:
    items = [
        MinuteItem(item_ref="1", heading="Apologies and declarations of interest", paragraphs=[
            paragraph("1.p1", "Apologies were received from Daniel."),
            paragraph("1.p2", "Tom Reid declared an interest in item 4 and left for that item."),
        ]),
        MinuteItem(item_ref="2", heading="Minutes of the previous meeting", paragraphs=[
            paragraph("2.p1", "The minutes of the previous meeting were approved.",
                      OutcomeType.APPROVED),
        ]),
        MinuteItem(item_ref="3", heading="Chief Executive's report", paragraphs=[
            paragraph("3.p1", "The Board noted the report.", OutcomeType.NOTED),
        ]),
        MinuteItem(item_ref="4", heading="Roof replacement programme: contract award", paragraphs=[
            paragraph("4.p1", "Priya Shah remained concerned that the 5% contingency was thin."),
            paragraph("4.p2", roof_text, OutcomeType.APPROVED),
        ]),
        MinuteItem(item_ref="5", heading="Any other business", paragraphs=[
            paragraph("5.p1", "There was no other business."),
        ]),
    ]  # fmt: skip
    return DraftMinutes(
        header=MeetingHeader(
            title="Minutes of a meeting of the Board of Trustees of Northbridge Housing Trust",
            meeting_date="12 March 2026",
            time_and_place="10:00, Head Office",
            present=["Ruth Okafor (Chair)"],
            in_attendance=["Amaka Bello", "Sam Hale"],
            apologies=["Daniel"],
        ),
        items=items,
        actions=[],
        questions=[
            ClarificationQuestion(
                question_id="Q1",
                requirement_ids=["R1"],
                anchor_kind=AnchorKind.PARAGRAPH,
                item_ref="4",
                paragraph_id="4.p2",
                anchor_text="phase one only",
                question="Who was asked to write to tenants about the roof works?",
            )
        ],
        drafting_notes=[],
    )


def validation(findings: bool = True) -> ValidationReport:
    found = [
        Finding(
            finding_id="F1",
            category=FindingCategory.COMPLETENESS,
            responsible_stage=ResponsibleStage.STYLE,
            significance=Significance.MATERIAL,
            item_ref="4",
            paragraph_id="4.p2",
            question_id=None,
            issue="Authority to sign the contract is missing.",
            suggested_change="State that the Finance Director may sign.",
            refs=[ref(11, 11)],
        )
    ]
    return ValidationReport(findings=found if findings else [], summary="One gap.")


def reconsideration() -> Reconsideration:
    return Reconsideration(
        decisions=[FindingDecision(finding_id="F1", decision=Disposition.ACCEPT, reason="Agreed.")],
        revised_minutes=draft(
            "The Board approved phase one only, capped at £1.2 million, "
            "and authorised the Finance Director to sign the contract."
        ),
    )


def all_stage_outputs(findings: bool = True) -> dict:
    return {
        "EvidenceAnalysis": analysis(),
        "PolicySelection": selection(),
        "DraftMinutes": draft(),
        "ValidationReport": validation(findings),
        "Reconsideration": reconsideration(),
    }

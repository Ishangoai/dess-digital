"""Profile changes learned from an edited copy: proposing them and applying the accepted ones."""

import uuid
from typing import Any, cast

from sqlalchemy import Connection, CursorResult, Engine, update
from sqlalchemy.orm import Session

from app.llm import LLMClient, LLMError
from app.minutes import amendments
from app.minutes.amendments import AmendmentDraft, Operation
from app.minutes.edit_review import Route, ensure_change_ids
from app.minutes.evidence import MeetingInfo
from app.minutes.profile_content import DimensionCode, ProfileContent
from app.models.draft import (
    AmendmentProposal,
    AmendmentSet,
    ClassificationStatus,
    EditedDocument,
    ProposalStatus,
)
from app.models.profile import MinutesProfileVersion, VersionOrigin, utcnow
from app.services import edits as edits_svc
from app.services import profile as profile_svc

AMENDMENT_STAGE = "amendment"
Status = ClassificationStatus


class AmendmentStateError(Exception):
    """The proposals cannot be changed or applied in their current state."""


def learn_in_background(
    bind: Engine | Connection, document_id: uuid.UUID, llm: LLMClient, *, explain: bool = True
) -> None:
    """Explain the edits, then propose profile changes from them (FastAPI BackgroundTasks)."""
    with Session(bind) as db:
        document = db.get(EditedDocument, document_id)
        if document is None or document.comparison is None:
            return
        row = document.comparison
        if explain:
            try:
                edits_svc.classify(db, llm, document)
            except Exception as e:  # never leave it stuck as running
                db.rollback()
                row.classification_status = Status.FAILED
                row.classification_error = str(e)
                db.commit()
        found = document.amendments
        if found is None or found.status != Status.PENDING:
            return
        if row.classification_status != Status.COMPLETED:
            found.status, found.error = Status.FAILED, "the edits could not all be explained"
            db.commit()
            return
        try:
            propose(db, llm, document)
        except Exception as e:
            db.rollback()
            found.status, found.error = Status.FAILED, str(e)
            db.commit()


def request_proposals(db: Session, document: EditedDocument) -> bool:
    """Queue new proposals. False if they are being written or were already applied."""
    found = document.amendments
    if found is None:
        document.amendments = AmendmentSet(
            profile_version_id=document.run.profile_version_id, status=Status.PENDING
        )
        db.commit()
        return True
    result = cast(
        CursorResult[Any],
        db.execute(
            update(AmendmentSet)
            .where(
                AmendmentSet.id == found.id,
                AmendmentSet.status != Status.RUNNING,
                AmendmentSet.applied_version_id.is_(None),
            )
            .values(status=Status.PENDING, error=None)
        ),
    )
    db.commit()
    db.refresh(found)
    return result.rowcount == 1


def propose(db: Session, llm: LLMClient, document: EditedDocument) -> AmendmentSet | None:
    """One model call per candidate-rule pattern; code then refuses what may not change."""
    found = document.amendments
    assert found is not None
    claimed = cast(
        CursorResult[Any],
        db.execute(
            update(AmendmentSet)
            .where(AmendmentSet.id == found.id, AmendmentSet.status == Status.PENDING)
            .values(status=Status.RUNNING)
        ),
    )
    db.commit()
    db.refresh(found)
    if claimed.rowcount != 1:
        return None

    result = edits_svc.classification_of(document)
    if result is None:
        raise AmendmentStateError("the edits have not been explained")
    profile = profile_svc.version_content(found.profile_version)
    changes = {c.change_id: c for c in ensure_change_ids(edits_svc.comparison_of(document))}
    reasons = {c.change_id: c.reason for c in result.changes}
    patterns = [p for p in result.patterns if p.route == Route.CANDIDATE_RULE]
    system = amendments.system_prompt(profile)
    prompts = [amendments.message(p, changes, reasons, profile) for p in patterns]

    found.proposals.clear()
    errors: list[str] = []
    outcomes = edits_svc.call_each(llm, system, AmendmentDraft, prompts)
    for n, (pattern, prompt, outcome) in enumerate(zip(patterns, prompts, outcomes, strict=True)):
        run = document.run
        if isinstance(outcome, LLMError):
            edits_svc.record_failure(run, llm, AMENDMENT_STAGE, system, prompt, outcome)
            errors.append(f"{pattern.dimension}: {outcome}")
            continue
        edits_svc.record_call(run, AMENDMENT_STAGE, system, prompt, outcome)
        a = amendments.check(outcome.output, pattern, profile)
        found.proposals.append(
            AmendmentProposal(
                position=n,
                pattern_id=a.pattern_id,
                change_ids=a.change_ids,
                dimension=a.dimension.value,
                operation=a.operation,
                target_rule_id=a.target_rule_id,
                text=a.text,
                proposed_text=a.text,
                kind=a.kind,
                overlap=a.overlap,
                overlap_with=a.overlap_with,
                reason=a.reason,
                refused=a.refused,
            )
        )
    found.status = Status.FAILED if errors else Status.COMPLETED
    found.error = "; ".join(errors) or None
    found.completed_at = utcnow()
    db.commit()
    return found


def update_proposal(
    db: Session,
    proposal: AmendmentProposal,
    *,
    status: ProposalStatus | None = None,
    text: str | None = None,
    by: str | None = None,
) -> AmendmentProposal:
    if proposal.amendment_set.applied_version_id is not None:
        raise AmendmentStateError("these changes were already applied to the profile")
    if text is not None:
        if proposal.operation == Operation.REMOVE:
            raise ValueError("a removal has no wording")
        if not text.strip():
            raise ValueError("the wording cannot be empty")
        proposal.text = text.strip()
    if status is not None:
        if status == ProposalStatus.ACCEPTED and proposal.refused:
            raise AmendmentStateError(proposal.refused)
        proposal.status = status
    proposal.decided_by = by
    proposal.decided_at = utcnow()
    db.commit()
    return proposal


def apply(db: Session, document: EditedDocument, *, by: str | None = None) -> MinutesProfileVersion:
    """Create the next profile version with the accepted changes and make it active.

    The version the draft used is never modified; changes to hard floors or fixed rules are
    refused here and again by the profile service.
    """
    found = document.amendments
    if found is None or found.status != Status.COMPLETED:
        raise AmendmentStateError("there are no proposed changes to apply yet")
    if found.applied_version_id is not None:
        raise AmendmentStateError("these changes were already applied to the profile")
    accepted = [p for p in found.proposals if p.status == ProposalStatus.ACCEPTED]
    if not accepted:
        raise AmendmentStateError("accept at least one change first")
    base = found.profile_version
    latest = profile_svc.latest_version(base.profile)
    if latest is not None and latest.id != base.id:
        raise AmendmentStateError(
            f"the profile has a newer version (v{latest.version_number}) than the one this "
            f"draft used (v{base.version_number})"
        )

    content, summary = amendments.apply(
        profile_svc.version_content(base),
        [
            amendments.Accepted(
                dimension=DimensionCode(p.dimension),
                operation=p.operation,
                target_rule_id=p.target_rule_id,
                text=p.text,
                kind=p.kind,
                refused=p.refused,
            )
            for p in accepted
        ],
        _source_note(document),
    )
    version = profile_svc.create_version(
        db,
        base.profile,
        content,
        origin=VersionOrigin.FEEDBACK,
        change_summary=summary,
        created_by=by,
        parent_number=base.version_number,
    )
    profile_svc.confirm(db, version, by=by)
    for p in found.proposals:
        if p.status == ProposalStatus.PROPOSED:
            p.status = ProposalStatus.DEFERRED
    found.applied_version_id = version.id
    found.applied_at = utcnow()
    found.applied_by = by
    db.commit()
    return version


def current_rules(found: AmendmentSet) -> ProfileContent:
    return profile_svc.version_content(found.profile_version)


def _source_note(document: EditedDocument) -> str:
    info = MeetingInfo.model_validate(document.run.meeting_info or {})
    meeting = " ".join(x for x in (info.body_name, info.meeting_date) if x)
    return f"Learned from the edited minutes{f' of {meeting}' if meeting else ''}."

"""Amendment proposal and review service for minutes profile versioning."""

import uuid

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.client import LLMClient
from app.minutes.profile_content import (
    Dimension,
    ProfileContent,
    Provenance,
    Provision,
    ProvisionKind,
)
from app.models.amendment import (
    AmendmentOperation,
    AmendmentStatus,
    AmendmentTargetType,
    ProfileAmendmentProposal,
    ProfileAmendmentSet,
)
from app.models.profile import MinutesProfileVersion, VersionOrigin, utcnow
from app.services.profile import (
    confirm,
    create_version,
    version_content,
)

# ---------------------------------------------------------------------------
# LLM conflict-check schema
# ---------------------------------------------------------------------------


class ConflictCheckResult(BaseModel):
    has_conflict: bool
    conflict_type: str | None  # "contradiction" | "duplicate" | None
    warning: str | None  # human-readable explanation, null if no conflict


# ---------------------------------------------------------------------------
# Error classes
# ---------------------------------------------------------------------------


class AmendmentError(Exception):
    pass


class AmendmentSetNotFoundError(AmendmentError):
    pass


class ProposalNotFoundError(AmendmentError):
    pass


class FloorProtectionError(AmendmentError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AmendmentSetAlreadyAppliedError(AmendmentError):
    pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_dimension(content: ProfileContent, code: str) -> Dimension | None:
    """Return the Dimension matching *code* (a DimensionCode value string)."""
    for dim in content.dimensions():
        if dim.code == code:
            return dim
    return None


# ---------------------------------------------------------------------------
# Hard floor / evidential fundamental guard
# ---------------------------------------------------------------------------


def check_proposal_against_floors(
    proposal: ProfileAmendmentProposal,
    base_content: ProfileContent,
) -> None:
    """Raise FloorProtectionError if the proposal would alter a protected element."""
    dim = _find_dimension(base_content, proposal.target_dimension)
    if dim is None:
        # Unknown dimension — let higher-level validation catch it; not a floor issue.
        return

    if proposal.operation in (AmendmentOperation.REPLACE, AmendmentOperation.REMOVE):
        if proposal.target_provision:
            # Look up the provision by id.
            matching = next((p for p in dim.provisions if p.id == proposal.target_provision), None)
            if matching and matching.kind == ProvisionKind.EVIDENTIAL_FUNDAMENTAL:
                raise FloorProtectionError(
                    f"Provision '{proposal.target_provision}' is an evidential fundamental"
                    " and cannot be modified or removed."
                )

    if proposal.operation == AmendmentOperation.ADD:
        if proposal.kind == ProvisionKind.EVIDENTIAL_FUNDAMENTAL:
            raise FloorProtectionError(
                "New evidential fundamentals cannot be added via the amendment workflow."
            )


# ---------------------------------------------------------------------------
# Single LLM conflict check
# ---------------------------------------------------------------------------


def check_proposal_conflicts(
    proposal: ProfileAmendmentProposal,
    base_content: ProfileContent,
    llm: LLMClient,
) -> str | None:
    """Make ONE structured LLM call. Return a conflict warning string or None."""
    dim = _find_dimension(base_content, proposal.target_dimension)
    if dim is None:
        return None

    provision_lines = "\n".join(f"- [{p.kind}] id={p.id}: {p.text}" for p in dim.provisions)

    prompt = (
        "You are reviewing a proposed amendment to a minutes profile dimension.\n"
        "\n"
        f"Dimension: {proposal.target_dimension}\n"
        "Existing provisions:\n"
        f"{provision_lines}\n"
        "\n"
        "Proposed amendment:\n"
        f"  Operation: {proposal.operation}\n"
        f"  Target provision id: {proposal.target_provision or 'N/A (new)'}\n"
        f"  Proposed text: {proposal.proposed_text or 'N/A (remove)'}\n"
        "\n"
        "Does this proposal CONTRADICT or DUPLICATE any existing provision in this dimension?\n"
        "Reply with has_conflict: "
        'true/false, conflict_type ("contradiction" or "duplicate" or null),'
        " and a brief warning explaining the conflict (or null if none)."
    )

    result = llm.generate_structured(prompt, ConflictCheckResult)
    if result.output.has_conflict:
        return result.output.warning
    return None


# ---------------------------------------------------------------------------
# Create a proposal set
# ---------------------------------------------------------------------------


def create_amendment_set(
    db: Session,
    profile_version: MinutesProfileVersion,
    *,
    origin: VersionOrigin,
    title: str | None = None,
    created_by: str | None = None,
    proposals: list[dict],
    llm: LLMClient | None = None,
) -> ProfileAmendmentSet:
    """Create a ProfileAmendmentSet with its proposals, running floor and LLM checks."""
    if origin not in (VersionOrigin.CUSTOMISATION, VersionOrigin.FEEDBACK):
        raise AmendmentError(
            f"Amendment sets must use origin CUSTOMISATION or FEEDBACK, got '{origin}'."
        )

    base_content = version_content(profile_version)

    amendment_set = ProfileAmendmentSet(
        profile_version_id=profile_version.id,
        origin=origin,
        title=title,
        created_by=created_by,
    )
    db.add(amendment_set)
    # Flush to get the PK so proposals can reference it.
    db.flush()

    for raw in proposals:
        proposal = ProfileAmendmentProposal(
            amendment_set_id=amendment_set.id,
            target_dimension=raw.get("target_dimension"),
            target_provision=raw.get("target_provision"),
            target_type=raw.get("target_type"),
            operation=raw.get("operation"),
            proposed_text=raw.get("proposed_text"),
            kind=raw.get("kind"),
            provenance=raw.get("provenance"),
            scope=raw.get("scope"),
            reason=raw.get("reason"),
            evidence=raw.get("evidence"),
            status=AmendmentStatus.PROPOSED,
        )

        # Floor protection check — record and reject but do not raise.
        try:
            check_proposal_against_floors(proposal, base_content)
        except FloorProtectionError as e:
            proposal.conflict_warning = f"[FLOOR PROTECTION] {e.message}"
            proposal.status = AmendmentStatus.REJECTED
        else:
            # LLM conflict check — only if no floor protection warning already set.
            if llm is not None:
                warning = check_proposal_conflicts(proposal, base_content, llm)
                if warning:
                    proposal.conflict_warning = warning

        db.add(proposal)

    db.commit()
    db.refresh(amendment_set)
    return amendment_set


# ---------------------------------------------------------------------------
# Get / list amendment sets
# ---------------------------------------------------------------------------


def get_amendment_set(db: Session, set_id: uuid.UUID) -> ProfileAmendmentSet:
    """Return the amendment set with the given id, or raise AmendmentSetNotFoundError."""
    amendment_set = db.scalar(select(ProfileAmendmentSet).where(ProfileAmendmentSet.id == set_id))
    if amendment_set is None:
        raise AmendmentSetNotFoundError(f"Amendment set '{set_id}' not found.")
    return amendment_set


def list_amendment_sets(db: Session, profile_version_id: uuid.UUID) -> list[ProfileAmendmentSet]:
    """Return all amendment sets for a profile version, newest first."""
    return list(
        db.scalars(
            select(ProfileAmendmentSet)
            .where(ProfileAmendmentSet.profile_version_id == profile_version_id)
            .order_by(ProfileAmendmentSet.created_at.desc())
        )
    )


# ---------------------------------------------------------------------------
# Update a proposal (accept / reject / defer / reword)
# ---------------------------------------------------------------------------


def update_proposal(
    db: Session,
    proposal: ProfileAmendmentProposal,
    *,
    status: AmendmentStatus | None = None,
    proposed_text: str | None = None,
    decided_by: str | None = None,
) -> ProfileAmendmentProposal:
    """Update a proposal's text or status and persist the change."""
    if proposed_text is not None:
        proposal.proposed_text = proposed_text

    if status is not None:
        if (
            status == AmendmentStatus.ACCEPTED
            and proposal.conflict_warning
            and "[FLOOR PROTECTION]" in proposal.conflict_warning
        ):
            raise FloorProtectionError(
                f"Cannot accept proposal {proposal.id}: it violates floor protection."
            )
        proposal.status = status
        if status in (AmendmentStatus.ACCEPTED, AmendmentStatus.REJECTED, AmendmentStatus.DEFERRED):
            proposal.decided_at = utcnow()
            proposal.decided_by = decided_by

    db.commit()
    db.refresh(proposal)
    return proposal


# ---------------------------------------------------------------------------
# Apply accepted proposals → new profile version
# ---------------------------------------------------------------------------


def apply_amendment_set(
    db: Session,
    amendment_set: ProfileAmendmentSet,
    *,
    confirmed_by: str | None = None,
) -> MinutesProfileVersion:
    """Apply all ACCEPTED proposals to produce a new, confirmed profile version."""
    base_content = version_content(amendment_set.profile_version)

    accepted = [p for p in amendment_set.proposals if p.status == AmendmentStatus.ACCEPTED]
    if not accepted:
        raise AmendmentError("No accepted proposals to apply.")

    # Deep-copy content via round-trip through JSON.
    new_content = ProfileContent.model_validate(base_content.model_dump(mode="json"))

    for proposal in accepted:
        # Locate the target dimension in the mutable copy.
        dim = _find_dimension(new_content, proposal.target_dimension)
        if dim is None:
            # Skip proposals referencing unknown dimensions.
            continue

        if proposal.target_type == AmendmentTargetType.APPLICATION_NOTE:
            if proposal.operation in (AmendmentOperation.ADD, AmendmentOperation.REPLACE):
                if not proposal.proposed_text:
                    raise AmendmentError(
                        f"Proposal {proposal.id} requires 'proposed_text' for an application note."
                    )
                dim.application = proposal.proposed_text
            elif proposal.operation == AmendmentOperation.REMOVE:
                dim.application = None
        else:
            if proposal.operation == AmendmentOperation.ADD:
                if proposal.kind is None:
                    raise AmendmentError(f"Proposal {proposal.id} is missing a required 'kind'.")
                if not proposal.proposed_text:
                    raise AmendmentError(f"Proposal {proposal.id} is missing 'proposed_text'.")
                new_id = f"{proposal.target_dimension.lower()}-custom-{uuid.uuid4().hex[:8]}"
                new_provision = Provision(
                    id=new_id,
                    kind=proposal.kind,
                    text=proposal.proposed_text,
                    provenance=proposal.provenance or Provenance.INFERRED,
                    source_note=proposal.reason,
                )
                dim.provisions.append(new_provision)

            elif proposal.operation == AmendmentOperation.REPLACE:
                if not proposal.proposed_text:
                    raise AmendmentError(
                        f"Proposal {proposal.id} requires 'proposed_text' for a REPLACE operation."
                    )
                for prov in dim.provisions:
                    if prov.id == proposal.target_provision:
                        prov.text = proposal.proposed_text
                        break

            elif proposal.operation == AmendmentOperation.REMOVE:
                dim.provisions = [
                    prov for prov in dim.provisions if prov.id != proposal.target_provision
                ]

    # Build a human-readable change summary.
    summary_lines = []
    for p in accepted:
        body = p.proposed_text or f"removed {p.target_provision}"
        summary_lines.append(
            f"[{p.operation.upper()} {p.target_dimension}] {body} — {p.reason or ''}"
        )
    change_summary = "\n".join(summary_lines)

    # create_version runs check_floors automatically.
    new_version = create_version(
        db,
        amendment_set.profile_version.profile,
        new_content,
        origin=amendment_set.origin,
        change_summary=change_summary,
        created_by=confirmed_by or amendment_set.created_by,
    )

    # Auto-confirm the new version.
    confirm(db, new_version, by=confirmed_by)

    return new_version

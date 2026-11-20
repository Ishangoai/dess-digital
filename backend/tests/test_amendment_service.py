"""Tests for the amendment proposal and review service."""

import pytest
from sqlalchemy.orm import Session

from app.llm.client import LLMClient
from app.minutes.profile_content import ProfileContent, ProvisionKind, Provenance
from app.models.amendment import AmendmentOperation, AmendmentStatus, AmendmentTargetType
from app.models.profile import VersionOrigin
from app.services import amendment as amend_svc
from app.services import profile as svc
from app.services.amendment import ConflictCheckResult
from tests.fakes import ScriptedProvider


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded_profile(db: Session, profile_content: ProfileContent):
    """Seed and confirm a profile; return (profile, version, content)."""
    result = svc.seed_profile(db, profile_content, slug="std", confirm_version=True)
    return result.profile, result.version, profile_content


def make_llm(scripted_response: ConflictCheckResult | None = None) -> LLMClient:
    """Build an LLMClient backed by ScriptedProvider."""
    if scripted_response is None:
        # default: no conflict
        scripted_response = ConflictCheckResult(
            has_conflict=False, conflict_type=None, warning=None
        )
    provider = ScriptedProvider({"ConflictCheckResult": scripted_response})
    return LLMClient(provider, "test-model")


# ---------------------------------------------------------------------------
# Test 1: Apply flow — create, accept, compile
# ---------------------------------------------------------------------------


def test_apply_flow_creates_new_confirmed_version(
    db: Session, seeded_profile: tuple
) -> None:
    profile, version, content = seeded_profile
    llm = make_llm()

    aset = amend_svc.create_amendment_set(
        db,
        version,
        origin=VersionOrigin.FEEDBACK,
        title="Test amendments",
        created_by="tester",
        proposals=[
            {
                "target_dimension": "WS4",
                "target_provision": "ws4-names-for-actions",
                "target_type": "provision",
                "operation": "replace",
                "proposed_text": "Name action owners by full name.",
                "kind": "preference",
                "provenance": "professional_preference",
                "reason": "Client preference expressed in onboarding",
                "evidence": "Interview Q5 answer",
            }
        ],
        llm=llm,
    )
    assert len(aset.proposals) == 1
    proposal = aset.proposals[0]
    assert proposal.status == AmendmentStatus.PROPOSED
    assert proposal.conflict_warning is None  # no conflict

    # Accept the proposal
    amend_svc.update_proposal(db, proposal, status=AmendmentStatus.ACCEPTED, decided_by="fiifi")
    assert proposal.status == AmendmentStatus.ACCEPTED
    assert proposal.decided_by == "fiifi"
    assert proposal.decided_at is not None

    # Apply the set
    new_version = amend_svc.apply_amendment_set(db, aset, confirmed_by="fiifi")
    assert new_version.version_number == 2
    assert new_version.status.value == "confirmed"
    assert new_version.origin == VersionOrigin.FEEDBACK
    assert "WS4" in new_version.change_summary
    assert "Name action owners by full name." in new_version.change_summary
    assert "Client preference" in new_version.change_summary

    # Verify the content was actually changed
    new_content = svc.version_content(new_version)
    ws4 = next(d for d in new_content.writing_style if d.code == "WS4")
    p = next(p for p in ws4.provisions if p.id == "ws4-names-for-actions")
    assert p.text == "Name action owners by full name."


# ---------------------------------------------------------------------------
# Test 2: Rewording before accepting
# ---------------------------------------------------------------------------


def test_reword_then_accept(db: Session, seeded_profile: tuple) -> None:
    profile, version, content = seeded_profile
    llm = make_llm()

    aset = amend_svc.create_amendment_set(
        db,
        version,
        origin=VersionOrigin.CUSTOMISATION,
        proposals=[
            {
                "target_dimension": "WS4",
                "target_provision": "ws4-names-for-actions",
                "target_type": "provision",
                "operation": "replace",
                "proposed_text": "Original AI suggestion.",
                "kind": "preference",
            }
        ],
        llm=llm,
    )
    proposal = aset.proposals[0]

    # Reword it
    amend_svc.update_proposal(
        db, proposal, proposed_text="Governance professional's reword.", decided_by="paul"
    )
    assert proposal.proposed_text == "Governance professional's reword."

    # Accept it
    amend_svc.update_proposal(db, proposal, status=AmendmentStatus.ACCEPTED, decided_by="paul")
    new_version = amend_svc.apply_amendment_set(db, aset, confirmed_by="paul")

    new_content = svc.version_content(new_version)
    ws4 = next(d for d in new_content.writing_style if d.code == "WS4")
    p = next(p for p in ws4.provisions if p.id == "ws4-names-for-actions")
    assert p.text == "Governance professional's reword."


# ---------------------------------------------------------------------------
# Test 3: Reject flow
# ---------------------------------------------------------------------------


def test_reject_defer_excludes_from_new_version(db: Session, seeded_profile: tuple) -> None:
    profile, version, content = seeded_profile
    llm = make_llm()

    aset = amend_svc.create_amendment_set(
        db,
        version,
        origin=VersionOrigin.FEEDBACK,
        proposals=[
            {
                "target_dimension": "WS4",
                "target_provision": "ws4-names-for-actions",
                "target_type": "provision",
                "operation": "replace",
                "proposed_text": "Accepted change.",
                "kind": "preference",
            },
            {
                "target_dimension": "WS4",
                "target_provision": "ws4-names-for-actions",
                "target_type": "provision",
                "operation": "replace",
                "proposed_text": "Rejected change.",
                "kind": "preference",
            },
        ],
        llm=llm,
    )
    p0, p1 = aset.proposals[0], aset.proposals[1]

    # Accept first, reject second
    amend_svc.update_proposal(db, p0, status=AmendmentStatus.ACCEPTED, decided_by="fiifi")
    amend_svc.update_proposal(db, p1, status=AmendmentStatus.REJECTED, decided_by="fiifi")

    # Verify audit fields
    assert p1.decided_at is not None
    assert p1.decided_by == "fiifi"

    new_version = amend_svc.apply_amendment_set(db, aset, confirmed_by="fiifi")

    new_content = svc.version_content(new_version)
    ws4 = next(d for d in new_content.writing_style if d.code == "WS4")
    p = next(p for p in ws4.provisions if p.id == "ws4-names-for-actions")
    # Only the accepted change should be applied (last one wins since both target same provision)
    assert p.text == "Accepted change."
    assert "Rejected change." not in new_version.change_summary


# ---------------------------------------------------------------------------
# Test 4: Deferred proposals excluded
# ---------------------------------------------------------------------------


def test_deferred_proposals_excluded(db: Session, seeded_profile: tuple) -> None:
    profile, version, content = seeded_profile
    llm = make_llm()

    aset = amend_svc.create_amendment_set(
        db,
        version,
        origin=VersionOrigin.FEEDBACK,
        proposals=[
            {
                "target_dimension": "WS4",
                "target_provision": "ws4-names-for-actions",
                "target_type": "provision",
                "operation": "replace",
                "proposed_text": "Deferred change.",
                "kind": "preference",
            }
        ],
        llm=llm,
    )
    proposal = aset.proposals[0]
    amend_svc.update_proposal(db, proposal, status=AmendmentStatus.DEFERRED, decided_by="paul")

    with pytest.raises(amend_svc.AmendmentError, match="No accepted proposals"):
        amend_svc.apply_amendment_set(db, aset)


# ---------------------------------------------------------------------------
# Test 5: Conflict/duplicate detection stored
# ---------------------------------------------------------------------------


def test_conflict_warning_stored(db: Session, seeded_profile: tuple) -> None:
    profile, version, content = seeded_profile

    conflict_response = ConflictCheckResult(
        has_conflict=True,
        conflict_type="duplicate",
        warning="This provision duplicates ws4-names-for-actions which already says the same thing.",
    )
    llm = make_llm(scripted_response=conflict_response)

    aset = amend_svc.create_amendment_set(
        db,
        version,
        origin=VersionOrigin.FEEDBACK,
        proposals=[
            {
                "target_dimension": "WS4",
                "target_provision": None,
                "target_type": "provision",
                "operation": "add",
                "proposed_text": "Name action owners by role, not full name.",
                "kind": "preference",
            }
        ],
        llm=llm,
    )
    proposal = aset.proposals[0]
    assert proposal.conflict_warning is not None
    assert "duplicate" in proposal.conflict_warning.lower() or "ws4" in proposal.conflict_warning.lower()
    # Status should still be PROPOSED (conflict is a warning, not auto-rejection)
    assert proposal.status == AmendmentStatus.PROPOSED


# ---------------------------------------------------------------------------
# Test 6: Hard floor protection — evidential fundamental cannot be removed
# ---------------------------------------------------------------------------


def test_floor_protection_evidential_fundamental(db: Session, seeded_profile: tuple) -> None:
    profile, version, content = seeded_profile
    llm = make_llm()

    # Try to remove an evidential fundamental (mp4-no-silent-approval)
    aset = amend_svc.create_amendment_set(
        db,
        version,
        origin=VersionOrigin.FEEDBACK,
        proposals=[
            {
                "target_dimension": "MP4",
                "target_provision": "mp4-no-silent-approval",
                "target_type": "provision",
                "operation": "remove",
                "proposed_text": None,
                "kind": "evidential_fundamental",
            }
        ],
        llm=llm,
    )
    proposal = aset.proposals[0]
    # The floor protection guard auto-rejects it with a floor warning
    assert proposal.status == AmendmentStatus.REJECTED
    assert proposal.conflict_warning is not None
    warning_lower = proposal.conflict_warning.lower()
    assert "floor protection" in proposal.conflict_warning or "evidential fundamental" in warning_lower


# ---------------------------------------------------------------------------
# Test 7: Hard floor — cannot add new evidential fundamentals
# ---------------------------------------------------------------------------


def test_floor_protection_new_evidential_fundamental(db: Session, seeded_profile: tuple) -> None:
    profile, version, content = seeded_profile
    llm = make_llm()

    aset = amend_svc.create_amendment_set(
        db,
        version,
        origin=VersionOrigin.FEEDBACK,
        proposals=[
            {
                "target_dimension": "MP1",
                "target_provision": None,
                "target_type": "provision",
                "operation": "add",
                "proposed_text": "Some new fundamental rule.",
                "kind": "evidential_fundamental",
            }
        ],
        llm=llm,
    )
    proposal = aset.proposals[0]
    assert proposal.status == AmendmentStatus.REJECTED
    assert proposal.conflict_warning is not None


# ---------------------------------------------------------------------------
# Test 8: Apply refuses if no accepted proposals
# ---------------------------------------------------------------------------


def test_apply_with_no_accepted_raises(db: Session, seeded_profile: tuple) -> None:
    profile, version, content = seeded_profile
    llm = make_llm()

    aset = amend_svc.create_amendment_set(
        db,
        version,
        origin=VersionOrigin.FEEDBACK,
        proposals=[
            {
                "target_dimension": "WS4",
                "operation": "replace",
                "target_provision": "ws4-names-for-actions",
                "target_type": "provision",
                "proposed_text": "Some change.",
                "kind": "preference",
            }
        ],
        llm=llm,
    )
    # No proposal accepted — apply should fail
    with pytest.raises(amend_svc.AmendmentError):
        amend_svc.apply_amendment_set(db, aset)

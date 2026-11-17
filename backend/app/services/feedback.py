"""Reviewer feedback on drafts, and the score table per setup (profile version and model)."""

from dataclasses import dataclass

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.minutes.extract import UnsupportedFileError
from app.minutes.llm_schemas import DraftMinutes
from app.minutes.roundtrip import compare_final
from app.models.draft import DraftRun, DraftStatus
from app.models.feedback import REWARDS, DraftFeedback, Verdict
from app.models.profile import MinutesProfile, MinutesProfileVersion
from app.services import profile as profile_svc
from app.services.draft import InvalidInputError, InvalidStateError


def add_feedback(
    db: Session, run: DraftRun, verdict: Verdict, reason: str | None = None, by: str | None = None
) -> DraftFeedback:
    """Record one vote on a finished draft. A revision request needs a reason."""
    _require_finished(run)
    reason = (reason or "").strip() or None
    if verdict == Verdict.EDITED:
        raise InvalidInputError("upload the edited Word file instead")
    if verdict == Verdict.REVISION_REQUESTED and reason is None:
        raise InvalidInputError("say what needs revising")
    return _save(db, run, verdict, REWARDS[verdict], reason=reason, by=by)


def add_final(
    db: Session, run: DraftRun, filename: str, data: bytes, by: str | None = None
) -> DraftFeedback:
    """Compare the reviewer's edited copy with the draft; the reward is how much was kept."""
    _require_finished(run)
    if not filename.lower().endswith(".docx"):
        raise UnsupportedFileError(f"{filename}: upload the edited Word (.docx) file")
    assert run.draft is not None
    presentation = profile_svc.version_content(run.profile_version).presentation
    comparison = compare_final(
        data, DraftMinutes.model_validate(run.draft), str(run.id), presentation
    )
    return _save(
        db,
        run,
        Verdict.EDITED,
        comparison.similarity,
        filename=filename,
        comparison=comparison.model_dump(mode="json"),
        by=by,
    )


def votes_for(db: Session, run: DraftRun) -> list[DraftFeedback]:
    """All feedback on one draft, oldest first."""
    stmt = (
        select(DraftFeedback)
        .where(DraftFeedback.run_id == run.id)
        .order_by(DraftFeedback.created_at)
    )
    return list(db.scalars(stmt))


@dataclass(frozen=True)
class Score:
    """Feedback for one setup: a profile version and a model."""

    profile_slug: str
    profile_version: int
    model: str
    approvals: int
    revisions: int
    edits: int
    reward_total: float
    similarity_total: float  # summed over uploaded edits

    @property
    def votes(self) -> int:
        return self.approvals + self.revisions + self.edits

    @property
    def net(self) -> int:
        """The score counter: +1 per approval, -1 per revision request."""
        return self.approvals - self.revisions

    @property
    def approval_rate(self) -> float:
        decided = self.approvals + self.revisions
        return self.approvals / decided if decided else 0.0

    @property
    def mean_similarity(self) -> float | None:
        """How much of the draft reviewers kept, on average, when they edited it."""
        return self.similarity_total / self.edits if self.edits else None

    @property
    def expected(self) -> float:
        """Average reward pulled towards 50%, so a setup with little feedback isn't over-trusted."""
        return (self.reward_total + 1) / (self.votes + 2)


def scores(db: Session) -> list[Score]:
    """One row per setup that has feedback, best expected reward first."""

    def count(verdict: Verdict):  # noqa: ANN202
        return func.sum(case((DraftFeedback.verdict == verdict, 1), else_=0))

    edited_reward = case((DraftFeedback.verdict == Verdict.EDITED, DraftFeedback.reward), else_=0)
    setup = (MinutesProfile.slug, MinutesProfileVersion.version_number, DraftFeedback.model)
    stmt = (
        select(
            *setup,
            count(Verdict.APPROVED),
            count(Verdict.REVISION_REQUESTED),
            count(Verdict.EDITED),
            func.sum(DraftFeedback.reward),
            func.sum(edited_reward),
        )
        .join(MinutesProfileVersion, DraftFeedback.profile_version_id == MinutesProfileVersion.id)
        .join(MinutesProfile, MinutesProfileVersion.profile_id == MinutesProfile.id)
        .group_by(*setup)
    )
    rows = [
        Score(slug, version, model, int(a), int(r), int(e), float(total), float(similar))
        for slug, version, model, a, r, e, total, similar in db.execute(stmt)
    ]
    return sorted(rows, key=lambda s: (s.expected, s.votes), reverse=True)


def _require_finished(run: DraftRun) -> None:
    if run.status != DraftStatus.COMPLETED or run.draft is None:
        raise InvalidStateError(f"only finished drafts can be reviewed (status {run.status})")


def _save(
    db: Session, run: DraftRun, verdict: Verdict, reward: float, **fields: object
) -> DraftFeedback:
    feedback = DraftFeedback(
        run_id=run.id,
        verdict=verdict,
        reward=reward,
        reason=fields.get("reason"),
        filename=fields.get("filename"),
        comparison=fields.get("comparison"),
        profile_version_id=run.profile_version_id,
        model=_model(run),
        created_by=fields.get("by"),
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback


def _model(run: DraftRun) -> str:
    """The model that wrote the draft: the last successful LLM call."""
    return next((c.model for c in reversed(run.llm_calls) if c.ok), "unknown")

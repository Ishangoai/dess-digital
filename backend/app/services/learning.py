"""House examples: final minute texts an organisation's reviewers sent back, shown to the drafting
calls for similar items. Turning edits into profile changes goes through edit classification
(services/edits.py) and amendment proposals, never straight into the profile."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.draft import DraftRun
from app.models.feedback import DraftFeedback, Verdict
from app.models.profile import MinutesProfile, MinutesProfileVersion


def house_examples(
    db: Session,
    profile: MinutesProfile,
    per_kind: int = 2,
    max_chars: int = 2500,
    exclude_run: Any = None,
) -> dict[str, list[str]]:
    """Final item texts reviewers sent back for this organisation, newest first, by purpose."""
    if profile.based_on_profile_id is None:  # the shared standard learns from no one client
        return {}
    examples: dict[str, list[str]] = {}
    stmt = (
        select(DraftFeedback)
        .join(DraftRun, DraftFeedback.run_id == DraftRun.id)
        .join(MinutesProfileVersion, DraftRun.profile_version_id == MinutesProfileVersion.id)
        .where(MinutesProfileVersion.profile_id == profile.id)
        .where(DraftFeedback.verdict == Verdict.EDITED)
        .order_by(DraftFeedback.created_at.desc())
        .limit(20)
    )
    for fb in db.scalars(stmt):
        if fb.run_id == exclude_run:  # replaying a run must not see its own final
            continue
        agenda = (fb.run.mapping or {}).get("agenda_items", [])
        kinds = {i["ref"]: i["purpose_kind"] for i in agenda}
        for item in (fb.comparison or {}).get("items", []):
            kind, text = kinds.get(item["item_ref"]), item["final_text"]
            if kind and text and len(examples.setdefault(kind, [])) < per_kind:
                examples[kind].append(f"{item['heading']}\n{text[:max_chars]}")
    return examples

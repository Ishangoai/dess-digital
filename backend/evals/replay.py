"""Replay past drafts of one organisation with a candidate profile version, before confirming it.

Each past run that a reviewer sent back an edited copy of is re-drafted from its stored evidence
and confirmed mapping, once with the candidate version and once with the baseline (the active
version). Both drafts are compared with the reviewer's final text: the candidate should come
closer. Costs real LLM calls.

Usage:
    uv run python -m evals.replay --profile northbridge --version 2 --limit 3 \
        --out ../reference/replay
    # optional: --judge-model gemini-3.6-flash also asks the judge which draft is better
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.llm import build_llm_client, get_llm_client
from app.minutes.evidence import MeetingInfo
from app.minutes.llm_schemas import DraftMinutes, EvidenceAnalysis, EvidenceMap
from app.minutes.pipeline import Pipeline
from app.minutes.profile_content import ProfileContent
from app.minutes.prompts import PromptContext
from app.minutes.roundtrip import similarity, words
from app.models.draft import DraftRun
from app.models.feedback import DraftFeedback, Verdict
from app.models.profile import MinutesProfile, MinutesProfileVersion
from app.services import learning
from app.services import profile as profile_svc
from app.services.draft import bundle_for
from evals.judge import Judge, Minutes, Winner, minutes_markdown


def closeness(draft: DraftMinutes, final_items: list[dict]) -> float:
    """Word-weighted similarity of each drafted item to the reviewer's final text."""
    drafted = {i.item_ref: "\n".join(p.text for p in i.paragraphs) for i in draft.items}
    total = weight = 0.0
    for item in final_items:
        if item["item_ref"] == "header":
            continue
        text = drafted.get(item["item_ref"], "")
        w = max(len(words(text)), len(words(item["final_text"])), 1)
        total += similarity(text, item["final_text"]) * w
        weight += w
    return total / weight if weight else 1.0


def finals(db: Session, profile: MinutesProfile, limit: int) -> list[DraftFeedback]:
    """The latest edited copy of each of the organisation's most recent reviewed runs."""
    stmt = (
        select(DraftFeedback)
        .join(DraftRun, DraftFeedback.run_id == DraftRun.id)
        .join(MinutesProfileVersion, DraftRun.profile_version_id == MinutesProfileVersion.id)
        .where(MinutesProfileVersion.profile_id == profile.id)
        .where(DraftFeedback.verdict == Verdict.EDITED)
        .order_by(DraftFeedback.created_at.desc())
    )
    latest: dict[object, DraftFeedback] = {}
    for fb in db.scalars(stmt):
        latest.setdefault(fb.run_id, fb)
    return list(latest.values())[:limit]


def redraft(db: Session, run: DraftRun, content: ProfileContent) -> DraftMinutes:
    ctx = PromptContext(
        profile=content,
        bundle=bundle_for(run),
        meeting_info=MeetingInfo.model_validate(run.meeting_info or {}),
        examples=learning.house_examples(db, run.profile_version.profile, exclude_run=run.id),
    )
    pipeline = Pipeline(get_llm_client(), ctx, settings.minutes_max_output_tokens,
                        workers=settings.minutes_parallel_calls)  # fmt: skip
    analysis = EvidenceAnalysis.model_validate(run.analysis)
    return pipeline.run_drafting(EvidenceMap.model_validate(run.mapping), analysis).draft


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay past drafts with a candidate version")
    parser.add_argument("--profile", required=True, help="organisation profile slug")
    parser.add_argument("--version", type=int, required=True, help="candidate version number")
    parser.add_argument("--baseline", type=int, help="version to compare with (default: active)")
    parser.add_argument("--limit", type=int, default=3, help="past runs to replay")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--judge-model", help="also ask this model which draft is better")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    with SessionLocal() as db:
        profile = profile_svc.get_profile(db, args.profile)
        candidate = profile_svc.get_version(profile, args.version)
        base = (
            profile_svc.get_version(profile, args.baseline)
            if args.baseline
            else profile_svc.active_version(profile)
        )
        if base is None:
            parser.error(f"profile '{args.profile}' has no active version to compare with")
        runs = finals(db, profile, args.limit)
        if not runs:
            parser.error("no edited finals to replay: upload reviewers' Word copies first")

        rows: list[dict[str, Any]] = []
        for fb in runs:
            run = fb.run
            final_items = (fb.comparison or {}).get("items", [])
            print(f"replaying {run.id} ...", flush=True)
            drafts = {
                "baseline": redraft(db, run, profile_svc.version_content(base)),
                "candidate": redraft(db, run, profile_svc.version_content(candidate)),
            }
            row: dict[str, Any] = {
                "run_id": str(run.id),
                **{k: round(closeness(d, final_items), 4) for k, d in drafts.items()},
            }
            if args.judge_model:
                cfg = settings.model_copy(update={"llm_model": args.judge_model})
                judge = Judge(build_llm_client(cfg), profile_svc.version_content(base).logic,
                              bundle_for(run), 32768)  # fmt: skip
                shown = {k: Minutes(k, minutes_markdown(d)) for k, d in drafts.items()}
                win = judge.compare(shown["candidate"], shown["baseline"])
                row["judge"] = {Winner.FIRST: "candidate", Winner.SECOND: "baseline"}.get(
                    win, "tie"
                )
            folder = args.out / str(run.id)
            folder.mkdir(parents=True, exist_ok=True)
            for name, d in drafts.items():
                (folder / f"{name}.json").write_text(d.model_dump_json(indent=2), encoding="utf-8")
            rows.append(row)

    lines = [
        f"Candidate v{candidate.version_number} vs baseline v{base.version_number}: "
        "closeness to the reviewer's final text (1.0 = identical)",
        "",
        "| run | baseline | candidate | judge |",
        "|---|---|---|---|",
    ]
    lines += [f"| {r['run_id'][:8]} | {r['baseline']:.3f} | {r['candidate']:.3f} | "
              f"{r.get('judge', '-')} |" for r in rows]  # fmt: skip
    mean = {k: sum(r[k] for r in rows) / len(rows) for k in ("baseline", "candidate")}
    lines.append(f"| mean | {mean['baseline']:.3f} | {mean['candidate']:.3f} | |")
    text = "\n".join(lines)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.md").write_text(text, encoding="utf-8")
    (args.out / "results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

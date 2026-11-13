"""Run eval cases through the real pipeline and check the judgement it applies.

Usage:
    uv run python -m evals.minutes_eval evals/cases/*.yaml \
        --profile ../reference/profiles/dess_standard.yaml --out ../reference/evals/out
"""

import argparse
import json
import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from app.llm import get_llm_client
from app.minutes.docx_export import render_minutes_docx
from app.minutes.evidence import EvidenceBundle, MeetingInfo, SourceRole, SourceText
from app.minutes.extract import extract_text
from app.minutes.pipeline import Pipeline, StageError
from app.minutes.profile_content import ProfileContent, load_profile_file
from app.minutes.prompts import PromptContext
from evals.checks import Assertion, check


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None
    agenda: Path
    transcript: Path | None = None
    notes: Path | None = None
    meeting_info: MeetingInfo = MeetingInfo()
    assertions: list[Assertion]


def load_case(path: Path) -> Case:
    case = Case.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    base = path.parent  # file paths in a case are relative to the case file
    case.agenda = base / case.agenda
    case.transcript = base / case.transcript if case.transcript else None
    case.notes = base / case.notes if case.notes else None
    return case


def bundle_for(case: Case) -> EvidenceBundle:
    files = [(SourceRole.AGENDA, case.agenda, "A")]
    files += [(SourceRole.TRANSCRIPT, case.transcript, "T")] if case.transcript else []
    files += [(SourceRole.NOTES, case.notes, "N")] if case.notes else []
    return EvidenceBundle(
        [
            SourceText(sid, role, p.name, extract_text(p.name, p.read_bytes()))
            for role, p, sid in files
        ]
    )


def run_case(case: Case, profile: ProfileContent, out: Path, attempt: int) -> list[dict]:
    ctx = PromptContext(profile, bundle_for(case), case.meeting_info)
    pipeline = Pipeline(get_llm_client(), ctx, max_tokens=65536)
    try:
        analysis = pipeline.analyse_evidence().output
        result = pipeline.run_drafting(analysis.evidence_map(), analysis)
    except StageError as e:
        return [{"case": case.name, "attempt": attempt, "check": "pipeline", "ok": False,
                 "detail": str(e)}]  # fmt: skip

    folder = out / case.name / f"attempt-{attempt}"
    folder.mkdir(parents=True, exist_ok=True)
    for name, model in (("analysis", analysis), ("selection", result.selection),
                        ("validation", result.validation), ("draft", result.draft)):  # fmt: skip
        (folder / f"{name}.json").write_text(model.model_dump_json(indent=2), encoding="utf-8")
    (folder / "minutes.docx").write_bytes(render_minutes_docx(result.draft, profile.presentation))

    rows = []
    for a in case.assertions:
        ok, detail = check(a, analysis, result.draft)
        label = f"{a.type} {a.item or ''} {a.outcome or a.pattern or ''}".strip()
        rows.append({"case": case.name, "attempt": attempt, "check": label, "ok": ok,
                     "detail": detail, "note": a.note})  # fmt: skip
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate minuting judgement on test cases")
    parser.add_argument("cases", nargs="+", type=Path)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=1, help="runs per case (outputs vary)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    profile = load_profile_file(args.profile)
    rows: list[dict] = []
    for path in args.cases:
        case = load_case(path)
        for attempt in range(1, args.repeat + 1):
            print(f"running {case.name} ({attempt}/{args.repeat}) ...", flush=True)
            rows += run_case(case, profile, args.out, attempt)

    report = ["| case | run | check | result | detail |", "|---|---|---|---|---|"]
    for r in rows:
        mark = "PASS" if r["ok"] else "FAIL"
        report.append(f"| {r['case']} | {r['attempt']} | {r['check']} | {mark} | {r['detail']} |")
    passed = sum(r["ok"] for r in rows)
    report.append(f"\n{passed}/{len(rows)} checks passed")
    text = "\n".join(report)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.md").write_text(text, encoding="utf-8")
    (args.out / "results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(text)
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())

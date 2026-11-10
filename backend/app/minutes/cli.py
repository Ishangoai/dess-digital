"""Run the minuting pipeline on local files, without the API or database.

Usage:
    uv run python -m app.minutes.cli --profile ../reference/profiles/dess_standard.yaml \
        --agenda agenda.docx --transcript transcript.txt --out ../reference/out
"""

import argparse
import json
from pathlib import Path

from app.llm import get_llm_client
from app.minutes.evidence import EvidenceBundle, MeetingInfo, SourceRole, SourceText
from app.minutes.extract import extract_text
from app.minutes.pipeline import Pipeline, StageError, StageResult
from app.minutes.profile_content import load_profile_file
from app.minutes.prompts import PromptContext


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Draft minutes from local files")
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--agenda", type=Path, required=True)
    parser.add_argument("--transcript", type=Path)
    parser.add_argument("--notes", type=Path)
    parser.add_argument("--out", type=Path, required=True, help="folder for the JSON outputs")
    parser.add_argument("--max-tokens", type=int, default=65536)
    args = parser.parse_args(argv)
    if not args.transcript and not args.notes:
        parser.error("give --transcript and/or --notes")

    files = [(SourceRole.AGENDA, args.agenda, "A")]
    files += [(SourceRole.TRANSCRIPT, args.transcript, "T")] if args.transcript else []
    files += [(SourceRole.NOTES, args.notes, "N")] if args.notes else []
    bundle = EvidenceBundle(
        [
            SourceText(sid, role, p.name, extract_text(p.name, p.read_bytes()))
            for role, p, sid in files
        ]
    )
    ctx = PromptContext(load_profile_file(args.profile), bundle, MeetingInfo())
    pipeline = Pipeline(get_llm_client(), ctx, max_tokens=args.max_tokens)
    args.out.mkdir(parents=True, exist_ok=True)

    def save(result: StageResult) -> None:
        path = args.out / f"{result.stage}.json"
        path.write_text(result.output.model_dump_json(indent=2), encoding="utf-8")
        u = result.usage
        print(
            f"{result.stage:16} {u.input_tokens:>8} in {u.output_tokens:>7} out "
            f"{result.latency_ms / 1000:6.1f}s -> {path.name}"
        )

    try:
        analysis = pipeline.analyse_evidence()
        save(analysis)
        if analysis.output.essential_input_problems:
            print("blocked:", [p.description for p in analysis.output.essential_input_problems])
            return 2
        result = pipeline.run_drafting(
            analysis.output.evidence_map(), analysis.output, on_stage=save
        )
    except StageError as e:
        print(f"failed: {e}")
        if e.raw_text:
            (args.out / f"{e.stage}.raw.txt").write_text(e.raw_text, encoding="utf-8")
        return 1

    (args.out / "draft.json").write_text(result.draft.model_dump_json(indent=2), encoding="utf-8")
    (args.out / "lint.json").write_text(json.dumps([str(i) for i in result.lint]), encoding="utf-8")
    print(f"done: {len(result.draft.items)} items, {len(result.draft.questions)} questions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

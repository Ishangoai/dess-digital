"""Score sets of minutes of one meeting with the LLM judge and compare them to a reference.

Usage:
    uv run python -m evals.compare --agenda agenda.docx --transcript transcript.docx \
        --reference gold.docx --out ../reference/compare A/draft.json B/minutes.docx ...

Minutes can be .docx, .md/.txt, or a pipeline draft.json. The judge runs on LLM_PROVIDER /
LLM_MODEL unless --judge-provider / --judge-model are given; use a strong model.
"""

import argparse
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.config import settings
from app.llm import build_llm_client
from app.minutes.evidence import EvidenceBundle, SourceRole, SourceText
from app.minutes.extract import extract_text
from app.minutes.profile_content import DEFAULT_PROFILE_PATH, load_profile_file
from evals.judge import RUBRIC, Judge, Minutes, ScoreReport, Winner, averages, load_minutes


def evidence(agenda: Path, transcript: Path | None, notes: Path | None) -> EvidenceBundle:
    files = [(SourceRole.AGENDA, agenda, "A"), (SourceRole.TRANSCRIPT, transcript, "T"),
             (SourceRole.NOTES, notes, "N")]  # fmt: skip
    return EvidenceBundle(
        [
            SourceText(sid, role, p.name, extract_text(p.name, p.read_bytes()))
            for role, p, sid in files
            if p
        ]
    )


def report_markdown(
    rows: list[tuple[Minutes, ScoreReport]], wins: dict[str, Winner], reference: str | None
) -> str:
    head = ["minutes", "words", "items covered", *RUBRIC, "overall"]
    if reference:
        head.append(f"vs {reference}")
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for m, report in rows:
        avg = averages(report)
        covered = f"{sum(i.covered for i in report.items)}/{len(report.items)}"
        cells = [m.label, str(m.words), covered, *(f"{avg[k]:.1f}" for k in (*RUBRIC, "overall"))]
        if reference:
            win = wins.get(m.label)
            cells.append({Winner.FIRST: "wins", Winner.SECOND: "loses",
                          Winner.TIE: "tie"}.get(win, "-") if win else "-")  # fmt: skip
        lines.append("| " + " | ".join(cells) + " |")

    for m, report in rows:
        lines += ["", f"## {m.label}", "", report.summary]
        for i in report.items:
            gaps = [f"  - missing: {x}" for x in i.missing] + [f"  - error: {x}" for x in i.errors]
            scores = ", ".join(f"{k} {getattr(i, k)}" for k in RUBRIC)
            lines += [f"- **{i.item_ref} {i.heading}**: {scores}", *gaps]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Judge and compare minutes of one meeting")
    parser.add_argument("minutes", nargs="+", type=Path)
    parser.add_argument("--agenda", type=Path, required=True)
    parser.add_argument("--transcript", type=Path)
    parser.add_argument("--notes", type=Path)
    parser.add_argument("--reference", type=Path, help="gold minutes to compare each against")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--judge-provider", default=settings.llm_provider)
    parser.add_argument("--judge-model", default=settings.llm_model)
    parser.add_argument("--max-tokens", type=int, default=32768)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    cfg = settings.model_copy(
        update={"llm_provider": args.judge_provider, "llm_model": args.judge_model}
    )
    bundle = evidence(args.agenda, args.transcript, args.notes)
    judge = Judge(build_llm_client(cfg), load_profile_file(args.profile).logic, bundle,
                  args.max_tokens)  # fmt: skip
    candidates = [load_minutes(p) for p in args.minutes]
    reference = load_minutes(args.reference) if args.reference else None
    everything = candidates + ([reference] if reference else [])

    def against_reference(m: Minutes) -> Winner:
        assert reference is not None
        return judge.compare(m, reference)

    others = [m for m in candidates if reference and m.label != reference.label]
    with ThreadPoolExecutor(args.workers) as pool:
        scored = list(pool.map(judge.score, everything))
        verdicts = list(pool.map(against_reference, others))
    rows = list(zip(everything, scored, strict=True))
    wins = {m.label: w for m, w in zip(others, verdicts, strict=True)}

    args.out.mkdir(parents=True, exist_ok=True)
    text = report_markdown(rows, wins, reference.label if reference else None)
    (args.out / "report.md").write_text(text, encoding="utf-8")
    results = [{"label": m.label, "words": m.words, "averages": averages(r),
                "vs_reference": wins.get(m.label), "scores": r.model_dump()}
               for m, r in rows]  # fmt: skip
    (args.out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(text.split("\n\n## ")[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

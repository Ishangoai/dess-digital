"""Build the DESS Standard profile: both DESS documents, verbatim, as one markdown file.

Usage:
    uv run python -m app.minutes.build_logic STANDARDS.docx OPS_LOGIC.docx

Writes app/minutes/profiles/dess_standard.md, which every deploy seeds as the profile.
"""

import argparse
import re
from pathlib import Path

from app.minutes.extract import docx_to_markdown, extract_text
from app.minutes.profile_content import DEFAULT_PROFILE_PATH

HEADER = """# DESS Standard Minutes Profile

This document holds the complete standards and operating logic for drafting the minutes. \
Part A, the Professional Standards, sets what the minutes must achieve: nine Minuting Policy \
dimensions (MP1 to MP9: what to record and in what depth) and six Writing Style dimensions \
(WS1 to WS6: how to write and present it). Part B, the Operational AI Logic, sets how to apply \
those standards to the meeting evidence, stage by stage. Apply both in full."""

MIN_COVERAGE = 0.99


def words(text: str) -> int:
    return len(re.findall(r"\w+", text))


def convert(path: Path) -> tuple[str, float]:
    """Markdown for one .docx, and the share of the document's words it kept."""
    data = path.read_bytes()
    markdown = docx_to_markdown(data, heading_offset=1)
    coverage = words(markdown) / max(words(extract_text(path.name, data)), 1)
    return markdown, coverage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("standards", type=Path, help="Professional Standards .docx")
    parser.add_argument("logic", type=Path, help="Operational AI Logic .docx")
    parser.add_argument("--out", type=Path, default=DEFAULT_PROFILE_PATH, help="output .md")
    args = parser.parse_args(argv)

    parts = [HEADER]
    for title, path in (
        ("Part A: Professional Standards", args.standards),
        ("Part B: Operational AI Logic", args.logic),
    ):
        markdown, coverage = convert(path)
        print(f"{path.name}: {words(markdown):,} words, {coverage:.1%} of the document")
        if coverage < MIN_COVERAGE:
            print(f"failed: less than {MIN_COVERAGE:.0%} of {path.name} was converted")
            return 1
        parts.append(f"# {title}\n\n{markdown}")

    text = "\n\n".join(parts)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"wrote {args.out} ({words(text):,} words)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

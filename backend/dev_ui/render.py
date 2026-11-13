"""Markdown and table views of API responses (no Gradio imports, so it is testable)."""

from typing import Any

MAPPING_COLUMNS = ["segment_id", "source", "start", "end", "item_ref", "association", "summary"]


def run_status(run: dict[str, Any]) -> str:
    lines = [f"**Run** `{run['id']}`: **{run['status']}**"]
    lines.append(f"Profile: {run['profile_slug']} v{run['profile_version']}")
    if run.get("blocked_reasons"):
        lines.append("**Blocked:** " + "; ".join(run["blocked_reasons"]))
    if run.get("error"):
        lines.append(f"**Error** ({run.get('error_stage')}): {run['error']}")
    return "\n\n".join(lines)


def analysis_summary(run: dict[str, Any]) -> str:
    analysis = run.get("analysis")
    if not analysis:
        return ""
    lines = ["### Sources"]
    for s in analysis["sources"]:
        limits = f" (limitations: {'; '.join(s['limitations'])})" if s["limitations"] else ""
        lines.append(f"- **{s['source_id']}**: {s['description']}{limits}")
    if analysis["uncertainties"]:
        lines.append("### Uncertainties")
        for u in analysis["uncertainties"]:
            readings = " / ".join(u["competing_readings"])
            lines.append(f"- item {u['item_ref'] or '-'}: {u['description']} ({readings})")
    return "\n".join(lines)


def mapping_rows(review: dict[str, Any]) -> list[list[Any]]:
    return [
        [
            s["segment_id"],
            s["source"]["source_id"],
            s["source"]["start"],
            s["source"]["end"],
            s["item_ref"] or "",
            s["association"],
            s["summary"],
        ]
        for s in review["segments"]
    ]


def mapping_from_rows(original: dict[str, Any], rows: list[list[Any]]) -> dict[str, Any]:
    """Rebuild the EvidenceMap from the edited table, keeping the agenda as proposed."""
    previous = {s["segment_id"]: s for s in original["segments"]}
    segments = []
    for row in rows:
        values = dict(zip(MAPPING_COLUMNS, row, strict=False))
        if not str(values.get("segment_id") or "").strip():
            continue
        sid = str(values["segment_id"]).strip()
        segments.append(
            {
                "segment_id": sid,
                "source": {
                    "source_id": str(values["source"]).strip(),
                    "start": int(values["start"]),
                    "end": int(values["end"]),
                },
                "item_ref": str(values["item_ref"]).strip() or None,
                "association": str(values["association"]).strip(),
                "summary": str(values["summary"]),
                "apparent_outcome": previous.get(sid, {}).get("apparent_outcome"),
            }
        )
    return {
        "agenda_items": original["agenda_items"],
        "additional_business": original["additional_business"],
        "segments": segments,
    }


def uncovered_summary(review: dict[str, Any]) -> str:
    if not review["uncovered"]:
        return "Every transcript/notes line is mapped."
    lines = ["**Lines not mapped to any item** (check nothing material is missing):"]
    for ref, excerpt in zip(review["uncovered"], review["uncovered_excerpts"], strict=True):
        lines.append(f"- {ref['source_id']}{ref['start']}-{ref['end']}: {excerpt}")
    return "\n".join(lines)


def draft_markdown(draft: dict[str, Any] | None) -> str:
    if not draft:
        return "_No draft yet._"
    h = draft["header"]
    questions = draft["questions"]
    lines = [f"# {h['title']}"]
    for value in (h.get("meeting_date"), h.get("time_and_place")):
        if value:
            lines.append(value)
    for label, names in (
        ("Present", h["present"]),
        ("In attendance", h["in_attendance"]),
        ("Apologies", h["apologies"]),
    ):
        if names:
            lines.append(f"**{label}:** {', '.join(names)}")
    lines += _questions(q for q in questions if q["anchor_kind"] == "meeting_heading")

    for item in draft["items"]:
        lines.append(f"## {item['item_ref']} {item['heading']}")
        lines += _questions(
            q
            for q in questions
            if q["anchor_kind"] == "item_heading" and q["item_ref"] == item["item_ref"]
        )
        for p in item["paragraphs"]:
            text = p["text"]
            mine = [q for q in questions if q["paragraph_id"] == p["paragraph_id"]]
            for q in mine:
                if q.get("anchor_text") and q["anchor_text"] in text:
                    text = text.replace(q["anchor_text"], f"=={q['anchor_text']}==", 1)
            lines.append(text)
            lines += _questions(mine)
    if draft["actions"]:
        lines.append("## Actions")
        for a in draft["actions"]:
            lines.append(f"- {a['text']} ({a['owner'] or 'owner not agreed'}, {a['due'] or '-'})")
    return "\n\n".join(lines)


def _questions(questions) -> list[str]:
    return [f"> **{q['question_id']}** {q['question']}" for q in questions]


def review_notes(run: dict[str, Any]) -> str:
    """Validation findings, how they were handled, and automated check results."""
    lines = []
    validation = run.get("validation")
    if validation:
        lines += ["### Validation", validation["summary"]]
        decisions = {
            d["finding_id"]: d for d in (run.get("reconsideration") or {}).get("decisions", [])
        }
        for f in validation["findings"]:
            d = decisions.get(f["finding_id"])
            outcome = f" -> **{d['decision']}**: {d['reason']}" if d else ""
            lines.append(f"- [{f['significance']}, {f['category']}] {f['issue']}{outcome}")
    if run.get("lint"):
        lines += ["### Automated checks", *[f"- {issue}" for issue in run["lint"]]]
    notes = (run.get("draft") or {}).get("drafting_notes") or []
    if notes:
        lines += ["### Drafting notes", *[f"- {n}" for n in notes]]
    return "\n".join(lines) or "_Nothing to report._"


def usage_rows(run: dict[str, Any]) -> list[list[Any]]:
    rows = [
        [c["stage"], c["model"], c["input_tokens"], c["output_tokens"],
         round(c["latency_ms"] / 1000, 1), "ok" if c["ok"] else c["error"]]
        for c in run.get("llm_calls", [])
    ]  # fmt: skip
    total = run.get("usage_total")
    if total:
        rows.append(
            ["total", "", total["input_tokens"], total["output_tokens"],
             round(total["latency_ms"] / 1000, 1), ""]
        )  # fmt: skip
    return rows


def profile_markdown(version: dict[str, Any]) -> str:
    c = version["content"]
    lines = [
        f"# {c['name']} (v{version['version_number']}, {version['status']})",
        c.get("description") or "",
        "## Hard floors",
        *[f"- {f}" for f in c["hard_floors"]],
    ]
    for section, key in (
        ("Minuting Policy", "minuting_policy"),
        ("Writing Style", "writing_style"),
    ):
        lines.append(f"## {section}")
        for d in c[key]:
            lines += [f"### {d['code']} {d['title']}", d["default_standard"]]
    return "\n\n".join(lines)

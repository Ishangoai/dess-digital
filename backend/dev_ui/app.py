"""Gradio screens: upload -> review mapping -> generate -> download Word; profiles."""

import tempfile
from pathlib import Path
from typing import Any

import gradio as gr
import yaml

from dev_ui import render
from dev_ui.api import ApiError, MinutesApi

ASSOCIATIONS = ["primary", "related", "additional_business", "procedural", "uncertain"]


def build(api: MinutesApi) -> gr.Blocks:
    with gr.Blocks(title="DESS Minutes (dev)") as demo:
        gr.Markdown("# DESS Minutes: dev interface")
        run_state = gr.State({})  # latest run JSON
        mapping_state = gr.State({})  # mapping as proposed, for rebuilding edits

        with gr.Tab("Draft minutes"):
            with gr.Row():
                agenda = gr.File(label="Agenda (required)", type="filepath")
                transcript = gr.File(label="Transcript", type="filepath")
                notes = gr.File(label="Meeting notes", type="filepath")
            with gr.Row():
                organisation = gr.Textbox(label="Organisation")
                body_name = gr.Textbox(label="Board / committee")
                meeting_date = gr.Textbox(label="Meeting date")
                profile_slug = gr.Textbox(label="Profile", value="dess-standard")
            auto_confirm = gr.Checkbox(label="Skip mapping review (draft in one step)")
            analyse_btn = gr.Button("1. Analyse evidence", variant="primary")
            status = gr.Markdown()

            with gr.Accordion("2. Review the mapping of evidence to agenda items", open=True):
                analysis_md = gr.Markdown()
                mapping_table = gr.Dataframe(
                    headers=render.MAPPING_COLUMNS,
                    type="array",
                    interactive=True,
                    wrap=True,
                    label="Edit item_ref, line ranges or association, then generate",
                )
                uncovered_md = gr.Markdown()
                generate_btn = gr.Button("3. Confirm mapping and draft minutes", variant="primary")

            with gr.Row():
                with gr.Column(scale=3):
                    draft_md = gr.Markdown(label="Draft minutes")
                with gr.Column(scale=2):
                    notes_md = gr.Markdown()
                    usage = gr.Dataframe(
                        headers=["stage", "model", "in", "out", "seconds", "status"],
                        label="LLM calls",
                        interactive=False,
                    )
            with gr.Row():
                template = gr.File(
                    label="Word template (optional, {{MINUTES}} marker)", type="filepath"
                )
                export_btn = gr.Button("4. Download Word document")
                docx_file = gr.File(label="Word document")

        with gr.Tab("Runs"):
            refresh_runs = gr.Button("Refresh")
            runs_table = gr.Dataframe(
                headers=["id", "status", "organisation", "created"], interactive=False
            )
            run_id_box = gr.Textbox(label="Run id to open")
            open_btn = gr.Button("Open run in the Draft tab")

        with gr.Tab("Profiles"):
            load_profiles = gr.Button("Load profiles")
            profiles_json = gr.JSON(label="Profiles")
            slug_box = gr.Textbox(label="Profile slug", value="dess-standard")
            show_active = gr.Button("Show active version")
            profile_md = gr.Markdown()
            with gr.Accordion("Upload a new version", open=False):
                profile_file = gr.File(label="Profile YAML/JSON", type="filepath")
                change_summary = gr.Textbox(label="Change summary")
                upload_btn = gr.Button("Create proposed version")
                version_no = gr.Number(label="Version number", precision=0)
                with gr.Row():
                    review_btn = gr.Button("Mark reviewed")
                    confirm_btn = gr.Button("Confirm")
                    withdraw_btn = gr.Button("Withdraw")
                profile_msg = gr.Markdown()

        # handlers

        def show_run(run: dict[str, Any]) -> tuple:
            mapping: dict[str, Any] = {}
            rows: list[list[Any]] = []
            uncovered = ""
            if run.get("mapping"):
                review = api.get_mapping(run["id"])
                mapping, rows = review["mapping"], render.mapping_rows(review)
                uncovered = render.uncovered_summary(review)
            return (
                run,
                mapping,
                render.run_status(run),
                render.analysis_summary(run),
                rows,
                uncovered,
                render.draft_markdown(run.get("draft")),
                render.review_notes(run),
                render.usage_rows(run),
            )

        run_outputs = [
            run_state,
            mapping_state,
            status,
            analysis_md,
            mapping_table,
            uncovered_md,
            draft_md,
            notes_md,
            usage,
        ]

        def on_analyse(
            agenda, transcript, notes, organisation, body_name, meeting_date, slug, auto
        ):
            if not agenda:
                raise gr.Error("Upload an agenda first.")
            if not transcript and not notes:
                raise gr.Error("Upload a transcript or meeting notes.")
            form = {
                "organisation": organisation,
                "body_name": body_name,
                "meeting_date": meeting_date,
                "profile_slug": slug,
                "auto_confirm_mapping": str(bool(auto)).lower(),
            }
            try:
                run = api.create_draft(
                    Path(agenda),
                    Path(transcript) if transcript else None,
                    Path(notes) if notes else None,
                    {k: v for k, v in form.items() if v},
                )
                return show_run(api.get_draft(run["id"]))
            except ApiError as e:
                raise gr.Error(str(e)) from e

        analyse_btn.click(
            on_analyse,
            [agenda, transcript, notes, organisation, body_name, meeting_date, profile_slug,
             auto_confirm],
            run_outputs,
        )  # fmt: skip

        def on_generate(run, mapping, rows):
            if not run:
                raise gr.Error("Analyse the evidence first.")
            try:
                edited = render.mapping_from_rows(mapping, rows) if mapping else None
                api.generate(run["id"], edited)
                return show_run(api.get_draft(run["id"]))
            except (ApiError, ValueError) as e:
                raise gr.Error(str(e)) from e

        generate_btn.click(on_generate, [run_state, mapping_state, mapping_table], run_outputs)

        def on_export(run, template_path):
            if not run or not run.get("draft"):
                raise gr.Error("Generate a draft first.")
            try:
                content = api.document(run["id"], Path(template_path) if template_path else None)
            except ApiError as e:
                raise gr.Error(str(e)) from e
            out = Path(tempfile.mkdtemp()) / f"draft-minutes-{run['id'][:8]}.docx"
            out.write_bytes(content)
            return str(out)

        export_btn.click(on_export, [run_state, template], docx_file)

        def on_refresh():
            rows = [
                [r["id"], r["status"], r["meeting_info"].get("organisation") or "", r["created_at"]]
                for r in api.list_drafts()
            ]
            return rows

        refresh_runs.click(on_refresh, None, runs_table)

        def on_open(run_id):
            try:
                return show_run(api.get_draft(run_id.strip()))
            except ApiError as e:
                raise gr.Error(str(e)) from e

        open_btn.click(on_open, run_id_box, run_outputs)

        def on_load_profiles():
            return api.list_profiles()

        load_profiles.click(on_load_profiles, None, profiles_json)

        def on_show_active(slug):
            try:
                return render.profile_markdown(api.active_profile(slug))
            except ApiError as e:
                raise gr.Error(str(e)) from e

        show_active.click(on_show_active, slug_box, profile_md)

        def on_upload(slug, path, summary):
            if not path:
                raise gr.Error("Choose a profile file.")
            text = Path(path).read_text(encoding="utf-8")
            content = yaml.safe_load(text)  # JSON is valid YAML
            try:
                version = api.create_profile_version(slug, content, summary)
            except ApiError as e:
                raise gr.Error(str(e)) from e
            return version["version_number"], f"Created version {version['version_number']}."

        upload_btn.click(on_upload, [slug_box, profile_file, change_summary],
                         [version_no, profile_msg])  # fmt: skip

        def status_handler(new_status: str):
            def handler(slug, number):
                try:
                    v = api.set_status(slug, int(number), new_status)
                except (ApiError, TypeError, ValueError) as e:
                    raise gr.Error(str(e)) from e
                return f"Version {v['version_number']} is now {v['status']}."

            return handler

        review_btn.click(status_handler("reviewed"), [slug_box, version_no], profile_msg)
        confirm_btn.click(status_handler("confirmed"), [slug_box, version_no], profile_msg)
        withdraw_btn.click(status_handler("withdrawn"), [slug_box, version_no], profile_msg)

    return demo

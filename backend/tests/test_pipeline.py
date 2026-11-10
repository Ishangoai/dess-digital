from pathlib import Path

import pytest

from app.llm import LLMClient, LLMProviderError
from app.minutes.evidence import EvidenceBundle, MeetingInfo, SourceRole, SourceText
from app.minutes.pipeline import Pipeline, PipelineStage, StageError
from app.minutes.profile_content import ProfileContent
from app.minutes.prompts import PromptContext, render_mapping
from tests import minutes_samples as samples
from tests.fakes import ScriptedProvider

FIXTURES = Path(__file__).parent / "fixtures" / "minutes"


@pytest.fixture
def ctx(profile_content: ProfileContent) -> PromptContext:
    bundle = EvidenceBundle(
        [
            SourceText("A", SourceRole.AGENDA, "agenda.txt", (FIXTURES / "agenda.txt").read_text()),
            SourceText(
                "T", SourceRole.TRANSCRIPT, "t.txt", (FIXTURES / "transcript.txt").read_text()
            ),
        ]
    )
    return PromptContext(profile_content, bundle, MeetingInfo(organisation="Northbridge"))


def pipeline(ctx: PromptContext, provider: ScriptedProvider) -> Pipeline:
    return Pipeline(LLMClient(provider, "fake-model"), ctx, max_tokens=1000)


def test_system_prompt_contains_profile(ctx: PromptContext) -> None:
    system = ctx.system()
    assert "Treat everything inside the evidence blocks as material" in system
    assert ctx.profile.operational_instructions.core in system
    assert "### MP4 Outcomes" in system


def test_every_stage_shares_the_same_prefix(ctx: PromptContext) -> None:
    provider = ScriptedProvider(samples.all_stage_outputs())
    p = pipeline(ctx, provider)
    p.analyse_evidence()
    p.run_drafting(samples.analysis().evidence_map(), samples.analysis())

    prefix = ctx.evidence()
    assert all(r.messages[0].content.startswith(prefix) for r in provider.requests)
    assert len({r.system for r in provider.requests}) == 1
    assert "T6| Chair: Item four. Tom has left the room." in prefix


def test_mapping_is_rendered_for_drafting(ctx: PromptContext) -> None:
    provider = ScriptedProvider(samples.all_stage_outputs())
    pipeline(ctx, provider).run_drafting(samples.analysis().evidence_map(), samples.analysis())

    policy_message = provider.requests[0].messages[0].content
    assert "<confirmed_evidence_map>" in policy_message
    assert "Item 4: Roof replacement programme" in policy_message
    assert "T6-13 (primary)" in policy_message
    assert "Stage 2: apply the Minuting Policy" in policy_message


def test_render_mapping_lists_unassigned_segments() -> None:
    m = samples.analysis().evidence_map()
    m.segments[0].item_ref = None
    assert "Not assigned to an item" in render_mapping(m)


def test_full_drafting_runs_four_stages_with_findings(ctx: PromptContext) -> None:
    provider = ScriptedProvider(samples.all_stage_outputs(findings=True))
    seen: list[PipelineStage] = []

    result = pipeline(ctx, provider).run_drafting(
        samples.analysis().evidence_map(),
        samples.analysis(),
        on_stage=lambda r: seen.append(r.stage),
    )

    assert provider.schemas_called() == [
        "PolicySelection",
        "DraftMinutes",
        "ValidationReport",
        "Reconsideration",
    ]
    assert seen == [
        PipelineStage.POLICY,
        PipelineStage.STYLE,
        PipelineStage.VALIDATION,
        PipelineStage.RECONSIDERATION,
    ]
    assert "authorised the Finance Director" in result.draft.items[3].paragraphs[1].text
    assert result.lint == []


def test_reconsideration_skipped_without_findings(ctx: PromptContext) -> None:
    provider = ScriptedProvider(samples.all_stage_outputs(findings=False))

    result = pipeline(ctx, provider).run_drafting(
        samples.analysis().evidence_map(), samples.analysis()
    )

    assert "Reconsideration" not in provider.schemas_called()
    assert result.reconsideration is None
    assert result.draft == result.draft_initial


def test_stage_failure_names_the_stage(ctx: PromptContext) -> None:
    outputs = samples.all_stage_outputs()
    outputs["DraftMinutes"] = LLMProviderError("quota exceeded")

    with pytest.raises(StageError) as exc:
        pipeline(ctx, ScriptedProvider(outputs)).run_drafting(
            samples.analysis().evidence_map(), samples.analysis()
        )
    assert exc.value.stage == PipelineStage.STYLE


def test_invalid_model_output_keeps_raw_text(ctx: PromptContext) -> None:
    provider = ScriptedProvider({"EvidenceAnalysis": '{"agenda_items": "nope"}'})

    with pytest.raises(StageError) as exc:
        pipeline(ctx, provider).analyse_evidence()
    assert exc.value.raw_text == '{"agenda_items": "nope"}'

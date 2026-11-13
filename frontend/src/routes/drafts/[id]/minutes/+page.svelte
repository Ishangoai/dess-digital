<script lang="ts">
	import { api, errorText } from '#lib/api.ts';
	import DraftDocument from '#lib/components/DraftDocument.svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	let run = $derived(data.run);
	let draft = $derived(run.draft!);

	let template = $state<FileList | null>(null);
	let exporting = $state(false);
	let exportError = $state('');

	const decisions = $derived(
		new Map((run.reconsideration?.decisions ?? []).map((d) => [d.finding_id, d]))
	);
	const seconds = (ms: number) => (ms / 1000).toFixed(1);

	async function downloadWithTemplate() {
		if (!template?.[0]) return;
		exporting = true;
		exportError = '';
		try {
			const blob = await api.documentWithTemplate(run.id, template[0]);
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = `draft-minutes-${run.id.slice(0, 8)}.docx`;
			a.click();
			URL.revokeObjectURL(url);
		} catch (e) {
			exportError = errorText(e);
		} finally {
			exporting = false;
		}
	}
</script>

<div class="layout">
	<section class="card doc">
		<div class="row doc-head">
			<h2>3. Draft minutes</h2>
			<span class="muted small">
				{draft.questions.length} clarification question{draft.questions.length === 1 ? '' : 's'}
			</span>
		</div>
		<DraftDocument {draft} />
	</section>

	<div class="side stack">
		<section class="card stack">
			<h2>4. Export to Word</h2>
			<p class="muted small">Clarification questions become Word comments on the highlighted text.</p>
			<a class="btn primary" href={api.documentUrl(run.id)} download>Download Word document</a>
			<label class="field">
				Or build it into your template (.docx, with a {'{{MINUTES}}'} paragraph)
				<input type="file" accept=".docx" bind:files={template} />
			</label>
			<button class="btn" onclick={downloadWithTemplate} disabled={!template?.[0] || exporting}>
				{#if exporting}<span class="spinner"></span>{/if}
				Download with template
			</button>
			{#if exportError}<p class="alert error small">{exportError}</p>{/if}
		</section>

		<section class="card stack">
			<h2>Review notes</h2>
			{#if run.validation}
				<div>
					<h3>Validation</h3>
					<p class="small">{run.validation.summary}</p>
					<ul class="small">
						{#each run.validation.findings as f (f.finding_id)}
							{@const d = decisions.get(f.finding_id)}
							<li>
								<span class="tag" class:material={f.significance === 'material'}>{f.significance}</span>
								<span class="muted">{f.category.replace('_', ' ')}</span>
								{f.issue}
								{#if d}<div class="muted">{d.decision.replaceAll('_', ' ')}: {d.reason}</div>{/if}
							</li>
						{/each}
					</ul>
				</div>
			{/if}
			{#if run.lint.length}
				<div>
					<h3>Automated checks</h3>
					<ul class="small">{#each run.lint as issue, i (i)}<li>{issue}</li>{/each}</ul>
				</div>
			{/if}
			{#if draft.drafting_notes.length}
				<div>
					<h3>Drafting notes</h3>
					<ul class="small">{#each draft.drafting_notes as n, i (i)}<li>{n}</li>{/each}</ul>
				</div>
			{/if}
			{#if !run.validation && !run.lint.length && !draft.drafting_notes.length}
				<p class="muted small">Nothing to report.</p>
			{/if}
		</section>

		<section class="card stack">
			<h2>LLM calls</h2>
			<div class="table-wrap">
				<table class="small">
					<thead><tr><th>Stage</th><th>In</th><th>Out</th><th>s</th><th></th></tr></thead>
					<tbody>
						{#each run.llm_calls as c, i (i)}
							<tr>
								<td>{c.stage}<div class="muted">{c.model}</div></td>
								<td>{c.input_tokens}</td>
								<td>{c.output_tokens}</td>
								<td>{seconds(c.latency_ms)}</td>
								<td>{c.ok ? 'ok' : c.error}</td>
							</tr>
						{/each}
						<tr class="total">
							<td>Total</td>
							<td>{run.usage_total.input_tokens}</td>
							<td>{run.usage_total.output_tokens}</td>
							<td>{seconds(run.usage_total.latency_ms)}</td>
							<td></td>
						</tr>
					</tbody>
				</table>
			</div>
		</section>

		<a class="small" href="/drafts/{run.id}/mapping">View the confirmed mapping</a>
	</div>
</div>

<style>
	.layout {
		display: grid;
		grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
		gap: 1rem;
		align-items: start;
	}

	@media (max-width: 900px) {
		.layout {
			grid-template-columns: 1fr;
		}
	}

	.doc-head {
		justify-content: space-between;
		margin-bottom: 0.5rem;
	}

	p {
		margin: 0;
	}

	ul {
		margin: 0.25rem 0 0;
		padding-left: 1.1rem;
	}

	li {
		margin-bottom: 0.4rem;
	}

	.tag {
		font-size: 0.7rem;
		font-weight: 600;
		text-transform: uppercase;
		padding: 0.05rem 0.4rem;
		border-radius: 4px;
		background: var(--bg);
		border: 1px solid var(--border);
	}

	.tag.material {
		background: var(--err-bg);
		color: var(--err-fg);
		border-color: transparent;
	}

	.total td {
		font-weight: 600;
	}
</style>

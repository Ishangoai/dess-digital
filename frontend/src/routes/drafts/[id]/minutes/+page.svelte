<script lang="ts">
	import { api, errorText, plural } from '#lib/api.ts';
	import DraftDocument from '#lib/components/DraftDocument.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	let run = $derived(data.run);
	let draft = $derived(run.draft!);

	let active = $state<string | null>(null);
	let templateInput: HTMLInputElement;
	let exporting = $state(false);
	let exportError = $state('');

	const findings = $derived(run.validation?.findings ?? []);
	const decisions = $derived(
		new Map((run.reconsideration?.decisions ?? []).map((d) => [d.finding_id, d]))
	);
	const headings = $derived(new Map(draft.items.map((i) => [i.item_ref, i.heading])));
	const seconds = (ms: number) => `${(ms / 1000).toFixed(1)}s`;
	const tokens = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));

	function where(q: (typeof draft.questions)[number]): string {
		if (q.anchor_kind === 'meeting_heading') return 'Meeting details';
		const ref = q.item_ref ?? q.paragraph_id?.split('.')[0];
		return ref ? `${ref}. ${headings.get(ref) ?? ''}` : 'Minutes';
	}

	function select(id: string, scroll = false) {
		active = active === id && !scroll ? null : id;
		if (scroll) document.getElementById(`q-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
		else document.getElementById(`rail-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
	}

	async function downloadWithTemplate(file: File | undefined) {
		if (!file) return;
		exporting = true;
		exportError = '';
		try {
			const blob = await api.documentWithTemplate(run.id, file);
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
			templateInput.value = '';
		}
	}
</script>

<div class="toolbar">
	<div class="stack tight">
		<h2>Draft minutes</h2>
		<p class="small muted">
			{draft.questions.length
				? `${plural(draft.questions.length, 'question')} for you to answer. They go into Word as comments.`
				: 'No questions for you. The draft is ready to review in Word.'}
		</p>
	</div>
	<span class="spacer"></span>
	<a class="btn ghost" href="/drafts/{run.id}/mapping"><Icon name="map" /> Mapping</a>
	<details class="menu">
		<summary class="btn">
			{#if exporting}<span class="spinner"></span>{/if}
			Use a template <Icon name="chevronDown" size={14} />
		</summary>
		<div class="menu-body">
			<p class="small">
				Build the minutes into your own Word template. It needs a paragraph containing
				<code>{'{{MINUTES}}'}</code>.
			</p>
			<button class="btn sm" onclick={() => templateInput.click()} disabled={exporting}>
				<Icon name="upload" size={14} /> Choose template (.docx)
			</button>
			<input
				bind:this={templateInput}
				type="file"
				accept=".docx"
				hidden
				onchange={(e) => downloadWithTemplate(e.currentTarget.files?.[0])}
			/>
		</div>
	</details>
	<a class="btn primary" href={api.documentUrl(run.id)} download>
		<Icon name="download" /> Download Word
	</a>
</div>

{#if exportError}<p class="alert error small">{exportError}</p>{/if}

<div class="layout">
	<div class="paper">
		<DraftDocument {draft} {active} onselect={(id) => select(id)} />
	</div>

	<aside class="rail">
		<section class="panel">
			<header class="panel-head">
				<Icon name="message" size={15} />
				<h3>Questions</h3>
				<span class="count">{draft.questions.length}</span>
			</header>
			{#if draft.questions.length}
				<ol class="questions">
					{#each draft.questions as q, i (q.question_id)}
						<li id="rail-{q.question_id}">
							<button class="q" class:active={active === q.question_id} onclick={() => select(q.question_id, true)}>
								<span class="q-num">{i + 1}</span>
								<span class="q-body">
									<span class="tiny muted">{where(q)}</span>
									<span>{q.question}</span>
								</span>
							</button>
						</li>
					{/each}
				</ol>
			{:else}
				<p class="panel-empty">Nothing needs clarifying.</p>
			{/if}
		</section>

		<details class="panel" open={findings.length > 0}>
			<summary class="panel-head">
				<Icon name="shield" size={15} />
				<h3>How it was checked</h3>
				<span class="count">{findings.length ? plural(findings.length, 'finding') : 'passed'}</span>
				<Icon name="chevronDown" size={14} />
			</summary>
			<div class="panel-body">
				{#if run.validation}<p class="small muted">{run.validation.summary}</p>{/if}
				{#each findings as f (f.finding_id)}
					{@const d = decisions.get(f.finding_id)}
					<div class="finding">
						<div class="row tight">
							<span class="sig" class:material={f.significance === 'material'}>{f.significance}</span>
							<span class="tiny muted">{f.category.replaceAll('_', ' ')}{f.item_ref ? `, item ${f.item_ref}` : ''}</span>
						</div>
						<p class="small">{f.issue}</p>
						{#if d}
							<p class="tiny decision" class:accepted={d.decision.startsWith('accept')}>
								<strong>{d.decision.replaceAll('_', ' ')}:</strong> {d.reason}
							</p>
						{/if}
					</div>
				{/each}
				{#if run.lint.length}
					<div class="stack tight">
						<span class="eyebrow">Automated checks</span>
						<ul class="small">{#each run.lint as issue, i (i)}<li>{issue}</li>{/each}</ul>
					</div>
				{/if}
				{#if draft.drafting_notes.length}
					<div class="stack tight">
						<span class="eyebrow">Drafting notes</span>
						<ul class="small">{#each draft.drafting_notes as n, i (i)}<li>{n}</li>{/each}</ul>
					</div>
				{/if}
			</div>
		</details>

		<details class="panel">
			<summary class="panel-head">
				<Icon name="layers" size={15} />
				<h3>Model usage</h3>
				<span class="count">{tokens(run.usage_total.total_tokens)} tokens · {seconds(run.usage_total.latency_ms)}</span>
				<Icon name="chevronDown" size={14} />
			</summary>
			<div class="panel-body">
				<table class="usage">
					<thead><tr><th>Stage</th><th>In</th><th>Out</th><th>Time</th></tr></thead>
					<tbody>
						{#each run.llm_calls as c, i (i)}
							<tr class:bad={!c.ok} title={c.error ?? c.model}>
								<td>{c.stage}</td>
								<td>{tokens(c.input_tokens)}</td>
								<td>{tokens(c.output_tokens)}</td>
								<td>{seconds(c.latency_ms)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
				<p class="tiny muted">{run.llm_calls[0]?.model ?? ''}</p>
			</div>
		</details>
	</aside>
</div>

<style>
	.toolbar {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		flex-wrap: wrap;
	}

	.menu {
		position: relative;
	}

	.menu[open] > summary {
		background: var(--surface-2);
	}

	.menu-body {
		position: absolute;
		right: 0;
		top: calc(100% + 6px);
		z-index: 20;
		width: 280px;
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: 0.7rem;
		padding: 0.9rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		box-shadow: var(--shadow-lg);
	}

	.layout {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 320px;
		gap: 1.5rem;
		align-items: start;
	}

	.paper {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 6px;
		box-shadow: var(--shadow);
		padding: 3rem 3.5rem;
		max-width: 800px;
		width: 100%;
		justify-self: center;
	}

	.rail {
		position: sticky;
		top: 1.25rem;
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		max-height: calc(100vh - 2.5rem);
		overflow-y: auto;
	}

	.panel {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		box-shadow: var(--shadow-sm);
	}

	.panel-head {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.75rem 0.9rem;
		color: var(--text-2);
	}

	.panel-head h3 {
		flex: 1;
	}

	.count {
		font-size: 0.74rem;
		color: var(--muted);
	}

	details.panel[open] > .panel-head :global(svg:last-child) {
		transform: rotate(180deg);
	}

	details.panel[open] > .panel-head,
	section.panel > .panel-head {
		border-bottom: 1px solid var(--border);
	}

	.panel-empty {
		padding: 0.8rem 0.9rem;
		font-size: 0.85rem;
		color: var(--muted);
	}

	.panel-body {
		display: flex;
		flex-direction: column;
		gap: 0.8rem;
		padding: 0.8rem 0.9rem;
	}

	.questions {
		list-style: none;
		margin: 0;
		padding: 0.35rem;
	}

	.q {
		all: unset;
		box-sizing: border-box;
		display: flex;
		gap: 0.6rem;
		width: 100%;
		padding: 0.6rem;
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: 0.86rem;
		line-height: 1.45;
	}

	.q:hover {
		background: var(--surface-2);
	}

	.q.active {
		background: var(--mark-soft);
		box-shadow: inset 3px 0 0 var(--warn);
	}

	.q:focus-visible {
		outline: 2px solid var(--accent);
	}

	.q-num {
		display: grid;
		place-items: center;
		flex-shrink: 0;
		width: 1.3rem;
		height: 1.3rem;
		border-radius: 50%;
		background: var(--mark);
		color: var(--warn-fg);
		font-size: 0.68rem;
		font-weight: 700;
	}

	.q-body {
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
	}

	.finding {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
		padding-left: 0.7rem;
		border-left: 2px solid var(--border);
	}

	.row.tight {
		gap: 0.4rem;
	}

	.sig {
		font-size: 0.66rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		padding: 0.05rem 0.4rem;
		border-radius: 4px;
		background: #f1f2f4;
		color: var(--text-2);
	}

	.sig.material {
		background: var(--err-bg);
		color: var(--err-fg);
	}

	.decision {
		color: var(--muted);
	}

	.decision.accepted strong {
		color: var(--ok-fg);
	}

	ul {
		margin: 0;
		padding-left: 1.1rem;
	}

	.usage {
		font-size: 0.8rem;
	}

	.usage th,
	.usage td {
		padding: 0.35rem 0.4rem;
	}

	.usage tr.bad td {
		color: var(--err-fg);
	}

	@media (max-width: 1080px) {
		.layout {
			grid-template-columns: 1fr;
		}

		.rail {
			position: static;
			max-height: none;
			order: -1;
		}

		.paper {
			padding: 2rem 1.5rem;
		}
	}
</style>

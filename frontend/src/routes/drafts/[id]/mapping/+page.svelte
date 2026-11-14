<script lang="ts">
	import { slide } from 'svelte/transition';
	import { goto, invalidate } from '$app/navigation';
	import { page } from '$app/state';
	import {
		ASSOCIATION_INFO,
		ASSOCIATIONS,
		api,
		draftsChanged,
		errorText,
		lineRef,
		plural,
		type Association,
		type EvidenceMap,
		type LineRef
	} from '#lib/api.ts';
	import Icon from '#lib/components/Icon.svelte';
	import Working from '#lib/components/Working.svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	let run = $derived(data.run);
	let review = $derived(data.review);

	interface Row {
		segment_id: string;
		source_id: string;
		start: number;
		end: number;
		item_ref: string;
		association: Association;
		summary: string;
		excerpt: string;
	}

	function toRows(): Row[] {
		return review.segments.map((s) => ({
			segment_id: s.segment_id,
			source_id: s.source.source_id,
			start: s.source.start,
			end: s.source.end,
			item_ref: s.item_ref ?? '',
			association: s.association,
			summary: s.summary,
			excerpt: s.excerpt
		}));
	}

	// Local editable copy, reset whenever a new review loads.
	let rows = $state<Row[]>([]);
	let dirty = $state(false);
	let editing = $state<string | null>(null);
	let open = $state<Record<string, boolean>>({});
	$effect.pre(() => {
		rows = toRows();
		dirty = false;
		editing = null;
	});

	let attentionOpen = $state(false);
	let attentionBox = $state<HTMLDetailsElement>();

	function showAttention() {
		attentionOpen = true;
		attentionBox?.scrollIntoView({ behavior: 'smooth', block: 'start' });
	}
	let busy = $state(false);
	let elapsed = $state(0);
	let error = $state('');

	const editable = $derived(run.status === 'awaiting_mapping_review');
	const retryDrafting = $derived(
		run.status === 'failed' && !!run.error_stage && run.error_stage !== 'evidence'
	);
	const groups = $derived([
		...review.mapping.agenda_items.map((i) => ({ ref: i.ref, heading: i.heading, extra: false })),
		...review.mapping.additional_business.map((b) => ({ ref: b.key, heading: b.heading, extra: true }))
	]);
	const headings = $derived(new Map(groups.map((g) => [g.ref, g.heading])));
	const sourceIds = $derived([...new Set(run.documents.map((d) => d.source_id))]);
	const sourceNames = $derived(new Map(run.documents.map((d) => [d.source_id, d.role])));
	const unassigned = $derived(rows.filter((r) => !r.item_ref || !headings.has(r.item_ref)));
	// Uncertainties and source limitations from the analysis, shown with the items needing attention.
	const notes = $derived([
		...(run.analysis?.uncertainties ?? []).map((u) => ({
			ref: u.item_ref ? `Item ${u.item_ref}` : 'Meeting',
			text: u.description,
			extra: u.competing_readings.length ? `Possible readings: ${u.competing_readings.join(' / ')}` : ''
		})),
		...(run.analysis?.sources ?? [])
			.filter((src) => src.limitations.length)
			.map((src) => ({ ref: src.source_id, text: src.limitations.join('; '), extra: '' }))
	]);
	const attention = $derived(unassigned.length + review.uncovered.length + notes.length);

	function rowsFor(ref: string) {
		return rows.filter((r) => r.item_ref === ref);
	}

	function edited() {
		dirty = true;
	}

	function removeRow(id: string) {
		rows = rows.filter((r) => r.segment_id !== id);
		editing = null;
		edited();
	}

	function fileUncovered(ref: LineRef, excerpt: string, itemRef: string) {
		if (!itemRef) return;
		const used = new Set(rows.map((r) => r.segment_id));
		let n = rows.length + 1;
		while (used.has(`S${n}`)) n++;
		rows.push({
			segment_id: `S${n}`,
			source_id: ref.source_id,
			start: ref.start,
			end: ref.end,
			item_ref: itemRef,
			association: 'primary',
			summary: '',
			excerpt
		});
		edited();
	}

	const covered = $derived(
		new Set(rows.map((r) => `${r.source_id}${r.start}-${r.end}`))
	);

	function editedMapping(): EvidenceMap {
		const previous = new Map(review.mapping.segments.map((s) => [s.segment_id, s]));
		return {
			agenda_items: review.mapping.agenda_items,
			additional_business: review.mapping.additional_business,
			segments: rows.map((r) => ({
				segment_id: r.segment_id.trim(),
				source: { source_id: r.source_id, start: Number(r.start), end: Number(r.end) },
				item_ref: r.item_ref || null,
				association: r.association,
				summary: r.summary,
				apparent_outcome: previous.get(r.segment_id)?.apparent_outcome ?? null
			}))
		};
	}

	function discard() {
		rows = toRows();
		dirty = false;
		editing = null;
	}

	async function generate() {
		busy = true;
		error = '';
		elapsed = 0;
		const timer = window.setInterval(() => elapsed++, 1000);
		const id = run.id;
		// Pick up the drafting status once the request has started, so the header, sidebar and
		// AI activity page follow the stages live.
		const started = window.setTimeout(() => {
			invalidate('app:run');
			draftsChanged();
		}, 800);
		try {
			// A failed drafting run keeps its confirmed mapping; only send edits while reviewing.
			await api.generate(id, editable && dirty ? editedMapping() : null);
			await invalidate('app:run');
			draftsChanged();
			// Only move on if the user is still looking at this meeting's mapping.
			if (page.url.pathname === `/drafts/${id}/mapping`) await goto(`/drafts/${id}/minutes`);
		} catch (e) {
			error = errorText(e);
			await invalidate('app:run');
			draftsChanged();
		} finally {
			window.clearTimeout(started);
			window.clearInterval(timer);
			busy = false;
		}
	}
</script>

{#snippet passage(row: Row)}
	{@const isEditing = editing === row.segment_id}
	<li class="passage" class:editing={isEditing}>
		<div class="p-main">
			<span class="ref" title="{sourceNames.get(row.source_id) ?? row.source_id}, lines {row.start} to {row.end}">
				{lineRef({ source_id: row.source_id, start: row.start, end: row.end })}
			</span>
			<div class="p-body">
				<p class:empty={!row.summary}>{row.summary || 'No summary'}</p>
				<div class="p-meta">
					{#if row.association !== 'primary'}
						<span class="assoc {row.association}" title={ASSOCIATION_INFO[row.association].hint}>
							{ASSOCIATION_INFO[row.association].label}
						</span>
					{/if}
					{#if row.excerpt}
						<button class="link-btn tiny" onclick={() => (open[row.segment_id] = !open[row.segment_id])}>
							{open[row.segment_id] ? 'Hide' : 'Show'} what was said
						</button>
					{/if}
				</div>
			</div>
			{#if editable}
				<button
					class="btn ghost sm"
					onclick={() => (editing = isEditing ? null : row.segment_id)}
					aria-expanded={isEditing}
					aria-label="Edit passage {row.segment_id}"
				>
					{#if isEditing}<Icon name="check" size={14} /> Done{:else}<Icon name="pencil" size={14} /> Edit{/if}
				</button>
			{/if}
		</div>

		{#if open[row.segment_id] && row.excerpt}
			<pre class="excerpt" transition:slide={{ duration: 140 }}>{row.excerpt}</pre>
		{/if}

		{#if isEditing}
			<div class="editor" transition:slide={{ duration: 160 }}>
				<label class="field">
					Agenda item
					<select bind:value={row.item_ref} onchange={edited}>
						<option value="">Not assigned</option>
						{#each review.valid_item_refs as ref (ref)}
							<option value={ref}>{ref}. {headings.get(ref) ?? ''}</option>
						{/each}
					</select>
				</label>
				<label class="field">
					How it relates
					<select bind:value={row.association} onchange={edited}>
						{#each ASSOCIATIONS as a (a)}<option value={a}>{ASSOCIATION_INFO[a].label}</option>{/each}
					</select>
					<span class="tiny muted hint">{ASSOCIATION_INFO[row.association].hint}</span>
				</label>
				<div class="field lines">
					<span>Lines</span>
					<div class="row tight">
						<select bind:value={row.source_id} onchange={edited} aria-label="Source">
							{#each sourceIds as id (id)}<option value={id}>{id}</option>{/each}
						</select>
						<input type="number" min="1" bind:value={row.start} oninput={edited} aria-label="First line" />
						<span class="muted">to</span>
						<input type="number" min="1" bind:value={row.end} oninput={edited} aria-label="Last line" />
					</div>
				</div>
				<label class="field summary">
					Summary
					<textarea rows="2" bind:value={row.summary} oninput={edited}></textarea>
				</label>
				<div class="editor-actions">
					<button class="btn ghost sm danger" onclick={() => removeRow(row.segment_id)}>
						<Icon name="trash" size={14} /> Remove passage
					</button>
				</div>
			</div>
		{/if}
	</li>
{/snippet}

{#if busy}
	<Working
		icon="file"
		title="Drafting the minutes"
		message="Selecting what belongs in the record, writing it up and checking it against the evidence."
		seconds={elapsed}
		note="This usually takes under a minute. Long meetings can take a few."
	/>
{:else}
	<div class="layout">
		<div class="lead">
			<p class="small">
				{#if editable}
					Move anything in the wrong place; the minutes are written from this mapping.
				{:else}
					The minutes were written from this mapping, so it is now locked. Correct the draft in the Word
					document, or <a href="/drafts/new">start new minutes</a> with the same files to map it again.
				{/if}
				{#if run.mapping_edited && !editable}<strong>It was edited before drafting.</strong>{/if}
			</p>
			<span class="counts">
				{#if attention}
					<button class="attn-pill" onclick={showAttention} title="Show what needs attention">
						<Icon name="alert" size={13} />
						<strong>{attention}</strong> need{attention === 1 ? 's' : ''} attention
					</button>
				{/if}
				<span><strong>{rows.length}</strong> {rows.length === 1 ? 'passage' : 'passages'}</span>
				<span><strong>{groups.length}</strong> agenda {groups.length === 1 ? 'item' : 'items'}</span>
			</span>
		</div>

		{#if attention}
			<details class="group attention" bind:open={attentionOpen} bind:this={attentionBox}>
				<summary class="g-head">
					<span class="g-ref warn"><Icon name="alert" size={14} /></span>
					<h3>Needs attention</h3>
					<span class="tiny muted">Unsure, unmapped or flagged by the analysis</span>
					<span class="spacer"></span>
					<Icon name="chevronDown" size={16} />
				</summary>
				{#if notes.length}
					<ul class="passages">
						{#each notes as n, i (i)}
							<li class="passage">
								<div class="p-main">
									<span class="ref">{n.ref}</span>
									<div class="p-body">
										<p>{n.text}</p>
										{#if n.extra}<span class="tiny muted">{n.extra}</span>{/if}
									</div>
								</div>
							</li>
						{/each}
					</ul>
				{/if}
				{#if unassigned.length}
					<ul class="passages">
						{#each unassigned as row (row.segment_id)}{@render passage(row)}{/each}
					</ul>
				{/if}
				{#if review.uncovered.length}
					<ul class="passages">
						{#each review.uncovered as ref, i (lineRef(ref))}
							{@const filed = covered.has(`${ref.source_id}${ref.start}-${ref.end}`)}
							<li class="passage uncovered" class:filed>
								<div class="p-main">
									<span class="ref">{lineRef(ref)}</span>
									<div class="p-body">
										<p class="small">{review.uncovered_excerpts[i]}</p>
										<span class="tiny muted">
											{filed
												? 'Filed. It is saved when you draft the minutes.'
												: editable
													? 'Not filed under any agenda item. File it under one if it belongs in the minutes.'
													: 'Not filed under any agenda item.'}
										</span>
									</div>
									{#if editable && !filed}
										<select
											class="file-under"
											aria-label="File these lines under an agenda item"
											onchange={(e) => fileUncovered(ref, review.uncovered_excerpts[i], e.currentTarget.value)}
										>
											<option value="">File under...</option>
											{#each review.valid_item_refs as r (r)}
												<option value={r}>{r}. {headings.get(r) ?? ''}</option>
											{/each}
										</select>
									{/if}
								</div>
							</li>
						{/each}
					</ul>
				{/if}
			</details>
		{:else}
			<p class="all-good small"><Icon name="check" size={14} /> Every line of the transcript and notes is mapped.</p>
		{/if}

		{#each groups as g (g.ref)}
			{@const list = rowsFor(g.ref)}
			<section class="group">
				<header class="g-head">
					<span class="g-ref">{g.extra ? '+' : g.ref}</span>
					<h3>{g.heading}</h3>
					{#if g.extra}<span class="assoc additional_business">Not on agenda</span>{/if}
					<span class="spacer"></span>
					<span class="tiny muted">{list.length ? plural(list.length, 'passage') : ''}</span>
				</header>
				{#if list.length}
					<ul class="passages">
						{#each list as row (row.segment_id)}{@render passage(row)}{/each}
					</ul>
				{:else}
					<p class="none">No discussion mapped to this item.</p>
				{/if}
			</section>
		{/each}

		{#if error}<p class="alert error">{error}</p>{/if}

		<div class="actionbar">
			{#if editable || retryDrafting}
				<span class="small" class:muted={!dirty}>
					{#if retryDrafting}
						Drafting failed. The mapping is kept; try drafting again.
					{:else if dirty}
						<strong>You have unsaved edits.</strong> They are saved when you draft.
					{:else}
						Happy with the mapping?
					{/if}
				</span>
				<span class="spacer"></span>
				{#if dirty && editable}
					<button class="btn ghost" onclick={discard}>Discard edits</button>
				{/if}
				<button class="btn primary lg" onclick={generate}>
					{retryDrafting ? 'Retry drafting' : dirty ? 'Save and draft minutes' : 'Draft the minutes'}
					<Icon name="arrowRight" />
				</button>
			{:else if run.draft}
				<span class="spacer"></span>
				<a class="btn primary" href="/drafts/{run.id}/minutes">View the minutes <Icon name="arrowRight" /></a>
			{/if}
		</div>
	</div>
{/if}

<style>
	.layout {
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}

	.lead {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.5rem 1.5rem;
		flex-wrap: wrap;
	}

	.lead p {
		color: var(--muted);
	}

	.lead p {
		max-width: 72ch;
	}

	.lead p strong {
		color: var(--text-2);
		font-weight: 500;
	}

	.counts {
		display: flex;
		gap: 0.4rem;
	}

	.attn-pill {
		font: inherit;
		display: inline-flex;
		align-items: center;
		gap: 0.3rem;
		font-size: 0.78rem;
		padding: 0.2rem 0.6rem;
		border: 1px solid #f3d39b;
		border-radius: 999px;
		background: var(--warn-bg);
		color: var(--warn-fg);
		cursor: pointer;
	}

	.attn-pill:hover {
		border-color: var(--warn);
	}

	.attn-pill strong {
		font-weight: 600;
	}

	.counts span {
		font-size: 0.78rem;
		color: var(--muted);
		padding: 0.2rem 0.6rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		background: var(--surface);
	}

	.counts strong {
		color: var(--text);
		font-weight: 600;
	}

	.attention > summary {
		cursor: pointer;
	}

	.attention:not([open]) > summary {
		border-bottom: none;
	}

	.attention > summary :global(svg:last-child) {
		color: var(--warn);
		transition: transform 0.15s;
	}

	.attention[open] > summary :global(svg:last-child) {
		transform: rotate(180deg);
	}

	.all-good {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		color: var(--ok-fg);
	}

	.group {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		box-shadow: var(--shadow-sm);
		overflow: hidden;
	}

	.group.attention {
		border-color: #f3d39b;
	}

	.g-head {
		display: flex;
		align-items: center;
		gap: 0.65rem;
		padding: 0.75rem 1rem;
		border-bottom: 1px solid var(--border);
		background: var(--surface-2);
	}

	.attention .g-head {
		background: var(--warn-bg);
		border-color: #f3d39b;
	}

	.g-ref {
		display: grid;
		place-items: center;
		min-width: 1.6rem;
		height: 1.6rem;
		padding: 0 0.35rem;
		border-radius: 6px;
		background: var(--surface);
		border: 1px solid var(--border);
		font-size: 0.78rem;
		font-weight: 600;
		color: var(--text-2);
	}

	.g-ref.warn {
		color: var(--warn);
		border-color: #f3d39b;
	}

	.passages {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.passage {
		border-top: 1px solid var(--border);
		padding: 0.75rem 1rem;
	}

	.passages:first-of-type .passage:first-child,
	.g-head + .passages .passage:first-child {
		border-top: none;
	}

	.passage.editing {
		background: #fcfcfd;
	}

	.passage.filed {
		opacity: 0.55;
	}

	.p-main {
		display: flex;
		align-items: flex-start;
		gap: 0.8rem;
	}

	.p-main > .ref {
		margin-top: 0.15rem;
		min-width: 4.5rem;
		text-align: center;
	}

	.p-body {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
	}

	.p-body p {
		font-size: 0.9rem;
		color: var(--text);
	}

	.p-body p.empty {
		color: var(--faint);
		font-style: italic;
	}

	.p-meta {
		display: flex;
		align-items: center;
		gap: 0.6rem;
	}

	.assoc {
		font-size: 0.7rem;
		font-weight: 600;
		padding: 0.1rem 0.45rem;
		border-radius: 999px;
		background: #f1f2f4;
		color: var(--text-2);
	}

	.assoc.uncertain {
		background: var(--warn-bg);
		color: var(--warn-fg);
	}

	.assoc.additional_business {
		background: #f1ecfd;
		color: #5b21b6;
	}

	.assoc.procedural {
		background: var(--info-bg);
		color: var(--info-fg);
	}

	.excerpt {
		white-space: pre-wrap;
		font-family: var(--font);
		font-size: 0.82rem;
		line-height: 1.55;
		color: var(--text-2);
		background: var(--surface-2);
		border: 1px solid var(--border);
		border-radius: var(--radius-sm);
		padding: 0.7rem 0.85rem;
		margin: 0.6rem 0 0 5.3rem;
		max-height: 260px;
		overflow: auto;
	}

	.editor {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 0.8rem;
		margin: 0.8rem 0 0 5.3rem;
		padding: 0.9rem;
		border: 1px solid var(--border);
		border-radius: var(--radius-sm);
		background: var(--surface);
	}

	.editor .summary,
	.editor-actions {
		grid-column: 1 / -1;
	}

	.lines .row.tight {
		gap: 0.4rem;
		flex-wrap: nowrap;
	}

	.lines select {
		width: 4rem;
	}

	.lines input {
		width: 5.5rem;
	}

	.hint {
		font-weight: 400;
	}

	.editor-actions {
		display: flex;
		justify-content: flex-start;
	}

	.danger {
		color: var(--err);
	}

	.file-under {
		width: auto;
		max-width: 220px;
		font-size: 0.8rem;
		padding: 0.3rem 0.5rem;
	}

	.none {
		padding: 0.75rem 1rem;
		font-size: 0.84rem;
		color: var(--faint);
	}

	.actionbar {
		position: sticky;
		bottom: 1rem;
		z-index: 10;
		display: flex;
		align-items: center;
		gap: 0.75rem;
		flex-wrap: wrap;
		padding: 0.75rem 0.85rem 0.75rem 1.1rem;
		margin-top: 0.5rem;
		background: rgba(255, 255, 255, 0.92);
		backdrop-filter: blur(8px);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		box-shadow: var(--shadow-lg);
	}

	.actionbar:empty {
		display: none;
	}

	@media (max-width: 640px) {
		.p-main {
			flex-wrap: wrap;
		}

		.excerpt,
		.editor {
			margin-left: 0;
		}

		.editor {
			grid-template-columns: 1fr;
		}
	}
</style>

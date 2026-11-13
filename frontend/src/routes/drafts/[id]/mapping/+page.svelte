<script lang="ts">
	import { goto, invalidate } from '$app/navigation';
	import {
		ASSOCIATIONS,
		api,
		errorText,
		lineRef,
		type Association,
		type EvidenceMap,
		type LineRef
	} from '#lib/api.ts';
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
	$effect.pre(() => {
		rows = toRows();
		dirty = false;
	});

	let busy = $state(false);
	let elapsed = $state(0);
	let error = $state('');

	const editable = $derived(run.status === 'awaiting_mapping_review');
	const retryDrafting = $derived(
		run.status === 'failed' && !!run.error_stage && run.error_stage !== 'evidence'
	);
	const headings = $derived(
		new Map([
			...review.mapping.agenda_items.map((i) => [i.ref, i.heading] as const),
			...review.mapping.additional_business.map((b) => [b.key, b.heading] as const)
		])
	);
	const sourceIds = $derived([...new Set(run.documents.map((d) => d.source_id))]);

	function edited() {
		dirty = true;
	}

	function removeRow(i: number) {
		rows.splice(i, 1);
		edited();
	}

	function addUncovered(ref: LineRef, excerpt: string) {
		const used = new Set(rows.map((r) => r.segment_id));
		let n = rows.length + 1;
		while (used.has(`S${n}`)) n++;
		rows.push({
			segment_id: `S${n}`,
			source_id: ref.source_id,
			start: ref.start,
			end: ref.end,
			item_ref: '',
			association: 'uncertain',
			summary: '',
			excerpt
		});
		edited();
	}

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

	async function generate() {
		busy = true;
		error = '';
		elapsed = 0;
		const timer = window.setInterval(() => elapsed++, 1000);
		try {
			// A failed drafting run keeps its confirmed mapping; only send edits while reviewing.
			await api.generate(run.id, editable && dirty ? editedMapping() : null);
			await invalidate('app:run');
			await goto(`/drafts/${run.id}/minutes`);
		} catch (e) {
			error = errorText(e);
			await invalidate('app:run');
		} finally {
			window.clearInterval(timer);
			busy = false;
		}
	}
</script>

<div class="stack">
	{#if run.analysis}
		<section class="card stack">
			<h2>What the evidence covers</h2>
			<ul class="plain">
				{#each run.analysis.sources as s (s.source_id)}
					<li>
						<strong>{s.source_id}</strong>: {s.description}
						{#if s.limitations.length}
							<div class="muted small">Limitations: {s.limitations.join('; ')}</div>
						{/if}
					</li>
				{/each}
			</ul>
			{#if run.analysis.uncertainties.length}
				<h3>Uncertainties</h3>
				<ul class="plain">
					{#each run.analysis.uncertainties as u (u.uncertainty_id)}
						<li>
							<span class="mono">{u.uncertainty_id}</span> item {u.item_ref ?? '-'}: {u.description}
							<div class="muted small">Readings: {u.competing_readings.join(' / ')}</div>
						</li>
					{/each}
				</ul>
			{/if}
		</section>
	{/if}

	<section class="card stack">
		<div>
			<h2>2. Review the mapping of evidence to agenda items</h2>
			<p class="muted small">
				Each row is a passage of the transcript or notes. Check it sits under the right item; fix
				the item, line range or association where it does not.
				{#if run.mapping_edited}<strong>This mapping has been edited.</strong>{/if}
			</p>
		</div>

		<div class="agenda small">
			{#each review.mapping.agenda_items as item (item.ref)}
				<span><strong>{item.ref}</strong> {item.heading}</span>
			{/each}
			{#each review.mapping.additional_business as b (b.key)}
				<span><strong>{b.key}</strong> {b.heading}</span>
			{/each}
		</div>

		<div class="table-wrap">
			<table class="mapping">
				<thead>
					<tr>
						<th>Seg</th>
						<th>Lines</th>
						<th>Item</th>
						<th>Association</th>
						<th>Summary and excerpt</th>
						{#if editable}<th></th>{/if}
					</tr>
				</thead>
				<tbody>
					{#each rows as row, i (row.segment_id + i)}
						<tr class:unassigned={!row.item_ref}>
							<td class="mono">{row.segment_id}</td>
							<td class="lines">
								<select bind:value={row.source_id} disabled={!editable} onchange={edited} aria-label="Source">
									{#each sourceIds as id (id)}<option value={id}>{id}</option>{/each}
								</select>
								<input type="number" min="1" bind:value={row.start} disabled={!editable} oninput={edited} aria-label="Start line" />
								<input type="number" min="1" bind:value={row.end} disabled={!editable} oninput={edited} aria-label="End line" />
							</td>
							<td>
								<select bind:value={row.item_ref} disabled={!editable} onchange={edited} aria-label="Agenda item">
									<option value="">Unassigned</option>
									{#each review.valid_item_refs as ref (ref)}
										<option value={ref}>{ref} {headings.get(ref) ?? ''}</option>
									{/each}
								</select>
							</td>
							<td>
								<select bind:value={row.association} disabled={!editable} onchange={edited} aria-label="Association">
									{#each ASSOCIATIONS as a (a)}<option value={a}>{a.replace('_', ' ')}</option>{/each}
								</select>
							</td>
							<td class="summary">
								{#if editable}
									<textarea rows="2" bind:value={row.summary} oninput={edited} aria-label="Summary"></textarea>
								{:else}
									<div>{row.summary}</div>
								{/if}
								{#if row.excerpt}
									<details>
										<summary class="muted small">Excerpt</summary>
										<pre>{row.excerpt}</pre>
									</details>
								{/if}
							</td>
							{#if editable}
								<td><button class="btn small" onclick={() => removeRow(i)} title="Remove this row">Remove</button></td>
							{/if}
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		<div>
			{#if review.uncovered.length === 0}
				<p class="alert ok small">Every transcript and notes line is mapped.</p>
			{:else}
				<h3>Lines not mapped to any item</h3>
				<p class="muted small">Check nothing material is missing.</p>
				<ul class="plain">
					{#each review.uncovered as ref, i (lineRef(ref))}
						<li class="uncovered">
							<span class="mono">{lineRef(ref)}</span>
							<span class="small">{review.uncovered_excerpts[i]}</span>
							{#if editable}
								<button class="btn small" onclick={() => addUncovered(ref, review.uncovered_excerpts[i])}>Add as row</button>
							{/if}
						</li>
					{/each}
				</ul>
			{/if}
		</div>
	</section>

	{#if error}<p class="alert error">{error}</p>{/if}

	<div class="row">
		{#if editable || retryDrafting}
			<button class="btn primary" onclick={generate} disabled={busy}>
				{#if busy}<span class="spinner"></span>{/if}
				{retryDrafting ? 'Retry drafting' : dirty ? 'Save edits and draft minutes' : 'Confirm mapping and draft minutes'}
			</button>
			{#if dirty && editable}
				<button class="btn" onclick={() => { rows = toRows(); dirty = false; }} disabled={busy}>Discard edits</button>
			{/if}
			{#if busy}
				<span class="muted small">
					Selecting content, writing and validating the minutes, {elapsed}s. This usually takes a few
					minutes.
				</span>
			{/if}
		{:else if run.draft}
			<a class="btn primary" href="/drafts/{run.id}/minutes">View draft minutes</a>
			<span class="muted small">The mapping is locked once drafting starts.</span>
		{/if}
	</div>
</div>

<style>
	p {
		margin: 0;
	}

	.plain {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.agenda {
		display: flex;
		flex-wrap: wrap;
		gap: 0.35rem 1.25rem;
		color: var(--text-2);
	}

	.mapping select,
	.mapping input {
		font-size: 0.82rem;
		padding: 0.3rem 0.4rem;
	}

	.lines {
		display: flex;
		gap: 0.25rem;
		min-width: 190px;
	}

	.lines select {
		width: 3.5rem;
	}

	.lines input {
		width: 4.5rem;
	}

	.mapping td:nth-child(3) select {
		min-width: 180px;
	}

	.mapping td:nth-child(4) select {
		min-width: 140px;
	}

	.summary {
		min-width: 280px;
	}

	.summary textarea {
		font-size: 0.85rem;
	}

	tr.unassigned {
		background: var(--warn-bg);
	}

	pre {
		white-space: pre-wrap;
		font-size: 0.8rem;
		background: var(--bg);
		padding: 0.5rem;
		border-radius: 6px;
		margin: 0.25rem 0 0;
		max-height: 240px;
		overflow: auto;
	}

	.uncovered {
		display: flex;
		gap: 0.75rem;
		align-items: baseline;
	}

	.btn.small {
		padding: 0.25rem 0.6rem;
		font-size: 0.8rem;
	}
</style>

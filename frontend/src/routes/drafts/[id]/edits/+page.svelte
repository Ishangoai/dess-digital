<script lang="ts">
	import { goto, invalidate } from '$app/navigation';
	import {
		api,
		EDIT_CAUSES,
		EDIT_KINDS,
		errorText,
		formatDate,
		lineRef,
		plural,
		ROUTES,
		type AlignedParagraph,
		type EditLabel,
		type Route
	} from '#lib/api.ts';
	import Icon from '#lib/components/Icon.svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	let run = $derived(data.run);
	let review = $derived(data.review);

	let busy = $state(false);
	let error = $state('');
	let onlyChanges = $state(true);
	let fileInput = $state<HTMLInputElement>();

	const percent = (n: number) => `${Math.round(n * 100)}%`;
	const ROUTE_ORDER: Route[] = ['candidate', 'defect', 'meeting_only'];
	const STATUS_LABELS: Record<string, string> = {
		unchanged: 'Unchanged',
		changed: 'Changed',
		removed: 'Removed',
		added: 'Added',
		moved: 'Moved'
	};

	const comments = $derived(new Map((review?.comments ?? []).map((c) => [c.id, c])));
	const sections = $derived(
		(review?.sections ?? []).map((s) => {
			const rows = (review?.paragraphs ?? []).filter((p) => p.item_ref === s.item_ref);
			return { ...s, rows, changed: rows.filter((r) => r.status !== 'unchanged' || r.labels.length).length };
		})
	);

	async function act(action: () => Promise<unknown>) {
		busy = true;
		error = '';
		try {
			await action();
		} catch (e) {
			error = errorText(e);
		} finally {
			busy = false;
		}
	}

	function upload(file: File | undefined) {
		if (!file) return;
		act(async () => {
			const f = await api.uploadFinal(run.id, file);
			await goto(`/drafts/${run.id}/edits?e=${f.edited_document_id}`, { invalidateAll: true });
		}).then(() => {
			if (fileInput) fileInput.value = '';
		});
	}

	const classify = () =>
		act(async () => {
			if (!review) return;
			await api.classifyEdit(run.id, review.id);
			await invalidate('app:edits');
		});

	function labelTitle(l: EditLabel): string {
		return `${EDIT_CAUSES[l.cause] ?? l.cause} · ${l.dimensions.join(', ')} · ${EDIT_KINDS[l.kind] ?? l.kind}`;
	}

	function shown(rows: AlignedParagraph[]): AlignedParagraph[] {
		return onlyChanges ? rows.filter((r) => r.status !== 'unchanged' || r.labels.length) : rows;
	}
</script>

<div class="page stack">
	<header class="top">
		<div>
			<h2>Edits</h2>
			{#if review}
				<p class="small muted">
					{review.filename} · uploaded {formatDate(review.created_at)} ·
					<strong>{percent(review.similarity)}</strong> of the draft kept
				</p>
			{:else}
				<p class="small muted">Download the Word draft, edit it in Word as usual, then upload it here.</p>
			{/if}
		</div>
		<div class="row">
			{#if data.edits.length > 1}
				<select
					aria-label="Uploaded copy"
					value={review?.id}
					onchange={(e) => goto(`?e=${e.currentTarget.value}`)}
				>
					{#each data.edits as e (e.id)}<option value={e.id}>{formatDate(e.created_at)} · {e.filename}</option>{/each}
				</select>
			{/if}
			<button class="btn sm" onclick={() => fileInput?.click()} disabled={busy}>
				<Icon name="upload" size={14} /> Upload edited Word file
			</button>
			<input
				bind:this={fileInput}
				type="file"
				accept=".docx"
				hidden
				aria-label="Edited Word file"
				onchange={(e) => upload(e.currentTarget.files?.[0])}
			/>
			{#if review}
				<button class="btn sm primary" onclick={classify} disabled={busy}>
					{busy ? 'Working...' : review.classified_at ? 'Classify again' : 'Classify edits'}
				</button>
			{/if}
		</div>
	</header>

	{#if error}<p class="alert error small">{error}</p>{/if}

	{#if review}
		<div class="counts small">
			{#each Object.entries(review.counts) as [status, n] (status)}
				<span class="status {status}">{plural(n, STATUS_LABELS[status].toLowerCase() + ' paragraph')}</span>
			{/each}
		</div>
		{#if review.original_recreated}
			<p class="alert small">
				No stored download was found for this copy, so the original was rendered again from the draft.
			</p>
		{/if}
		{#if review.classify_error}<p class="alert error small">{review.classify_error}</p>{/if}

		{#if review.classified_at}
			<section class="card stack findings" aria-label="What was learned">
				<h3>What the edits show</h3>
				{#each ROUTE_ORDER as route (route)}
					{@const group = review.findings.filter((f) => f.route === route)}
					{#if group.length}
						<div class="route {route}">
							<h4>{ROUTES[route].label} <span class="muted">({group.reduce((n, f) => n + f.count, 0)})</span></h4>
							<p class="tiny muted">{ROUTES[route].about}</p>
							<ul>
								{#each group as f (f.key)}
									<li>
										<strong>{f.pattern}</strong>
										{#if f.count > 1}<span class="count">×{f.count}</span>{/if}
										<span class="tiny muted">
											{EDIT_CAUSES[f.cause] ?? f.cause} · {f.dimensions.join(', ')} · {EDIT_KINDS[f.kind] ?? f.kind}
											· {f.items.length === 1 ? 'item' : 'items'} {f.items.join(', ')}
										</span>
										<div class="small">{f.reason}</div>
										{#if f.profile_basis}<div class="tiny muted">Profile: {f.profile_basis}</div>{/if}
										{#if f.evidence.length}<div class="tiny muted mono">{f.evidence.map(lineRef).join(', ')}</div>{/if}
									</li>
								{/each}
							</ul>
						</div>
					{/if}
				{/each}
				{#if !review.findings.length}<p class="small muted">No edits to classify.</p>{/if}
			</section>
		{/if}

		{#if review.answers.length}
			<section class="card stack">
				<h3>Answers to questions</h3>
				{#each review.answers as a (a.question_id)}
					<div class="answer small">
						<span class="mono">{a.question_id}</span> {a.question}
						<div><strong>{a.author}:</strong> {a.reply}</div>
					</div>
				{/each}
			</section>
		{/if}

		<label class="small toggle"><input type="checkbox" bind:checked={onlyChanges} /> Only show changed paragraphs</label>

		{#each sections as s (s.item_ref)}
			{#if !onlyChanges || s.changed}
				<section class="card item">
					<h3>
						{s.item_ref === 'header' ? 'Header' : s.added ? s.heading : `${s.item_ref}. ${s.heading}`}
						{#if s.added}<span class="status added">added by the reviewer</span>{/if}
					</h3>
					<div class="grid head tiny muted"><span>Draft</span><span>Edited copy</span></div>
					{#each shown(s.rows) as r (r.id)}
						<div class="grid row-{r.status}">
							<div class="cell">
								<span class="status {r.status}">{STATUS_LABELS[r.status]}</span>
								{#if r.status === 'moved' && r.original_item_ref}<span class="tiny muted">from item {r.original_item_ref}</span>{/if}
								<p>
									{#each r.diff as d, i (i)}
										{#if d.op === 'equal'}{d.text}{:else if d.op === 'delete'}<del>{d.text}</del>{/if}
									{/each}
								</p>
							</div>
							<div class="cell">
								<p>
									{#each r.diff as d, i (i)}
										{#if d.op === 'equal'}{d.text}{:else if d.op === 'insert'}<ins>{d.text}</ins>{/if}
									{/each}
								</p>
								{#if r.tracked.length}<p class="tiny muted">{plural(r.tracked.length, 'tracked change')}</p>{/if}
								{#each r.comment_ids as cid (cid)}
									{@const c = comments.get(cid)}
									{#if c}<p class="comment tiny"><Icon name="message" size={11} /> <strong>{c.author}:</strong> {c.text}</p>{/if}
								{/each}
							</div>
							{#if r.labels.length}
								<ul class="labels">
									{#each r.labels as l (l.id)}
										<li class="label {l.route}">
											<details>
												<summary>{labelTitle(l)}</summary>
												<div class="small">{l.reason}</div>
												{#if l.before || l.after}
													<div class="tiny mono">"{l.before || '—'}" → "{l.after || '—'}"</div>
												{/if}
												{#if l.profile_basis}<div class="tiny muted">Profile: {l.profile_basis}</div>{/if}
												{#if l.support !== 'not_applicable'}
													<div class="tiny muted">Added content: {l.support === 'transcript' ? 'supported by the transcript' : "the professional's own knowledge"}</div>
												{/if}
												{#if l.evidence.length}<div class="tiny muted mono">{l.evidence.map(lineRef).join(', ')}</div>{/if}
												<div class="tiny muted">{l.source === 'code' ? 'Labelled by a rule' : 'Labelled by the model'}</div>
											</details>
										</li>
									{/each}
								</ul>
							{/if}
						</div>
					{/each}
				</section>
			{/if}
		{/each}
	{/if}
</div>

<style>
	.page {
		max-width: 1100px;
	}

	.top {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 1rem;
		flex-wrap: wrap;
	}

	.top p,
	h3,
	h4 {
		margin: 0;
	}

	.counts {
		display: flex;
		gap: 0.5rem;
		flex-wrap: wrap;
	}

	.status {
		display: inline-block;
		font-size: 0.68rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.02em;
		padding: 0.05rem 0.4rem;
		border-radius: 4px;
		background: var(--surface-2);
		color: var(--muted);
		margin-right: 0.35rem;
	}

	.status.changed,
	.status.moved {
		background: var(--warn-bg);
		color: var(--warn-fg);
	}

	.status.added {
		background: var(--ok-bg);
		color: var(--ok-fg);
	}

	.status.removed {
		background: var(--err-bg);
		color: var(--err-fg);
	}

	.findings ul {
		margin: 0.3rem 0 0;
		padding-left: 1.1rem;
		display: flex;
		flex-direction: column;
		gap: 0.45rem;
	}

	.route {
		border-left: 3px solid var(--border);
		padding-left: 0.75rem;
	}

	.route.candidate {
		border-color: var(--accent);
	}

	.route.defect {
		border-color: var(--warn);
	}

	.count {
		font-weight: 600;
		color: var(--accent);
		margin: 0 0.3rem;
	}

	.toggle {
		display: flex;
		gap: 0.4rem;
		align-items: center;
	}

	.item {
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}

	.grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 0.25rem 1rem;
		padding: 0.5rem 0;
		border-top: 1px solid var(--border);
	}

	.grid.head {
		border-top: none;
		padding: 0;
	}

	.cell p {
		margin: 0.2rem 0 0;
		line-height: 1.5;
	}

	del {
		background: var(--err-bg);
		color: var(--err-fg);
	}

	ins {
		background: var(--ok-bg);
		color: var(--ok-fg);
		text-decoration: none;
	}

	.comment {
		margin-top: 0.3rem;
		color: var(--text-2);
	}

	.labels {
		grid-column: 1 / -1;
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}

	.label {
		border-left: 3px solid var(--border);
		padding: 0.2rem 0.6rem;
		background: var(--surface-2);
		border-radius: 0 4px 4px 0;
		font-size: 0.8rem;
	}

	.label.candidate {
		border-color: var(--accent);
	}

	.label.defect {
		border-color: var(--warn);
	}

	.label summary {
		cursor: pointer;
		font-weight: 600;
	}

	.answer {
		border-left: 3px solid var(--accent);
		padding-left: 0.6rem;
	}
</style>

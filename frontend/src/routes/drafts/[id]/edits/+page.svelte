<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { invalidate } from '$app/navigation';
	import {
		api,
		errorText,
		plural,
		type AmendmentProposal,
		type ChangeStatus,
		type CommentThread,
		type DiffSegment,
		type EditRoute,
		type ParagraphChange,
		type ProposalStatus
	} from '#lib/api.ts';
	import FileDrop from '#lib/components/FileDrop.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	let run = $derived(data.run);
	let edited = $derived(data.edited);
	let comparison = $derived(edited?.comparison);

	let files = $state<File[]>([]);
	let uploading = $state(false);
	let uploadError = $state('');
	let showUnchanged = $state(false);
	let allOpen = $state(false);
	let openItems = $state<Record<string, boolean>>({});
	let requesting = $state(false);
	let actionError = $state('');
	let busy = $state<string | null>(null);
	let applying = $state(false);
	let editing = $state<string | null>(null);
	let wording = $state('');

	const EDITS: ChangeStatus[] = ['changed', 'added', 'removed', 'moved'];
	const ROUTE_LABEL: Record<EditRoute, string> = {
		candidate_rule: 'Possible rule change',
		draft_mistake: 'Draft mistake',
		meeting_only: 'This meeting only'
	};

	const editCount = (counts: Partial<Record<ChangeStatus, number>> | undefined) =>
		EDITS.reduce((n, s) => n + (counts?.[s] ?? 0), 0);

	const questions = $derived(new Map((run.draft?.questions ?? []).map((q, i) => [q.question_id, { n: i + 1, text: q.question }])));
	const threads = $derived(new Map((comparison?.comments ?? []).map((t) => [t.comment_id, t])));
	const headings = $derived(new Map((comparison?.sections ?? []).map((s) => [s.section, s.heading])));
	const comments = $derived((comparison?.comments ?? []).filter((t) => !t.question_id || t.replies.length));
	const edits = $derived(editCount(comparison?.counts));
	const sections = $derived(
		(comparison?.sections ?? []).map((s) => ({
			...s,
			edits: editCount(s.counts),
			shown: s.changes.filter((c) => showUnchanged || c.status !== 'unchanged')
		}))
	);

	const classification = $derived(edited?.classification ?? null);
	const status = $derived(edited?.classification_status ?? null);
	const explaining = $derived(status === 'pending' || status === 'running');
	const labels = $derived(new Map((classification?.changes ?? []).map((c) => [c.change_id, c])));
	const set = $derived(edited?.amendments ?? null);
	const writing = $derived(!explaining && (set?.status === 'pending' || set?.status === 'running'));
	const working = $derived(explaining || writing);
	const applied = $derived(set?.applied_version != null);
	const proposals = $derived(set?.status === 'completed' ? set.proposals : []);
	const acceptedCount = $derived(proposals.filter((p) => p.status === 'accepted').length);
	const OUTCOME: Record<ProposalStatus, string> = {
		accepted: 'Added',
		rejected: 'Rejected',
		deferred: 'Not added',
		proposed: 'Not added'
	};
	const pills = $derived.by(() => {
		if (!classification) return [];
		const n = (route: EditRoute) => classification.changes.filter((c) => c.route === route).length;
		return [
			{ count: n('candidate_rule'), label: n('candidate_rule') === 1 ? 'suggests a rule change' : 'suggest rule changes', tone: 'rule' },
			{ count: n('draft_mistake'), label: n('draft_mistake') === 1 ? 'draft mistake' : 'draft mistakes', tone: 'mistake' },
			{ count: n('meeting_only'), label: 'this meeting only', tone: '' },
			{ count: classification.unclassified.length, label: 'not read', tone: '' }
		].filter((p) => p.count);
	});

	onMount(() => {
		// The edits are explained in the background; refresh until that settles.
		const timer = window.setInterval(async () => {
			if (!working) return;
			await invalidate('app:edits');
			if (!working) await invalidate('app:run');
		}, 3000);
		return () => window.clearInterval(timer);
	});

	async function explain() {
		requesting = true;
		uploadError = '';
		try {
			await api.classifyEdits(run.id);
			await invalidate('app:edits');
		} catch (e) {
			uploadError = errorText(e);
		} finally {
			requesting = false;
		}
	}

	const decidable = (p: AmendmentProposal) => !applied && !p.refused && p.overlap !== 'duplicate';

	async function act(id: string, work: () => Promise<unknown>) {
		busy = id;
		actionError = '';
		try {
			await work();
			await invalidate('app:edits');
		} catch (e) {
			actionError = errorText(e);
		} finally {
			busy = null;
		}
	}

	function decide(p: AmendmentProposal, choice: ProposalStatus) {
		const next = p.status === choice ? 'proposed' : choice;
		return act(p.id, () => api.updateAmendment(run.id, p.id, { status: next }));
	}

	async function saveWording(p: AmendmentProposal) {
		await act(p.id, () => api.updateAmendment(run.id, p.id, { text: wording }));
		if (!actionError) editing = null;
	}

	async function applyAll() {
		applying = true;
		await act('apply', () => api.applyAmendments(run.id));
		applying = false;
	}

	async function jump(changeIds: string[]) {
		const wanted = new Set(changeIds);
		allOpen = true;
		for (const s of comparison?.sections ?? []) {
			for (const c of s.changes) {
				if (!wanted.has(c.change_id)) continue;
				openItems[s.section] = true;
				if (c.status === 'unchanged') showUnchanged = true;
			}
		}
		await tick();
		document.getElementById(`change-${changeIds[0]}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
	}

	async function upload(file: File | undefined) {
		if (!file) return;
		uploading = true;
		uploadError = '';
		try {
			await api.uploadEdited(run.id, file);
			files = [];
			await Promise.all([invalidate('app:run'), invalidate('app:edits')]);
		} catch (e) {
			uploadError = errorText(e);
		} finally {
			uploading = false;
		}
	}

	function note(c: ParagraphChange): string {
		const parts: string[] = [];
		if (c.heading) parts.push('Heading');
		if (c.status === 'added') parts.push('New paragraph');
		if (c.status === 'removed') parts.push('Removed');
		if (c.status === 'moved') {
			parts.push(c.from_section ? `Moved from ${headings.get(c.from_section) ?? `item ${c.from_section}`}` : 'Moved within this item');
		}
		if (c.format_only) parts.push('Only the formatting changed');
		return parts.join(', ');
	}
</script>

{#snippet text(segments: DiffSegment[])}
	{#each segments as d, i (i)}{#if i}{' '}{/if}{#if d.op === 'equal'}{d.text}{:else if d.op === 'insert'}<ins>{d.text}</ins>{:else}<del>{d.text}</del>{/if}{/each}
{/snippet}

{#snippet thread(t: CommentThread)}
	{@const q = t.question_id ? questions.get(t.question_id) : null}
	<div class="thread">
		<p class="tiny muted">
			<Icon name="message" size={12} />
			{#if q}Question {q.n}{:else}Comment from {t.author ?? 'unknown'}{/if}
		</p>
		<p class="small">{q ? q.text : t.text}</p>
		{#each t.replies as r (r.comment_id)}
			<p class="small reply"><strong>{r.author ?? 'Reply'}:</strong> {r.text}</p>
		{/each}
	</div>
{/snippet}

{#if !edited}
	<section class="card stack intro">
		<div class="stack tight">
			<h2>Upload the edited minutes</h2>
			<p class="small muted">
				Download the draft from the Minutes step, edit it in Word as you normally would and upload
				the file here.
			</p>
		</div>
		<FileDrop label="Edited minutes" description="Drop the .docx here or" accept=".docx" bind:files disabled={uploading} />
		{#if uploadError}<p class="alert error small">{uploadError}</p>{/if}
		<div class="row">
			<button class="btn primary" onclick={() => upload(files[0])} disabled={!files.length || uploading}>
				{#if uploading}<span class="spinner"></span>{:else}<Icon name="upload" size={14} />{/if}
				Upload
			</button>
			<a class="btn ghost" href="/drafts/{run.id}/minutes">Back to the minutes</a>
		</div>
	</section>
{:else if comparison}
	<section class="card summary">
		<div class="row tight">
			<span class="chip">{edits ? plural(edits, 'edit') : 'No edits'}</span>
			{#each pills as p (p.label)}<span class="chip {p.tone}">{p.count} {p.label}</span>{/each}
		</div>

		{#if working}
			<p class="small muted row tight">
				<span class="spinner"></span>
				{explaining ? 'Reading your edits against the Minutes Profile.' : 'Writing the rule changes.'}
			</p>
		{:else if edits && !applied && (status !== 'completed' || !set || set.status === 'failed')}
			<div class="row tight">
				<p class="small muted grow" title={edited.classification_error ?? set?.error ?? ''}>
					{status === 'failed'
						? 'Some edits could not be read.'
						: set?.status === 'failed'
							? 'The rule changes could not be written.'
							: 'Find out which edits should change your rules.'}
				</p>
				<button class="btn sm" onclick={explain} disabled={requesting}>
					{#if requesting}<span class="spinner"></span>{:else}<Icon name="refresh" size={14} />{/if}
					{status === 'failed' || set?.status === 'failed' ? 'Try again' : 'Read the edits'}
				</button>
			</div>
		{/if}
		{#if uploadError || actionError}<p class="alert error small">{uploadError || actionError}</p>{/if}

		{#if proposals.length}
			<div class="stack">
				<h2>Rule changes</h2>
				<ul class="rules">
					{#each proposals as p (p.id)}
						{@const quiet = !!p.refused || p.overlap === 'duplicate' || p.status === 'rejected'}
						{@const why = labels.get(p.change_ids[0])?.reason}
						<li class:quiet class:accepted={p.status === 'accepted'}>
							<div class="rule-head">
								<strong class="grow">{p.dimension_title}</strong>
								{#if p.refused}
									<span class="tag" title={p.refused}>Fixed rule</span>
								{:else if p.overlap === 'duplicate'}
									<span class="tag">Already a rule</span>
								{:else if applied}
									<span class="tag" class:on={p.status === 'accepted'}>{OUTCOME[p.status]}</span>
								{:else}
									<div class="choice" role="group" aria-label="Decision">
										<button class:on={p.status === 'accepted'} disabled={busy !== null} onclick={() => decide(p, 'accepted')}>
											<Icon name="check" size={13} /> Accept
										</button>
										<button class:on={p.status === 'rejected'} disabled={busy !== null} onclick={() => decide(p, 'rejected')}>
											<Icon name="x" size={13} /> Reject
										</button>
									</div>
								{/if}
							</div>
							{#if why}<p class="small muted">{why}</p>{/if}
							{#if !p.refused && p.overlap !== 'duplicate'}
								{#if editing === p.id}
									<textarea class="wording" rows="3" bind:value={wording}></textarea>
									<div class="row tight">
										<button class="btn sm primary" disabled={busy !== null || !wording.trim()} onclick={() => saveWording(p)}>Save</button>
										<button class="btn sm ghost" onclick={() => (editing = null)}>Cancel</button>
									</div>
								{:else if p.operation === 'remove'}
									<p class="small"><del>{p.current_text}</del></p>
								{:else}
									{#if p.operation === 'replace' && p.current_text}<p class="small muted"><del>{p.current_text}</del></p>{/if}
									<p class="small">{p.text}</p>
								{/if}
							{/if}
							<p class="links">
								<button class="link-btn tiny" onclick={() => jump(p.change_ids)}>
									{p.change_ids.length > 1 ? `See the ${p.change_ids.length} edits` : 'See the edit'}
								</button>
								{#if decidable(p) && p.operation !== 'remove' && editing !== p.id}
									<button class="link-btn tiny" onclick={() => ((editing = p.id), (wording = p.text ?? ''))}>Change the wording</button>
								{/if}
							</p>
						</li>
					{/each}
				</ul>
				{#if applied}
					<div class="alert ok done">
						<Icon name="check" size={16} />
						<span class="grow">Profile updated. New meetings will use v{set?.applied_version}.</span>
						<a class="btn primary" href="/profiles/{set?.profile_slug}">View the profile</a>
					</div>
				{:else}
					<div class="row end">
						<button class="btn primary" disabled={!acceptedCount || applying || busy !== null} onclick={applyAll}>
							{#if applying}<span class="spinner"></span>{/if}
							Update the profile
						</button>
					</div>
				{/if}
			</div>
		{:else if set?.status === 'completed'}
			<p class="small muted">Your edits do not suggest any rule changes.</p>
		{/if}
	</section>

	<details class="panel" bind:open={allOpen}>
		<summary class="panel-head">
			<h3>All changes, item by item</h3>
			<span class="count">{plural(edits, 'edit')}</span>
			<Icon name="chevronDown" size={14} />
		</summary>
		<div class="panel-body">
			<label class="small toggle">
				<input type="checkbox" bind:checked={showUnchanged} /> Show unchanged paragraphs
			</label>
			{#each sections as s (s.section)}
				<details class="item" bind:open={openItems[s.section]}>
					<summary>
						<Icon name="chevronRight" size={14} />
						<span class="grow">{s.heading}</span>
						<span class="count">{s.edits ? plural(s.edits, 'edit') : 'No edits'}</span>
					</summary>
					<div class="item-body">
						{#each s.shown as c, i (i)}
							{@const k = labels.get(c.change_id)}
							{@const n = note(c)}
							<article class="change status-{c.status}" id="change-{c.change_id}">
								{#if n}<p class="tiny muted">{n}</p>{/if}
								<p class="minute" class:muted={c.status === 'unchanged'}>
									{#if c.status === 'added'}<ins>{c.edited}</ins>
									{:else if c.status === 'removed'}<del>{c.original}</del>
									{:else if c.status === 'unchanged' || !c.diff.length}{c.edited}
									{:else}{@render text(c.diff)}{/if}
								</p>
								{#if k}
									<p class="why tiny"><span class="tag route-{k.route}">{ROUTE_LABEL[k.route]}</span> {k.reason}</p>
								{/if}
								{#each c.comment_ids as id (id)}
									{@const t = threads.get(id)}
									{#if t && (t.replies.length || !t.question_id)}{@render thread(t)}{/if}
								{/each}
							</article>
						{:else}
							<p class="small muted">No edits in this item.</p>
						{/each}
					</div>
				</details>
			{/each}
			{#if comments.length}
				<details class="item">
					<summary>
						<Icon name="chevronRight" size={14} />
						<span class="grow">Comments in your file</span>
						<span class="count">{comments.length}</span>
					</summary>
					<div class="item-body">
						{#each comments as t (t.comment_id)}{@render thread(t)}{/each}
					</div>
				</details>
			{/if}
		</div>
	</details>
{/if}

<style>
	.intro {
		max-width: 640px;
	}

	.summary {
		display: flex;
		flex-direction: column;
		gap: 1.1rem;
	}

	.grow {
		flex: 1;
		min-width: 0;
	}

	.row.tight {
		gap: 0.4rem;
	}

	.chip.rule {
		background: var(--accent-soft);
		color: var(--accent);
	}

	.chip.mistake {
		background: var(--warn-bg);
		color: var(--warn-fg);
	}

	.rules {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 1.1rem;
	}

	.rules li {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		padding-left: 0.85rem;
		border-left: 3px solid var(--border-strong);
	}

	.rules li.accepted {
		border-left-color: var(--accent);
	}

	.rules li.quiet {
		opacity: 0.6;
	}

	.rule-head {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		flex-wrap: wrap;
	}

	.wording {
		width: 100%;
		font: inherit;
		padding: 0.5rem 0.6rem;
		border: 1px solid var(--border-strong);
		border-radius: var(--radius-sm);
		background: var(--surface);
		color: var(--text);
		resize: vertical;
	}

	.choice {
		display: inline-flex;
		border: 1px solid var(--border-strong);
		border-radius: 999px;
		overflow: hidden;
	}

	.choice button {
		display: inline-flex;
		align-items: center;
		gap: 0.25rem;
		padding: 0.2rem 0.7rem;
		font: inherit;
		font-size: 0.8rem;
		background: var(--surface);
		color: var(--text-2);
		border: 0;
		cursor: pointer;
	}

	.choice button + button {
		border-left: 1px solid var(--border-strong);
	}

	.choice button.on {
		background: var(--accent);
		color: var(--surface);
	}

	.choice button:last-child.on {
		background: var(--text-2);
	}

	.choice button:disabled {
		cursor: default;
	}

	.links {
		display: flex;
		gap: 1rem;
	}

	.row.end {
		justify-content: flex-end;
	}

	.done {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		flex-wrap: wrap;
	}

	.tag.on {
		background: var(--accent-soft);
		color: var(--accent);
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

	details.panel[open] > .panel-head :global(svg) {
		transform: rotate(180deg);
	}

	.panel-body {
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
		padding: 0 0.9rem 0.9rem;
	}

	.count {
		font-size: 0.74rem;
		color: var(--muted);
		white-space: nowrap;
	}

	.toggle {
		align-self: flex-end;
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		color: var(--text-2);
		cursor: pointer;
	}

	details.item {
		border: 1px solid var(--border);
		border-radius: var(--radius-sm);
	}

	details.item > summary {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.6rem 0.75rem;
		font-size: 0.9rem;
		font-weight: 500;
	}

	details.item > summary :global(svg) {
		flex-shrink: 0;
		color: var(--muted);
		transition: transform 0.15s;
	}

	details.item[open] > summary :global(svg) {
		transform: rotate(90deg);
	}

	.item-body {
		display: flex;
		flex-direction: column;
		gap: 0.9rem;
		padding: 0.2rem 0.75rem 0.9rem 2rem;
	}

	.change {
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
		padding-left: 0.75rem;
		border-left: 3px solid var(--border-strong);
	}

	.change.status-changed {
		border-left-color: var(--accent);
	}

	.change.status-added {
		border-left-color: var(--ok);
	}

	.change.status-removed {
		border-left-color: var(--err);
	}

	.change.status-moved {
		border-left-color: var(--warn);
	}

	.minute {
		font-family: var(--serif);
		font-size: 0.98rem;
		line-height: 1.55;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}

	ins {
		background: var(--ok-bg);
		color: var(--ok-fg);
		text-decoration: none;
		border-radius: 3px;
		padding: 0 0.1rem;
	}

	del {
		background: var(--err-bg);
		color: var(--err-fg);
		border-radius: 3px;
		padding: 0 0.1rem;
	}

	.why {
		color: var(--text-2);
	}

	.tag {
		display: inline-block;
		font-size: 0.74rem;
		margin-right: 0.3rem;
		padding: 0.05rem 0.45rem;
		border-radius: 999px;
		background: var(--surface-2);
		font-weight: 500;
	}

	.tag.route-candidate_rule {
		background: var(--accent-soft);
		color: var(--accent);
	}

	.tag.route-draft_mistake {
		background: var(--warn-bg);
		color: var(--warn-fg);
	}

	.thread {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		padding: 0.5rem 0.7rem;
		border-left: 2px solid var(--mark);
		background: var(--mark-soft);
		border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
	}

	.thread p:first-child {
		display: flex;
		align-items: center;
		gap: 0.35rem;
	}

	.reply {
		padding-left: 0.6rem;
	}
</style>

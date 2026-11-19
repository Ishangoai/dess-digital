<script lang="ts">
	import { invalidate } from '$app/navigation';
	import {
		api,
		errorText,
		formatDay,
		plural,
		type ChangeStatus,
		type CommentThread,
		type DiffSegment,
		type ParagraphChange
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
	let replaceInput = $state<HTMLInputElement>();

	const LABELS: Record<ChangeStatus, string> = {
		changed: 'Changed',
		added: 'Added',
		removed: 'Removed',
		moved: 'Moved',
		unchanged: 'Unchanged'
	};
	const ORDER: ChangeStatus[] = ['changed', 'added', 'removed', 'moved', 'unchanged'];

	const questions = $derived(new Map((run.draft?.questions ?? []).map((q, i) => [q.question_id, { n: i + 1, text: q.question }])));
	const threads = $derived(new Map((comparison?.comments ?? []).map((t) => [t.comment_id, t])));
	const headings = $derived(new Map((comparison?.sections ?? []).map((s) => [s.section, s.heading])));
	const answered = $derived((comparison?.comments ?? []).filter((t) => t.question_id && t.replies.length));
	const otherComments = $derived((comparison?.comments ?? []).filter((t) => !t.question_id));
	const edits = $derived(ORDER.slice(0, 4).reduce((n, s) => n + (comparison?.counts[s] ?? 0), 0));
	const sections = $derived(
		(comparison?.sections ?? [])
			.map((s) => ({ ...s, shown: s.changes.filter((c) => showUnchanged || c.status !== 'unchanged') }))
			.filter((s) => s.shown.length)
	);

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
			if (replaceInput) replaceInput.value = '';
		}
	}

	function trackedSummary(c: ParagraphChange): string {
		const counts = new Map<string, number>();
		for (const t of c.tracked_changes) counts.set(t.kind, (counts.get(t.kind) ?? 0) + 1);
		const words: Record<string, string> = {
			insertion: 'insertion',
			deletion: 'deletion',
			move_from: 'move',
			move_to: 'move',
			formatting: 'formatting change'
		};
		const authors = [...new Set(c.tracked_changes.map((t) => t.author).filter(Boolean))];
		const parts = [...counts].map(([k, n]) => plural(n, words[k]));
		return `Tracked: ${parts.join(', ')}${authors.length ? ` by ${authors.join(', ')}` : ''}`;
	}

	function movedNote(c: ParagraphChange): string {
		if (!c.from_section) return 'Moved within this item';
		return `Moved from ${headings.get(c.from_section) ?? `item ${c.from_section}`}`;
	}

	function side(diff: DiffSegment[], keep: 'insert' | 'delete'): DiffSegment[] {
		return diff.filter((d) => d.op === 'equal' || d.op === keep);
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
			{#if t.resolved}<span class="chip tiny">Resolved</span>{/if}
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
				Download the draft from the Minutes step, edit it in Word as you normally would (with Track
				Changes on or off) and upload the file here. You will see what changed, item by item.
			</p>
		</div>
		<FileDrop label="Edited minutes" description="Drop the .docx here or" accept=".docx" bind:files disabled={uploading} />
		{#if uploadError}<p class="alert error small">{uploadError}</p>{/if}
		<div class="row">
			<button class="btn primary" onclick={() => upload(files[0])} disabled={!files.length || uploading}>
				{#if uploading}<span class="spinner"></span>{:else}<Icon name="upload" size={14} />{/if}
				Compare with the draft
			</button>
			<a class="btn ghost" href="/drafts/{run.id}/minutes">Back to the minutes</a>
		</div>
	</section>
{:else if comparison}
	<section class="card summary">
		<div class="row">
			<div class="stack tight grow">
				<h2>{edits ? `${plural(edits, 'edit')} to the draft` : 'No changes to the wording'}</h2>
				<p class="tiny muted">
					{edited.filename}, uploaded {formatDay(edited.uploaded_at)}. Compared with the draft
					downloaded {formatDay(edited.exported_at)}{edited.export_used_template ? ' (with your template)' : ''}.
				</p>
			</div>
			<button class="btn sm" onclick={() => replaceInput?.click()} disabled={uploading}>
				{#if uploading}<span class="spinner"></span>{:else}<Icon name="upload" size={14} />{/if}
				Upload a newer version
			</button>
			<input bind:this={replaceInput} type="file" accept=".docx" hidden onchange={(e) => upload(e.currentTarget.files?.[0])} />
		</div>
		<div class="row tight">
			{#each ORDER as s (s)}
				{#if comparison.counts[s]}
					<span class="chip status-{s}">{comparison.counts[s]} {LABELS[s].toLowerCase()}</span>
				{/if}
			{/each}
			<span class="spacer"></span>
			<label class="small toggle">
				<input type="checkbox" bind:checked={showUnchanged} /> Show unchanged paragraphs
			</label>
		</div>
		{#if comparison.bookmarks_expected && comparison.bookmarks_found === 0}
			<p class="alert info small">
				This file has no paragraph markers (it was probably downloaded before they were added), so
				paragraphs were matched by their wording.
			</p>
		{:else if comparison.bookmarks_found < comparison.bookmarks_expected}
			<p class="tiny muted">
				{comparison.bookmarks_found} of {comparison.bookmarks_expected} paragraphs kept their marker; the
				rest were matched by wording.
			</p>
		{/if}
		{#if uploadError}<p class="alert error small">{uploadError}</p>{/if}
	</section>

	{#if answered.length || otherComments.length}
		<section class="card stack tight">
			<h3>Comments in the edited file</h3>
			{#each [...answered, ...otherComments] as t (t.comment_id)}{@render thread(t)}{/each}
		</section>
	{/if}

	{#if !sections.length}
		<p class="card small muted">Every paragraph matches the draft.</p>
	{/if}

	{#each sections as s (s.section)}
		<section class="item">
			<header class="item-head">
				<h2>{s.heading}</h2>
				<span class="tiny muted">
					{ORDER.filter((k) => k !== 'unchanged' && s.counts[k]).map((k) => `${s.counts[k]} ${LABELS[k].toLowerCase()}`).join(', ') || 'no changes'}
				</span>
			</header>
			{#each s.shown as c, i (i)}
				<article class="change status-{c.status}">
					<div class="change-meta row tight">
						<span class="chip status-{c.status}">{c.heading ? `Heading ${LABELS[c.status].toLowerCase()}` : LABELS[c.status]}</span>
						{#if c.status === 'moved'}<span class="tiny muted">{movedNote(c)}{c.text_changed ? ', and reworded' : ''}</span>{/if}
						{#if c.format_only}<span class="tiny muted">Only spacing or formatting changed</span>{/if}
						{#if c.matched_by === 'text' && c.status !== 'added' && c.status !== 'removed'}
							<span class="tiny muted" title="Similarity {Math.round((c.similarity ?? 0) * 100)}%">Matched by wording</span>
						{/if}
					</div>
					{#if c.status === 'unchanged'}
						<p class="minute muted">{c.edited}</p>
					{:else}
						<div class="sides">
							<div class="side">
								<span class="eyebrow">Draft</span>
								{#if c.original === null}
									<p class="small muted">Not in the draft</p>
								{:else if c.status === 'removed'}
									<p class="minute"><del>{c.original}</del></p>
								{:else}
									<p class="minute">{@render text(side(c.diff, 'delete'))}</p>
								{/if}
							</div>
							<div class="side">
								<span class="eyebrow">Edited</span>
								{#if c.edited === null}
									<p class="small muted">Removed</p>
								{:else if c.status === 'added'}
									<p class="minute"><ins>{c.edited}</ins></p>
								{:else}
									<p class="minute">{@render text(side(c.diff, 'insert'))}</p>
								{/if}
							</div>
						</div>
					{/if}
					{#if c.tracked_changes.length}<p class="tiny muted">{trackedSummary(c)}</p>{/if}
					{#each c.comment_ids as id (id)}
						{@const t = threads.get(id)}
						{#if t && (t.replies.length || !t.question_id)}{@render thread(t)}{/if}
					{/each}
				</article>
			{/each}
		</section>
	{/each}
{/if}

<style>
	.intro {
		max-width: 640px;
	}

	.summary {
		display: flex;
		flex-direction: column;
		gap: 0.8rem;
	}

	.grow {
		flex: 1;
		min-width: 240px;
	}

	.row.tight {
		gap: 0.4rem;
	}

	.toggle {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		color: var(--text-2);
		cursor: pointer;
	}

	.item {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
	}

	.item-head {
		display: flex;
		align-items: baseline;
		gap: 0.75rem;
		flex-wrap: wrap;
		padding-top: 0.5rem;
	}

	.change {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
		padding: 0.9rem 1rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-left: 3px solid var(--border-strong);
		border-radius: var(--radius-sm);
		box-shadow: var(--shadow-sm);
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

	.chip.status-changed {
		background: var(--accent-soft);
		color: var(--accent);
	}

	.chip.status-added {
		background: var(--ok-bg);
		color: var(--ok-fg);
	}

	.chip.status-removed {
		background: var(--err-bg);
		color: var(--err-fg);
	}

	.chip.status-moved {
		background: var(--warn-bg);
		color: var(--warn-fg);
	}

	.sides {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1rem;
	}

	.side {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		min-width: 0;
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

	@media (max-width: 760px) {
		.sides {
			grid-template-columns: 1fr;
		}
	}
</style>

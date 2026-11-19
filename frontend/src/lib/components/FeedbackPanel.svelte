<script lang="ts">
	import { invalidate } from '$app/navigation';
	import { api, errorText, formatDate, plural, type Feedback, type Verdict } from '#lib/api.ts';
	import Icon from '#lib/components/Icon.svelte';

	let { runId, votes }: { runId: string; votes: Feedback[] } = $props();

	let revising = $state(false);
	let reason = $state('');
	let busy = $state(false);
	let error = $state('');
	let fileInput = $state<HTMLInputElement>();

	const latest = $derived(votes.at(-1));
	const count = (v: Verdict) => votes.filter((f) => f.verdict === v).length;
	const percent = (n: number) => `${Math.round(n * 100)}%`;
	const LABELS: Record<Verdict, string> = {
		approved: 'Approved',
		revision_requested: 'Revision requested',
		edited: 'Edited copy uploaded'
	};

	async function run(action: () => Promise<unknown>) {
		busy = true;
		error = '';
		try {
			await action();
			revising = false;
			reason = '';
			await invalidate('app:feedback'); // reload the feedback
		} catch (e) {
			error = errorText(e);
		} finally {
			busy = false;
		}
	}

	const send = (verdict: Verdict) => run(() => api.addFeedback(runId, verdict, reason));

	function upload(file: File | undefined) {
		if (!file) return;
		run(() => api.uploadFinal(runId, file)).then(() => {
			if (fileInput) fileInput.value = '';
		});
	}
</script>

<section class="panel" aria-label="Review">
	<header class="panel-head">
		<Icon name="check" size={15} />
		<h3>Review</h3>
		{#if votes.length}
			<span class="count">
				{plural(count('approved'), 'approval')} · {plural(count('revision_requested'), 'revision')}
				{#if count('edited')} · {plural(count('edited'), 'edit')}{/if}
			</span>
		{/if}
	</header>

	<div class="body">
		{#if latest}
			<div class="small latest {latest.verdict}">
				<strong>{LABELS[latest.verdict]}</strong>
				<span class="tiny muted">{formatDate(latest.created_at)}</span>
				{#if latest.reason}<span class="reason">{latest.reason}</span>{/if}
				{#if latest.comparison}
					{@const changed = latest.comparison.items.filter((i) => i.status !== 'unchanged')}
					<span class="reason">
						{percent(latest.comparison.similarity)} of the draft kept{changed.length
							? `; ${plural(changed.length, 'part')} changed:`
							: ', nothing changed.'}
					</span>
					{#if changed.length}
						<ul class="changes">
							{#each changed as item (item.item_ref)}
								<li>
									<span class="status {item.status}">{item.status}</span>
									{item.heading}
									{#if item.status === 'edited' || item.status === 'rewritten'}
										<span class="tiny muted">+{item.words_added} / -{item.words_removed} words</span>
									{/if}
								</li>
							{/each}
						</ul>
					{/if}
					{#if latest.edited_document_id}
						<a class="reason small" href="/drafts/{runId}/edits?e={latest.edited_document_id}">
							Review the changes paragraph by paragraph
						</a>
					{/if}
				{/if}
			</div>
		{:else}
			<p class="small muted">
				Is this draft good enough? Approve it, ask for a revision, or edit the Word file and upload
				your final copy so the system can learn from your changes.
			</p>
		{/if}

		{#if revising}
			<label class="field">
				What needs revising?
				<textarea rows="3" bind:value={reason} placeholder="e.g. Item 4 leaves out the dissent"></textarea>
			</label>
			<div class="row">
				<button class="btn sm primary" onclick={() => send('revision_requested')} disabled={busy || !reason.trim()}>
					Send
				</button>
				<button class="btn sm ghost" onclick={() => (revising = false)} disabled={busy}>Cancel</button>
			</div>
		{:else}
			<div class="row">
				<button class="btn sm primary" onclick={() => send('approved')} disabled={busy}>
					<Icon name="check" size={14} /> Approve
				</button>
				<button class="btn sm" onclick={() => (revising = true)} disabled={busy}>
					<Icon name="pencil" size={14} /> Request revision
				</button>
			</div>
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
		{/if}

		{#if error}<p class="alert error small">{error}</p>{/if}
	</div>
</section>

<style>
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
		border-bottom: 1px solid var(--border);
	}

	.panel-head h3 {
		flex: 1;
	}

	.count {
		font-size: 0.74rem;
		color: var(--muted);
	}

	.body {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
		padding: 0.8rem 0.9rem;
	}

	.latest {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 0.25rem 0.5rem;
		margin: 0;
	}

	.latest strong {
		color: var(--accent);
	}

	.latest.approved strong {
		color: var(--ok);
	}

	.latest.revision_requested strong {
		color: var(--err);
	}

	.reason,
	.changes {
		flex-basis: 100%;
	}

	.changes {
		margin: 0;
		padding-left: 1rem;
	}

	.status {
		font-size: 0.7rem;
		font-weight: 600;
		text-transform: uppercase;
		color: var(--muted);
	}

	.status.deleted,
	.status.rewritten {
		color: var(--err);
	}

	.row button {
		margin: 0;
	}
</style>

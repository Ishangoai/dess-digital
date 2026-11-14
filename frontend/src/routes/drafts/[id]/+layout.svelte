<script lang="ts">
	import { onMount } from 'svelte';
	import { invalidate } from '$app/navigation';
	import { api, draftsChanged, errorText, formatDay, isRunning, SOURCE_ROLES } from '#lib/api.ts';
	import Icon from '#lib/components/Icon.svelte';
	import StatusBadge from '#lib/components/StatusBadge.svelte';
	import Working from '#lib/components/Working.svelte';
	import type { LayoutProps } from './$types';

	let { data, children }: LayoutProps = $props();
	let run = $derived(data.run);

	let retrying = $state(false);
	let retryError = $state('');

	// 0: reading evidence, 1: checking the mapping, 2: drafting, 3: done
	const stage = $derived(
		run.status === 'completed'
			? 3
			: run.status === 'drafting' || (run.status === 'failed' && run.error_stage !== 'evidence')
				? 2
				: run.mapping
					? 1
					: 0
	);
	const failed = $derived(run.status === 'failed' || run.status === 'blocked');
	const STEPS = ['Read the evidence', 'Check the mapping', 'Draft the minutes'];

	const meta = $derived(
		[run.meeting_info.meeting_date, run.meeting_info.meeting_type].filter(Boolean).join(' · ')
	);

	onMount(() => {
		// A stage may be running in another tab or request; refresh until it settles.
		let wasRunning = isRunning(run.status);
		const timer = window.setInterval(async () => {
			if (!isRunning(run.status)) return;
			await invalidate('app:run');
			if (wasRunning && !isRunning(run.status)) draftsChanged();
			wasRunning = isRunning(run.status);
		}, 4000);
		return () => window.clearInterval(timer);
	});

	async function retryAnalysis() {
		retrying = true;
		retryError = '';
		try {
			await api.retryAnalysis(run.id);
			await invalidate('app:run');
			draftsChanged();
		} catch (e) {
			retryError = errorText(e);
		} finally {
			retrying = false;
		}
	}
</script>

<div class="page">
	<header class="head">
		<div class="title-row">
			<div class="title">
				<h1>{run.title}</h1>
				<p class="muted small">
					{meta ? `${meta} · ` : ''}Started {formatDay(run.created_at)}
				</p>
			</div>
			<StatusBadge status={run.status} />
		</div>

		<div class="files">
			{#each run.documents as doc (doc.source_id)}
				<span class="chip" title="{doc.line_count} lines">
					<Icon name="file" size={13} />
					<span class="role">{SOURCE_ROLES[doc.role] ?? doc.role}</span>
					<span class="fname">{doc.filename}</span>
				</span>
			{/each}
			<a class="chip profile" href="/profiles/{run.profile_slug}?v={run.profile_version}" title="Minutes profile">
				<Icon name="shield" size={13} />
				{run.profile_slug} v{run.profile_version}
			</a>
		</div>

		<ol class="progress" aria-label="Progress">
			{#each STEPS as label, i (label)}
				<li
					class:done={i < stage}
					class:current={i === stage && !failed}
					class:failed={i === stage && failed}
					aria-current={i === stage ? 'step' : undefined}
				>
					<span class="bar"></span>
					<span class="label">
						{#if i < stage}<Icon name="check" size={12} />{/if}
						{label}
					</span>
				</li>
			{/each}
		</ol>
	</header>

	{#if run.blocked_reasons.length}
		<div class="alert error stack tight">
			<strong>No draft can be produced from these files.</strong>
			<ul>
				{#each run.blocked_reasons as reason, i (i)}<li>{reason}</li>{/each}
			</ul>
			<div><a class="btn sm" href="/drafts/new">Start again with different files</a></div>
		</div>
	{/if}

	{#if run.error}
		<div class="alert error stack tight">
			<div><strong>Something went wrong while {run.error_stage === 'evidence' ? 'reading the evidence' : 'drafting'}.</strong></div>
			<div class="small">{run.error}</div>
			{#if run.status === 'failed' && run.error_stage === 'evidence'}
				<div class="row">
					<button class="btn sm" onclick={retryAnalysis} disabled={retrying}>
						{#if retrying}<span class="spinner"></span>{:else}<Icon name="refresh" size={14} />{/if}
						Try again
					</button>
				</div>
			{/if}
			{#if retryError}<div class="small">{retryError}</div>{/if}
		</div>
	{/if}

	{#if run.status === 'analysing'}
		<Working title="Reading the meeting" message="Working out which parts of the discussion belong to each agenda item." />
	{:else if run.status === 'drafting'}
		<Working
			icon="file"
			title="Drafting the minutes"
			message="Selecting what belongs in the record, writing it up and checking it against the evidence."
		/>
	{:else}
		{@render children()}
	{/if}
</div>

<style>
	.page {
		max-width: 1100px;
		margin: 0 auto;
		display: flex;
		flex-direction: column;
		gap: 1.25rem;
	}

	.head {
		display: flex;
		flex-direction: column;
		gap: 0.9rem;
	}

	.title-row {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 1rem;
	}

	.title {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
		min-width: 0;
	}

	.files {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
	}

	.chip {
		max-width: 100%;
		color: var(--muted);
	}

	.role {
		color: var(--text-2);
		font-weight: 600;
	}

	.fname {
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 26ch;
	}

	.profile:hover {
		text-decoration: none;
		border-color: var(--border-strong);
	}

	.progress {
		list-style: none;
		margin: 0.25rem 0 0;
		padding: 0;
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 0.5rem;
	}

	.progress li {
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}

	.bar {
		height: 4px;
		border-radius: 2px;
		background: var(--border);
	}

	.done .bar {
		background: var(--ok);
	}

	.current .bar {
		background: var(--accent);
	}

	.failed .bar {
		background: var(--err);
	}

	.label {
		display: flex;
		align-items: center;
		gap: 0.3rem;
		font-size: 0.76rem;
		color: var(--faint);
	}

	.done .label {
		color: var(--ok-fg);
	}

	.current .label {
		color: var(--text);
		font-weight: 600;
	}

	.failed .label {
		color: var(--err-fg);
		font-weight: 600;
	}

	ul {
		margin: 0;
		padding-left: 1.1rem;
	}
</style>

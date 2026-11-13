<script lang="ts">
	import { onMount } from 'svelte';
	import { invalidate } from '$app/navigation';
	import { page } from '$app/state';
	import { api, errorText, formatDate } from '#lib/api.ts';
	import StatusBadge from '#lib/components/StatusBadge.svelte';
	import Steps from '#lib/components/Steps.svelte';
	import type { LayoutProps } from './$types';

	let { data, children }: LayoutProps = $props();
	let run = $derived(data.run);

	let retrying = $state(false);
	let retryError = $state('');

	const current = $derived(
		page.url.pathname.endsWith('/minutes')
			? 'minutes'
			: page.url.pathname.endsWith('/mapping')
				? 'mapping'
				: run.draft
					? 'minutes'
					: 'mapping'
	);
	const title = $derived(
		[run.meeting_info.organisation, run.meeting_info.body_name].filter(Boolean).join(': ') ||
			'Untitled meeting'
	);

	onMount(() => {
		// Another tab or request may be running a stage; refresh until it settles.
		const timer = window.setInterval(() => {
			if (run.status === 'analysing' || run.status === 'drafting') invalidate('app:run');
		}, 5000);
		return () => window.clearInterval(timer);
	});

	async function retryAnalysis() {
		retrying = true;
		retryError = '';
		try {
			await api.retryAnalysis(run.id);
			await invalidate('app:run');
		} catch (e) {
			retryError = errorText(e);
		} finally {
			retrying = false;
		}
	}
</script>

<div class="stack">
	<Steps {current} {run} />

	<header class="card run-head">
		<div>
			<h1>{title}</h1>
			<p class="muted small">
				{#if run.meeting_info.meeting_date}{run.meeting_info.meeting_date}.{/if}
				Profile {run.profile_slug} v{run.profile_version}. Created {formatDate(run.created_at)}.
				<span class="mono">{run.id}</span>
			</p>
			<p class="muted small">
				{#each run.documents as doc, i (doc.source_id)}
					{i ? ', ' : ''}<strong>{doc.source_id}</strong> {doc.role}: {doc.filename} ({doc.line_count}
					lines)
				{/each}
			</p>
		</div>
		<StatusBadge status={run.status} />
	</header>

	{#if run.status === 'analysing' || run.status === 'drafting'}
		<p class="alert info">
			{run.status === 'analysing' ? 'Analysing the evidence' : 'Drafting the minutes'}. This page
			refreshes every few seconds.
		</p>
	{/if}

	{#if run.blocked_reasons.length}
		<div class="alert error">
			<strong>Blocked: no draft can be produced.</strong>
			<ul>
				{#each run.blocked_reasons as reason, i (i)}<li>{reason}</li>{/each}
			</ul>
			<a href="/drafts/new">Start a new draft with different files</a>
		</div>
	{/if}

	{#if run.error}
		<div class="alert error stack">
			<div><strong>Failed at {run.error_stage ?? 'unknown stage'}:</strong> {run.error}</div>
			{#if run.status === 'failed' && run.error_stage === 'evidence'}
				<div class="row">
					<button class="btn" onclick={retryAnalysis} disabled={retrying}>
						{#if retrying}<span class="spinner"></span>{/if}
						Retry analysis
					</button>
					{#if retrying}<span class="small">Re-running analysis on the uploaded files...</span>{/if}
				</div>
			{/if}
			{#if retryError}<div>{retryError}</div>{/if}
		</div>
	{/if}

	{@render children()}
</div>

<style>
	.run-head {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 1rem;
	}

	.run-head p {
		margin: 0.25rem 0 0;
	}

	ul {
		margin: 0.5rem 0;
	}
</style>

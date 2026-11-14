<script lang="ts">
	import { onMount } from 'svelte';
	import { fly } from 'svelte/transition';
	import { invalidate } from '$app/navigation';
	import { api, draftsChanged, errorText, formatDay, isRunning } from '#lib/api.ts';
	import AiPanel from '#lib/components/AiPanel.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import Stepper from '#lib/components/Stepper.svelte';
	import Working from '#lib/components/Working.svelte';
	import { ui } from '#lib/ui.svelte.ts';
	import type { LayoutProps } from './$types';

	let { data, children }: LayoutProps = $props();
	let run = $derived(data.run);

	let retrying = $state(false);
	let retryError = $state('');

	const date = $derived(run.meeting_info.meeting_date || formatDay(run.created_at));

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

<div class="draft" class:with-panel={ui.aiPanelOpen}>
	<div class="page">
		<header class="head">
			<div class="title-row">
				<h1 title={run.title}>{run.title}</h1>
				<p class="meta small" title="{date} · {run.profile_slug} v{run.profile_version}">
					{date}
					<span class="sep">·</span>
					<a href="/profiles/{run.profile_slug}?v={run.profile_version}" title="Minutes profile">{run.profile_slug} v{run.profile_version}</a>
				</p>
				<span class="spacer"></span>
				<button
					class="btn sm ai-toggle"
					class:on={ui.aiPanelOpen}
					onclick={() => ui.setAiPanel(!ui.aiPanelOpen)}
					aria-pressed={ui.aiPanelOpen}
				>
					<Icon name={ui.aiPanelOpen ? 'eyeOff' : 'eye'} size={14} />
					{ui.aiPanelOpen ? 'Hide AI activity' : 'View AI activity'}
					{#if run.llm_calls.length}<span class="count">{run.llm_calls.length}</span>{/if}
				</button>
			</div>
			<div class="step-row">
				<div class="steps"><Stepper {run} /></div>
			</div>
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
				<div>
					<strong>Something went wrong while {run.error_stage === 'evidence' ? 'reading the evidence' : 'drafting'}.</strong>
				</div>
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

		{#snippet watch()}
			{#if !ui.aiPanelOpen}
				<button class="btn sm" onclick={() => ui.setAiPanel(true)}>
					<Icon name="eye" size={14} /> Watch the AI activity live
				</button>
			{/if}
		{/snippet}

		{#if run.status === 'analysing'}
			<Working title="Reading the meeting" message="Working out which parts of the discussion belong to each agenda item." note="">
				{@render watch()}
			</Working>
		{:else if run.status === 'drafting'}
			<Working
				icon="file"
				title="Drafting the minutes"
				message="Selecting what belongs in the record, writing it up and checking it against the evidence."
			>
				{@render watch()}
			</Working>
		{:else}
			{@render children()}
		{/if}
	</div>

	{#if ui.aiPanelOpen}
		<div class="panel-wrap" transition:fly={{ x: 40, duration: 180 }}>
			<AiPanel {run} onclose={() => ui.setAiPanel(false)} />
		</div>
	{/if}
</div>

<style>
	.draft {
		--panel-w: 500px;
	}

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
		align-items: flex-start;
		gap: 0.6rem;
	}

	.title-row,
	.step-row {
		align-self: stretch;
	}

	.step-row {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		flex-wrap: wrap;
	}

	.steps {
		margin-left: -0.5rem;
	}

	.title-row {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		min-width: 0;
	}

	/* Long titles and profile names truncate so the AI button keeps its place. */
	h1,
	.meta {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	h1 {
		flex: 0 1 auto;
	}

	.meta {
		flex: 0 100 auto;
	}

	.ai-toggle {
		flex-shrink: 0;
	}

	h1 {
		font-size: 1.35rem;
	}

	.meta {
		color: var(--muted);
	}

	.meta a {
		color: var(--muted);
	}

	.meta a:hover {
		color: var(--accent);
	}

	.sep {
		margin: 0 0.3rem;
		color: var(--faint);
	}

	.ai-toggle.on {
		background: var(--accent-soft);
		border-color: #c7d0f6;
		color: var(--accent);
	}

	.count {
		font-size: 0.7rem;
		font-weight: 600;
		padding: 0 0.35rem;
		border-radius: 999px;
		background: #f1f2f4;
		color: var(--muted);
	}

	.on .count {
		background: #fff;
		color: var(--accent);
	}

	ul {
		margin: 0;
		padding-left: 1.1rem;
	}

	.panel-wrap {
		position: fixed;
		top: 0;
		right: 0;
		bottom: 0;
		width: var(--panel-w);
		max-width: 100vw;
		z-index: 25;
		box-shadow: var(--shadow-lg);
	}

	/* Wide screens: push the page aside instead of covering it. */
	@media (min-width: 1280px) {
		.draft.with-panel {
			padding-right: calc(var(--panel-w) - 1rem);
		}

		.panel-wrap {
			box-shadow: none;
		}
	}
</style>

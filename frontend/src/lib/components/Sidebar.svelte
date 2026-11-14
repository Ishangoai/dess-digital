<script lang="ts">
	import { onMount } from 'svelte';
	import { afterNavigate } from '$app/navigation';
	import { page } from '$app/state';
	import {
		api,
		DRAFTS_CHANGED,
		errorText,
		formatDay,
		isRunning,
		STATUS_LABELS,
		type DraftRunSummary
	} from '#lib/api.ts';
	import Icon from '#lib/components/Icon.svelte';

	let { onnavigate }: { onnavigate?: () => void } = $props();

	let runs = $state<DraftRunSummary[]>([]);
	let loaded = $state(false);
	let error = $state('');
	let query = $state('');

	const filtered = $derived(
		query.trim()
			? runs.filter((r) => r.title.toLowerCase().includes(query.trim().toLowerCase()))
			: runs
	);
	const activeId = $derived(page.params.id ?? null);

	async function load() {
		try {
			runs = await api.listDrafts();
			error = '';
		} catch (e) {
			error = errorText(e);
		} finally {
			loaded = true;
		}
	}

	onMount(() => {
		load();
		const refresh = () => load();
		window.addEventListener(DRAFTS_CHANGED, refresh);
		const timer = window.setInterval(() => {
			if (runs.some((r) => isRunning(r.status))) load();
		}, 5000);
		return () => {
			window.removeEventListener(DRAFTS_CHANGED, refresh);
			window.clearInterval(timer);
		};
	});

	afterNavigate(() => onnavigate?.());
</script>

<div class="sidebar">
	<a class="brand" href="/">
		<span class="logo" aria-hidden="true">D</span>
		<span>DESS Minutes</span>
	</a>

	<a class="btn primary new" href="/drafts/new">
		<Icon name="plus" />
		New minutes
	</a>

	<div class="section">
		<div class="section-head">
			<span class="eyebrow">Meetings</span>
			{#if runs.length}<span class="count">{runs.length}</span>{/if}
		</div>
		{#if runs.length > 5}
			<label class="search">
				<Icon name="search" size={14} />
				<input type="search" placeholder="Search meetings" bind:value={query} aria-label="Search meetings" />
			</label>
		{/if}
	</div>

	<nav class="list" aria-label="Meetings">
		{#if !loaded}
			<p class="empty">Loading...</p>
		{:else if error}
			<p class="empty err">{error}</p>
		{:else if runs.length === 0}
			<p class="empty">No meetings yet. Minutes you draft will be listed here.</p>
		{:else if filtered.length === 0}
			<p class="empty">No meetings match "{query}".</p>
		{:else}
			{#each filtered as run (run.id)}
				<a class="item" class:active={run.id === activeId} href="/drafts/{run.id}">
					<span class="title">{run.title}</span>
					<span class="meta">
						<span class="dot {run.status}" title={STATUS_LABELS[run.status]}></span>
						{#if isRunning(run.status)}
							{STATUS_LABELS[run.status]}...
						{:else if run.status !== 'completed'}
							{STATUS_LABELS[run.status]}
						{:else}
							{run.meeting_info.meeting_date || formatDay(run.created_at)}
						{/if}
					</span>
				</a>
			{/each}
		{/if}
	</nav>

	<div class="foot">
		<a href="/profiles" class:active={page.url.pathname.startsWith('/profiles')}>
			<Icon name="book" />
			Minutes profiles
		</a>
	</div>
</div>

<style>
	.sidebar {
		display: flex;
		flex-direction: column;
		height: 100%;
		padding: 1rem 0.75rem;
		gap: 1rem;
	}

	.brand {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		padding: 0.25rem 0.5rem;
		font-weight: 650;
		font-size: 0.98rem;
		color: var(--text);
		text-decoration: none;
	}

	.logo {
		width: 1.75rem;
		height: 1.75rem;
		border-radius: 7px;
		display: grid;
		place-items: center;
		background: linear-gradient(135deg, #2d4fd6, #5b3fd1);
		color: #fff;
		font-size: 0.85rem;
		font-weight: 700;
	}

	.new {
		width: 100%;
	}

	.section {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		padding: 0 0.25rem;
	}

	.section-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0 0.25rem;
	}

	.count {
		font-size: 0.72rem;
		color: var(--faint);
	}

	.search {
		position: relative;
		display: flex;
		align-items: center;
		color: var(--faint);
	}

	.search :global(svg) {
		position: absolute;
		left: 0.6rem;
	}

	.search input {
		padding-left: 1.9rem;
		font-size: 0.84rem;
		background: var(--surface);
	}

	.list {
		flex: 1;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: 2px;
		margin: 0 -0.25rem;
		padding: 0 0.25rem;
	}

	.item {
		display: flex;
		flex-direction: column;
		gap: 0.1rem;
		padding: 0.55rem 0.7rem;
		border-radius: var(--radius-sm);
		color: var(--text-2);
		text-decoration: none;
	}

	.item:hover {
		background: rgba(17, 24, 39, 0.04);
		text-decoration: none;
	}

	.item.active {
		background: var(--surface);
		box-shadow:
			var(--shadow-sm),
			inset 0 0 0 1px var(--border);
	}

	.title {
		font-size: 0.86rem;
		font-weight: 500;
		color: var(--text);
		line-height: 1.35;
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}

	.meta {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		font-size: 0.75rem;
		color: var(--muted);
	}

	.dot {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: var(--faint);
		flex-shrink: 0;
	}

	.dot.completed {
		background: var(--ok);
	}

	.dot.awaiting_mapping_review {
		background: var(--warn);
	}

	.dot.analysing,
	.dot.drafting {
		background: var(--accent);
		animation: pulse 1.2s ease-in-out infinite;
	}

	.dot.failed,
	.dot.blocked {
		background: var(--err);
	}

	@keyframes pulse {
		50% {
			opacity: 0.35;
		}
	}

	.empty {
		font-size: 0.82rem;
		color: var(--muted);
		padding: 0.5rem 0.7rem;
	}

	.empty.err {
		color: var(--err-fg);
	}

	.foot {
		border-top: 1px solid var(--border);
		padding-top: 0.75rem;
	}

	.foot a {
		display: flex;
		align-items: center;
		gap: 0.55rem;
		padding: 0.45rem 0.7rem;
		border-radius: var(--radius-sm);
		font-size: 0.85rem;
		color: var(--text-2);
		text-decoration: none;
	}

	.foot a:hover,
	.foot a.active {
		background: rgba(17, 24, 39, 0.04);
		color: var(--text);
	}
</style>

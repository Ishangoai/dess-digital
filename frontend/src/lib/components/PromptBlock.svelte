<script lang="ts">
	import type { Snippet } from 'svelte';
	import Icon from '#lib/components/Icon.svelte';
	import { approxTokens } from '#lib/prompt.ts';

	let {
		title,
		detail = '',
		badge = '',
		tone = 'neutral',
		text = '',
		open = false,
		children
	}: {
		title: string;
		detail?: string;
		badge?: string;
		tone?: 'neutral' | 'evidence' | 'guidance' | 'earlier' | 'task' | 'output' | 'instructions';
		text?: string;
		open?: boolean;
		children?: Snippet;
	} = $props();

	let copied = $state(false);

	async function copy(event: MouseEvent) {
		event.preventDefault();
		event.stopPropagation();
		await navigator.clipboard.writeText(text);
		copied = true;
		window.setTimeout(() => (copied = false), 1500);
	}
</script>

<details class="block {tone}" {open}>
	<summary>
		<Icon name="chevronRight" size={14} />
		<span class="title">{title}</span>
		{#if detail}<span class="detail">{detail}</span>{/if}
		<span class="spacer"></span>
		{#if badge}<span class="badge">{badge}</span>{/if}
		{#if text}
			<span class="size">{approxTokens(text)}</span>
			<button class="btn ghost sm copy" onclick={copy} aria-label="Copy {title}">
				{#if copied}<Icon name="check" size={13} /> Copied{:else}Copy{/if}
			</button>
		{/if}
	</summary>
	<div class="content">
		{#if children}{@render children()}{:else}<pre>{text}</pre>{/if}
	</div>
</details>

<style>
	.block {
		border: 1px solid var(--border);
		border-left: 3px solid var(--border-strong);
		border-radius: var(--radius-sm);
		background: var(--surface);
	}

	.block.evidence {
		border-left-color: #94a3b8;
	}

	.block.guidance {
		border-left-color: #8b5cf6;
	}

	.block.earlier {
		border-left-color: #0ea5e9;
	}

	.block.task {
		border-left-color: var(--accent);
	}

	.block.output {
		border-left-color: var(--ok);
	}

	.block.instructions {
		border-left-color: #f59e0b;
	}

	summary {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.55rem 0.6rem 0.55rem 0.75rem;
		min-height: 2.6rem;
	}

	summary :global(svg:first-child) {
		color: var(--faint);
		transition: transform 0.15s;
	}

	.block[open] > summary :global(svg:first-child) {
		transform: rotate(90deg);
	}

	.block[open] > summary {
		border-bottom: 1px solid var(--border);
	}

	.title {
		font-size: 0.88rem;
		font-weight: 600;
		color: var(--text);
	}

	.detail {
		font-size: 0.78rem;
		color: var(--muted);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
	}

	.badge {
		font-size: 0.68rem;
		font-weight: 600;
		padding: 0.1rem 0.45rem;
		border-radius: 999px;
		background: #f1f2f4;
		color: var(--muted);
		white-space: nowrap;
	}

	.size {
		font-size: 0.72rem;
		color: var(--faint);
		white-space: nowrap;
	}

	.copy {
		padding: 0.2rem 0.5rem;
		font-size: 0.74rem;
	}

	.content {
		padding: 0.75rem;
	}

	pre {
		margin: 0;
		white-space: pre-wrap;
		word-break: break-word;
		font-family: var(--mono);
		font-size: 0.76rem;
		line-height: 1.55;
		color: var(--text-2);
		max-height: 520px;
		overflow: auto;
	}
</style>

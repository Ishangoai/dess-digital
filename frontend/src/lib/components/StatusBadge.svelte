<script lang="ts">
	import { isRunning, STATUS_LABELS, type DraftStatus } from '#lib/api.ts';

	let { status }: { status: DraftStatus } = $props();

	const tone: Record<DraftStatus, string> = {
		analysing: 'info',
		drafting: 'info',
		awaiting_mapping_review: 'warn',
		blocked: 'err',
		failed: 'err',
		completed: 'ok'
	};
</script>

<span class="badge {tone[status]}">
	{#if isRunning(status)}<span class="spinner"></span>{:else}<span class="dot"></span>{/if}
	{STATUS_LABELS[status]}
</span>

<style>
	.badge {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		padding: 0.25rem 0.65rem;
		border-radius: 999px;
		font-size: 0.76rem;
		font-weight: 600;
		white-space: nowrap;
	}

	.badge .spinner {
		width: 0.7rem;
		height: 0.7rem;
	}

	.dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: currentColor;
	}

	.info {
		background: var(--info-bg);
		color: var(--info-fg);
	}

	.warn {
		background: var(--warn-bg);
		color: var(--warn-fg);
	}

	.err {
		background: var(--err-bg);
		color: var(--err-fg);
	}

	.ok {
		background: var(--ok-bg);
		color: var(--ok-fg);
	}
</style>

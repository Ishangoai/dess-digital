<script lang="ts">
	import { STATUS_LABELS, type DraftStatus } from '#lib/api.ts';

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
	{#if status === 'analysing' || status === 'drafting'}<span class="spinner"></span>{/if}
	{STATUS_LABELS[status]}
</span>

<style>
	.badge {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		padding: 0.15rem 0.6rem;
		border-radius: 999px;
		font-size: 0.75rem;
		font-weight: 600;
		white-space: nowrap;
	}

	.badge .spinner {
		width: 0.7rem;
		height: 0.7rem;
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

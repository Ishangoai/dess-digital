<script lang="ts">
	import type { DraftRun } from '#lib/api.ts';

	type Step = 'upload' | 'mapping' | 'minutes';

	let { current, run = null }: { current: Step; run?: DraftRun | null } = $props();

	const steps: { key: Step; label: string }[] = [
		{ key: 'upload', label: 'Upload evidence' },
		{ key: 'mapping', label: 'Review mapping' },
		{ key: 'minutes', label: 'Draft and export' }
	];

	function href(key: Step): string | null {
		if (!run) return key === 'upload' ? '/drafts/new' : null;
		if (key === 'mapping' && run.mapping) return `/drafts/${run.id}/mapping`;
		if (key === 'minutes' && run.draft) return `/drafts/${run.id}/minutes`;
		return null;
	}

	const order = steps.map((s) => s.key);
	const done = (key: Step) =>
		order.indexOf(key) < order.indexOf(current) || (key === 'minutes' && !!run?.draft);
</script>

<ol class="steps">
	{#each steps as step, i (step.key)}
		{@const link = step.key === current ? null : href(step.key)}
		<li class:current={step.key === current} class:done={done(step.key)}>
			<span class="num">{i + 1}</span>
			{#if link}<a href={link}>{step.label}</a>{:else}<span>{step.label}</span>{/if}
		</li>
	{/each}
</ol>

<style>
	.steps {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem 1.5rem;
		list-style: none;
		margin: 0;
		padding: 0;
		font-size: 0.9rem;
		color: var(--muted);
	}

	li {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	.num {
		width: 1.6rem;
		height: 1.6rem;
		border-radius: 50%;
		display: grid;
		place-items: center;
		font-size: 0.8rem;
		font-weight: 600;
		border: 1px solid var(--border-strong);
		background: var(--surface);
	}

	.done .num {
		background: var(--ok-bg);
		color: var(--ok-fg);
		border-color: transparent;
	}

	.current {
		color: var(--text);
		font-weight: 600;
	}

	.current .num {
		background: var(--accent);
		color: #fff;
		border-color: var(--accent);
	}
</style>

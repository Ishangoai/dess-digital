<script lang="ts">
	import { page } from '$app/state';
	import type { DraftRun } from '#lib/api.ts';
	import Icon from '#lib/components/Icon.svelte';

	let { run }: { run: DraftRun } = $props();

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
	const steps = $derived([
		{ label: 'Evidence', href: null },
		{ label: 'Mapping', href: run.mapping ? `/drafts/${run.id}/mapping` : null },
		{ label: 'Minutes', href: run.draft ? `/drafts/${run.id}/minutes` : null }
	]);
</script>

<ol class="stepper" aria-label="Progress">
	{#each steps as step, i (step.label)}
		{@const here = !!step.href && page.url.pathname === step.href}
		<li
			class:done={i < stage}
			class:current={i === stage && !failed}
			class:failed={i === stage && failed}
			class:here
			aria-current={here ? 'page' : undefined}
		>
			{#if step.href && !here}
				<a href={step.href} title="View the {step.label.toLowerCase()}">
					<span class="dot">{#if i < stage}<Icon name="check" size={10} />{:else}{i + 1}{/if}</span>
					{step.label}
				</a>
			{:else}
				<span class="step">
					<span class="dot">{#if i < stage}<Icon name="check" size={10} />{:else}{i + 1}{/if}</span>
					{step.label}
				</span>
			{/if}
		</li>
		{#if i < steps.length - 1}<li class="sep" aria-hidden="true"></li>{/if}
	{/each}
</ol>

<style>
	.stepper {
		display: flex;
		align-items: center;
		gap: 0.35rem;
		list-style: none;
		margin: 0;
		padding: 0;
		font-size: 0.8rem;
	}

	.sep {
		width: 1.25rem;
		height: 1px;
		background: var(--border-strong);
	}

	a,
	.step {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		padding: 0.25rem 0.5rem;
		border-radius: 999px;
		color: var(--faint);
		text-decoration: none;
	}

	a:hover {
		background: rgba(17, 24, 39, 0.05);
		text-decoration: none;
	}

	.dot {
		display: grid;
		place-items: center;
		width: 1.1rem;
		height: 1.1rem;
		border-radius: 50%;
		border: 1px solid var(--border-strong);
		font-size: 0.64rem;
		font-weight: 600;
	}

	.done a,
	.done .step {
		color: var(--text-2);
	}

	.done .dot {
		background: var(--ok);
		border-color: var(--ok);
		color: #fff;
	}

	.current .step,
	.current a {
		color: var(--text);
		font-weight: 600;
	}

	.current .dot {
		background: var(--accent);
		border-color: var(--accent);
		color: #fff;
	}

	.failed .step {
		color: var(--err-fg);
		font-weight: 600;
	}

	.failed .dot {
		background: var(--err);
		border-color: var(--err);
		color: #fff;
	}

	.here .step {
		background: var(--surface);
		box-shadow: inset 0 0 0 1px var(--border);
		color: var(--text);
		font-weight: 600;
	}
</style>

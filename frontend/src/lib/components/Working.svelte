<script lang="ts">
	import Icon, { type IconName } from '#lib/components/Icon.svelte';

	let {
		title,
		message,
		seconds = null,
		icon = 'layers',
		note = 'A short meeting takes under a minute; a long board meeting can take a few. You can leave this page and come back.'
	}: {
		title: string;
		message: string;
		seconds?: number | null;
		icon?: IconName;
		note?: string;
	} = $props();

	const clock = $derived(
		seconds === null ? '' : `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
	);
</script>

<div class="working card" role="status">
	<span class="pulse"><Icon name={icon} size={22} /></span>
	<h2>{title}</h2>
	<p class="muted">{message}</p>
	{#if clock}<p class="clock">{clock}</p>{/if}
	<p class="tiny muted">{note}</p>
</div>

<style>
	.working {
		display: flex;
		flex-direction: column;
		align-items: center;
		text-align: center;
		gap: 0.6rem;
		padding: 3rem 2rem;
	}

	h2 {
		font-size: 1.25rem;
	}

	p {
		max-width: 48ch;
	}

	.pulse {
		display: grid;
		place-items: center;
		width: 3.25rem;
		height: 3.25rem;
		border-radius: 50%;
		background: var(--accent-soft);
		color: var(--accent);
		margin-bottom: 0.5rem;
		animation: breathe 1.6s ease-in-out infinite;
	}

	@keyframes breathe {
		50% {
			box-shadow: 0 0 0 10px rgba(45, 79, 214, 0.08);
		}
	}

	.clock {
		font-family: var(--mono);
		font-size: 1.1rem;
		color: var(--text-2);
		margin: 0.25rem 0;
	}
</style>

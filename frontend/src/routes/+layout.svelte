<script lang="ts">
	import '../app.css';
	import favicon from '#lib/assets/favicon.svg';
	import Icon from '#lib/components/Icon.svelte';
	import Sidebar from '#lib/components/Sidebar.svelte';
	import { ui } from '#lib/ui.svelte.ts';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();
	let menuOpen = $state(false);
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<title>DESS Minutes</title>
</svelte:head>

<div class="shell" class:collapsed={ui.sidebarCollapsed}>
	<header class="mobile-bar">
		<button class="btn ghost" onclick={() => (menuOpen = true)} aria-label="Open menu">
			<Icon name="menu" size={18} />
		</button>
		<a class="mobile-brand" href="/">DESS Minutes</a>
	</header>

	<aside class="side" class:open={menuOpen}>
		<Sidebar
			onnavigate={() => (menuOpen = false)}
			collapsed={ui.sidebarCollapsed && !menuOpen}
			ontoggle={menuOpen ? undefined : ui.toggleSidebar}
		/>
	</aside>
	{#if menuOpen}
		<button class="scrim" onclick={() => (menuOpen = false)} aria-label="Close menu"></button>
	{/if}

	<main class="main">
		{@render children()}
	</main>
</div>

<style>
	.shell {
		--side-w: 264px;
		display: grid;
		grid-template-columns: var(--side-w) minmax(0, 1fr);
		min-height: 100vh;
		background: linear-gradient(
			to right,
			var(--sidebar) calc(var(--side-w) - 1px),
			var(--border) calc(var(--side-w) - 1px) var(--side-w),
			var(--bg) var(--side-w)
		);
	}

	.shell.collapsed {
		--side-w: 64px;
	}

	.side {
		position: sticky;
		top: 0;
		height: 100vh;
		background: var(--sidebar);
		border-right: 1px solid var(--border);
	}

	.main {
		min-width: 0;
		padding: 2rem 2.5rem 4rem;
	}

	.mobile-bar,
	.scrim {
		display: none;
	}

	@media (max-width: 860px) {
		.shell,
		.shell.collapsed {
			grid-template-columns: 1fr;
			background: var(--bg);
		}

		.mobile-bar {
			display: flex;
			align-items: center;
			gap: 0.5rem;
			padding: 0.5rem 0.75rem;
			background: var(--surface);
			border-bottom: 1px solid var(--border);
			position: sticky;
			top: 0;
			z-index: 20;
		}

		.mobile-brand {
			font-weight: 650;
			color: var(--text);
		}

		.side {
			position: fixed;
			inset: 0 auto 0 0;
			width: 280px;
			z-index: 40;
			transform: translateX(-100%);
			transition: transform 0.2s ease;
		}

		.side.open {
			transform: none;
			box-shadow: var(--shadow-lg);
		}

		.scrim {
			display: block;
			position: fixed;
			inset: 0;
			z-index: 30;
			border: none;
			background: rgba(17, 24, 39, 0.35);
		}

		.main {
			padding: 1.25rem 1rem 3rem;
		}
	}
</style>

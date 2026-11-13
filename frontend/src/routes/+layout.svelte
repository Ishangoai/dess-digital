<script lang="ts">
	import '../app.css';
	import favicon from '#lib/assets/favicon.svg';
	import { page } from '$app/state';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();

	const links = [
		{ href: '/', label: 'Drafts', match: (p: string) => p === '/' || p.startsWith('/drafts/') && p !== '/drafts/new' },
		{ href: '/drafts/new', label: 'New draft', match: (p: string) => p === '/drafts/new' },
		{ href: '/profiles', label: 'Profiles', match: (p: string) => p.startsWith('/profiles') },
		{ href: '/uploads', label: 'File uploads', match: (p: string) => p.startsWith('/uploads') }
	];
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<title>DESS Minutes</title>
</svelte:head>

<header class="topbar">
	<a class="brand" href="/">DESS Minutes</a>
	<nav>
		{#each links as link (link.href)}
			<a href={link.href} class:active={link.match(page.url.pathname)}>{link.label}</a>
		{/each}
	</nav>
</header>

<main class="content">
	{@render children()}
</main>

<style>
	.topbar {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.5rem 1.5rem;
		padding: 0.75rem 1rem;
		background: var(--surface);
		border-bottom: 1px solid var(--border);
	}

	.brand {
		font-weight: 700;
		color: var(--text);
		text-decoration: none;
	}

	nav {
		display: flex;
		flex-wrap: wrap;
		gap: 0.25rem;
	}

	nav a {
		color: var(--muted);
		text-decoration: none;
		font-size: 0.9rem;
		padding: 0.35rem 0.65rem;
		border-radius: 6px;
	}

	nav a:hover {
		color: var(--text);
		background: var(--bg);
	}

	nav a.active {
		color: var(--accent);
		background: var(--accent-soft);
		font-weight: 500;
	}

	.content {
		max-width: 1200px;
		margin: 0 auto;
		padding: 1.5rem 1rem 3rem;
	}
</style>

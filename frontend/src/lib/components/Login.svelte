<script lang="ts">
	let { onsuccess }: { onsuccess: () => void } = $props();

	let username = $state('');
	let password = $state('');
	let error = $state('');
	let loading = $state(false);

	async function handleSubmit(e: SubmitEvent) {
		e.preventDefault();
		error = '';
		loading = true;
		try {
			const res = await fetch('/api/auth/login', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ username, password })
			});
			if (!res.ok) {
				error = 'Invalid username or password';
				return;
			}
			password = '';
			onsuccess();
		} catch {
			error = 'Unable to reach server';
		} finally {
			loading = false;
		}
	}
</script>

<div class="login-wrap">
	<form class="login-card" onsubmit={handleSubmit}>
		<div class="login-brand">
			<span class="logo" aria-hidden="true">D</span>
			<span>DESS Minutes</span>
		</div>

		{#if error}
			<p class="err">{error}</p>
		{/if}

		<input type="text" placeholder="Username" bind:value={username} required />
		<input type="password" placeholder="Password" bind:value={password} required />

		<button class="btn primary" type="submit" disabled={loading}>
			{loading ? 'Signing in...' : 'Sign In'}
		</button>
	</form>
</div>

<style>
	.login-wrap {
		min-height: 100vh;
		display: grid;
		place-items: center;
		background: var(--bg);
		padding: 1rem;
	}

	.login-card {
		width: 100%;
		max-width: 340px;
		display: flex;
		flex-direction: column;
		gap: 0.85rem;
		padding: 1.75rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius-sm);
		box-shadow: var(--shadow-lg);
	}

	.login-brand {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		font-weight: 650;
		font-size: 1.05rem;
		color: var(--text);
		margin-bottom: 0.25rem;
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

	.err {
		margin: 0;
		font-size: 0.84rem;
		color: var(--err-fg);
	}
	.login-card input {
		width: 100%;
		padding: 0.6rem 0.75rem;
		border: 1px solid var(--border);
		border-radius: var(--radius-sm);
		background: var(--surface);
		color: var(--text);
		font: inherit;
		font-size: 0.92rem;
	}

	.login-card input:focus {
		outline: none;
		border-color: var(--accent);
	}
</style>
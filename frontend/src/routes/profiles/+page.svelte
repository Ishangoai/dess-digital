<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { api, errorText, type ProfileSummary } from '#lib/api.ts';

	let profiles = $state<ProfileSummary[]>([]);
	let loading = $state(true);
	let error = $state('');

	let organisation = $state('');
	let body = $state('Board');
	let base = $state('dess-standard');
	let busy = $state(false);
	let createError = $state('');

	// Profiles an organisation profile can start from: the shared standards, not other clients.
	const bases = $derived(profiles.filter((p) => !p.based_on_slug && p.active_version));
	const slug = $derived(
		organisation
			.toLowerCase()
			.replace(/[^a-z0-9]+/g, '-')
			.replace(/^-|-$/g, '')
	);

	onMount(async () => {
		try {
			profiles = await api.listProfiles();
		} catch (e) {
			error = errorText(e);
		} finally {
			loading = false;
		}
	});

	async function create(event: SubmitEvent) {
		event.preventDefault();
		busy = true;
		createError = '';
		try {
			const p = await api.createProfile({
				slug,
				name: `${organisation.trim()} minutes`,
				body_name: body.trim() || null,
				based_on_slug: base
			});
			await goto(`/profiles/${p.slug}`);
		} catch (e) {
			createError = errorText(e);
		} finally {
			busy = false;
		}
	}
</script>

<div class="stack contained">
	<div>
		<h1>Minutes profiles</h1>
		<p class="muted">
			A profile holds the minuting logic a draft follows. Drafts use the latest confirmed version.
			Give each organisation its own profile so what is learned from its reviewers stays its own.
		</p>
	</div>

	<section class="card">
		{#if loading}
			<p class="muted">Loading...</p>
		{:else if error}
			<p class="alert error">{error}</p>
		{:else if profiles.length === 0}
			<p class="muted">
				No profiles yet. Seed the DESS Standard with
				<code>uv run python -m app.seed_profile --confirm</code>.
			</p>
		{:else}
			<div class="table-wrap">
				<table>
					<thead>
						<tr><th>Profile</th><th>Body</th><th>Based on</th><th>Active</th><th>Latest</th></tr>
					</thead>
					<tbody>
						{#each profiles as p (p.slug)}
							<tr>
								<td>
									<a href="/profiles/{p.slug}">{p.name}</a>
									<div class="muted small mono">{p.slug}</div>
								</td>
								<td>{p.body_name ?? '-'}</td>
								<td class="mono small">{p.based_on_slug ?? '-'}</td>
								<td>{p.active_version ? `v${p.active_version}` : 'none confirmed'}</td>
								<td>{p.latest_version ? `v${p.latest_version}` : '-'}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</section>

	{#if bases.length}
		<section class="card stack">
			<h2>New organisation profile</h2>
			<p class="small muted">
				Starts as a copy of the standard. Changes learned from this organisation's reviewers apply to
				it, never to the standard.
			</p>
			<form class="stack create" onsubmit={create}>
				<label class="field">
					Organisation
					<input type="text" bind:value={organisation} placeholder="e.g. VeriFocal plc" required />
				</label>
				<label class="field">
					Board or committee
					<input type="text" bind:value={body} />
				</label>
				<label class="field">
					Based on
					<select bind:value={base}>
						{#each bases as b (b.slug)}<option value={b.slug}>{b.name}</option>{/each}
					</select>
				</label>
				<div>
					<button class="btn primary" type="submit" disabled={busy || !slug}>Create profile</button>
				</div>
				{#if createError}<p class="alert error small">{createError}</p>{/if}
			</form>
		</section>
	{/if}
</div>

<style>
	p {
		margin: 0;
	}

	.create {
		max-width: 420px;
	}
</style>

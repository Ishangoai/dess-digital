<script lang="ts">
	import { onMount } from 'svelte';
	import { api, errorText, type ProfileSummary } from '#lib/api.ts';

	let profiles = $state<ProfileSummary[]>([]);
	let loading = $state(true);
	let error = $state('');

	onMount(async () => {
		try {
			profiles = await api.listProfiles();
		} catch (e) {
			error = errorText(e);
		} finally {
			loading = false;
		}
	});
</script>

<div class="stack contained">
	<div>
		<h1>Minutes profiles</h1>
		<p class="muted">
			A profile holds the Minuting Policy (MP1 to MP9) and Writing Style (WS1 to WS6) a draft
			follows. Drafts use the latest confirmed version.
		</p>
	</div>

	<section class="card">
		{#if loading}
			<p class="muted">Loading...</p>
		{:else if error}
			<p class="alert error">{error}</p>
		{:else if profiles.length === 0}
			<p class="muted">
				No profiles yet. Seed one with
				<code>uv run python -m app.seed_profile path/to/profile.yaml --confirm</code>.
			</p>
		{:else}
			<div class="table-wrap">
				<table>
					<thead>
						<tr><th>Profile</th><th>Body</th><th>Active</th><th>Latest</th></tr>
					</thead>
					<tbody>
						{#each profiles as p (p.slug)}
							<tr>
								<td>
									<a href="/profiles/{p.slug}">{p.name}</a>
									<div class="muted small mono">{p.slug}</div>
								</td>
								<td>{p.body_name ?? '-'}</td>
								<td>{p.active_version ? `v${p.active_version}` : 'none confirmed'}</td>
								<td>{p.latest_version ? `v${p.latest_version}` : '-'}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</section>
</div>

<style>
	p {
		margin: 0;
	}
</style>

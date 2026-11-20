<script lang="ts">
	import { onMount } from 'svelte';
	import { api, errorText, type Score } from '#lib/api.ts';

	let scores = $state<Score[]>([]);
	let loading = $state(true);
	let error = $state('');

	onMount(async () => {
		try {
			scores = await api.getScores();
		} catch (e) {
			error = errorText(e);
		} finally {
			loading = false;
		}
	});

	const percent = (n: number | null) => (n === null ? '-' : `${Math.round(n * 100)}%`);
</script>

<div class="stack contained">
	<div>
		<h1>Draft scores</h1>
		<p class="muted">
			Every piece of feedback earns a reward from 0 to 1: an approval 1, a revision request 0, and an
			uploaded edited copy the share of the draft the reviewer kept. Setups are ranked by expected
			reward, which starts at 50% and moves towards the real average as feedback comes in.
		</p>
	</div>

	<section class="card">
		{#if loading}
			<p class="muted">Loading...</p>
		{:else if error}
			<p class="alert error">{error}</p>
		{:else if scores.length === 0}
			<p class="muted">No feedback yet. Review a finished draft, or upload your edited copy of it.</p>
		{:else}
			<div class="table-wrap">
				<table>
					<thead>
						<tr>
							<th>Profile</th><th>Model</th><th>Approved</th><th>Revisions</th><th>Score</th><th
								>Edited copies</th
							><th>Kept when edited</th><th>Expected</th>
						</tr>
					</thead>
					<tbody>
						{#each scores as s (`${s.profile_slug}-${s.profile_version}-${s.model}`)}
							<tr>
								<td><a href="/profiles/{s.profile_slug}?v={s.profile_version}">{s.profile_slug} v{s.profile_version}</a></td>
								<td class="mono small">{s.model}</td>
								<td>{s.approvals}</td>
								<td>{s.revisions}</td>
								<td><strong>{s.net > 0 ? `+${s.net}` : s.net}</strong></td>
								<td>{s.edits}</td>
								<td>{percent(s.mean_similarity)}</td>
								<td>{percent(s.expected)}</td>
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

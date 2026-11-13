<script lang="ts">
	import { onMount } from 'svelte';
	import { api, errorText, formatDate, type DraftRunSummary } from '#lib/api.ts';
	import StatusBadge from '#lib/components/StatusBadge.svelte';

	let runs = $state<DraftRunSummary[]>([]);
	let loading = $state(true);
	let error = $state('');

	async function load() {
		try {
			runs = await api.listDrafts();
			error = '';
		} catch (e) {
			error = errorText(e);
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		load();
		// Pick up runs still analysing or drafting.
		const timer = window.setInterval(() => {
			if (runs.some((r) => r.status === 'analysing' || r.status === 'drafting')) load();
		}, 5000);
		return () => window.clearInterval(timer);
	});
</script>

<div class="stack">
	<div class="row head">
		<div>
			<h1>Dess Digital Minutes</h1>
			<p class="muted">First-draft minutes from an agenda and a transcript or meeting notes.</p>
		</div>
		<a class="btn primary" href="/drafts/new">New draft</a>
	</div>

	<section class="card">
		<div class="row head">
			<h2>Draft runs</h2>
			<button class="btn" onclick={load}>Refresh</button>
		</div>

		{#if loading}
			<p class="muted">Loading...</p>
		{:else if error}
			<p class="alert error">{error}</p>
		{:else if runs.length === 0}
			<p class="muted">No drafts yet. <a href="/drafts/new">Start one</a>.</p>
		{:else}
			<div class="table-wrap">
				<table>
					<thead>
						<tr>
							<th>Meeting</th>
							<th>Status</th>
							<th>Profile</th>
							<th>Created</th>
						</tr>
					</thead>
					<tbody>
						{#each runs as run (run.id)}
							<tr>
								<td>
									<a href="/drafts/{run.id}">
										{run.meeting_info.organisation || run.meeting_info.body_name || 'Untitled meeting'}
									</a>
									<div class="muted small">
										{[run.meeting_info.body_name, run.meeting_info.meeting_date]
											.filter(Boolean)
											.join(', ')}
										<span class="mono">{run.id.slice(0, 8)}</span>
									</div>
								</td>
								<td><StatusBadge status={run.status} /></td>
								<td class="small">{run.profile_slug} v{run.profile_version}</td>
								<td class="small">{formatDate(run.created_at)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</section>
</div>

<style>
	.head {
		justify-content: space-between;
	}

	p {
		margin: 0;
	}
</style>

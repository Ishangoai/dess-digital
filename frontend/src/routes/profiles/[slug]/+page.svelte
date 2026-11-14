<script lang="ts">
	import { goto, invalidate } from '$app/navigation';
	import { parse } from 'yaml';
	import { api, errorText, formatDate, type VersionStatus } from '#lib/api.ts';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	let profile = $derived(data.profile);
	let version = $derived(data.version);

	const NEXT: Record<VersionStatus, { status: VersionStatus; label: string }[]> = {
		proposed: [
			{ status: 'reviewed', label: 'Mark reviewed' },
			{ status: 'withdrawn', label: 'Withdraw' }
		],
		reviewed: [
			{ status: 'confirmed', label: 'Confirm' },
			{ status: 'withdrawn', label: 'Withdraw' }
		],
		confirmed: [],
		withdrawn: []
	};

	let message = $state('');
	let error = $state('');
	let busy = $state(false);
	let file = $state<FileList | null>(null);
	let summary = $state('');

	async function setStatus(n: number, status: VersionStatus) {
		busy = true;
		error = message = '';
		try {
			const v = await api.setStatus(profile.slug, n, status);
			message = `Version ${v.version_number} is now ${v.status}.`;
			await invalidate('app:profile');
		} catch (e) {
			error = errorText(e);
		} finally {
			busy = false;
		}
	}

	async function upload(event: SubmitEvent) {
		event.preventDefault();
		if (!file?.[0]) return (error = 'Choose a profile file.');
		busy = true;
		error = message = '';
		try {
			const content = parse(await file[0].text()); // JSON is valid YAML
			const v = await api.createVersion(profile.slug, content, summary);
			message = `Created version ${v.version_number} (proposed). Review and confirm it to make it active.`;
			summary = '';
			file = null;
			(event.target as HTMLFormElement).reset();
			await goto(`/profiles/${profile.slug}?v=${v.version_number}`, { invalidateAll: true });
		} catch (e) {
			error = errorText(e);
		} finally {
			busy = false;
		}
	}
</script>

<div class="stack contained">
	<div>
		<a class="small" href="/profiles">All profiles</a>
		<h1>{profile.name}</h1>
		<p class="muted">
			<span class="mono">{profile.slug}</span>
			{#if profile.body_name}, {profile.body_name}{/if}
			{#if profile.based_on_slug}, based on {profile.based_on_slug}{/if}
		</p>
		{#if profile.description}<p>{profile.description}</p>{/if}
	</div>

	{#if message}<p class="alert ok">{message}</p>{/if}
	{#if error}<p class="alert error">{error}</p>{/if}

	<section class="card stack">
		<h2>Versions</h2>
		<div class="table-wrap">
			<table>
				<thead>
					<tr><th>Version</th><th>Status</th><th>Change</th><th>Created</th><th></th></tr>
				</thead>
				<tbody>
					{#each [...profile.versions].reverse() as v (v.version_number)}
						<tr class:selected={version?.version_number === v.version_number}>
							<td>
								<a href="?v={v.version_number}">v{v.version_number}</a>
								{#if profile.active_version === v.version_number}<span class="active">active</span>{/if}
							</td>
							<td>{v.status}</td>
							<td class="small">{v.change_summary ?? '-'}</td>
							<td class="small">{formatDate(v.created_at)}<div class="muted">{v.created_by ?? ''}</div></td>
							<td class="row">
								{#each NEXT[v.status] as next (next.status)}
									<button class="btn small" disabled={busy} onclick={() => setStatus(v.version_number, next.status)}>
										{next.label}
									</button>
								{/each}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		<details>
			<summary>Upload a new version</summary>
			<form class="stack upload" onsubmit={upload}>
				<label class="field">
					Profile file (.yaml or .json)
					<input type="file" accept=".yaml,.yml,.json" bind:files={file} />
				</label>
				<label class="field">
					Change summary
					<input type="text" bind:value={summary} />
				</label>
				<div><button class="btn primary" type="submit" disabled={busy}>Create proposed version</button></div>
			</form>
		</details>
	</section>

	{#if version}
		{@const c = version.content}
		<section class="card stack">
			<h2>{c.name} v{version.version_number} ({version.status})</h2>
			{#if c.description}<p>{c.description}</p>{/if}
			<div>
				<h3>Hard floors</h3>
				<ul>{#each c.hard_floors as floor, i (i)}<li>{floor}</li>{/each}</ul>
			</div>
			{#each [['Minuting Policy', c.minuting_policy], ['Writing Style', c.writing_style]] as const as [title, dims] (title)}
				<div>
					<h3>{title}</h3>
					{#each dims as d (d.code)}
						<details>
							<summary><strong>{d.code}</strong> {d.title}</summary>
							<p class="standard">{d.default_standard}</p>
						</details>
					{/each}
				</div>
			{/each}
		</section>
	{/if}
</div>

<style>
	p {
		margin: 0;
	}

	.active {
		margin-left: 0.4rem;
		font-size: 0.7rem;
		font-weight: 600;
		padding: 0.05rem 0.4rem;
		border-radius: 4px;
		background: var(--ok-bg);
		color: var(--ok-fg);
	}

	tr.selected {
		background: var(--accent-soft);
	}

	.upload {
		margin-top: 0.75rem;
		max-width: 480px;
	}

	details {
		margin-bottom: 0.4rem;
	}

	summary {
		cursor: pointer;
	}

	.standard {
		white-space: pre-wrap;
		font-size: 0.9rem;
		margin: 0.4rem 0 0.75rem 1rem;
		color: var(--text-2);
	}

	ul {
		margin: 0.25rem 0 0;
		padding-left: 1.1rem;
	}

	.btn.small {
		padding: 0.25rem 0.6rem;
		font-size: 0.8rem;
	}
</style>

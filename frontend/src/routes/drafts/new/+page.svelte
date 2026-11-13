<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { api, errorText, type ProfileSummary } from '#lib/api.ts';
	import Steps from '#lib/components/Steps.svelte';

	const ACCEPT = '.docx,.txt,.md,.vtt';

	let agenda = $state<FileList | null>(null);
	let transcript = $state<FileList | null>(null);
	let notes = $state<FileList | null>(null);
	let papers = $state<FileList | null>(null);
	let organisation = $state('');
	let bodyName = $state('');
	let meetingDate = $state('');
	let meetingType = $state('');
	let profileSlug = $state('dess-standard');
	let autoConfirm = $state(false);

	let profiles = $state<ProfileSummary[]>([]);
	let error = $state('');
	let busy = $state(false);
	let elapsed = $state(0);

	onMount(async () => {
		try {
			profiles = await api.listProfiles();
			const usable = profiles.filter((p) => p.active_version !== null);
			if (usable.length && !usable.some((p) => p.slug === profileSlug)) {
				profileSlug = usable[0].slug;
			}
		} catch (e) {
			error = errorText(e);
		}
	});

	async function submit(event: SubmitEvent) {
		event.preventDefault();
		error = '';
		if (!agenda?.[0]) return (error = 'Upload an agenda first.');
		if (!transcript?.[0] && !notes?.[0]) return (error = 'Upload a transcript or meeting notes.');

		const form = new FormData();
		form.append('agenda', agenda[0]);
		if (transcript?.[0]) form.append('transcript', transcript[0]);
		if (notes?.[0]) form.append('notes', notes[0]);
		for (const paper of papers ?? []) form.append('papers', paper);
		const fields = {
			organisation,
			body_name: bodyName,
			meeting_date: meetingDate,
			meeting_type: meetingType,
			profile_slug: profileSlug
		};
		for (const [key, value] of Object.entries(fields)) if (value.trim()) form.append(key, value.trim());
		form.append('auto_confirm_mapping', String(autoConfirm));

		busy = true;
		elapsed = 0;
		const timer = window.setInterval(() => elapsed++, 1000);
		try {
			const run = await api.createDraft(form);
			await goto(`/drafts/${run.id}`);
		} catch (e) {
			error = errorText(e);
		} finally {
			window.clearInterval(timer);
			busy = false;
		}
	}
</script>

<div class="stack">
	<Steps current="upload" />
	<div>
		<h1>New draft</h1>
		<p class="muted">
			Upload the agenda plus a transcript and/or meeting notes. The evidence is mapped to the
			agenda items, then you review that mapping before the minutes are drafted.
		</p>
	</div>

	<form class="stack" onsubmit={submit}>
		<section class="card stack">
			<h2>1. Evidence</h2>
			<div class="grid">
				<label class="field">
					Agenda (required)
					<input type="file" accept={ACCEPT} bind:files={agenda} />
				</label>
				<label class="field">
					Transcript
					<input type="file" accept={ACCEPT} bind:files={transcript} />
				</label>
				<label class="field">
					Meeting notes
					<input type="file" accept={ACCEPT} bind:files={notes} />
				</label>
				<label class="field">
					Papers (optional, several)
					<input type="file" accept={ACCEPT} multiple bind:files={papers} />
				</label>
			</div>
			<p class="muted small">Supported: .docx, .txt, .md, .vtt</p>
		</section>

		<section class="card stack">
			<h2>Meeting details</h2>
			<div class="grid">
				<label class="field">
					Organisation
					<input type="text" bind:value={organisation} />
				</label>
				<label class="field">
					Board / committee
					<input type="text" bind:value={bodyName} />
				</label>
				<label class="field">
					Meeting date
					<input type="text" placeholder="e.g. 12 March 2026" bind:value={meetingDate} />
				</label>
				<label class="field">
					Meeting type
					<input type="text" placeholder="e.g. board" bind:value={meetingType} />
				</label>
				<label class="field">
					Minutes profile
					{#if profiles.length}
						<select bind:value={profileSlug}>
							{#each profiles as p (p.slug)}
								<option value={p.slug} disabled={p.active_version === null}>
									{p.name} ({p.slug}{p.active_version ? ` v${p.active_version}` : ', no confirmed version'})
								</option>
							{/each}
						</select>
					{:else}
						<input type="text" bind:value={profileSlug} />
					{/if}
				</label>
			</div>
			<label class="row small">
				<input type="checkbox" bind:checked={autoConfirm} />
				Skip mapping review and draft in one step
			</label>
		</section>

		{#if error}<p class="alert error">{error}</p>{/if}

		<div class="row">
			<button class="btn primary" type="submit" disabled={busy}>
				{#if busy}<span class="spinner"></span>{/if}
				{autoConfirm ? 'Analyse and draft minutes' : 'Analyse evidence'}
			</button>
			{#if busy}
				<span class="muted small">
					{autoConfirm ? 'Analysing and drafting' : 'Analysing evidence'}, {elapsed}s. Long meetings
					can take several minutes; keep this tab open.
				</span>
			{/if}
		</div>
	</form>
</div>

<style>
	p {
		margin: 0;
	}
</style>

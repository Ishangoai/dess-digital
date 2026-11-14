<script lang="ts">
	import { onMount } from 'svelte';
	import { slide } from 'svelte/transition';
	import { goto } from '$app/navigation';
	import { api, draftsChanged, errorText, type ProfileSummary } from '#lib/api.ts';
	import FileDrop from '#lib/components/FileDrop.svelte';
	import Icon from '#lib/components/Icon.svelte';

	let agenda = $state<File[]>([]);
	let transcript = $state<File[]>([]);
	let notes = $state<File[]>([]);
	let papers = $state<File[]>([]);
	let showMore = $state(false);
	let showDetails = $state(false);

	let organisation = $state('');
	let bodyName = $state('');
	let meetingDate = $state('');
	let profileSlug = $state('dess-standard');

	let profiles = $state<ProfileSummary[]>([]);
	let error = $state('');
	let busy = $state(false);

	const ready = $derived(agenda.length > 0 && transcript.length > 0);
	const extras = $derived(notes.length + papers.length);
	const usable = $derived(profiles.filter((p) => p.active_version !== null));
	const details = $derived([organisation, bodyName, meetingDate].filter((v) => v.trim()).length);
	const profileName = $derived(profiles.find((p) => p.slug === profileSlug)?.name ?? profileSlug);

	onMount(async () => {
		try {
			profiles = await api.listProfiles();
			const usable = profiles.filter((p) => p.active_version !== null);
			if (usable.length && !usable.some((p) => p.slug === profileSlug)) profileSlug = usable[0].slug;
		} catch (e) {
			error = errorText(e);
		}
	});

	async function submit(event: SubmitEvent) {
		event.preventDefault();
		if (!ready) return (error = 'Add the agenda and the transcript to continue.');
		error = '';

		const form = new FormData();
		form.append('agenda', agenda[0]);
		form.append('transcript', transcript[0]);
		if (notes[0]) form.append('notes', notes[0]);
		for (const paper of papers) form.append('papers', paper);
		const fields = {
			organisation,
			body_name: bodyName,
			meeting_date: meetingDate,
			profile_slug: profileSlug
		};
		for (const [key, value] of Object.entries(fields)) if (value.trim()) form.append(key, value.trim());
		// Return as soon as the files are stored; the meeting page follows the analysis live.
		form.append('background', 'true');

		busy = true;
		try {
			const run = await api.createDraft(form);
			draftsChanged();
			await goto(`/drafts/${run.id}`);
		} catch (e) {
			error = errorText(e);
		} finally {
			busy = false;
		}
	}
</script>

<div class="page">
		<header class="head">
			<h1>New minutes</h1>
			<p class="muted">
				Add the agenda and transcript. You will check how the discussion maps to the agenda, then the
				first draft is written against the {profileName}.
			</p>
		</header>

		<form class="card form" onsubmit={submit}>
			<div class="drops">
				<FileDrop label="Agenda" bind:files={agenda} />
				<FileDrop label="Transcript" bind:files={transcript} />
			</div>

			<div class="more">
				{#if showMore}
					<div class="extra" transition:slide={{ duration: 160 }}>
						<FileDrop label="Meeting notes" compact bind:files={notes} />
						<FileDrop label="Supporting papers" compact multiple bind:files={papers} />
					</div>
				{/if}
				{#if showDetails}
					<div class="details" transition:slide={{ duration: 160 }}>
						<label class="field">
							Organisation
							<input type="text" bind:value={organisation} placeholder="e.g. VeriFocal plc" />
						</label>
						<label class="field">
							Board or committee
							<input type="text" bind:value={bodyName} placeholder="e.g. Board of Directors" />
						</label>
						<label class="field">
							Meeting date
							<input type="text" bind:value={meetingDate} placeholder="e.g. 5 November 2026" />
						</label>
						{#if usable.length > 1}
							<label class="field profile">
								Minutes profile
								<select bind:value={profileSlug}>
									{#each usable as p (p.slug)}
										<option value={p.slug}>{p.name} (v{p.active_version})</option>
									{/each}
								</select>
							</label>
						{/if}
					</div>
				{/if}
				<div class="adders">
					{#if !showMore}
						<button type="button" class="link-btn" onclick={() => (showMore = true)}>
							<Icon name="plus" size={14} />
							Add meeting notes or papers
						</button>
					{/if}
					{#if !showDetails}
						<button type="button" class="link-btn" onclick={() => (showDetails = true)}>
							<Icon name="plus" size={14} />
							Add meeting details
						</button>
					{/if}
					{#if !showMore && extras}<span class="tiny muted">{extras} files added</span>{/if}
					{#if !showDetails && details}<span class="tiny muted">{details} details added</span>{/if}
				</div>
			</div>

			{#if error}<p class="alert error">{error}</p>{/if}

			<div class="actions">
				<span class="tiny muted">.docx, .txt, .md or .vtt</span>
				<button class="btn primary lg" type="submit" disabled={!ready || busy}>
					{#if busy}<span class="spinner"></span> Uploading{:else}Analyse meeting <Icon name="arrowRight" />{/if}
				</button>
			</div>
		</form>
</div>

<style>
	.page {
		max-width: 760px;
		margin: 0 auto;
		display: flex;
		flex-direction: column;
		gap: 1.5rem;
	}

	.head {
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}

	.head p {
		max-width: 60ch;
	}

	.form {
		display: flex;
		flex-direction: column;
		gap: 1.1rem;
		padding: 1.5rem;
	}

	.drops {
		display: grid;
		/* minmax(0, 1fr) lets columns shrink below long filenames, which then truncate. */
		grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
		gap: 1rem;
	}

	.more {
		display: flex;
		flex-direction: column;
		gap: 0.9rem;
	}

	.adders {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.5rem 1.5rem;
	}

	.extra {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
		gap: 0.75rem;
	}

	.details {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 0.9rem;
	}

	.details .profile {
		grid-column: 1 / -1;
		max-width: 360px;
	}

	.actions {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		padding-top: 0.25rem;
	}

	@media (max-width: 640px) {
		.drops,
		.extra,
		.details {
			grid-template-columns: 1fr;
		}
	}
</style>

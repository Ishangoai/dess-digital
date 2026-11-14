<script lang="ts">
	import { onMount } from 'svelte';
	import { slide } from 'svelte/transition';
	import { goto } from '$app/navigation';
	import { api, draftsChanged, errorText, type ProfileSummary } from '#lib/api.ts';
	import FileDrop from '#lib/components/FileDrop.svelte';
	import Icon from '#lib/components/Icon.svelte';
	import Working from '#lib/components/Working.svelte';

	let agenda = $state<File[]>([]);
	let transcript = $state<File[]>([]);
	let notes = $state<File[]>([]);
	let papers = $state<File[]>([]);
	let showMore = $state(false);
	let showOptions = $state(false);

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

	const ready = $derived(agenda.length > 0 && transcript.length > 0);
	const extras = $derived(notes.length + papers.length);
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
			draftsChanged();
			await goto(`/drafts/${run.id}`);
		} catch (e) {
			error = errorText(e);
		} finally {
			window.clearInterval(timer);
			busy = false;
		}
	}
</script>

<div class="page">
	{#if busy}
		<div class="working-wrap">
			<Working
				title={autoConfirm ? 'Analysing and drafting' : 'Reading the meeting'}
				message={autoConfirm
					? 'Mapping the discussion to the agenda, then writing and checking the minutes.'
					: 'Working out which parts of the discussion belong to each agenda item.'}
				seconds={elapsed}
				note="A short meeting takes under a minute; a long board meeting can take a few. Keep this tab open."
			/>
		</div>
	{:else}
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
				{:else}
					<button type="button" class="link-btn" onclick={() => (showMore = true)}>
						<Icon name="plus" size={14} />
						Add meeting notes or papers
					</button>
				{/if}
				{#if !showMore && extras}<span class="tiny muted">{extras} added</span>{/if}
			</div>

			<div class="divider"></div>

			<div class="details">
				<label class="field">
					<span>Organisation <span class="opt">optional</span></span>
					<input type="text" bind:value={organisation} placeholder="e.g. VeriFocal plc" />
				</label>
				<label class="field">
					<span>Board or committee <span class="opt">optional</span></span>
					<input type="text" bind:value={bodyName} placeholder="e.g. Board of Directors" />
				</label>
				<label class="field">
					<span>Meeting date <span class="opt">optional</span></span>
					<input type="text" bind:value={meetingDate} placeholder="e.g. 5 November 2026" />
				</label>
			</div>

			<details class="options" bind:open={showOptions}>
				<summary class="link-btn muted-link">
					<Icon name={showOptions ? 'chevronDown' : 'chevronRight'} size={14} />
					More options
				</summary>
				<div class="options-body">
					<label class="field">
						Minutes profile
						{#if profiles.length}
							<select bind:value={profileSlug}>
								{#each profiles as p (p.slug)}
									<option value={p.slug} disabled={p.active_version === null}>
										{p.name}{p.active_version ? ` (v${p.active_version})` : ' (no confirmed version)'}
									</option>
								{/each}
							</select>
						{:else}
							<input type="text" bind:value={profileSlug} />
						{/if}
					</label>
					<label class="field">
						<span>Meeting type <span class="opt">optional</span></span>
						<input type="text" bind:value={meetingType} placeholder="e.g. board" />
					</label>
					<label class="check">
						<input type="checkbox" bind:checked={autoConfirm} />
						<span>
							Skip the mapping check
							<span class="tiny muted">Draft straight away, without reviewing the mapping first.</span>
						</span>
					</label>
				</div>
			</details>

			{#if error}<p class="alert error">{error}</p>{/if}

			<div class="actions">
				<span class="tiny muted">.docx, .txt, .md or .vtt</span>
				<button class="btn primary lg" type="submit" disabled={!ready}>
					{autoConfirm ? 'Analyse and draft' : 'Analyse meeting'}
					<Icon name="arrowRight" />
				</button>
			</div>
		</form>
	{/if}
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
		grid-template-columns: 1fr 1fr;
		gap: 1rem;
	}

	.more {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: 0.4rem;
	}

	.extra {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 0.75rem;
		width: 100%;
	}

	.divider {
		height: 1px;
		background: var(--border);
		margin: 0.25rem 0;
	}

	.details {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 0.9rem;
	}

	.muted-link {
		color: var(--muted);
	}

	.options-body {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 0.9rem;
		margin-top: 0.9rem;
	}

	.check {
		grid-column: 1 / -1;
		display: flex;
		align-items: flex-start;
		gap: 0.6rem;
		font-size: 0.86rem;
		color: var(--text-2);
	}

	.check input {
		margin-top: 0.2rem;
	}

	.check span {
		display: flex;
		flex-direction: column;
	}

	.actions {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		padding-top: 0.25rem;
	}

	.working-wrap {
		margin-top: 2rem;
	}

	@media (max-width: 640px) {
		.drops,
		.extra,
		.details,
		.options-body {
			grid-template-columns: 1fr;
		}
	}
</style>

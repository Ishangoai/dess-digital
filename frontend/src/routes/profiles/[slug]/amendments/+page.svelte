<script lang="ts">
	import { invalidate } from '$app/navigation';
	import { api, errorText, formatDate, type AmendmentSetOut, type ProposalOut } from '#lib/api.ts';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	let profile = $derived(data.profile);
	let sets = $state<AmendmentSetOut[]>([]);

	$effect(() => {
		sets = data.sets;
	});

	let busy = $state(false);
	let errors = $state<Record<string, string>>({});
	let messages = $state<Record<string, string>>({});

	// Per-proposal reword state
	let rewordingId = $state<string | null>(null);
	let rewordText = $state('');

	function startReword(p: ProposalOut) {
		rewordingId = p.id;
		rewordText = p.proposed_text ?? '';
	}

	function cancelReword() {
		rewordingId = null;
		rewordText = '';
	}

	async function decide(
		slug: string,
		setId: string,
		proposalId: string,
		status: 'accepted' | 'rejected' | 'deferred',
		proposedText?: string
	) {
		busy = true;
		errors[proposalId] = '';
		try {
			const body: { status: 'accepted' | 'rejected' | 'deferred'; proposed_text?: string; decided_by: string } = {
				status,
				decided_by: 'governance-professional'
			};
			if (proposedText !== undefined) body.proposed_text = proposedText;
			await api.updateProposal(slug, setId, proposalId, body);
			rewordingId = null;
			// Refresh sets from server
			sets = await api.listAmendmentSets(slug);
		} catch (e) {
			errors[proposalId] = errorText(e);
		} finally {
			busy = false;
		}
	}

	async function applySet(slug: string, setId: string, confirmedBy: string) {
		busy = true;
		errors[setId] = '';
		messages[setId] = '';
		try {
			const newVersion = await api.applyAmendmentSet(slug, setId, confirmedBy || null);
			messages[setId] = `Created version v${newVersion.version_number} (${newVersion.status}). Change summary: ${newVersion.change_summary ?? 'No change summary'}`;
			await invalidate('app:amendments');
			sets = await api.listAmendmentSets(slug);
		} catch (e) {
			errors[setId] = errorText(e);
		} finally {
			busy = false;
		}
	}

	const OP_LABEL: Record<string, string> = { add: 'ADD', replace: 'REPLACE', remove: 'REMOVE' };
	const KIND_LABEL: Record<string, string> = {
		evidential_fundamental: 'Evidential fundamental',
		requirement: 'Requirement',
		professional_default: 'Professional default',
		preference: 'Preference'
	};
	const PROV_LABEL: Record<string, string> = {
		dess_standard: 'DESS standard',
		inferred: 'Inferred',
		explicit_requirement: 'Explicit requirement',
		professional_preference: 'Professional preference'
	};
</script>

<div class="stack contained">
	<div>
		<a class="small" href="/profiles/{profile.slug}">← {profile.name}</a>
		<h1>Amendment proposals</h1>
		<p class="muted">
			Review, reword, and decide on granular amendment proposals before confirming them into a new profile version.
		</p>
	</div>

	{#if sets.length === 0}
		<section class="card">
			<p class="muted">No amendment proposal sets submitted for this profile yet.</p>
		</section>
	{:else}
		{#each sets as aset (aset.id)}
			<section class="card stack">
				<div class="set-header row">
					<div>
						<h2>{aset.title ?? 'Amendment Proposal Set'}</h2>
						<span class="badge origin">{aset.origin}</span>
					</div>
					<span class="muted small">{formatDate(aset.created_at)}{aset.created_by ? ` · ${aset.created_by}` : ''}</span>
				</div>

				<div class="proposals-list stack">
					{#each aset.proposals as proposal (proposal.id)}
						<div class="proposal" class:decided={proposal.status !== 'proposed'}>
							<div class="prop-header row">
								<span class="badge dim mono">{proposal.target_dimension}</span>
								<span class="badge op op-{proposal.operation}">{OP_LABEL[proposal.operation] ?? proposal.operation}</span>
								{#if proposal.target_provision}
									<code class="small">{proposal.target_provision}</code>
								{/if}
								{#if proposal.scope}
									<span class="muted small">· {proposal.scope}</span>
								{/if}
								<span class="spacer"></span>
								<span class="badge status-{proposal.status}">{proposal.status}</span>
							</div>

							{#if proposal.kind || proposal.provenance}
								<div class="badges">
									{#if proposal.kind}
										<span class="badge kind">{KIND_LABEL[proposal.kind] ?? proposal.kind}</span>
									{/if}
									{#if proposal.provenance}
										<span class="badge prov">{PROV_LABEL[proposal.provenance] ?? proposal.provenance}</span>
									{/if}
								</div>
							{/if}

							{#if proposal.conflict_warning}
								<div class="alert warn conflict-warning">
									<strong>⚠️ Conflict Warning:</strong> {proposal.conflict_warning}
								</div>
							{/if}

							{#if rewordingId === proposal.id}
								<div class="reword-box stack">
									<label class="field">
										Reword proposal (plain English)
										<textarea rows="3" bind:value={rewordText}></textarea>
									</label>
									<div class="row">
										<button
											class="btn primary small"
											disabled={busy}
											onclick={() =>
												decide(profile.slug, aset.id, proposal.id, 'accepted', rewordText)}
										>
											Save & Accept
										</button>
										<button class="btn small" disabled={busy} onclick={cancelReword}>Cancel</button>
									</div>
								</div>
							{:else}
								{#if proposal.proposed_text}
									<p class="proposed-text">{proposal.proposed_text}</p>
								{:else}
									<p class="muted small"><em>Remove provision</em></p>
								{/if}
							{/if}

							{#if proposal.reason || proposal.evidence}
								<details class="evidence-details">
									<summary class="small muted">Reason & Evidence</summary>
									{#if proposal.reason}
										<p class="small"><strong>Reason:</strong> {proposal.reason}</p>
									{/if}
									{#if proposal.evidence}
										<p class="small muted"><strong>Evidence:</strong> {proposal.evidence}</p>
									{/if}
								</details>
							{/if}

							{#if proposal.status !== 'proposed'}
								<p class="small muted decided-info">
									{proposal.status} by {proposal.decided_by ?? 'governance-professional'} on {formatDate(proposal.decided_at)}
								</p>
							{:else}
								<div class="controls row">
									<button
										class="btn primary small"
										disabled={busy}
										onclick={() => decide(profile.slug, aset.id, proposal.id, 'accepted')}
									>
										Accept
									</button>
									<button
										class="btn small"
										disabled={busy}
										onclick={() => startReword(proposal)}
									>
										Reword
									</button>
									<button
										class="btn danger small"
										disabled={busy}
										onclick={() => decide(profile.slug, aset.id, proposal.id, 'rejected')}
									>
										Reject
									</button>
									<button
										class="btn small"
										disabled={busy}
										onclick={() => decide(profile.slug, aset.id, proposal.id, 'deferred')}
									>
										Defer
									</button>
								</div>
							{/if}

							{#if errors[proposal.id]}
								<p class="alert error small">{errors[proposal.id]}</p>
							{/if}
						</div>
					{/each}
				</div>

				<!-- Apply section -->
				<div class="apply-section stack">
					{#if messages[aset.id]}
						<div class="alert ok">{messages[aset.id]}</div>
					{/if}
					{#if errors[aset.id]}
						<div class="alert error">{errors[aset.id]}</div>
					{/if}
					{#if aset.proposals.some((p) => p.status === 'accepted')}
						{@const acceptedCount = aset.proposals.filter((p) => p.status === 'accepted').length}
						<div class="row apply-row">
							<button
								class="btn primary"
								disabled={busy}
								onclick={() => applySet(profile.slug, aset.id, 'governance-professional')}
							>
								Create new profile version ({acceptedCount} accepted proposal{acceptedCount === 1 ? '' : 's'})
							</button>
						</div>
					{:else}
						<p class="muted small">
							No proposals have been accepted in this set yet. Accept one or more proposals above to compile a new profile version.
						</p>
					{/if}
				</div>
			</section>
		{/each}
	{/if}
</div>

<style>
	.set-header {
		justify-content: space-between;
		align-items: flex-start;
		flex-wrap: wrap;
		gap: 0.5rem;
		border-bottom: 1px solid var(--border, #e0e0e0);
		padding-bottom: 0.5rem;
	}

	.set-header h2 {
		margin: 0;
		font-size: 1.2rem;
		display: inline-block;
		margin-right: 0.5rem;
	}

	.proposals-list {
		gap: 0.75rem;
	}

	.proposal {
		border: 1px solid var(--border, #e0e0e0);
		border-radius: 6px;
		padding: 0.85rem;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		background: var(--bg-1, #fff);
	}

	.proposal.decided {
		opacity: 0.8;
	}

	.prop-header {
		align-items: center;
		flex-wrap: wrap;
		gap: 0.4rem;
	}

	.spacer {
		flex: 1;
	}

	.badge {
		font-size: 0.72rem;
		font-weight: 600;
		padding: 0.1rem 0.45rem;
		border-radius: 4px;
		white-space: nowrap;
	}

	.badge.dim {
		background: var(--accent-soft);
		color: var(--text-1, currentColor);
	}

	.badge.origin {
		background: var(--accent-soft);
		color: var(--text-2);
		font-weight: 500;
	}

	.badge.op-add {
		background: #d1fae5;
		color: #065f46;
	}
	.badge.op-replace {
		background: #dbeafe;
		color: #1e40af;
	}
	.badge.op-remove {
		background: #fee2e2;
		color: #991b1b;
	}

	.badge.status-proposed {
		background: #f3f4f6;
		color: #374151;
	}
	.badge.status-accepted {
		background: var(--ok-bg);
		color: var(--ok-fg);
	}
	.badge.status-rejected {
		background: var(--error-bg, #fee2e2);
		color: var(--error-fg, #991b1b);
	}
	.badge.status-deferred {
		background: #fef9c3;
		color: #854d0e;
	}

	.badge.kind {
		background: #f3f4f6;
		color: #374151;
	}
	.badge.prov {
		background: #ede9fe;
		color: #5b21b6;
	}

	.badges {
		display: flex;
		gap: 0.3rem;
		flex-wrap: wrap;
	}

	.conflict-warning {
		font-size: 0.875rem;
		border-radius: 4px;
		padding: 0.5rem 0.75rem;
	}

	.proposed-text {
		margin: 0;
		font-size: 0.95rem;
		padding: 0.5rem 0.75rem;
		background: var(--accent-soft);
		border-radius: 4px;
		white-space: pre-wrap;
	}

	.evidence-details {
		font-size: 0.875rem;
	}

	.evidence-details p {
		margin: 0.25rem 0 0 1rem;
	}

	.reword-box {
		background: var(--accent-soft);
		padding: 0.75rem;
		border-radius: 6px;
	}

	.controls {
		gap: 0.4rem;
		flex-wrap: wrap;
	}

	.btn.danger {
		background: var(--error-bg, #fee2e2);
		color: var(--error-fg, #991b1b);
		border: 1px solid var(--error-fg, #991b1b);
	}

	.btn.danger:hover:not(:disabled) {
		background: var(--error-fg, #991b1b);
		color: white;
	}

	.decided-info {
		margin: 0;
	}

	.apply-section {
		border-top: 1px solid var(--border, #e0e0e0);
		padding-top: 0.75rem;
		margin-top: 0.25rem;
	}

	.apply-row {
		margin-top: 0.25rem;
	}

	textarea {
		width: 100%;
		font-family: inherit;
		font-size: 0.95rem;
		padding: 0.4rem;
		border: 1px solid var(--border, #ccc);
		border-radius: 4px;
		resize: vertical;
		box-sizing: border-box;
	}

	p {
		margin: 0;
	}
</style>

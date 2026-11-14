<script lang="ts">
	import type { ClarificationQuestion, DraftMinutes } from '#lib/api.ts';

	let {
		draft,
		active = null,
		onselect
	}: {
		draft: DraftMinutes;
		active?: string | null;
		onselect?: (questionId: string) => void;
	} = $props();

	const number = $derived(new Map(draft.questions.map((q, i) => [q.question_id, i + 1])));
	const meetingQuestions = $derived(draft.questions.filter((q) => q.anchor_kind === 'meeting_heading'));
	const itemQuestions = (ref: string) =>
		draft.questions.filter((q) => q.anchor_kind === 'item_heading' && q.item_ref === ref);
	const paragraphQuestions = (id: string) =>
		draft.questions.filter((q) => q.anchor_kind === 'paragraph' && q.paragraph_id === id);

	// Split a paragraph so each question's anchor text can be highlighted (first occurrence).
	function parts(text: string, questions: ClarificationQuestion[]) {
		let out: { text: string; qid?: string }[] = [{ text }];
		for (const q of questions) {
			if (!q.anchor_text) continue;
			const next: typeof out = [];
			let placed = false;
			for (const part of out) {
				const at = part.qid || placed ? -1 : part.text.indexOf(q.anchor_text);
				if (at < 0) {
					next.push(part);
					continue;
				}
				placed = true;
				if (at > 0) next.push({ text: part.text.slice(0, at) });
				next.push({ text: q.anchor_text, qid: q.question_id });
				const rest = part.text.slice(at + q.anchor_text.length);
				if (rest) next.push({ text: rest });
			}
			out = next;
		}
		return out;
	}

	// Questions whose anchor text was not found are flagged at the end of the paragraph.
	function unplaced(text: string, questions: ClarificationQuestion[]) {
		const placed = new Set(parts(text, questions).map((p) => p.qid).filter(Boolean));
		return questions.filter((q) => !placed.has(q.question_id));
	}

	const h = $derived(draft.header);
</script>

{#snippet flags(list: ClarificationQuestion[])}
	{#each list as q (q.question_id)}
		<button
			id="q-{q.question_id}"
			class="flag"
			class:active={active === q.question_id}
			onclick={() => onselect?.(q.question_id)}
			title={q.question}
		>
			{number.get(q.question_id)}
		</button>
	{/each}
{/snippet}

<article class="minutes">
	<header class="m-head">
		<h1>{h.title} {@render flags(meetingQuestions)}</h1>
		{#if h.meeting_date || h.time_and_place}
			<p class="when">{[h.meeting_date, h.time_and_place].filter(Boolean).join(' · ')}</p>
		{/if}
		<dl>
			{#each [['Present', h.present], ['In attendance', h.in_attendance], ['Apologies', h.apologies]] as const as [label, names] (label)}
				{#if names.length}
					<dt>{label}</dt>
					<dd>{names.join(', ')}</dd>
				{/if}
			{/each}
		</dl>
	</header>

	{#each draft.items as item (item.item_ref)}
		<section>
			<h2><span class="num">{item.item_ref}</span> {item.heading} {@render flags(itemQuestions(item.item_ref))}</h2>
			{#each item.paragraphs as p (p.paragraph_id)}
				{@const mine = paragraphQuestions(p.paragraph_id)}
				<p class:outcome={p.kind === 'outcome'}>
					{#each parts(p.text, mine) as part, i (i)}
						{#if part.qid}
							<button
								id="q-{part.qid}"
								class="anchor"
								class:active={active === part.qid}
								onclick={() => onselect?.(part.qid!)}
							>{part.text}<sup>{number.get(part.qid)}</sup></button>
						{:else}{part.text}{/if}
					{/each}
					{@render flags(unplaced(p.text, mine))}
				</p>
			{/each}
		</section>
	{/each}

	{#if draft.actions.length}
		<section>
			<h2>Actions</h2>
			<table>
				<thead><tr><th>Action</th><th>Owner</th><th>Due</th></tr></thead>
				<tbody>
					{#each draft.actions as a (a.action_id)}
						<tr>
							<td>{a.text}</td>
							<td class:open={!a.owner}>{a.owner ?? 'Not agreed'}</td>
							<td class:open={!a.due}>{a.due ?? 'Not agreed'}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</section>
	{/if}
</article>

<style>
	.minutes {
		font-family: var(--serif);
		font-size: 1.02rem;
		line-height: 1.65;
		color: #1f2328;
	}

	.m-head {
		padding-bottom: 1.25rem;
		margin-bottom: 0.5rem;
		border-bottom: 1px solid var(--border);
	}

	h1 {
		font-family: var(--serif);
		font-size: 1.55rem;
		font-weight: 600;
		letter-spacing: 0;
		margin-bottom: 0.4rem;
	}

	.when {
		color: var(--muted);
		margin-bottom: 0.9rem;
	}

	dl {
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: 0.3rem 1rem;
		margin: 0;
		font-size: 0.95rem;
	}

	dt {
		font-family: var(--font);
		font-size: 0.72rem;
		font-weight: 600;
		letter-spacing: 0.05em;
		text-transform: uppercase;
		color: var(--muted);
		padding-top: 0.2rem;
	}

	dd {
		margin: 0;
	}

	h2 {
		font-family: var(--serif);
		font-size: 1.15rem;
		font-weight: 600;
		letter-spacing: 0;
		margin: 1.6rem 0 0.6rem;
	}

	.num {
		display: inline-block;
		min-width: 1.6rem;
		color: var(--muted);
	}

	p {
		margin: 0 0 0.7rem;
	}

	.outcome {
		font-weight: 600;
	}

	.anchor {
		all: unset;
		background: var(--mark-soft);
		border-bottom: 2px solid var(--mark);
		cursor: pointer;
		border-radius: 2px;
		scroll-margin: 6rem;
	}

	.anchor.active {
		background: var(--mark);
		border-color: var(--warn);
	}

	sup {
		font-family: var(--font);
		font-size: 0.62rem;
		font-weight: 700;
		color: var(--warn-fg);
		margin-left: 0.1rem;
	}

	.flag {
		display: inline-grid;
		place-items: center;
		vertical-align: middle;
		width: 1.25rem;
		height: 1.25rem;
		margin-left: 0.3rem;
		padding: 0;
		border: none;
		border-radius: 50%;
		background: var(--mark);
		color: var(--warn-fg);
		font-family: var(--font);
		font-size: 0.66rem;
		font-weight: 700;
		cursor: pointer;
		scroll-margin: 6rem;
	}

	.flag.active {
		background: var(--warn);
		color: #fff;
	}

	table {
		font-family: var(--font);
		font-size: 0.86rem;
		margin-top: 0.25rem;
	}

	td.open {
		color: var(--faint);
		font-style: italic;
	}
</style>

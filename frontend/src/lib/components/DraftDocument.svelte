<script lang="ts">
	import type { ClarificationQuestion, DraftMinutes } from '#lib/api.ts';

	let { draft }: { draft: DraftMinutes } = $props();

	const meetingQuestions = $derived(
		draft.questions.filter((q) => q.anchor_kind === 'meeting_heading')
	);
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

	const h = $derived(draft.header);
</script>

{#snippet questions(list: ClarificationQuestion[])}
	{#each list as q (q.question_id)}
		<aside class="question"><span class="qid">{q.question_id}</span> {q.question}</aside>
	{/each}
{/snippet}

<article class="minutes">
	<h1>{h.title}</h1>
	{#if h.meeting_date}<p>{h.meeting_date}</p>{/if}
	{#if h.time_and_place}<p>{h.time_and_place}</p>{/if}
	{#each [['Present', h.present], ['In attendance', h.in_attendance], ['Apologies', h.apologies]] as const as [label, names] (label)}
		{#if names.length}<p><strong>{label}:</strong> {names.join(', ')}</p>{/if}
	{/each}
	{@render questions(meetingQuestions)}

	{#each draft.items as item (item.item_ref)}
		<section>
			<h2>{item.item_ref} {item.heading}</h2>
			{@render questions(itemQuestions(item.item_ref))}
			{#each item.paragraphs as p (p.paragraph_id)}
				{@const mine = paragraphQuestions(p.paragraph_id)}
				<p class:outcome={p.kind === 'outcome'} title={p.paragraph_id}>
					{#each parts(p.text, mine) as part, i (i)}
						{#if part.qid}<mark title={part.qid}>{part.text}<sup>{part.qid}</sup></mark>{:else}{part.text}{/if}
					{/each}
				</p>
				{@render questions(mine)}
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
							<td>{a.owner ?? 'Owner not agreed'}</td>
							<td>{a.due ?? '-'}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</section>
	{/if}
</article>

<style>
	.minutes {
		font-family: Georgia, 'Times New Roman', serif;
		font-size: 1rem;
		line-height: 1.6;
	}

	.minutes h1 {
		font-size: 1.4rem;
	}

	.minutes h2 {
		font-size: 1.1rem;
		margin-top: 1.5rem;
	}

	.minutes p {
		margin: 0 0 0.6rem;
	}

	.outcome {
		font-weight: 600;
	}

	mark {
		background: var(--mark);
		padding: 0 0.1rem;
		border-radius: 2px;
	}

	sup {
		font-family: system-ui, sans-serif;
		font-size: 0.65rem;
		margin-left: 0.15rem;
	}

	.question {
		font-family: system-ui, sans-serif;
		font-size: 0.85rem;
		border-left: 3px solid var(--warn-fg);
		background: var(--warn-bg);
		color: var(--warn-fg);
		padding: 0.4rem 0.75rem;
		margin: 0 0 0.75rem;
		border-radius: 0 6px 6px 0;
	}

	.qid {
		font-weight: 700;
	}

	table {
		font-family: system-ui, sans-serif;
	}
</style>

<script lang="ts">
	import { slide } from 'svelte/transition';
	import {
		api,
		compact,
		errorText,
		isRunning,
		STAGE_INFO,
		type DraftRun,
		type LLMCallDetail
	} from '#lib/api.ts';
	import Icon from '#lib/components/Icon.svelte';
	import JsonView from '#lib/components/JsonView.svelte';
	import PromptBlock from '#lib/components/PromptBlock.svelte';
	import { parseMessage, parseSystem } from '#lib/prompt.ts';

	let { run, onclose }: { run: DraftRun; onclose: () => void } = $props();

	let calls = $state<LLMCallDetail[]>([]);
	let error = $state('');
	let expanded = $state<string | null>(null);
	let raw = $state(false);

	// Reload whenever the run reloads (the layout polls while a stage runs).
	$effect(() => {
		const id = run.id;
		void run.llm_calls.length;
		void run.status;
		api
			.getCalls(id)
			.then((c) => {
				calls = c;
				error = '';
			})
			.catch((e) => (error = errorText(e)));
	});

	const total = $derived(calls.reduce((n, c) => n + c.input_tokens + c.output_tokens, 0));
	const model = $derived(calls[0]?.model ?? '');
	const seconds = (ms: number) => `${(ms / 1000).toFixed(1)}s`;

	function sections(c: LLMCallDetail) {
		const message = c.prompt ? parseMessage(c.prompt) : [];
		return {
			system: c.system_prompt ? parseSystem(c.system_prompt) : [],
			context: message.filter((s) => s.kind === 'meeting' || s.kind === 'evidence'),
			rest: message.filter((s) => s.kind !== 'meeting' && s.kind !== 'evidence')
		};
	}

	function output(c: LLMCallDetail) {
		const text = c.output ?? c.raw_output;
		if (!text) return null;
		try {
			const value = JSON.parse(text);
			return { text: JSON.stringify(value, null, 2), value };
		} catch {
			return { text, value: null };
		}
	}

	function toggle(id: string) {
		expanded = expanded === id ? null : id;
		raw = false;
	}

	function download() {
		const blob = new Blob([JSON.stringify({ run_id: run.id, title: run.title, calls }, null, 2)], {
			type: 'application/json'
		});
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = `ai-activity-${run.id.slice(0, 8)}.json`;
		a.click();
		URL.revokeObjectURL(url);
	}
</script>

<aside class="panel" aria-label="AI activity">
	<header class="head">
		<div class="title">
			<h2><Icon name="eye" size={16} /> AI activity</h2>
			<p class="tiny muted">
				{#if calls.length}
					{calls.length} call{calls.length === 1 ? '' : 's'} · {compact(total)} tokens{model ? ` · ${model}` : ''}
				{:else}
					What the model is sent and returns
				{/if}
			</p>
		</div>
		<button class="btn sm" onclick={download} disabled={!calls.length} title="Download every call as JSON">
			<Icon name="download" size={14} /> Download
		</button>
		<button class="btn ghost sm" onclick={onclose} aria-label="Close AI activity">
			<Icon name="x" size={16} />
		</button>
	</header>

	<div class="body">
		{#if error}<p class="alert error small">{error}</p>{/if}

		<ol class="calls">
			{#each calls as c, i (c.id)}
				{@const open = expanded === c.id}
				<li class="call" class:open>
					<button class="row" onclick={() => toggle(c.id)} aria-expanded={open}>
						<span class="n" class:ok={c.ok}>
							<Icon name={c.ok ? 'check' : 'x'} size={11} />
						</span>
						<span class="label">{i + 1}. {STAGE_INFO[c.stage]?.label ?? c.stage}</span>
						<span class="meta">{compact(c.input_tokens)} → {compact(c.output_tokens)} · {seconds(c.latency_ms)}</span>
						<Icon name="chevronDown" size={14} />
					</button>

					{#if open}
						{@const s = sections(c)}
						{@const out = output(c)}
						<div class="detail" transition:slide={{ duration: 150 }}>
							{#if !c.ok}<p class="alert error small">{c.error}</p>{/if}
							{#if !c.prompt && !c.system_prompt}
								<p class="small muted">The full prompt was not stored for this call.</p>
							{:else}
								<span class="eyebrow">Sent</span>
								{#if s.system.length}
									<PromptBlock title="Instructions" badge="Same every call" tone="instructions" text={c.system_prompt ?? ''}>
										<div class="nest">
											{#each s.system as part (part.key)}
												<PromptBlock title={part.title} text={part.text} tone="instructions" />
											{/each}
										</div>
									</PromptBlock>
								{/if}
								{#if s.context.length}
									<PromptBlock
										title="Evidence"
										detail={s.context.filter((x) => x.kind === 'evidence').map((x) => x.title).join(', ')}
										tone="evidence"
										text={s.context.map((x) => x.text).join('\n\n')}
									>
										<div class="nest">
											{#each s.context as part (part.key)}
												<PromptBlock title={part.title} detail={part.detail} text={part.text} tone="evidence" />
											{/each}
										</div>
									</PromptBlock>
								{/if}
								{#each s.rest as part (part.key)}
									<PromptBlock
										title={part.title}
										text={part.text}
										tone={part.kind === 'instructions' || part.kind === 'meeting' ? 'neutral' : part.kind}
										open={part.kind === 'task'}
									/>
								{/each}

								<span class="eyebrow">Returned</span>
								{#if out}
									<PromptBlock title="Output" tone="output" text={out.text} open>
										{#if out.value !== null}
											<div class="switch" role="group" aria-label="Output view">
												<button class:on={!raw} onclick={() => (raw = false)}>Readable</button>
												<button class:on={raw} onclick={() => (raw = true)}>JSON</button>
											</div>
										{/if}
										{#if out.value !== null && !raw}
											<div class="scroll"><JsonView value={out.value} /></div>
										{:else}
											<pre class="scroll">{out.text}</pre>
										{/if}
									</PromptBlock>
								{:else}
									<p class="small muted">Nothing was returned.</p>
								{/if}
							{/if}
						</div>
					{/if}
				</li>
			{/each}
			{#if isRunning(run.status)}
				<li class="call running">
					<div class="row">
						<span class="n"><span class="spinner"></span></span>
						<span class="label">{calls.length + 1}. Working on the next step</span>
					</div>
				</li>
			{/if}
		</ol>

		{#if !calls.length && !isRunning(run.status) && !error}
			<p class="small muted empty">No calls yet.</p>
		{/if}
	</div>
</aside>

<style>
	.panel {
		display: flex;
		flex-direction: column;
		height: 100%;
		background: var(--surface);
		border-left: 1px solid var(--border);
	}

	.head {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		padding: 0.9rem 0.9rem 0.9rem 1.1rem;
		border-bottom: 1px solid var(--border);
	}

	.title {
		flex: 1;
		min-width: 0;
	}

	h2 {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		font-size: 0.98rem;
	}

	h2 :global(svg) {
		color: var(--accent);
	}

	.title p {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.body {
		flex: 1;
		overflow-y: auto;
		padding: 0.75rem;
	}

	.calls {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}

	.call {
		border: 1px solid var(--border);
		border-radius: var(--radius-sm);
		background: var(--surface);
	}

	.call.open {
		box-shadow: var(--shadow-sm);
	}

	.row {
		all: unset;
		box-sizing: border-box;
		display: flex;
		align-items: center;
		gap: 0.55rem;
		width: 100%;
		padding: 0.6rem 0.7rem;
		cursor: pointer;
		font-size: 0.86rem;
	}

	.row:focus-visible {
		outline: 2px solid var(--accent);
		border-radius: var(--radius-sm);
	}

	.row :global(svg:last-child) {
		color: var(--faint);
		transition: transform 0.15s;
	}

	.open .row :global(svg:last-child) {
		transform: rotate(180deg);
	}

	.running .row {
		cursor: default;
		color: var(--accent);
	}

	.n {
		display: grid;
		place-items: center;
		flex-shrink: 0;
		width: 1.2rem;
		height: 1.2rem;
		border-radius: 50%;
		background: var(--err-bg);
		color: var(--err);
	}

	.n.ok {
		background: var(--ok-bg);
		color: var(--ok);
	}

	.running .n {
		background: var(--accent-soft);
		color: var(--accent);
	}

	.running .spinner {
		width: 0.65rem;
		height: 0.65rem;
	}

	.label {
		flex: 1;
		font-weight: 500;
	}

	.meta {
		font-size: 0.74rem;
		color: var(--muted);
		white-space: nowrap;
	}

	.detail {
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
		padding: 0.25rem 0.7rem 0.8rem;
		border-top: 1px solid var(--border);
	}

	.eyebrow {
		margin-top: 0.5rem;
	}

	.nest {
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
	}

	.switch {
		display: inline-flex;
		padding: 2px;
		margin-bottom: 0.6rem;
		border: 1px solid var(--border);
		border-radius: var(--radius-sm);
		background: var(--surface-2);
	}

	.switch button {
		font: inherit;
		font-size: 0.76rem;
		padding: 0.2rem 0.65rem;
		border: none;
		border-radius: 6px;
		background: transparent;
		color: var(--muted);
		cursor: pointer;
	}

	.switch button.on {
		background: var(--surface);
		color: var(--text);
		box-shadow: var(--shadow-sm);
	}

	.scroll {
		max-height: 520px;
		overflow: auto;
	}

	pre.scroll {
		margin: 0;
		white-space: pre-wrap;
		word-break: break-word;
		font-family: var(--mono);
		font-size: 0.74rem;
		line-height: 1.55;
	}

	.empty {
		padding: 0.5rem;
	}
</style>

<script lang="ts">
	import JsonView from '#lib/components/JsonView.svelte';

	let { value, depth = 0 }: { value: unknown; depth?: number } = $props();

	const label = (key: string) => {
		const s = key.replaceAll('_', ' ');
		return s.charAt(0).toUpperCase() + s.slice(1);
	};
	const isPlain = (v: unknown) => v === null || typeof v !== 'object';
	const isObject = (v: unknown): v is Record<string, unknown> =>
		!!v && typeof v === 'object' && !Array.isArray(v);
	// Short arrays of plain values read best inline.
	const inlineList = (v: unknown[]) => v.every(isPlain) && v.join(', ').length < 120;
	// A one-line title for an object in a list, if it has an obvious one.
	function heading(o: Record<string, unknown>): string {
		for (const k of ['heading', 'question', 'issue', 'text', 'summary', 'description', 'title']) {
			if (typeof o[k] === 'string') return o[k] as string;
		}
		return '';
	}
	function idOf(o: Record<string, unknown>): string {
		for (const [k, v] of Object.entries(o)) if (/(_id|^ref|item_ref)$/.test(k) && typeof v === 'string') return v;
		return '';
	}
</script>

{#if value === null || value === undefined}
	<span class="none">none</span>
{:else if typeof value === 'boolean'}
	<span class="plain">{value ? 'yes' : 'no'}</span>
{:else if typeof value !== 'object'}
	<span class="plain">{String(value)}</span>
{:else if Array.isArray(value)}
	{#if value.length === 0}
		<span class="none">none</span>
	{:else if inlineList(value)}
		<span class="plain">{value.join(', ')}</span>
	{:else}
		<ol class="list">
			{#each value as item, i (i)}
				<li>
					{#if isObject(item)}
						<details open={depth < 1 && value.length <= 12}>
							<summary>
								{#if idOf(item)}<span class="id">{idOf(item)}</span>{/if}
								<span class="head">{heading(item) || `Item ${i + 1}`}</span>
							</summary>
							<div class="nested"><JsonView value={item} depth={depth + 1} /></div>
						</details>
					{:else}
						<JsonView value={item} depth={depth + 1} />
					{/if}
				</li>
			{/each}
		</ol>
	{/if}
{:else}
	<dl class="obj">
		{#each Object.entries(value as Record<string, unknown>) as [k, v] (k)}
			<dt>{label(k)}</dt>
			<dd><JsonView value={v} depth={depth + 1} /></dd>
		{/each}
	</dl>
{/if}

<style>
	.obj {
		display: grid;
		grid-template-columns: minmax(110px, max-content) 1fr;
		gap: 0.35rem 0.9rem;
		margin: 0;
		font-size: 0.84rem;
	}

	dt {
		color: var(--muted);
		font-size: 0.76rem;
		font-weight: 500;
		padding-top: 0.1rem;
	}

	dd {
		margin: 0;
		min-width: 0;
		color: var(--text);
	}

	.plain {
		white-space: pre-wrap;
		word-break: break-word;
	}

	.none {
		color: var(--faint);
		font-style: italic;
	}

	.list {
		margin: 0;
		padding: 0;
		list-style: none;
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
	}

	.list > li {
		border: 1px solid var(--border);
		border-radius: 6px;
		background: var(--surface-2);
	}

	summary {
		display: flex;
		gap: 0.5rem;
		align-items: baseline;
		padding: 0.4rem 0.6rem;
		font-size: 0.82rem;
	}

	.id {
		font-family: var(--mono);
		font-size: 0.72rem;
		color: var(--muted);
		white-space: nowrap;
	}

	.head {
		overflow: hidden;
		text-overflow: ellipsis;
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
	}

	.nested {
		padding: 0.5rem 0.6rem 0.6rem;
		border-top: 1px solid var(--border);
		background: var(--surface);
		border-radius: 0 0 6px 6px;
	}
</style>

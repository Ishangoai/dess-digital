<script lang="ts">
	import { fileSize } from '#lib/api.ts';
	import Icon from '#lib/components/Icon.svelte';

	let {
		label,
		description = '',
		files = $bindable([]),
		multiple = false,
		compact = false,
		accept = '.docx,.txt,.md,.vtt',
		disabled = false
	}: {
		label: string;
		description?: string;
		files?: File[];
		multiple?: boolean;
		compact?: boolean;
		accept?: string;
		disabled?: boolean;
	} = $props();

	let input: HTMLInputElement;
	let over = $state(false);
	const id = $props.id();

	function add(list: FileList | null | undefined) {
		const picked = [...(list ?? [])];
		if (!picked.length) return;
		files = multiple ? [...files, ...picked] : [picked[0]];
	}

	function remove(i: number) {
		files = files.filter((_, j) => j !== i);
		input.value = '';
	}

	function drop(event: DragEvent) {
		event.preventDefault();
		over = false;
		if (!disabled) add(event.dataTransfer?.files);
	}
</script>

<div class="drop" class:compact class:filled={files.length > 0} class:over>
	<input
		bind:this={input}
		{id}
		type="file"
		{accept}
		{multiple}
		{disabled}
		class="visually-hidden"
		aria-label={label}
		onchange={(e) => add(e.currentTarget.files)}
	/>

	{#if files.length && !multiple}
		<div class="file">
			<span class="file-icon"><Icon name="file" size={18} /></span>
			<span class="file-text">
				<span class="eyebrow">{label}</span>
				<span class="name" title={files[0].name}>{files[0].name}</span>
				<span class="tiny muted">{fileSize(files[0].size)}</span>
			</span>
			<button type="button" class="btn ghost sm" onclick={() => remove(0)} {disabled} aria-label="Remove {label}">
				<Icon name="x" size={14} />
			</button>
		</div>
	{:else}
		<label
			for={id}
			class="target"
			ondragover={(e) => {
				e.preventDefault();
				over = true;
			}}
			ondragleave={() => (over = false)}
			ondrop={drop}
		>
			<span class="target-icon"><Icon name="upload" size={compact ? 16 : 20} /></span>
			<span class="target-text">
				<span class="target-label">{label}</span>
				<span class="tiny muted">
					{description || 'Drop a file here or'} <span class="browse">browse</span>
				</span>
			</span>
		</label>
		{#if multiple && files.length}
			<ul class="files">
				{#each files as f, i (f.name + i)}
					<li>
						<Icon name="file" size={14} />
						<span class="name" title={f.name}>{f.name}</span>
						<span class="tiny muted">{fileSize(f.size)}</span>
						<button type="button" class="btn ghost sm" onclick={() => remove(i)} {disabled} aria-label="Remove {f.name}">
							<Icon name="x" size={12} />
						</button>
					</li>
				{/each}
			</ul>
		{/if}
	{/if}
</div>

<style>
	.visually-hidden {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
		white-space: nowrap;
	}

	.drop {
		position: relative;
		border-radius: var(--radius);
	}

	.target {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		text-align: center;
		gap: 0.6rem;
		min-height: 148px;
		padding: 1.25rem;
		border: 1.5px dashed var(--border-strong);
		border-radius: var(--radius);
		background: var(--surface-2);
		cursor: pointer;
		transition:
			border-color 0.15s,
			background 0.15s;
	}

	.target:hover,
	.over .target {
		border-color: var(--accent);
		background: var(--accent-soft);
	}

	.drop:focus-within .target {
		border-color: var(--accent);
		box-shadow: 0 0 0 3px var(--accent-ring);
	}

	.target-icon {
		display: grid;
		place-items: center;
		width: 2.5rem;
		height: 2.5rem;
		border-radius: 50%;
		background: var(--surface);
		border: 1px solid var(--border);
		color: var(--accent);
	}

	.target-text {
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
	}

	.target-label {
		font-weight: 600;
		font-size: 0.92rem;
	}

	.browse {
		color: var(--accent);
		font-weight: 500;
	}

	.compact .target {
		flex-direction: row;
		justify-content: flex-start;
		text-align: left;
		min-height: 0;
		padding: 0.7rem 0.9rem;
	}

	.compact .target-icon {
		width: 2rem;
		height: 2rem;
	}

	.compact .target-label {
		font-size: 0.86rem;
	}

	.file {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		min-height: 148px;
		padding: 1rem 1.1rem;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: var(--surface);
		box-shadow: var(--shadow-sm);
	}

	.compact .file {
		min-height: 0;
		padding: 0.6rem 0.8rem;
	}

	.file-icon {
		display: grid;
		place-items: center;
		width: 2.5rem;
		height: 2.5rem;
		border-radius: 10px;
		background: var(--ok-bg);
		color: var(--ok);
		flex-shrink: 0;
	}

	.compact .file-icon {
		width: 2rem;
		height: 2rem;
	}

	.file-text {
		display: flex;
		flex-direction: column;
		min-width: 0;
		flex: 1;
	}

	.name {
		font-size: 0.88rem;
		font-weight: 500;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.files {
		list-style: none;
		margin: 0.5rem 0 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}

	.files li {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.3rem 0.4rem 0.3rem 0.7rem;
		border: 1px solid var(--border);
		border-radius: var(--radius-sm);
		background: var(--surface);
		color: var(--muted);
	}

	.files .name {
		flex: 1;
		color: var(--text);
		font-size: 0.84rem;
	}
</style>

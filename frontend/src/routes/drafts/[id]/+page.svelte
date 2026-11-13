<script lang="ts">
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
</script>

{#if data.run.status === 'analysing'}
	<p class="muted">The mapping appears here once the analysis finishes.</p>
{:else if !data.run.error && !data.run.blocked_reasons.length}
	<p class="muted">Nothing to review yet.</p>
{/if}

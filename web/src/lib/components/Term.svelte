<script>
	import { glossary } from '$lib/glossary.js';
	let { name = '' } = $props();
	let entry = $derived(glossary.find((g) => g.term.toLowerCase() === name.toLowerCase()));
</script>

{#if entry}
	<span class="term" title={entry.def}>{name}</span>
{:else}
	{name}
{/if}

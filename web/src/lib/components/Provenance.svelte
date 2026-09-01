<script>
	let { text = '' } = $props();
</script>

{#if text}
	<span class="provenance">{text}</span>
{/if}

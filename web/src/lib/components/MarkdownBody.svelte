<script>
	let { html = '' } = $props();
</script>

{#if html}
	<div class="prose">
		{@html html}
	</div>
{/if}

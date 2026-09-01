<script>
	let { tone = 'accent', eyebrow = '', children } = $props();
	let cls = $derived(tone === 'accent' ? '' : tone);
</script>

<div class="callout {cls}">
	{#if eyebrow}<span class="eyebrow">{eyebrow}</span>{/if}
	<p>{@render children?.()}</p>
</div>

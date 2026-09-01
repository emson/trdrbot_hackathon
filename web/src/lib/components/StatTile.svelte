<script>
	let { label = '', value = '', tone = '', provenance = '' } = $props();
</script>

<div class="stat-tile">
	<span class="label">{label}</span>
	<span class="big {tone}">{value}</span>
	{#if provenance}<span class="provenance">{provenance}</span>{/if}
</div>

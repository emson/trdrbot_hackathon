<script>
	let { img = '/img/elf-thinking.jpg', caption = 'Nothing here yet.', sub = '' } = $props();
</script>

<div class="empty-state">
	<div class="plate sm" style="width:96px">
		<img src={img} alt="" width="96" height="80" loading="lazy" />
	</div>
	<p style="font-weight:650; color:var(--ink)">{caption}</p>
	{#if sub}<p class="muted" style="max-width:38ch">{sub}</p>{/if}
</div>

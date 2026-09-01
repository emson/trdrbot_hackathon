<script>
	import { siteConfig } from '$lib/site.config.js';
	import { relativeTime } from '$lib/format.js';

	let { tick = null, generatedAt = '', now = Date.now() } = $props();
</script>

{#if siteConfig.frozen}
	<span class="tick-indicator frozen">
		<span class="tick-dot"></span>
		competition run complete · record final as of {generatedAt ? generatedAt.slice(0, 10) : ''}
	</span>
{:else}
	<span class="tick-indicator">
		<span class="tick-dot"></span>
		tick {tick ?? '?'} · updated {relativeTime(generatedAt, now)}
	</span>
{/if}

<script>
	import { siteConfig } from '$lib/site.config.js';
	let { path = '', sha = '', label = '' } = $props();
	let href = $derived(
		siteConfig.repoUrl ? `${siteConfig.repoUrl}/blob/${sha || 'main'}/${path}` : ''
	);
</script>

{#if href}
	<a class="source-link" {href} target="_blank" rel="noopener noreferrer">{label || path}</a>
{:else}
	<span class="source-link" style="border-bottom-style:none">{label || path}</span>
{/if}

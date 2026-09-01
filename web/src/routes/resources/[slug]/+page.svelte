<script>
	import Icon from '$lib/components/Icon.svelte';

	let { data } = $props();
	let r = $derived(data.resource);
</script>

<svelte:head><title>{r.title} — trdrbot resources</title></svelte:head>

<section class="block ledger" style="padding-bottom:1.2rem">
	<div class="wrap">
		<a href="/resources" class="fine" style="text-decoration:none">&larr; resources</a>
		<div style="display:flex; justify-content:space-between; align-items:flex-end; gap:1rem; flex-wrap:wrap; margin-top:1rem">
			<div>
				<h1 style="font-size:var(--d2)">{r.title}</h1>
				<p class="standfirst" style="margin-top:.5rem">{r.description}</p>
			</div>
			{#if r.fullPageHref && r.embedSrc}
				<a class="btn ghost sm" href={r.fullPageHref} target="_blank" rel="noopener noreferrer">
					Open full-screen <Icon name="external" size={14} />
				</a>
			{/if}
		</div>
	</div>
</section>

{#if r.embedSrc}
	<section class="block ledger" style="padding-top:0">
		<div class="wrap">
			<div class="card" style="padding:0; overflow:hidden">
				<iframe
					src={r.embedSrc}
					title={r.title}
					style="width:100%; height:min(88vh, 1150px); border:0; display:block"
					loading="lazy"
				></iframe>
			</div>
			<p class="fine" style="margin-top:.6rem">
				Scrolls independently — use "Open full-screen" above for more room.
			</p>
		</div>
	</section>
{:else if r.fullPageHref}
	<section class="block ledger" style="padding-top:0">
		<div class="wrap">
			<a class="card pad-lg" href={r.fullPageHref} target="_blank" rel="noopener noreferrer"
				style="flex-direction:row; align-items:center; justify-content:space-between; gap:1rem">
				<span>
					<span class="tag code">Opens in a new tab</span>
					<h3 style="margin-top:.4rem">{r.title}</h3>
				</span>
				<span class="btn primary sm" style="pointer-events:none">Open <Icon name="external" size={14} /></span>
			</a>
		</div>
	</section>
{/if}

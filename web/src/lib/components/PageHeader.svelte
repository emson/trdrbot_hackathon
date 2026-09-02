<script>
	// The kicker + h1 + standfirst trio every page opens with. Pulled out
	// because it had drifted: home and submission hand-rolled it in the
	// brand register with a .lead paragraph while every other page used
	// this exact markup in the ledger register - two visually different
	// headings for the same job. One component means one look, and a new
	// page can't reintroduce the drift by copy-pasting the wrong page.
	let { kicker, back, heading, children } = $props();
</script>

<!-- One element, so a flex/grid parent using `gap` (the homepage hero's
     .stack) treats this as a single item instead of gapping the kicker,
     h1 and standfirst apart from each other too. -->
<div>
	{#if back}
		<a href={back.href} class="fine" style="text-decoration:none">&larr; {back.label}</a>
		<span class="kicker" style="display:block; margin-top:1rem">{kicker}</span>
	{:else}
		<span class="kicker">{kicker}</span>
	{/if}
	<h1 style="margin:.5rem 0 .8rem">{@render heading()}</h1>
	{#if children}
		<p class="standfirst">{@render children()}</p>
	{/if}
</div>

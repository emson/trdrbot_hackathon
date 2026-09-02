<script>
	import { glossary } from '$lib/glossary.js';
</script>

<svelte:head><title>Glossary — trdrbot</title></svelte:head>

<section class="block ledger">
	<div class="wrap narrow">
		<span class="kicker">Plain English</span>
		<h1 style="margin:.5rem 0 .8rem">Glossary.</h1>
		<p class="standfirst">
			Every dotted-underlined term on this site shows its plain-English definition on hover —
			this page just collects them all in one place. No prior options-trading knowledge assumed.
		</p>

		<dl style="margin:1.6rem 0 0; display:flex; flex-direction:column; gap:1.1rem">
			{#each glossary as g}
				<div style="border-bottom:1px solid var(--paper-line); padding-bottom:1.1rem">
					<dt style="font-weight:650; font-family:var(--serif); font-size:1.05rem">{g.term}</dt>
					<dd style="margin:.3rem 0 0; color:var(--ink-soft)">{g.def}</dd>
				</div>
			{/each}
		</dl>
	</div>
</section>

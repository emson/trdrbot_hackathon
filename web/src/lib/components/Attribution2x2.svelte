<script>
	let { attribution = {} } = $props();

	let total = $derived(attribution.total || 0);
	const cells = [
		{ key: 'held_profit', row: 0, col: 0, tone: 'good', note: 'reinforce both' },
		{ key: 'held_loss', row: 0, col: 1, tone: 'warn', note: 'the view was fine — the structure wasn’t' },
		{ key: 'failed_loss', row: 1, col: 0, tone: '', note: 'correct the view; the structure was faithful' },
		{ key: 'failed_profit', row: 1, col: 1, tone: 'bad', note: 'luck — learn nothing from this' }
	];
</script>

<div class="qgrid">
	<div class="hd"></div>
	<div class="hd" style="justify-content:center">Profit</div>
	<div class="hd" style="justify-content:center">Loss</div>

	<div class="rh">View held</div>
	{#each cells.filter((c) => c.row === 0) as c}
		<div class="cell {c.tone}">
			<b>{attribution[c.key] ?? 0}</b>
			<span>{c.note}</span>
		</div>
	{/each}

	<div class="rh">View failed</div>
	{#each cells.filter((c) => c.row === 1) as c}
		<div class="cell {c.tone}">
			<b>{attribution[c.key] ?? 0}</b>
			<span>{c.note}</span>
		</div>
	{/each}
</div>
{#if total === 0 || (attribution.unattributed ?? 0) === total}
	<p class="muted" style="margin-top:.6rem; font-size:.86rem">
		No positions have reached their thesis horizon yet, so nothing has been attributed —
		attribution only fires once a claim's stated resolution date has actually passed.
		{#if attribution.unattributed}({attribution.unattributed} of {total} still pending.){/if}
	</p>
{:else if attribution.unattributed}
	<p class="muted" style="margin-top:.6rem; font-size:.86rem">
		{attribution.unattributed} of {total} position(s) haven't reached their thesis horizon yet.
	</p>
{/if}

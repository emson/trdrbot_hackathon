<script>
	// Where ideas go (notes/028 section 4.6) - every real count from the
	// record, with the not-taken remainder written out beside the part that
	// made it through. No Sankey: the bars are the visual, the text is the
	// record.
	let { funnel = {} } = $props();

	function topReasons(pairs) {
		return (pairs || [])
			.slice(0, 2)
			.map(([reason, n]) => `${reason} (${n})`)
			.join(', ');
	}

	let steps = $derived([
		{
			label: 'ideas',
			n: (funnel.ideas?.muse_candidates ?? 0) + (funnel.ideas?.research_opportunities ?? 0) +
				(funnel.ideas?.discovery_opportunities ?? 0),
			note: `${funnel.ideas?.muse_candidates ?? 0} from the muse · ` +
				`${funnel.ideas?.research_opportunities ?? 0} from research · ` +
				`${funnel.ideas?.discovery_opportunities ?? 0} from discovery`
		},
		{
			label: 'gates',
			n: funnel.rejected?.gates ?? 0,
			note: `${funnel.rejected?.research ?? 0} rejected at research · ` +
				`${funnel.rejected?.gates ?? 0} rejected at the gates` +
				(funnel.rejected?.gate_reasons?.length ? ` (${topReasons(funnel.rejected.gate_reasons)})` : '')
		},
		{
			label: 'claims',
			n: funnel.claims?.recorded ?? 0,
			note: `${funnel.claims?.recorded ?? 0} recorded · ` +
				`${funnel.claims?.code_default_probability ?? 0} carried a code-default probability`
		},
		{
			label: 'structures',
			n: funnel.structures?.claims_priced ?? 0,
			note: `${funnel.structures?.claims_priced ?? 0} claims priced · ` +
				`${funnel.structures?.thrown_out ?? 0} structures thrown out`
		},
		{
			label: 'sized',
			n: funnel.sized?.sized ?? 0,
			note: `${funnel.sized?.sized ?? 0} sized · ${funnel.sized?.refused ?? 0} refused`
		},
		{
			label: 'traded',
			n: funnel.traded?.traded ?? 0,
			note: `${funnel.traded?.traded ?? 0} traded · ${funnel.traded?.never_filled ?? 0} never filled · ` +
				`${funnel.traded?.cycles_declined ?? 0} cycles declined outright`
		},
		{
			label: 'scored',
			n: (funnel.scored?.held ?? 0) + (funnel.scored?.failed ?? 0),
			note: `${funnel.scored?.held ?? 0} held · ${funnel.scored?.failed ?? 0} failed · ` +
				`${funnel.scored?.open ?? 0} still open`
		},
		{
			label: 'attributed',
			n: funnel.attributed?.attributed ?? 0,
			note: `${funnel.attributed?.attributed ?? 0} attributed · ` +
				`${funnel.attributed?.unscoreable ?? 0} unscoreable · ` +
				`${funnel.attributed?.awaiting ?? 0} awaiting the horizon`
		}
	]);
	let maxN = $derived(Math.max(1, ...steps.map((s) => s.n)));
</script>

<div class="funnel">
	{#each steps as s}
		<div class="funnel-step">
			<span class="funnel-label">{s.label}</span>
			<div class="funnel-track"><div class="funnel-bar" style="width:{((s.n / maxN) * 100).toFixed(1)}%"></div></div>
			<span class="fine">{s.note}</span>
		</div>
	{/each}
</div>

<script>
	import { pct } from '$lib/format.js';

	let { competence = {} } = $props();

	// Static gate definitions (src/trdrbot/competence.py TIERS) - a design
	// constant of the sizing system, not a number this export derives.
	const RUNGS = [
		{ key: 'explore', tier: 'Explore', cap: 0.1, minN: 0, req: 'Fixed 2.2% exploration allocation while the record is too thin for Kelly to mean anything.' },
		{ key: 'establish', tier: 'Establish', cap: 0.15, minN: 5, req: '5 resolved theses. Kelly engages, capped at 10% of the calculated fraction.' },
		{ key: 'scale', tier: 'Scale', cap: 0.2, minN: 15, req: '15 resolved theses, 60% attributable (view actually explicable, not just profitable).' },
		{ key: 'mature', tier: 'Mature', cap: 0.25, minN: 40, req: '40 resolved theses, reliability <0.04, 70% attributable — strictly enforced.' }
	];

	let currentIdx = $derived(RUNGS.findIndex((r) => r.key === competence.tier));
</script>

<div class="ladder">
	{#each RUNGS as r, i}
		<div class="rung {i === currentIdx ? 'current' : ''}" style="--lvl:{i}">
			<span class="tier">{r.tier}</span>
			<p class="req">{r.req}</p>
			<div class="caps">
				<div><b>{pct(r.cap, { digits: 0, sign: false })}</b><span>book cap</span></div>
				<div><b>{r.minN}</b><span>min resolved</span></div>
			</div>
		</div>
	{/each}
</div>
{#if currentIdx >= 0}
	<p class="muted" style="margin-top:.7rem; font-size:.86rem">
		Currently <strong>{RUNGS[currentIdx].tier}</strong> — {competence.resolved ?? 0} resolved theses,
		{competence.attributable_rate === null || competence.attributable_rate === undefined
			? 'attribution not yet measurable'
			: `${pct(competence.attributable_rate, { digits: 0, sign: false })} attributable`},
		Kelly ×{(competence.kelly_multiplier ?? 0).toFixed(2)}.
	</p>
{/if}

<script>
	import { pct } from '$lib/format.js';

	let { competence = {} } = $props();

	// The rungs come from `competence.ladder` in the snapshot, which the
	// exporter reads straight off `competence.TIERS` (D-099). They used to be
	// hardcoded here - a fourth copy of the sizing policy, on a public page -
	// and the derived exploration floor made the copy wrong at three of four
	// rungs while the appetite-SCALED Kelly rendered right beside the earned
	// caps. Prose is copy and stays here; every number is data.
	const REQ = {
		explore: 'The starting allocation, while the record is too thin for Kelly to mean anything.',
		establish: '5 resolved theses. Kelly engages, capped at 10% of the calculated fraction.',
		scale: '15 resolved theses, 60% attributable (view actually explicable, not just profitable).',
		mature: '40 resolved theses, reliability <0.04, 70% attributable — strictly enforced.'
	};
	const title = (s) => s.charAt(0).toUpperCase() + s.slice(1);

	let rungs = $derived(competence.ladder ?? []);
	let currentIdx = $derived(rungs.findIndex((r) => r.key === competence.tier));
	// 1.0 means the operator has not moved it; anything else and the caps
	// rendered below are EARNED, not the ones being enforced.
	let appetite = $derived(competence.appetite ?? 1);
</script>

<div class="ladder">
	{#each rungs as r, i}
		<div class="rung {i === currentIdx ? 'current' : ''}" style="--lvl:{i}">
			<span class="tier">{title(r.key)}</span>
			<p class="req">{REQ[r.key] ?? ''}</p>
			<div class="caps">
				<div><b>{pct(r.cap, { digits: 0, sign: false })}</b><span>book cap</span></div>
				<div><b>{pct(r.seed, { digits: 1, sign: false })}</b><span>floor</span></div>
				<div><b>{r.min_n}</b><span>min resolved</span></div>
			</div>
		</div>
	{/each}
</div>
{#if currentIdx >= 0}
	<p class="muted" style="margin-top:.7rem; font-size:.86rem">
		Currently <strong>{title(rungs[currentIdx].key)}</strong> — {competence.resolved ?? 0} resolved
		theses,
		{competence.attributable_rate === null || competence.attributable_rate === undefined
			? 'attribution not yet measurable'
			: `${pct(competence.attributable_rate, { digits: 0, sign: false })} attributable`},
		Kelly ×{(competence.kelly_multiplier ?? 0).toFixed(2)}.
	</p>
	{#if appetite !== 1}
		<p class="muted" style="margin-top:.35rem; font-size:.86rem">
			The rungs above are what each tier <em>earns</em>. An operator risk appetite of
			<strong>×{appetite.toFixed(2)}</strong> is applied on top, so the book cap actually enforced
			is <strong>{pct(competence.book_cap, { digits: 1, sign: false })}</strong> and the
			exploration floor <strong>{pct(competence.seed_fraction, { digits: 1, sign: false })}</strong
			>. It scales size, not selectivity.
		</p>
	{/if}
{/if}

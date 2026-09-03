<script>
	import { num3 } from '$lib/format.js';

	// One Coach lever, replayed exactly as `trdrbot coach status` reports it -
	// same tally, same floors, same verdict function - so the page and the
	// terminal can never disagree (notes/028).
	let { lever = {} } = $props();

	const SPARK_W = 160, SPARK_H = 28;

	function sparkPath(series) {
		if (!series || series.length < 2) return '';
		return series
			.map((p, i) => {
				const x = (i / (series.length - 1)) * SPARK_W;
				const y = SPARK_H - (Math.max(0, Math.min(1, p ?? 0.5)) * SPARK_H);
				return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
			})
			.join(' ');
	}

	let exp = $derived(lever.experiment);
	function floorX(v) {
		return Math.max(0, Math.min(100, v * 100));
	}
</script>

<div class="card pad-lg">
	<div class="row1" style="display:flex; justify-content:space-between; align-items:baseline; gap:.6rem; flex-wrap:wrap">
		<h3>{lever.name}</h3>
		<span class="tag neutral">{lever.subsystem}</span>
	</div>
	<p class="fine">
		incumbent {lever.incumbent?.id} {lever.incumbent?.fingerprint}
		({lever.incumbent?.origin}, since {lever.incumbent?.since ? lever.incumbent.since.slice(0, 10) : 'seed'})
	</p>
	<p class="muted" style="font-size:.88rem">{lever.reward_description}</p>

	{#if exp}
		<div class="stack" style="gap:.5rem; margin-top:.4rem">
			<p class="fine">{exp.challenger?.id ?? '?'} vs {lever.incumbent?.id} · {exp.runs} paired runs · challenger {exp.challenger?.survived}/{exp.challenger?.n} · incumbent {exp.incumbent?.survived}/{exp.incumbent?.n}</p>
			<div class="posterior">
				<div class="posterior-track">
					<div class="posterior-fill" style="width:{(exp.posterior * 100).toFixed(1)}%"></div>
					{#if exp.floors?.promote_at}
						<div class="posterior-tick" style="left:{floorX(exp.floors.promote_at)}%" title="promote at {num3(exp.floors.promote_at)}"></div>
					{/if}
					{#if exp.floors?.futility_at}
						<div class="posterior-tick caution" style="left:{floorX(exp.floors.futility_at)}%" title="futility at {num3(exp.floors.futility_at)}"></div>
					{/if}
				</div>
				<span class="num" style="font-size:.85rem">P(better) {num3(exp.posterior)}</span>
			</div>
			{#if exp.posterior_series?.length > 1}
				<svg width={SPARK_W} height={SPARK_H} viewBox="0 0 {SPARK_W} {SPARK_H}" role="img" aria-label="posterior over trials">
					<path d={sparkPath(exp.posterior_series)} fill="none" stroke="var(--accent)" stroke-width="1.4" />
				</svg>
			{/if}
			<p class="fine">{exp.verdict?.outcome ? `-> ${exp.verdict.outcome}: ${exp.verdict.reason}` : 'still gathering evidence'}</p>
			{#if exp.mutation_rationale}
				<div class="quote" style="padding:.7rem .9rem">
					<p style="font-size:.86rem">{exp.mutation_rationale}</p>
					<cite>the Coach's own reason for this challenger</cite>
				</div>
			{/if}
		</div>
	{:else}
		<p class="fine">no experiment open</p>
	{/if}
</div>

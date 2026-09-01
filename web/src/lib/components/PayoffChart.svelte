<script>
	import { usd } from '$lib/format.js';

	let { payoff = {}, entrySpot = null } = $props();
	const uid = $props.id();

	const W = 640, H = 280, M = { l: 64, r: 20, t: 20, b: 34 };
	const innerW = W - M.l - M.r, innerH = H - M.t - M.b;

	let points = $derived(payoff.points || []);
	let xmin = $derived(points.length ? Math.min(...points.map((p) => p[0])) : 0);
	let xmax = $derived(points.length ? Math.max(...points.map((p) => p[0])) : 1);
	let ymin = $derived(points.length ? Math.min(...points.map((p) => p[1])) : -1);
	let ymax = $derived(points.length ? Math.max(...points.map((p) => p[1])) : 1);

	function xs(price) {
		return M.l + ((price - xmin) / (xmax - xmin || 1)) * innerW;
	}
	function ys(pnl) {
		return M.t + ((ymax - pnl) / (ymax - ymin || 1)) * innerH;
	}

	let zeroY = $derived(ys(0));
	let linePath = $derived(
		points.map((p, i) => `${i === 0 ? 'M' : 'L'}${xs(p[0]).toFixed(1)},${ys(p[1]).toFixed(1)}`).join(' ')
	);
	let areaPath = $derived(
		points.length
			? `${linePath} L${xs(points[points.length - 1][0]).toFixed(1)},${zeroY.toFixed(1)} L${xs(points[0][0]).toFixed(1)},${zeroY.toFixed(1)} Z`
			: ''
	);
	let breakevens = $derived((payoff.breakevens || []).filter((b) => b >= xmin && b <= xmax));
	let xTicks = $derived([xmin, (xmin + xmax) / 2, xmax]);
</script>

{#if payoff.derivable && points.length}
	<div class="chart-wrap">
		<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="Payoff at expiry chart">
			<clipPath id="above-{uid}"><rect x={M.l} y={M.t} width={innerW} height={Math.max(0, zeroY - M.t)} /></clipPath>
			<clipPath id="below-{uid}"><rect x={M.l} y={zeroY} width={innerW} height={Math.max(0, M.t + innerH - zeroY)} /></clipPath>

			<path d={areaPath} fill="var(--accent-soft)" clip-path="url(#above-{uid})" />
			<path d={areaPath} fill="var(--danger-soft)" clip-path="url(#below-{uid})" />

			<line x1={M.l} x2={M.l + innerW} y1={zeroY} y2={zeroY} stroke="var(--paper-line)" stroke-dasharray="3 3" />

			{#each breakevens as be}
				<line x1={xs(be)} x2={xs(be)} y1={M.t} y2={M.t + innerH} stroke="var(--ink-faint)" stroke-dasharray="2 3" />
				<text x={xs(be)} y={M.t + 12} class="axis" text-anchor="middle">BE {be}</text>
			{/each}

			{#if entrySpot !== null && entrySpot >= xmin && entrySpot <= xmax}
				<line x1={xs(entrySpot)} x2={xs(entrySpot)} y1={M.t} y2={M.t + innerH} stroke="var(--accent)" stroke-width="1.4" />
				<text x={xs(entrySpot)} y={M.t + innerH + 26} class="axis" text-anchor="middle" fill="var(--accent)">entry {entrySpot}</text>
			{/if}

			<path d={linePath} fill="none" stroke="var(--ink)" stroke-width="2" stroke-linejoin="round" />

			{#each xTicks as t}
				<text x={xs(t)} y={M.t + innerH + 18} class="axis" text-anchor="middle">{t.toFixed(0)}</text>
			{/each}
			<text x={M.l - 8} y={ys(ymax) + 4} class="axis" text-anchor="end">{usd(ymax)}</text>
			<text x={M.l - 8} y={zeroY + 4} class="axis" text-anchor="end">$0</text>
			<text x={M.l - 8} y={ys(ymin) + 4} class="axis" text-anchor="end">{usd(ymin)}</text>
		</svg>
	</div>
{:else}
	<p class="muted" style="font-size:.88rem">
		Payoff not shown — {payoff.reason || 'not derivable from the recorded legs'}.
	</p>
{/if}

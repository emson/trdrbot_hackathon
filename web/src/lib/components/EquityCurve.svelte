<script>
	import { usd } from '$lib/format.js';

	// `markers`, when given, are [{index, underlying, strategy}] placed on the
	// curve at the tick closest to each position's open (see `equityMarkers`
	// in demo.js) - so the curve reads as a consequence of decisions rather
	// than a line that moved on its own. The scoreboard passes none and the
	// curve is drawn exactly as before.
	let { series = [], start = 100000, markers = [] } = $props();

	const W = 640, H = 240, M = { l: 66, r: 16, t: 16, b: 26 };
	const innerW = W - M.l - M.r, innerH = H - M.t - M.b;

	let pts = $derived(series.filter((p) => typeof p.equity === 'number'));
	let ymin = $derived(pts.length ? Math.min(start, ...pts.map((p) => p.equity)) : start - 1);
	let ymax = $derived(pts.length ? Math.max(start, ...pts.map((p) => p.equity)) : start + 1);

	function xs(i) {
		return M.l + (pts.length > 1 ? (i / (pts.length - 1)) * innerW : innerW / 2);
	}
	function ys(v) {
		return M.t + ((ymax - v) / (ymax - ymin || 1)) * innerH;
	}

	let linePath = $derived(pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${xs(i).toFixed(1)},${ys(p.equity).toFixed(1)}`).join(' '));
	let areaPath = $derived(
		pts.length ? `${linePath} L${xs(pts.length - 1).toFixed(1)},${(M.t + innerH).toFixed(1)} L${xs(0).toFixed(1)},${(M.t + innerH).toFixed(1)} Z` : ''
	);
	let startY = $derived(ys(start));
</script>

{#if pts.length > 1}
	<div class="chart-wrap">
		<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="Equity over time">
			<path d={areaPath} fill="var(--accent-soft)" />
			<line x1={M.l} x2={M.l + innerW} y1={startY} y2={startY} stroke="var(--paper-line)" stroke-dasharray="3 3" />
			<text x={M.l + innerW} y={startY - 4} class="axis" text-anchor="end">start {usd(start)}</text>
			<path d={linePath} fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round" />

			{#each markers as m}
				{#if pts[m.index]}
					<circle cx={xs(m.index)} cy={ys(pts[m.index].equity)} r="4"
						fill="var(--paper-raised)" stroke="var(--ink)" stroke-width="1.8">
						<title>opened {m.underlying} {m.strategy} at {usd(pts[m.index].equity)}</title>
					</circle>
				{/if}
			{/each}

			<text x={M.l - 8} y={ys(ymax) + 4} class="axis" text-anchor="end">{usd(ymax)}</text>
			<text x={M.l - 8} y={ys(ymin) + 4} class="axis" text-anchor="end">{usd(ymin)}</text>
		</svg>
	</div>
{:else}
	<p class="muted" style="font-size:.88rem">Not enough ticks recorded yet to draw a curve.</p>
{/if}

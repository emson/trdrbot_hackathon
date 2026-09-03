<script>
	import { usd } from '$lib/format.js';

	// `closes` is {dates[], closes[]} bounded at export time to end at the
	// claim's horizon (or the decision day, if the horizon hasn't arrived
	// yet) - never the ticker's CURRENT price history, so replaying an old
	// cycle can never show a chart drawn through sessions it could not have
	// known about (notes/028).
	let {
		closes = null, underlying = '', decisionDay = '', band = null,
		resolved = null // {price_at_horizon, outcome} or null
	} = $props();

	const W = 640, H = 220, M = { l: 60, r: 16, t: 16, b: 26 };
	const innerW = W - M.l - M.r, innerH = H - M.t - M.b;

	let dates = $derived(closes?.dates || []);
	let series = $derived(closes?.closes || []);
	let decisionIdx = $derived(dates.findIndex((d) => d >= decisionDay));
	let ymin = $derived(series.length ? Math.min(...series) : 0);
	let ymax = $derived(series.length ? Math.max(...series) : 1);

	function xs(i) {
		return M.l + (series.length > 1 ? (i / (series.length - 1)) * innerW : innerW / 2);
	}
	function ys(v) {
		return M.t + ((ymax - v) / (ymax - ymin || 1)) * innerH;
	}

	let linePath = $derived(
		series.map((v, i) => `${i === 0 ? 'M' : 'L'}${xs(i).toFixed(1)},${ys(v).toFixed(1)}`).join(' ')
	);
	let bandY0 = $derived(band ? ys(Math.min(band.high ?? ymax, ymax)) : null);
	let bandY1 = $derived(band ? ys(Math.max(band.low ?? ymin, ymin)) : null);
	let resolvedIdx = $derived(dates.length ? dates.length - 1 : -1);
</script>

{#if series.length > 1}
	<div class="chart-wrap">
		<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="{underlying} closes with the claimed band">
			{#if band && bandY1 > bandY0}
				<rect x={M.l} y={bandY0} width={innerW} height={bandY1 - bandY0}
					fill="var(--accent)" opacity="0.09" />
			{/if}

			{#if decisionIdx >= 0}
				<line x1={xs(decisionIdx)} x2={xs(decisionIdx)} y1={M.t} y2={M.t + innerH}
					stroke="var(--ink-faint)" stroke-width="1.4" />
				<text x={xs(decisionIdx)} y={M.t + innerH + 18} class="axis" text-anchor="middle">decided</text>
			{/if}

			<line x1={xs(series.length - 1)} x2={xs(series.length - 1)} y1={M.t} y2={M.t + innerH}
				stroke="var(--ink-faint)" stroke-dasharray="2 3" />
			<text x={xs(series.length - 1)} y={M.t + innerH + 18} class="axis" text-anchor="middle">horizon</text>

			<path d={linePath} fill="none" stroke="var(--ink)" stroke-width="1.6" stroke-linejoin="round" />

			{#if resolved && resolvedIdx >= 0}
				<circle cx={xs(resolvedIdx)} cy={ys(resolved.price_at_horizon)} r="3.5"
					fill={resolved.outcome ? 'var(--accent)' : 'var(--danger)'} />
				<text x={xs(resolvedIdx) - 8} y={ys(resolved.price_at_horizon) - 8} class="axis"
					text-anchor="end" fill={resolved.outcome ? 'var(--accent)' : 'var(--danger)'}>
					{resolved.outcome ? 'held' : 'failed'}
				</text>
			{/if}

			<text x={M.l - 8} y={ys(ymax) + 4} class="axis" text-anchor="end">{usd(ymax)}</text>
			<text x={M.l - 8} y={ys(ymin) + 4} class="axis" text-anchor="end">{usd(ymin)}</text>
		</svg>
	</div>
{:else}
	<p class="muted" style="font-size:.88rem">No price history on record for {underlying}.</p>
{/if}

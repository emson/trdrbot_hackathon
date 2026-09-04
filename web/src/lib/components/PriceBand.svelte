<script>
	import { usd } from '$lib/format.js';
	import { coneBounds } from '$lib/demo.js';

	// `closes` is {dates[], closes[]} bounded at export time to end at the
	// claim's horizon (or the decision day, if the horizon hasn't arrived
	// yet) - never the ticker's CURRENT price history, so replaying an old
	// cycle can never show a chart drawn through sessions it could not have
	// known about (notes/028).
	//
	// `cone`, when given, is {spot, ivPct, days} and draws the one- and
	// two-sigma envelope the underlying's own implied vol projects forward
	// from the decision day. It is MODELLED and the caller labels it so.
	// Without it the chart is exactly what it was before: history and a band.
	let {
		closes = null, underlying = '', decisionDay = '', band = null,
		resolved = null, // {price_at_horizon, outcome} or null
		cone = null
	} = $props();

	const W = 720, H = 260, M = { l: 58, r: 18, t: 18, b: 26 };
	const innerW = W - M.l - M.r, innerH = H - M.t - M.b;
	const CONE_STEPS = 14;

	let dates = $derived(closes?.dates || []);
	let series = $derived(closes?.closes || []);

	// Where the claim was made. `findIndex` returns -1 when the decision day
	// is past the end of the series, which is the resolved case - the whole
	// series is then history and the cone has nothing to add.
	let decisionIdx = $derived(
		(() => {
			const i = dates.findIndex((d) => d >= decisionDay);
			return i >= 0 ? i : Math.max(0, series.length - 1);
		})()
	);

	// Sessions already drawn to the right of the decision. When the horizon
	// has not arrived that is zero, and the cone needs its own space.
	let drawnForward = $derived(Math.max(0, series.length - 1 - decisionIdx));
	let coneCurve = $derived(
		cone ? coneBounds(cone.spot, cone.ivPct, cone.days, CONE_STEPS) : []
	);
	// Enough forward room that the cone reads as a shape rather than a sliver
	// next to 40-odd sessions of history.
	let coneSpan = $derived(coneCurve.length ? Math.max(drawnForward, 12) : drawnForward);
	let totalUnits = $derived(Math.max(1, decisionIdx + coneSpan));

	let coneValues = $derived(coneCurve.flatMap((c) => [c.up2, c.dn2]));
	let ymin = $derived(Math.min(...[...series, ...coneValues, band?.low, band?.high].filter((v) => typeof v === 'number')));
	let ymax = $derived(Math.max(...[...series, ...coneValues, band?.low, band?.high].filter((v) => typeof v === 'number')));
	let pad = $derived((ymax - ymin) * 0.08 || 1);

	function xs(i) {
		return M.l + (i / totalUnits) * innerW;
	}
	function ys(v) {
		return M.t + ((ymax + pad - v) / (ymax - ymin + 2 * pad || 1)) * innerH;
	}
	function coneX(step) {
		return xs(decisionIdx + (step / CONE_STEPS) * coneSpan);
	}

	function envelope(upKey, dnKey) {
		if (!coneCurve.length) return '';
		const up = coneCurve.map((c) => `${coneX(c.step).toFixed(1)},${ys(c[upKey]).toFixed(1)}`);
		const dn = coneCurve.slice().reverse().map((c) => `${coneX(c.step).toFixed(1)},${ys(c[dnKey]).toFixed(1)}`);
		return `M${up.join(' L')} L${dn.join(' L')} Z`;
	}

	let linePath = $derived(
		series.map((v, i) => `${i === 0 ? 'M' : 'L'}${xs(i).toFixed(1)},${ys(v).toFixed(1)}`).join(' ')
	);
	let bandY0 = $derived(band ? ys(Math.min(band.high ?? ymax + pad, ymax + pad)) : null);
	let bandY1 = $derived(band ? ys(Math.max(band.low ?? ymin - pad, ymin - pad)) : null);

	// The band belongs to the future the claim is about, so it is drawn from
	// the decision forward. When there is no future on the chart yet - an
	// unresolved claim whose horizon has not arrived, so the series stops at
	// the decision day and no cone was drawn - that span is zero and the band
	// would vanish. Then it spans the whole plot instead, which is what this
	// chart did before the cone existed and is still the honest reading: the
	// claim is about the level, and no part of the drawn tape contradicts it.
	let hasForward = $derived(coneCurve.length > 0 || drawnForward > 0);
	let bandX = $derived(hasForward ? xs(decisionIdx) : M.l);
	let bandW = $derived(Math.max(0, (hasForward ? xs(totalUnits) : M.l + innerW) - bandX));
	let bandLabel = $derived(
		!band ? '' :
		band.low == null ? `below ${band.high}` :
		band.high == null ? `above ${band.low}` : `${band.low} to ${band.high}`
	);
	let resolvedIdx = $derived(series.length ? series.length - 1 : -1);
</script>

{#if series.length > 1}
	<div class="chart-wrap">
		<svg class="chart" viewBox="0 0 {W} {H}" role="img"
			aria-label="{underlying} closes with the claimed band{coneCurve.length ? ' and the modelled forward cone' : ''}">
			{#if coneCurve.length}
				<path d={envelope('up2', 'dn2')} fill="var(--accent)" opacity="0.07" />
				<path d={envelope('up1', 'dn1')} fill="var(--accent)" opacity="0.11" />
			{/if}

			{#if band && bandY1 > bandY0}
				<rect x={bandX} y={bandY0} width={bandW} height={bandY1 - bandY0}
					fill="var(--accent)" opacity="0.10" />
				<rect x={bandX} y={bandY0} width={bandW} height={bandY1 - bandY0}
					fill="none" stroke="var(--accent)" stroke-width="1.4" stroke-dasharray="4 3" rx="2" />
				<!-- Anchored from whichever side keeps it inside the plot: a band
				     that starts in the right half would otherwise run its label
				     off the edge (measured: it did). -->
				<text x={bandX < M.l + innerW / 2 ? bandX + 6 : bandX + bandW}
					y={bandY0 - 6} class="axis" fill="var(--accent)"
					text-anchor={bandX < M.l + innerW / 2 ? 'start' : 'end'}>
					the claim · {bandLabel}
				</text>
			{/if}

			<line x1={xs(decisionIdx)} x2={xs(decisionIdx)} y1={M.t} y2={M.t + innerH}
				stroke="var(--ink-faint)" stroke-width="1.4" />
			<text x={xs(decisionIdx)} y={M.t + innerH + 18} class="axis"
				text-anchor={hasForward ? 'middle' : 'end'}>decided</text>

			<!-- Only when there is somewhere for the horizon to BE. Without a
			     future on the chart it sits exactly on the decision line, and
			     the two labels overprint each other (measured: they did). -->
			{#if hasForward}
				<line x1={xs(totalUnits)} x2={xs(totalUnits)} y1={M.t} y2={M.t + innerH}
					stroke="var(--ink-faint)" stroke-dasharray="2 3" />
				<text x={xs(totalUnits)} y={M.t + innerH + 18} class="axis" text-anchor="end">horizon</text>
			{/if}

			<path d={linePath} fill="none" stroke="var(--ink)" stroke-width="1.7" stroke-linejoin="round" />

			{#if resolved && resolvedIdx >= 0 && typeof resolved.price_at_horizon === 'number'}
				<circle cx={xs(resolvedIdx)} cy={ys(resolved.price_at_horizon)} r="4"
					fill={resolved.outcome ? 'var(--accent)' : 'var(--danger)'} />
				<text x={xs(resolvedIdx) - 8} y={ys(resolved.price_at_horizon) - 9} class="axis"
					text-anchor="end" fill={resolved.outcome ? 'var(--accent)' : 'var(--danger)'}>
					{resolved.outcome ? 'held' : 'failed'} at {resolved.price_at_horizon}
				</text>
			{/if}

			<text x={M.l - 8} y={ys(ymax) + 4} class="axis" text-anchor="end">{usd(ymax)}</text>
			<text x={M.l - 8} y={ys(ymin) + 4} class="axis" text-anchor="end">{usd(ymin)}</text>
		</svg>
	</div>
{:else}
	<p class="muted" style="font-size:.88rem">No price history on record for {underlying}.</p>
{/if}

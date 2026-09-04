<script>
	import { dateTime, pct, strategyLabel, usd } from '$lib/format.js';

	// `markers`, when given, are [{index, positions:[…]}] placed on the curve at
	// the tick closest to each position's open (see `equityMarkers` in demo.js)
	// - so the curve reads as a consequence of decisions rather than a line that
	// moved on its own. Each dot is a link to that position's page.
	//
	// `interactive` adds a crosshair and a readout that follow the pointer. It
	// is opt-in because the scoreboard's copy of this chart is a static summary
	// and gains nothing from it; passing neither prop renders exactly what this
	// component always rendered.
	let { series = [], start = 100000, markers = [], interactive = false } = $props();

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

	// --- the crosshair ------------------------------------------------------
	let hoverIdx = $state(null);
	let svgEl = $state(null);
	let markerIdx = $state(null);

	function onMove(e) {
		if (!interactive || !svgEl || pts.length < 2) return;
		const r = svgEl.getBoundingClientRect();
		if (!r.width) return;
		const vx = ((e.clientX - r.left) / r.width) * W;
		const i = Math.round(((vx - M.l) / innerW) * (pts.length - 1));
		hoverIdx = Math.max(0, Math.min(pts.length - 1, i));
	}
	function clear() {
		hoverIdx = null;
		markerIdx = null;
	}

	let active = $derived(hoverIdx === null ? null : pts[hoverIdx]);
	let activeMarker = $derived(
		markerIdx !== null
			? markers.find((m) => m.index === markerIdx)
			: hoverIdx === null
				? null
				: markers.find((m) => m.index === hoverIdx)
	);
	// Keep the readout inside the plot: past the midpoint it flips to the left
	// of the crosshair instead of running off the right edge.
	let tipRight = $derived(hoverIdx !== null && xs(hoverIdx) > M.l + innerW * 0.55);
</script>

{#if pts.length > 1}
	<div class="chart-wrap eq" class:live={interactive}>
		<svg
			class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="Equity over time"
			bind:this={svgEl} onmousemove={onMove} onmouseleave={clear}
		>
			<path d={areaPath} fill="var(--accent-soft)" />
			<line x1={M.l} x2={M.l + innerW} y1={startY} y2={startY} stroke="var(--paper-line)" stroke-dasharray="3 3" />
			<text x={M.l + innerW} y={startY - 4} class="axis" text-anchor="end">start {usd(start)}</text>
			<path d={linePath} fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round" />

			{#if hoverIdx !== null && active}
				<line x1={xs(hoverIdx)} x2={xs(hoverIdx)} y1={M.t} y2={M.t + innerH}
					stroke="var(--ink-faint)" stroke-width="1" stroke-dasharray="2 3" />
				<circle cx={xs(hoverIdx)} cy={ys(active.equity)} r="4" fill="var(--accent)" />
			{/if}

			{#each markers as m}
				{#if pts[m.index]}
					<a
						href="/ledger/{m.positions[0].id}"
						aria-label="{m.positions.length === 1
							? `${m.positions[0].underlying} ${strategyLabel(m.positions[0].strategy)} opened here`
							: `${m.positions.length} positions opened here`}, {usd(pts[m.index].equity)}"
						onmouseenter={() => { markerIdx = m.index; hoverIdx = m.index; }}
						onfocus={() => { markerIdx = m.index; hoverIdx = m.index; }}
						onblur={clear}
					>
						<circle cx={xs(m.index)} cy={ys(pts[m.index].equity)} r="9" fill="transparent" />
						<circle
							class="mk" cx={xs(m.index)} cy={ys(pts[m.index].equity)}
							r={markerIdx === m.index ? 5.5 : 4}
							fill="var(--paper-raised)" stroke="var(--ink)" stroke-width="1.8" />
						{#if m.positions.length > 1}
							<text x={xs(m.index)} y={ys(pts[m.index].equity) - 10} class="axis"
								text-anchor="middle">{m.positions.length}</text>
						{/if}
					</a>
				{/if}
			{/each}

			<text x={M.l - 8} y={ys(ymax) + 4} class="axis" text-anchor="end">{usd(ymax)}</text>
			<text x={M.l - 8} y={ys(ymin) + 4} class="axis" text-anchor="end">{usd(ymin)}</text>
		</svg>

		{#if interactive && active}
			<div class="tip" class:right={tipRight}
				style="left:{((xs(hoverIdx) / W) * 100).toFixed(2)}%">
				<span class="v">{usd(active.equity)}</span>
				<span class="d">{pct((active.equity - start) / start)} since inception</span>
				<span class="d">{dateTime(active.ts)}</span>
				{#if activeMarker}
					<span class="op">
						{#each activeMarker.positions as p}
							<span class="opline">opened {p.underlying} {strategyLabel(p.strategy)}</span>
						{/each}
						<span class="d">click the dot to open {activeMarker.positions.length === 1 ? 'it' : 'the first'}</span>
					</span>
				{/if}
			</div>
		{/if}
	</div>
	{#if interactive && markers.length}
		<p class="fine" style="margin-top:.4rem">
			Each ringed dot is a position opened at that tick; hover the line for the equity at any
			point, and open a dot to read that position's story.
		</p>
	{/if}
{:else}
	<p class="muted" style="font-size:.88rem">Not enough ticks recorded yet to draw a curve.</p>
{/if}

<style>
	.eq { position: relative; }
	.eq.live :global(svg) { cursor: crosshair; }
	.eq :global(a) { cursor: pointer; }
	.eq :global(a:focus-visible) { outline: 2px solid var(--accent); outline-offset: 2px; }
	.eq :global(circle.mk) { transition: r .12s ease; }

	.tip {
		position: absolute; top: .3rem; transform: translateX(.6rem);
		background: var(--paper-raised); border: 1px solid var(--paper-line);
		border-radius: var(--r-sharp); padding: .5rem .7rem; pointer-events: none;
		display: flex; flex-direction: column; gap: .1rem; white-space: nowrap;
		box-shadow: 0 4px 14px var(--shadow); z-index: 2;
	}
	.tip.right { transform: translateX(calc(-100% - .6rem)); }
	.tip .v { font-family: var(--mono); font-weight: 600; font-size: .95rem; }
	.tip .d { font-family: var(--mono); font-size: .68rem; color: var(--ink-faint); }
	.tip .op { display: flex; flex-direction: column; gap: .1rem; margin-top: .35rem;
		padding-top: .35rem; border-top: 1px solid var(--paper-line); }
	.tip .opline { font-family: var(--mono); font-size: .7rem; color: var(--ink); }

	@media (max-width: 620px) { .tip { display: none; } }
</style>

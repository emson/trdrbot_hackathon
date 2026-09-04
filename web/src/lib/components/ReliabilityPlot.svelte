<script>
	// Stated probability against how often those claims actually held, one dot
	// per non-empty decile, dot area proportional to the sample behind it. The
	// diagonal is perfect calibration. Nothing is smoothed and nothing is
	// fitted: a decile with three claims in it is drawn small and stays noisy,
	// which is the honest picture of a young record.
	let { buckets = [], excluded = 0 } = $props();

	const W = 460, H = 300, M = { l: 40, r: 16, t: 16, b: 40 };
	const innerW = W - M.l - M.r, innerH = H - M.t - M.b;

	let pts = $derived(
		(buckets || [])
			.filter((b) => b.n > 0)
			.map((b) => ({ stated: b.decile / 10 + 0.05, held: b.held / b.n, n: b.n, decile: b.decile }))
	);
	let maxN = $derived(pts.length ? Math.max(...pts.map((p) => p.n)) : 1);

	function xs(v) {
		return M.l + v * innerW;
	}
	function ys(v) {
		return M.t + (1 - v) * innerH;
	}
	function r(n) {
		return 3.2 + Math.sqrt(n / maxN) * 9;
	}
</script>

{#if pts.length}
	<div class="chart-wrap">
		<svg class="chart" viewBox="0 0 {W} {H}" role="img"
			aria-label="Reliability plot: stated probability against the share of those claims that held">
			{#each [0, 0.25, 0.5, 0.75, 1] as g}
				<line x1={M.l} x2={M.l + innerW} y1={ys(g)} y2={ys(g)} stroke="var(--paper-line)" />
				<text x={M.l - 6} y={ys(g) + 4} class="axis" text-anchor="end">{Math.round(g * 100)}</text>
				<text x={xs(g)} y={M.t + innerH + 16} class="axis" text-anchor="middle">{Math.round(g * 100)}</text>
			{/each}

			<line x1={xs(0)} y1={ys(0)} x2={xs(1)} y2={ys(1)} stroke="var(--ink-faint)"
				stroke-dasharray="4 4" stroke-width="1" />
			<text x={xs(1)} y={ys(1) - 6} class="axis" text-anchor="end">perfectly calibrated</text>

			{#each pts as p}
				<circle cx={xs(p.stated)} cy={ys(p.held)} r={r(p.n)} fill="var(--accent)" opacity="0.22" />
				<circle cx={xs(p.stated)} cy={ys(p.held)} r="2.6" fill="var(--accent)" />
				<title>stated {p.decile * 10}-{p.decile * 10 + 10}%: {p.held} of {p.n} held</title>
			{/each}

			<text x={M.l + innerW / 2} y={H - 6} class="axis" text-anchor="middle">stated probability %</text>
			<text x={12} y={M.t + innerH / 2} class="axis" text-anchor="middle"
				transform="rotate(-90 12 {M.t + innerH / 2})">held %</text>
		</svg>
	</div>
	{#if excluded > 0}
		<p class="fine" style="margin-top:.4rem">
			{excluded} resolved claim{excluded === 1 ? '' : 's'} carried a code-default probability and
			{excluded === 1 ? 'is' : 'are'} not plotted.
		</p>
	{/if}
{:else}
	<p class="muted" style="font-size:.88rem">No claim with a stated probability has resolved yet.</p>
{/if}

<script>
	// P(challenger better) across the paired trials of one Coach experiment,
	// against the bar it has to clear to be promoted and the floor at which it
	// is abandoned. Both thresholds come from the lever's own recorded floors,
	// never a constant here - the playbook's bar is 0.95 and the muse's 0.90,
	// and a chart that hard-coded either would lie about the other.
	let { series = [], promoteAt = 0.9, futilityAt = 0.05, label = '' } = $props();

	const W = 460, H = 180, M = { l: 34, r: 14, t: 14, b: 26 };
	const innerW = W - M.l - M.r, innerH = H - M.t - M.b;

	let pts = $derived((series || []).filter((v) => typeof v === 'number'));
	function xs(i) {
		return M.l + (pts.length > 1 ? (i / (pts.length - 1)) * innerW : innerW / 2);
	}
	function ys(v) {
		return M.t + (1 - v) * innerH;
	}
	let linePath = $derived(
		pts.map((v, i) => `${i === 0 ? 'M' : 'L'}${xs(i).toFixed(1)},${ys(v).toFixed(1)}`).join(' ')
	);
	let last = $derived(pts.length ? pts[pts.length - 1] : null);
	let promoted = $derived(last !== null && last >= promoteAt);
</script>

{#if pts.length > 1}
	<div class="chart-wrap">
		<svg class="chart" viewBox="0 0 {W} {H}" role="img"
			aria-label="Probability the challenger is better across {pts.length} paired trials{label ? `, ${label}` : ''}">
			{#each [0, 0.5, 1] as g}
				<line x1={M.l} x2={M.l + innerW} y1={ys(g)} y2={ys(g)} stroke="var(--paper-line)" />
				<text x={M.l - 6} y={ys(g) + 4} class="axis" text-anchor="end">{g.toFixed(1)}</text>
			{/each}

			<line x1={M.l} x2={M.l + innerW} y1={ys(promoteAt)} y2={ys(promoteAt)}
				stroke="var(--caution)" stroke-width="1.4" stroke-dasharray="4 3" />
			<text x={M.l + innerW} y={ys(promoteAt) - 5} class="axis" text-anchor="end" fill="var(--caution)">
				promote at {promoteAt}
			</text>

			<line x1={M.l} x2={M.l + innerW} y1={ys(futilityAt)} y2={ys(futilityAt)}
				stroke="var(--danger)" stroke-width="1" stroke-dasharray="3 3" opacity="0.7" />

			<path d={linePath} fill="none" stroke="var(--accent)" stroke-width="2.1" stroke-linejoin="round" />
			<circle cx={xs(pts.length - 1)} cy={ys(last)} r="4"
				fill={promoted ? 'var(--accent)' : 'var(--paper-raised)'} stroke="var(--accent)" stroke-width="2" />
			<text x={M.l + innerW / 2} y={H - 6} class="axis" text-anchor="middle">paired trials</text>
		</svg>
	</div>
{:else}
	<p class="muted" style="font-size:.88rem">No trial has been scored on this lever yet.</p>
{/if}

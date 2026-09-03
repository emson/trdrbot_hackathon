<script>
	// Every resolved forecast with a STATED probability, as a dot at that
	// probability - traded and declined alike, since D-052 scores a decline
	// exactly like a trade. A code-default 0.5 is never plotted (it is not a
	// claim anyone made).
	let { forecasts = [] } = $props();

	const W = 640, H = 140, M = { l: 16, r: 16, t: 16, b: 26 };
	const innerW = W - M.l - M.r;
	const LANE_HELD = M.t + 24;
	const LANE_FAILED = H - M.b - 24;

	let stated = $derived(
		forecasts.filter((f) => f.probability_stated !== false && typeof f.stated === 'number')
	);
	let excluded = $derived(forecasts.length - stated.length);

	function xs(p) {
		return M.l + p * innerW;
	}
</script>

{#if stated.length}
	<div class="chart-wrap">
		<svg class="chart" viewBox="0 0 {W} {H}" role="img"
			aria-label="Resolved forecasts by stated probability, held or failed">
			<line x1={M.l} x2={M.l + innerW} y1={LANE_HELD} y2={LANE_HELD} stroke="var(--paper-line)" />
			<line x1={M.l} x2={M.l + innerW} y1={LANE_FAILED} y2={LANE_FAILED} stroke="var(--paper-line)" />
			<text x={M.l} y={LANE_HELD - 8} class="axis">held</text>
			<text x={M.l} y={LANE_FAILED + 16} class="axis">failed</text>

			{#each [0, 0.25, 0.5, 0.75, 1] as p}
				<text x={xs(p)} y={H - 4} class="axis" text-anchor="middle">{(p * 100).toFixed(0)}%</text>
			{/each}

			{#each stated as f}
				<circle
					cx={xs(f.stated)} cy={f.held ? LANE_HELD : LANE_FAILED} r="4"
					fill={f.traded ? 'var(--accent)' : 'none'}
					stroke="var(--accent)" stroke-width="1.4"
				>
					<title>{f.underlying}: {(f.claim || '').slice(0, 120)}</title>
				</circle>
			{/each}
		</svg>
	</div>
	{#if excluded}
		<p class="fine" style="margin-top:.5rem">
			{excluded} claim{excluded === 1 ? '' : 's'} carried a code-default 0.5 and {excluded === 1 ? 'is' : 'are'} not plotted.
		</p>
	{/if}
{:else}
	<p class="muted" style="font-size:.88rem">No resolved forecasts with a stated probability yet.</p>
{/if}

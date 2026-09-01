<script>
	import { usd, pct, num, dateOnly } from '$lib/format.js';
	import Attribution2x2 from '$lib/components/Attribution2x2.svelte';
	import CompetenceLadder from '$lib/components/CompetenceLadder.svelte';
	import EquityCurve from '$lib/components/EquityCurve.svelte';
	import Callout from '$lib/components/Callout.svelte';
	import Term from '$lib/components/Term.svelte';

	let { data } = $props();
	let acct = $derived(data.account);
	let cal = $derived(data.calibration);
	let pnlTone = $derived((acct.pnl_usd ?? 0) >= 0 ? 'up' : 'down');
</script>

<svelte:head><title>Scoreboard — trdrbot</title></svelte:head>

<section class="block ledger">
	<div class="wrap">
		<span class="kicker">The scorecard</span>
		<h1 style="margin:.5rem 0 .8rem">Results, stated plainly.</h1>
		<p class="standfirst">
			P&amp;L Performance is a real judging category, and the number is reported here in full —
			but a genuinely 60%-edge agent only beats a coin flip 69% of the time over 20 trades
			(measured, not assumed), so a one-week P&amp;L is closer to noise than proof. The
			calibration and attribution below are the honest instruments for the harder question:
			did the agent actually know what it was doing.
		</p>
	</div>
</section>

<section class="block ledger" style="padding-top:0">
	<div class="wrap">
		<div class="cols c4">
			<div class="card"><span class="stat-tile"><span class="label">Equity</span>
				<span class="big">{usd(acct.equity)}</span>
				<span class="provenance">high water {usd(acct.high_water)}</span></span></div>
			<div class="card"><span class="stat-tile"><span class="label">P&amp;L</span>
				<span class="big {pnlTone}">{pct(acct.pnl_pct)}</span>
				<span class="provenance">{usd(acct.pnl_usd, { sign: true })} on {usd(acct.start)}</span></span></div>
			<div class="card"><span class="stat-tile"><span class="label">Drawdown</span>
				<span class="big">{pct(acct.drawdown, { sign: false })}</span>
				<span class="provenance">from high water</span></span></div>
			<div class="card"><span class="stat-tile"><span class="label">Data as of</span>
				<span class="big" style="font-size:1.1rem">{dateOnly(acct.as_of)}</span>
				<span class="provenance">{acct.start_note}</span></span></div>
		</div>

		<div class="card pad-lg" style="margin-top:1.2rem">
			<h3>Equity over time</h3>
			<EquityCurve series={data.equityCurve} start={acct.start} />
		</div>
	</div>
</section>

<section class="block ledger">
	<div class="wrap">
		<h2>Calibration.</h2>
		<p class="standfirst" style="margin-top:.5rem">
			Whether stated confidence matched observed frequency — a harder, more honest question
			than "did it make money." <Term name="Brier score" /> and the
			<Term name="Murphy decomposition" /> answer it directly.
		</p>
		<div class="cols c4" style="margin-top:1.2rem">
			<div class="card"><span class="stat-tile"><span class="label">Brier score</span>
				<span class="big">{cal.brier !== null ? cal.brier.toFixed(3) : 'n/a'}</span>
				<span class="provenance">0 = perfect, 0.25 = coin flip</span></span></div>
			<div class="card"><span class="stat-tile"><span class="label">Reliability</span>
				<span class="big">{cal.reliability !== null ? cal.reliability.toFixed(3) : 'n/a'}</span>
				<span class="provenance">lower is better</span></span></div>
			<div class="card"><span class="stat-tile"><span class="label">Resolution</span>
				<span class="big">{cal.resolution !== null ? cal.resolution.toFixed(3) : 'n/a'}</span>
				<span class="provenance">higher is better</span></span></div>
			<div class="card"><span class="stat-tile"><span class="label">Base rate</span>
				<span class="big">{cal.base_rate !== null ? pct(cal.base_rate, { sign: false }) : 'n/a'}</span>
				<span class="provenance">of resolved forecasts held</span></span></div>
		</div>
		<Callout eyebrow="Sample size — read this before the numbers above">
			{cal.sample_note}
		</Callout>
	</div>
</section>

<section class="block ledger">
	<div class="wrap">
		<div class="cols side-r">
			<div>
				<Attribution2x2 attribution={data.attribution} />
			</div>
			<div class="stack" style="gap:.7rem">
				<h2>Attribution.</h2>
				<p class="standfirst">
					Was the view right, and was the way it was expressed right — scored separately, so a
					profit on a wrong view (bottom-right) is excluded from what lets the agent size up.
				</p>
			</div>
		</div>
	</div>
</section>

<section class="block ledger">
	<div class="wrap">
		<h2>The competence ladder.</h2>
		<p class="standfirst" style="margin-top:.5rem">Position size is earned, not chosen — four rungs, gated on resolved theses, calibration reliability, and attribution rate.</p>
		<div style="margin-top:1.2rem">
			<CompetenceLadder competence={data.competence} />
		</div>
	</div>
</section>

<section class="block ledger">
	<div class="wrap">
		<h2>Book risk.</h2>
		<p class="standfirst" style="margin-top:.5rem">Beta-weighted, because names are not exposures.</p>
		<div class="cols c4" style="margin-top:1.2rem">
			<div class="card"><span class="stat-tile"><span class="label">Positions</span>
				<span class="big">{data.book.positions ?? 0}</span></span></div>
			<div class="card"><span class="stat-tile"><span class="label">Raw delta</span>
				<span class="big">{usd(data.book.delta_dollars)}</span></span></div>
			<div class="card"><span class="stat-tile"><span class="label">Beta-weighted delta</span>
				<span class="big">{usd(data.book.beta_weighted_delta)}</span></span></div>
			<div class="card"><span class="stat-tile"><span class="label">Vega / Theta</span>
				<span class="big" style="font-size:1.3rem">{usd(data.book.vega_dollars)} / {usd(data.book.theta_dollars)}</span></span></div>
		</div>
	</div>
</section>

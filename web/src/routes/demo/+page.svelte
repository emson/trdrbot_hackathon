<script>
	import { dateTime, pct, strategyLabel, usd, usd0 } from '$lib/format.js';
	import {
		candidatesFor, daysUntil, defaultCandidateRow, defaultThesis, frameHeading, hashFor,
		selectCycle
	} from '$lib/demo.js';
	import CandidateTable from '$lib/components/CandidateTable.svelte';
	import Callout from '$lib/components/Callout.svelte';
	import CoachCard from '$lib/components/CoachCard.svelte';
	import CycleReel from '$lib/components/CycleReel.svelte';
	import ForecastDots from '$lib/components/ForecastDots.svelte';
	import Funnel from '$lib/components/Funnel.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import MarkdownBody from '$lib/components/MarkdownBody.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import PayoffChart from '$lib/components/PayoffChart.svelte';
	import PriceBand from '$lib/components/PriceBand.svelte';
	import StatusPill from '$lib/components/StatusPill.svelte';

	let { data } = $props();

	const ATTR_TONE = {
		thesis_right_expression_right: 'good', thesis_right_expression_wrong: 'warn',
		thesis_wrong_expression_faithful: '', thesis_wrong_profited_anyway: 'bad', unscoreable: ''
	};
	const ELF = {
		traded: '/img/elf-confident.jpg', acted: '/img/elf-analysing.jpg',
		declined: '/img/elf-analysing.jpg', error: null
	};

	let hash = $state('');
	$effect(() => {
		hash = window.location.hash;
		const onHashChange = () => (hash = window.location.hash);
		window.addEventListener('hashchange', onHashChange);
		return () => window.removeEventListener('hashchange', onHashChange);
	});

	let cycle = $derived(selectCycle(data.cycles, hash));

	let selectedThesisId = $state('');
	let selectedCandidateName = $state('');
	$effect(() => {
		const cur = cycle;
		selectedThesisId = defaultThesis(cur)?.entry_id ?? '';
	});

	let thesis = $derived(
		(cycle?.think.theses || []).find((t) => t.entry_id === selectedThesisId) || defaultThesis(cycle)
	);
	let candBlock = $derived(thesis ? candidatesFor(cycle, thesis.entry_id) : null);
	let candRows = $derived(candBlock?.rows || []);
	$effect(() => {
		selectedCandidateName = defaultCandidateRow(candRows)?.name ?? '';
	});
	let selectedCandidate = $derived(
		candRows.find((r) => r.name === selectedCandidateName) || defaultCandidateRow(candRows)
	);

	let position = $derived(
		cycle?.act.position_id ? (data.positions || []).find((p) => p.id === cycle.act.position_id) : null
	);

	function pick(c) {
		hash = hashFor(c);
		window.history.replaceState(null, '', hash);
	}

	let band = $derived(thesis ? { low: thesis.band_low, high: thesis.band_high } : null);
</script>

<svelte:head><title>Watch it decide — trdrbot</title></svelte:head>

<section class="block ledger">
	<div class="wrap">
		<PageHeader kicker="Watch it decide">
			{#snippet heading()}Watch Theo decide.{/snippet}
			One real cycle of the loop, replayed from the record: what arrived, the claim it made, the
			structures it priced and threw out, what it did about it, and how that was scored
			afterwards. Nothing here is generated for this page. Every number was written by the loop
			at the moment it happened, and it refreshes with the record.
		</PageHeader>

		<p class="fine" style="margin-top:1.2rem">
			Equity {usd0(data.account.equity)} ({pct(data.account.pnl_pct)}) ·
			{data.counts.theses} claims · {data.counts.traded} traded · {data.counts.declined} declined ·
			{data.counts.forecasts_resolved} scored
		</p>

		{#if data.cycles.length}
			<div style="margin-top:1.4rem">
				<CycleReel cycles={data.cycles} selectedId={cycle?.id} onselect={pick} />
			</div>
			{#if cycle}
				<p class="fine" style="margin-top:.6rem">
					decision {cycle.id} · outcome {cycle.outcome} {cycle.outcome_ref} · model {cycle.model} ·
					{cycle.tool_calls} tool call{cycle.tool_calls === 1 ? '' : 's'}
				</p>
			{/if}
		{:else}
			<p class="muted" style="margin-top:1.4rem">No decide cycles are on the record yet.</p>
		{/if}
	</div>
</section>

{#if cycle}
	<!-- 01 · Sense -->
	<section class="block ledger frame">
		<div class="wrap">
			<span class="kicker">01 · Sense</span>
			<h2 style="margin:.4rem 0 1.2rem">What arrived.</h2>
			<div class="cols side">
				<div class="stack">
					{#if cycle.sense.items.length}
						{#each cycle.sense.items as item}
							{#if item.kind === 'opportunity'}
								<div class="card">
									<span class="tag neutral">{item.source} opportunity · {item.underlying}</span>
									<Callout eyebrow="the claim, as it entered the prompt">{item.claim}</Callout>
									<p class="fine">
										band {item.band_low}-{item.band_high} · resolves {item.horizon}
										{#if item.suggested_structures?.length}· suggested: {item.suggested_structures.join(' / ')}{/if}
									</p>
								</div>
							{:else if item.kind === 'news'}
								<div class="card">
									<p style="font-weight:600">{item.headline}</p>
									<p class="fine">{item.source} · {item.created_at} · {(item.symbols || []).join(', ')}</p>
								</div>
							{:else if item.kind === 'position_review' || item.kind === 'market_pulse'}
								<div class="card">
									<span class="tag neutral">reviewing open position{(item.underlyings || []).length === 1 ? '' : 's'}</span>
									<p class="fine">{item.reason} — {(item.underlyings || []).join(', ')}</p>
								</div>
							{:else if item.kind === 'manual'}
								<div class="card"><span class="tag neutral">operator note</span><p>{item.text}</p></div>
							{:else if item.kind === 'prediction_market'}
								<div class="card">
									<p style="font-weight:600">{item.question}</p>
									<p class="fine">implied probability {((item.implied_probability ?? 0) * 100).toFixed(1)}%</p>
								</div>
							{:else}
								<div class="card"><span class="fine">{item.kind} item {item.id}</span></div>
							{/if}
						{/each}
						{#if cycle.sense.items_total > cycle.sense.items.length}
							<p class="fine">and {cycle.sense.items_total - cycle.sense.items.length} more</p>
						{/if}
					{:else}
						<p class="muted">The decision read no inbox items this cycle (a positions-only review).</p>
					{/if}
				</div>
				<div>
					{#if cycle.sense.market}
						<div class="card">
							<span class="stat-tile-label fine">the market it saw — {cycle.sense.market.underlying}</span>
							<p class="fine">spot {cycle.sense.market.spot} · IV {cycle.sense.market.iv_pct}%
								{#if cycle.sense.market.sigma}· σ {cycle.sense.market.sigma}{/if}
								· {cycle.sense.market.days}d to {cycle.sense.market.expiry}</p>
							<p class="fine">priced {dateTime(cycle.sense.market.priced_at)}</p>
						</div>
					{:else}
						<p class="muted">No chain was priced this cycle.</p>
					{/if}
				</div>
			</div>
		</div>
	</section>

	<!-- 02 · Think -->
	<section class="block ledger frame">
		<div class="wrap">
			<div style="display:flex; justify-content:space-between; align-items:flex-start; gap:1rem">
				<div>
					<span class="kicker">02 · Think</span>
					<h2 style="margin:.4rem 0 1.2rem">A claim that can be proved wrong, and the ways to bet on it.</h2>
				</div>
				<div class="plate sm" style="width:72px; flex:none"><img src="/img/elf-thinking.jpg" alt="" width="72" height="60" loading="lazy" /></div>
			</div>

			{#if cycle.think.theses.length}
				<div class="cols" style="grid-template-columns:1fr; gap:.6rem" role="radiogroup" aria-label="Claims recorded this cycle">
					{#each cycle.think.theses as t}
						<button
							type="button" class="card" role="radio" aria-checked={t.entry_id === thesis?.entry_id}
							style="text-align:left; cursor:pointer; border-color:{t.entry_id === thesis?.entry_id ? 'var(--accent)' : 'var(--paper-line)'}"
							onclick={() => (selectedThesisId = t.entry_id)}
						>
							<div style="display:flex; gap:.5rem; align-items:baseline; flex-wrap:wrap">
								<span class="tag neutral">{t.underlying}</span>
								<span class="tag {t.kind === 'muse' ? 'ai' : 'neutral'}">{t.kind}</span>
							</div>
							<p>{t.claim}</p>
							<p class="fine">
								{t.probability_stated ? `stated ${(t.probability * 100).toFixed(0)}%` : 'probability not stated (0.5 assumed by code, excluded from calibration)'}
								· resolves {t.horizon}
								· band {t.band_high === null ? `above ${t.band_low}` : t.band_low === null ? `below ${t.band_high}` : `${t.band_low}-${t.band_high}`}
								{#if t.metric === 'realized_vol_pct'}· realised vol{/if}
							</p>
						</button>
					{/each}
				</div>

				{#if thesis}
					<div class="cols side" style="margin-top:1.4rem">
						<div class="card pad-lg">
							<span class="tag code">Fact — the tape</span>
							<PriceBand
								closes={thesis.closes} underlying={thesis.underlying} decisionDay={cycle.ts.slice(0, 10)}
								{band}
								resolved={thesis.resolved_at ? { price_at_horizon: thesis.price_at_horizon, outcome: thesis.outcome } : null}
							/>
						</div>
						<div class="cols" style="grid-template-columns:1fr">
							<div class="stat-tile"><span class="label">Resolves</span><span class="big">{thesis.horizon}</span></div>
							<div class="stat-tile"><span class="label">Band</span><span class="big" style="font-size:1.3rem">{thesis.band_low ?? '—'}–{thesis.band_high ?? '—'}</span></div>
						</div>
					</div>

					<h3 style="margin-top:1.6rem">Structures priced for this claim</h3>
					{#if candBlock}
						<CandidateTable rows={candRows} selectedName={selectedCandidate?.name} onselect={(r) => (selectedCandidateName = r.name)} />
						{#if selectedCandidate}
							<div class="card pad-lg" style="margin-top:1rem">
								<span class="tag code">Fact — contract arithmetic. The shaded band is the claim.</span>
								<PayoffChart payoff={selectedCandidate.payoff} band={{ low: thesis.band_low, high: thesis.band_high }} />
							</div>
						{/if}
						<p class="fine" style="margin-top:.5rem">structures from {candBlock.source} row {candBlock.ref}</p>
					{:else if thesis.position_id}
						<p class="muted">Structures were priced for this claim — see the trade story below.</p>
					{:else}
						<p class="muted">No structures were priced for this claim (the record itemises them from 3 Sep 2026 on).</p>
					{/if}
				{/if}

				{#if cycle.think.muse_fates.length}
					<h3 style="margin-top:1.6rem">Thrown out before a claim was even recorded</h3>
					<div class="stack" style="gap:.4rem">
						{#each cycle.think.muse_fates as f}
							<p class="fine">{f.underlying} — <span class="tag warn">{f.fate}</span> (stated {((f.stated ?? 0) * 100).toFixed(0)}%)</p>
						{/each}
					</div>
				{/if}
			{:else}
				<p class="muted">No new claim this cycle.</p>
			{/if}
		</div>
	</section>

	<!-- 03 · Act / Declined -->
	<section class="block ledger frame">
		<div class="wrap">
			<div style="display:flex; justify-content:space-between; align-items:flex-start; gap:1rem">
				<div>
					<span class="kicker">03 · {cycle.outcome === 'declined' ? 'Declined' : 'Act'}</span>
					<h2 style="margin:.4rem 0 1.2rem">{frameHeading(cycle.outcome)}</h2>
				</div>
				{#if ELF[cycle.outcome]}
					<div class="plate sm" style="width:72px; flex:none"><img src={ELF[cycle.outcome]} alt="" width="72" height="60" loading="lazy" /></div>
				{/if}
			</div>

			{#if cycle.outcome === 'traded' && cycle.act.sizing}
				<div class="cols c3">
					<div class="stat-tile"><span class="label">Contracts</span><span class="big">{cycle.act.sizing.contracts}</span><span class="provenance">{cycle.act.sizing.structure}</span></div>
					<div class="stat-tile"><span class="label">Fraction of equity</span><span class="big">{pct(cycle.act.sizing.fraction, { digits: 1 })}</span><span class="provenance">bound by {cycle.act.sizing.binding || 'not recorded'}</span></div>
					<div class="stat-tile"><span class="label">Max loss</span><span class="big down">{position ? usd0(position.max_loss_usd) : 'not recorded'}</span></div>
				</div>
				{#if cycle.act.competence}
					<p class="fine" style="margin-top:.8rem">sized at the {cycle.act.competence.tier} rung · book cap {pct(cycle.act.competence.book_cap, { digits: 0 })} · Kelly multiplier {(cycle.act.competence.kelly_multiplier ?? 0).toFixed(2)}</p>
				{/if}
				{#if position}
					<a class="btn ghost sm" style="margin-top:1rem" href="/ledger/{position.id}">open the position <Icon name="arrowRight" size={14} /></a>
				{/if}
			{:else if cycle.outcome === 'declined'}
				{#if cycle.act.summary_html}
					<div class="quote"><MarkdownBody html={cycle.act.summary_html} /><cite>the decision's own summary</cite></div>
				{:else}
					<p class="muted">The decision's summary was not usable (dropped by the prose guard).</p>
				{/if}
				{#if thesis}
					<Callout eyebrow="scored anyway">
						Theo declined the trade but recorded the claim. It resolves on {thesis.horizon} against
						the tape at zero capital risk, and counts in the calibration sample exactly like a
						traded one.
					</Callout>
				{/if}
			{:else if cycle.outcome === 'acted'}
				{#if cycle.act.summary_html}
					<div class="quote"><MarkdownBody html={cycle.act.summary_html} /><cite>the decision's own summary</cite></div>
				{:else}
					<p class="muted">An order action was taken this cycle (a replace or a close), with nothing new to size.</p>
				{/if}
			{:else if cycle.outcome === 'error'}
				<p class="muted">The cycle failed before deciding: {cycle.act.error_class || 'not recorded'}</p>
			{/if}
		</div>
	</section>

	<!-- 04 · Learn -->
	<section class="block ledger frame">
		<div class="wrap">
			<span class="kicker">04 · Learn</span>
			<h2 style="margin:.4rem 0 1.2rem">How it was scored.</h2>

			{#if thesis}
				<div class="card">
					{#if thesis.resolved_at}
						<span class="tag {thesis.outcome ? 'good' : 'bad'}">{thesis.outcome ? 'held' : 'failed'}</span>
						<p class="fine">close at horizon {usd(thesis.price_at_horizon)} vs band {thesis.band_low ?? '—'}-{thesis.band_high ?? '—'}</p>
					{:else}
						{@const d = daysUntil(thesis.horizon, data.generatedAt)}
						<p class="fine">{d !== null && d > 0 ? `resolves ${thesis.horizon} · in ${d} day${d === 1 ? '' : 's'}` : `awaiting a price for ${thesis.horizon}`}</p>
					{/if}
				</div>
			{/if}

			{#if position}
				<div class="card" style="margin-top:.8rem">
					<StatusPill status={position.status} />
					{#if position.close_reason}<p class="fine">{position.close_reason}</p>{/if}
					{#if position.last_pnl_pct !== null && position.last_pnl_pct !== undefined}
						<p class="big {position.last_pnl_pct >= 0 ? 'up' : 'down'}">{pct(position.last_pnl_pct)} of net entry cost</p>
					{/if}
					{#if position.attribution}
						<span class="tag {ATTR_TONE[position.attribution] || 'neutral'}">{position.attribution_label}</span>
					{:else}
						<p class="fine">attribution fires once the claim's horizon has passed</p>
					{/if}
				</div>
			{:else if cycle.outcome === 'traded'}
				<p class="muted">never filled, nothing to score</p>
			{/if}

			{#if !thesis && !position}
				<p class="muted">Nothing to score from this cycle yet.</p>
			{/if}
		</div>
	</section>

	<!-- 05 · Remember -->
	<section class="block ledger frame">
		<div class="wrap">
			<span class="kicker">05 · Remember</span>
			<h2 style="margin:.4rem 0 1.2rem">What it kept.</h2>
			<div class="cols c4">
				<div class="card">
					<h4>journal</h4>
					<p class="fine">{Object.values(cycle.remember.journal_kinds).reduce((a, b) => a + b, 0)} rows this cycle</p>
					<p class="fine">{Object.entries(cycle.remember.journal_kinds).map(([k, n]) => `${k} ${n}`).join(' · ')}</p>
				</div>
				<div class="card">
					<h4>ledger</h4>
					<p class="fine">{cycle.remember.ledger_entry_ids.length} claim(s) recorded</p>
				</div>
				<div class="card">
					<h4>wiki</h4>
					{#if position}
						<p class="fine">position and trade-blog pages written</p>
					{:else}
						<p class="fine">nothing new</p>
					{/if}
				</div>
				<div class="card">
					<h4>elfmem</h4>
					<p class="fine">{cycle.remember.journal_kinds.fill ? 'fill credited a memory block' : cycle.remember.journal_kinds.attribution_run ? 'attribution ran this cycle' : 'nothing credited yet'}</p>
				</div>
			</div>
		</div>
	</section>
{/if}

<!-- The funnel -->
<section class="block ledger">
	<div class="wrap">
		<span class="kicker">The funnel</span>
		<h2 style="margin:.4rem 0 .6rem">Where ideas go.</h2>
		<p class="muted" style="max-width:60ch; margin-bottom:1.2rem">
			Most of what Theo thinks of dies before money moves. Every step below is a count from the
			record, and the part that did not go on is written next to the part that did.
		</p>
		<Funnel funnel={data.funnel} />
	</div>
</section>

<!-- Calibration -->
<section class="block ledger">
	<div class="wrap">
		<span class="kicker">Calibration</span>
		<h2 style="margin:.4rem 0 1.2rem">Scored anyway.</h2>
		<Callout>{data.calibration.verdict}</Callout>
		<div style="margin-top:1.2rem">
			<ForecastDots forecasts={data.forecasts} />
		</div>
	</div>
</section>

<!-- The Coach -->
<section class="block ledger">
	<div class="wrap">
		<span class="kicker">The Coach</span>
		<h2 style="margin:.4rem 0 .6rem">Then it grades itself.</h2>
		<p class="muted" style="max-width:64ch; margin-bottom:1.2rem">
			Two levers the Coach is allowed to move, each scored by arithmetic it cannot reach. A
			challenger is promoted only on evidence, and there have been {data.coach.promotions_total}
			promotion{data.coach.promotions_total === 1 ? '' : 's'} so far.
		</p>
		{#if data.coach.enabled}
			<div class="cols c2">
				{#each data.coach.levers as lv}
					<CoachCard lever={lv} />
				{/each}
			</div>
		{:else}
			<p class="muted">The Coach is disabled in config.</p>
		{/if}
	</div>
</section>

<!-- Close -->
<section class="block ledger">
	<div class="wrap">
		<div class="cols c3">
			<a class="card" href="/ledger">
				<span class="kicker">Go deeper</span>
				<h3>Every decision, newest first.</h3>
			</a>
			<a class="card" href="/how-it-works">
				<span class="kicker">Go deeper</span>
				<h3>How the loop is built.</h3>
			</a>
			<a class="card" href="/submission">
				<span class="kicker">Go deeper</span>
				<h3>For judges.</h3>
			</a>
		</div>
	</div>
</section>

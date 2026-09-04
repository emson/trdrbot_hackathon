<script>
	import { dateTime, pct, strategyLabel, usd, usd0 } from '$lib/format.js';
	import {
		attributionBars, candidatesFor, claimHalfWidth, daysUntil, deciles, defaultCandidateRow,
		defaultThesis, equityMarkers, frameHeading, hashFor, horizonDays, impliedMove, marketFor,
		pBandHolds, selectCycle, sigmaT
	} from '$lib/demo.js';
	import CandidateTable from '$lib/components/CandidateTable.svelte';
	import Callout from '$lib/components/Callout.svelte';
	import CoachCard from '$lib/components/CoachCard.svelte';
	import CycleReel from '$lib/components/CycleReel.svelte';
	import EquityCurve from '$lib/components/EquityCurve.svelte';
	import ForecastDots from '$lib/components/ForecastDots.svelte';
	import Funnel from '$lib/components/Funnel.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import MarkdownBody from '$lib/components/MarkdownBody.svelte';
	import PayoffChart from '$lib/components/PayoffChart.svelte';
	import PosteriorTrace from '$lib/components/PosteriorTrace.svelte';
	import PriceBand from '$lib/components/PriceBand.svelte';
	import ReliabilityPlot from '$lib/components/ReliabilityPlot.svelte';
	import StatusPill from '$lib/components/StatusPill.svelte';

	let { data } = $props();

	const ATTR_TONE = {
		thesis_right_expression_right: 'good', thesis_right_expression_wrong: 'warn',
		thesis_wrong_expression_faithful: '', thesis_wrong_profited_anyway: 'bad', unscoreable: ''
	};
	const TABS = [
		{ id: 'loop', label: 'The loop' },
		{ id: 'book', label: 'The book' },
		{ id: 'coach', label: 'The coach' }
	];

	let tab = $state('loop');

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

	// --- the modelled cone, and the edge it implies -------------------------
	// Every value here is null unless the record actually carries what it
	// needs: a priced chain or an opened position for the vol, and a horizon
	// for the time. A cycle without them draws a band and no cone, which is
	// the honest picture rather than an invented one.
	let market = $derived(marketFor(cycle, data.positions));
	let coneDays = $derived(thesis ? horizonDays(cycle?.ts, thesis.horizon) : null);
	let cone = $derived(
		market && coneDays > 0 ? { spot: market.spot, ivPct: market.ivPct, days: coneDays } : null
	);
	let st = $derived(market ? sigmaT(market.ivPct, coneDays) : null);

	// P(the band holds). The agent records its own on every candidate row it
	// priced - the same number it gated on - and that one wins whenever it
	// exists, because showing a figure recomputed here next to a decision made
	// on a different one would be its own small lie. `p_band` is a property of
	// the claim, not the structure, so it is identical across the rows and any
	// of them will do. Falls back to recomputing from the chain's own vol, and
	// to nothing at all when the record has neither.
	let pRecorded = $derived(
		candRows.find((r) => typeof r.p_band === 'number')?.p_band ?? null
	);
	let pModelled = $derived(
		pRecorded !== null
			? pRecorded
			: thesis && market && st
				? pBandHolds(market.spot, thesis.band_low, thesis.band_high, st)
				: null
	);
	let pSource = $derived(pRecorded !== null ? "the agent's own, at decision time" : 'recomputed from the chain');
	let implied = $derived(market && st ? impliedMove(market.spot, st) : null);
	let claimed = $derived(
		thesis && market ? claimHalfWidth(market.spot, thesis.band_low, thesis.band_high) : null
	);
	let vsMax = $derived(Math.max(implied || 0, claimed || 0) || 1);

	// --- play the day -------------------------------------------------------
	let playing = $state(false);
	$effect(() => {
		if (!playing) return;
		const ordered = [...(data.cycles || [])].reverse();
		const id = setInterval(() => {
			const i = ordered.findIndex((c) => c.id === cycle?.id);
			pick(ordered[(i + 1) % ordered.length]);
		}, 2600);
		return () => clearInterval(id);
	});

	// --- the book -----------------------------------------------------------
	let markers = $derived(equityMarkers(data.positions, data.equityCurve));
	let attr = $derived(attributionBars(data.attribution));
	let attrMax = $derived(Math.max(1, ...attr.rows.map((r) => r.n)));
	let buckets = $derived(deciles(data.forecasts));
	let sortedPositions = $derived(
		[...(data.positions || [])].sort((a, b) => (b.opened || '').localeCompare(a.opened || ''))
	);

	// Header sparkline over the whole recorded curve.
	let sparkPath = $derived(
		(() => {
			const s = (data.equityCurve || []).map((p) => p.equity).filter((v) => typeof v === 'number');
			if (s.length < 2) return '';
			const lo = Math.min(...s), hi = Math.max(...s), span = hi - lo || 1;
			return s
				.map((v, i) => `${i === 0 ? 'M' : 'L'}${((i / (s.length - 1)) * 104).toFixed(1)},${(30 - ((v - lo) / span) * 26 - 2).toFixed(1)}`)
				.join(' ');
		})()
	);
</script>

<svelte:head><title>Watch it decide — trdrbot</title></svelte:head>

<!-- ============================ the bar ============================ -->
<section class="block ledger floor-bar">
	<div class="wrap">
		<div class="bar">
			<div class="bar-id">
				<h1>Theo's Floor</h1>
				<div class="pills-row">
					<span class="pill open">loop running</span>
					<span class="fine">tick {data.tick} · {data.counts.cycles} cycles</span>
				</div>
			</div>
			<div class="bar-stats">
				<div class="hstat spark">
					<div>
						<span class="label">equity</span>
						<span class="v">{usd0(data.account.equity)}
							<small class={data.account.pnl_pct >= 0 ? 'up' : 'down'}>{pct(data.account.pnl_pct)}</small>
						</span>
					</div>
					{#if sparkPath}
						<svg viewBox="0 0 104 30" role="img" aria-label="Equity since inception">
							<path d={sparkPath} fill="none" stroke="var(--accent)" stroke-width="1.7" stroke-linejoin="round" />
						</svg>
					{/if}
				</div>
				<div class="hstat">
					<span class="label">tier</span>
					<span class="v" style="font-size:.9rem">{data.competence.tier.toUpperCase()}</span>
					<div class="rungs" role="img" aria-label="Competence tier {data.competence.tier}">
						{#each data.competence.ladder as rung}
							<span class="rung" class:on={data.competence.ladder.findIndex((r) => r.key === data.competence.tier) >= data.competence.ladder.indexOf(rung)}></span>
						{/each}
					</div>
				</div>
				<div class="hstat">
					<span class="label">brier</span>
					<span class="v">{data.calibration.brier.toFixed(3)}</span>
					<span class="sub">{data.calibration.n} scored</span>
				</div>
				<div class="hstat">
					<span class="label">open</span>
					<span class="v">{data.counts.positions_open}</span>
					<span class="sub">of {data.counts.positions} taken</span>
				</div>
			</div>
		</div>

		<div class="tabs" role="tablist" aria-label="Views">
			{#each TABS as t}
				<button
					type="button" role="tab" class="tab" id="tab-{t.id}" aria-controls="panel-{t.id}"
					aria-selected={tab === t.id} onclick={() => (tab = t.id)}
				>{t.label}</button>
			{/each}
		</div>
	</div>
</section>

<!-- ============================ the loop ============================ -->
<section role="tabpanel" id="panel-loop" aria-labelledby="tab-loop" hidden={tab !== 'loop'}>
	<div class="block ledger">
		<div class="wrap">
			{#if data.cycles.length}
				<div class="reel-head">
					<span class="fine">{data.cycles.length} recent cycles, newest first</span>
					<button type="button" class="playb" aria-pressed={playing} onclick={() => (playing = !playing)}>
						{playing ? 'pause' : 'play the day'}
					</button>
				</div>
				<CycleReel cycles={data.cycles} selectedId={cycle?.id} onselect={(c) => { playing = false; pick(c); }} />
				{#if cycle}
					<p class="fine" style="margin-top:.6rem">
						decision {cycle.id} · outcome {cycle.outcome} · model {cycle.model} ·
						{cycle.tool_calls} tool call{cycle.tool_calls === 1 ? '' : 's'} · {dateTime(cycle.ts)}
					</p>
				{/if}
			{:else}
				<p class="muted">No decide cycles are on the record yet.</p>
			{/if}
		</div>
	</div>

	{#if cycle}
		<!-- the claim, drawn against what the market implied -->
		<div class="block ledger">
			<div class="wrap">
				<div class="cols side">
					<div class="card pad-lg">
						<div class="tile-head">
							<span class="kicker">02 · Think</span>
							<span>
								<span class="tag code">Fact — the tape</span>
								{#if cone}<span class="tag warn">Modelled — the cone</span>{/if}
							</span>
						</div>
						<h2 class="tile-h">{thesis ? `The claim on ${thesis.underlying}` : 'No claim this cycle.'}</h2>
						{#if thesis}
							<p class="claim">{thesis.claim}</p>
							<PriceBand
								closes={thesis.closes} underlying={thesis.underlying}
								decisionDay={cycle.ts.slice(0, 10)} {band} {cone}
								resolved={thesis.resolved_at ? { price_at_horizon: thesis.price_at_horizon, outcome: thesis.outcome } : null}
							/>
							{#if cone}
								<p class="fine" style="margin-top:.5rem">
									cone from {market.source} · {(market.ivPct * 100).toFixed(1)}% IV over {coneDays} day{coneDays === 1 ? '' : 's'},
									drift zero. The claim is the dashed box; the shaded cone is where the market said
									the price would be.
								</p>
							{:else}
								<p class="fine" style="margin-top:.5rem">
									Theo priced no chain this cycle, so there is no implied move to draw the claim
									against. The cycles marked <span class="tag good">traded</span> in the reel above
									have one.
								</p>
							{/if}
						{:else}
							<p class="muted">This cycle recorded no falsifiable claim, so there is nothing to draw.</p>
						{/if}
					</div>

					<div class="card pad-lg">
						<div class="tile-head"><span class="kicker">The edge</span></div>
						{#if thesis}
							<div class="edge-grid">
								<div class="eg">
									<span class="label">stated</span>
									<span class="n">{thesis.probability_stated ? `${(thesis.probability * 100).toFixed(0)}%` : 'not stated'}</span>
									<span class="sub">the agent's own number</span>
								</div>
								<div class="eg">
									<span class="label">modelled</span>
									<span class="n">{pModelled !== null ? `${(pModelled * 100).toFixed(0)}%` : 'no chain'}</span>
									<span class="sub">{pModelled !== null ? `P(band holds), ${pSource}` : 'none was priced this cycle'}</span>
								</div>
							</div>
							{#if implied && claimed}
								<div class="vs">
									<span class="label">what the market implies vs what the claim needs</span>
									<div class="vsbar"><i style="width:{((implied / vsMax) * 100).toFixed(0)}%; background:var(--paper-line)"></i></div>
									<p class="vsrow"><span>implied move, 1σ</span><span>±{usd(implied)}</span></p>
									<div class="vsbar"><i style="width:{((claimed / vsMax) * 100).toFixed(0)}%; background:var(--accent)"></i></div>
									<p class="vsrow"><span>the claimed band</span><span>±{usd(claimed)}</span></p>
								</div>
							{/if}
							<p class="fine" style="margin-top:.9rem">
								resolves {thesis.horizon}{#if coneDays > 0}, in {coneDays} day{coneDays === 1 ? '' : 's'}{/if}
							</p>
						{:else}
							<p class="muted">No claim, so no edge to state.</p>
						{/if}
					</div>
				</div>
			</div>
		</div>

		<!-- what arrived, and what it argued with itself about -->
		<div class="block ledger">
			<div class="wrap">
				<div class="cols side-l">
					<div class="card pad-lg">
						<div class="tile-head">
							<span class="kicker">01 · Sense</span>
							<span class="fine">{cycle.sense.items_total} item{cycle.sense.items_total === 1 ? '' : 's'}</span>
						</div>
						<h2 class="tile-h">What arrived.</h2>
						<div class="scrollbox">
							{#if cycle.sense.items.length}
								{#each cycle.sense.items as item}
									{#if item.kind === 'opportunity'}
										<div class="wrow">
											<span class="tag neutral">{item.source} · {item.underlying}</span>
											<p>{item.claim}</p>
											<p class="fine">band {item.band_low}-{item.band_high} · resolves {item.horizon}</p>
										</div>
									{:else if item.kind === 'news'}
										<div class="wrow">
											<span class="tag neutral">news</span>
											<p>{item.headline}</p>
											<p class="fine">{item.source} · {(item.symbols || []).join(', ')}</p>
										</div>
									{:else if item.kind === 'position_review' || item.kind === 'market_pulse'}
										<div class="wrow">
											<span class="tag neutral">position review</span>
											<p class="fine">{item.reason} — {(item.underlyings || []).join(', ')}</p>
										</div>
									{:else if item.kind === 'manual'}
										<div class="wrow"><span class="tag neutral">operator note</span><p>{item.text}</p></div>
									{:else if item.kind === 'prediction_market'}
										<div class="wrow">
											<span class="tag neutral">odds</span>
											<p>{item.question}</p>
											<p class="fine">implied {((item.implied_probability ?? 0) * 100).toFixed(1)}%</p>
										</div>
									{:else}
										<div class="wrow"><span class="fine">{item.kind} item {item.id}</span></div>
									{/if}
								{/each}
								{#if cycle.sense.items_total > cycle.sense.items.length}
									<p class="fine">and {cycle.sense.items_total - cycle.sense.items.length} more</p>
								{/if}
							{:else}
								<p class="muted">The decision read no inbox items this cycle (a positions-only review).</p>
							{/if}
						</div>
						{#if cycle.sense.market}
							<p class="fine" style="margin-top:.7rem; border-top:1px solid var(--paper-line); padding-top:.7rem">
								the chain it priced — {cycle.sense.market.underlying} spot {cycle.sense.market.spot} ·
								IV {cycle.sense.market.iv_pct}% · {cycle.sense.market.days}d to {cycle.sense.market.expiry}
							</p>
						{/if}
					</div>

					<div class="card pad-lg">
						<div class="tile-head">
							<span class="kicker">02 · Think</span>
							<span class="fine">
								{cycle.think.theses.length} claim{cycle.think.theses.length === 1 ? '' : 's'}{#if cycle.think.muse_fates.length}, {cycle.think.muse_fates.length} cut{/if}
							</span>
						</div>
						<h2 class="tile-h">Competing claims, narrowed to one.</h2>
						<div class="scrollbox">
							{#if cycle.think.theses.length}
								<div role="radiogroup" aria-label="Claims recorded this cycle" class="stack" style="gap:.5rem">
									{#each cycle.think.theses as t}
										<button
											type="button" class="trow" role="radio" aria-checked={t.entry_id === thesis?.entry_id}
											onclick={() => (selectedThesisId = t.entry_id)}
										>
											<span class="trow-top">
												<span class="tag neutral">{t.underlying}</span>
												<span class="tag {t.kind === 'muse' ? 'ai' : 'neutral'}">{t.kind}</span>
												{#if t.position_id}<span class="tag good">traded</span>{/if}
											</span>
											<span class="trow-claim">{t.claim}</span>
											<span class="fine">
												{t.probability_stated ? `stated ${(t.probability * 100).toFixed(0)}%` : 'probability not stated'}
												· resolves {t.horizon}
											</span>
										</button>
									{/each}
								</div>
							{:else}
								<p class="muted">No new claim this cycle.</p>
							{/if}

							{#if cycle.think.muse_fates.length}
								<p class="rnd">Cut before a claim was recorded</p>
								{#each cycle.think.muse_fates as f}
									<div class="wrow">
										<span class="fine">{f.underlying} — stated {((f.stated ?? 0) * 100).toFixed(0)}%</span>
										<p class="fate">{f.fate}</p>
									</div>
								{/each}
							{/if}
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- structures, and what it did about them -->
		<div class="block ledger">
			<div class="wrap">
				{#if candBlock}
					<div class="card pad-lg">
						<div class="tile-head">
							<span class="kicker">02 · Think</span>
							<span class="fine">structures from {candBlock.source}</span>
						</div>
						<h2 class="tile-h">The ways to bet on it, priced and thrown out.</h2>
						<CandidateTable rows={candRows} selectedName={selectedCandidate?.name} onselect={(r) => (selectedCandidateName = r.name)} />
					</div>
				{/if}

				<div class="cols side" style="margin-top:{candBlock ? '1.2rem' : '0'}">
					<div class="card pad-lg">
						<div class="tile-head">
							<span class="kicker">Payoff at expiry</span>
							<span>
								<span class="tag code">Fact — arithmetic</span>
								{#if market && st}<span class="tag warn">Modelled — where it lands</span>{/if}
							</span>
						</div>
						{#if selectedCandidate?.payoff}
							<PayoffChart
								payoff={selectedCandidate.payoff} band={band}
								density={market && st ? { spot: market.spot, sigmaT: st } : null}
							/>
							<p class="fine" style="margin-top:.5rem">
								A structure that expresses the claim is above zero inside the shaded band and below it
								outside{#if market && st}. The shading underneath is where the model says the price
								actually lands{/if}.
							</p>
						{:else if position?.payoff}
							<PayoffChart payoff={position.payoff} entrySpot={position.entry_spot} band={band} />
						{:else}
							<p class="muted">No structure was priced in this cycle's record.</p>
						{/if}
					</div>

					<div class="card pad-lg">
						<div class="tile-head">
							<span class="kicker">03 · {cycle.outcome === 'declined' ? 'Declined' : 'Act'}</span>
						</div>
						<h2 class="tile-h">{frameHeading(cycle.outcome)}</h2>

						{#if cycle.outcome === 'traded' && cycle.act.sizing}
							<div class="kv"><span class="k">structure</span><span class="v">{cycle.act.sizing.structure}</span></div>
							<div class="kv"><span class="k">contracts</span><span class="v">{cycle.act.sizing.contracts}</span></div>
							<div class="kv"><span class="k">fraction of equity</span><span class="v">{pct(cycle.act.sizing.fraction, { digits: 2, sign: false })}</span></div>
							<div class="kv"><span class="k">bound by</span><span class="v">{cycle.act.sizing.binding || 'not recorded'}</span></div>
							{#if position}
								<div class="kv"><span class="k">max loss</span><span class="v down">{usd0(position.max_loss_usd)}</span></div>
							{/if}
							{#if cycle.act.competence}
								<p class="fine" style="margin-top:.7rem">
									sized at the {cycle.act.competence.tier} rung · book cap
									{pct(cycle.act.competence.book_cap, { digits: 0, sign: false })} · Kelly multiplier
									{(cycle.act.competence.kelly_multiplier ?? 0).toFixed(2)}
								</p>
							{/if}
							{#if position}
								<a class="btn ghost sm" style="margin-top:.9rem" href="/ledger/{position.id}">open the position <Icon name="arrowRight" size={14} /></a>
							{/if}
						{:else if cycle.outcome === 'declined'}
							{#if cycle.act.summary_html}
								<div class="quote"><MarkdownBody html={cycle.act.summary_html} /><cite>the decision's own summary</cite></div>
							{:else}
								<p class="muted">The decision's summary was not usable (dropped by the prose guard).</p>
							{/if}
							{#if thesis}
								<Callout eyebrow="scored anyway">
									Theo declined the trade but kept the claim. It resolves on {thesis.horizon} against the
									tape at zero capital risk, and counts in calibration exactly like a traded one.
								</Callout>
							{/if}
						{:else if cycle.outcome === 'acted'}
							{#if cycle.act.summary_html}
								<div class="quote"><MarkdownBody html={cycle.act.summary_html} /><cite>the decision's own summary</cite></div>
							{:else}
								<p class="muted">An order action was taken this cycle, with nothing new to size.</p>
							{/if}
						{:else if cycle.outcome === 'error'}
							<p class="muted">The cycle failed before deciding: {cycle.act.error_class || 'not recorded'}</p>
						{/if}
					</div>
				</div>
			</div>
		</div>

		<!-- scored, and kept -->
		<div class="block ledger">
			<div class="wrap">
				<div class="cols side-l">
					<div class="card pad-lg">
						<div class="tile-head"><span class="kicker">04 · Learn</span></div>
						<h2 class="tile-h">How it was scored.</h2>
						{#if thesis}
							{#if thesis.resolved_at}
								<span class="tag {thesis.outcome ? 'good' : 'bad'}">{thesis.outcome ? 'held' : 'failed'}</span>
								<p class="fine" style="margin-top:.4rem">close at horizon {usd(thesis.price_at_horizon)} vs band {thesis.band_low ?? '—'}-{thesis.band_high ?? '—'}</p>
							{:else}
								{@const d = daysUntil(thesis.horizon, data.generatedAt)}
								<p class="fine">{d !== null && d > 0 ? `resolves ${thesis.horizon}, in ${d} day${d === 1 ? '' : 's'}` : `awaiting a price for ${thesis.horizon}`}</p>
							{/if}
						{/if}
						{#if position}
							<div style="margin-top:.9rem; border-top:1px solid var(--paper-line); padding-top:.9rem">
								<StatusPill status={position.status} />
								{#if position.close_reason}<p class="fine">{position.close_reason}</p>{/if}
								{#if position.last_pnl_pct !== null && position.last_pnl_pct !== undefined}
									<p class="big {position.last_pnl_pct >= 0 ? 'up' : 'down'}">{pct(position.last_pnl_pct)} of net entry cost</p>
								{/if}
								{#if position.attribution}
									<span class="tag {ATTR_TONE[position.attribution] || 'neutral'}">{position.attribution_label}</span>
								{:else}
									<p class="fine">attribution fires once the claim's horizon has passed, never on the money alone</p>
								{/if}
							</div>
						{:else if cycle.outcome === 'traded'}
							<p class="muted">never filled, nothing to score</p>
						{/if}
						{#if !thesis && !position}
							<p class="muted">Nothing to score from this cycle yet.</p>
						{/if}
					</div>

					<div class="card pad-lg">
						<div class="tile-head"><span class="kicker">05 · Remember</span></div>
						<h2 class="tile-h">What it kept.</h2>
						<div class="kv"><span class="k">journal</span><span class="v">{Object.values(cycle.remember.journal_kinds).reduce((a, b) => a + b, 0)} rows</span></div>
						<div class="kv"><span class="k">ledger</span><span class="v">{cycle.remember.ledger_entry_ids.length} claim(s)</span></div>
						<div class="kv"><span class="k">wiki</span><span class="v">{position ? 'position + blog written' : 'nothing new'}</span></div>
						<div class="kv"><span class="k">elfmem</span><span class="v">{cycle.remember.journal_kinds.fill ? 'fill credited' : cycle.remember.journal_kinds.attribution_run ? 'attribution ran' : 'nothing credited'}</span></div>
						<p class="fine" style="margin-top:.7rem">{Object.entries(cycle.remember.journal_kinds).map(([k, n]) => `${k} ${n}`).join(' · ')}</p>
					</div>
				</div>
			</div>
		</div>
	{/if}
</section>

<!-- ============================ the book ============================ -->
<section role="tabpanel" id="panel-book" aria-labelledby="tab-book" hidden={tab !== 'book'}>
	<div class="block ledger">
		<div class="wrap">
			<div class="card pad-lg">
				<div class="tile-head">
					<span class="kicker">Paper account</span>
					<span class="fine">markers are position opens</span>
				</div>
				<div class="cols c4" style="margin-bottom:1rem">
					<div class="stat-tile"><span class="label">Equity</span><span class="big">{usd0(data.account.equity)}</span><span class="provenance">from {usd0(data.account.start)}</span></div>
					<div class="stat-tile"><span class="label">Return</span><span class="big {data.account.pnl_pct >= 0 ? 'up' : 'down'}">{pct(data.account.pnl_pct)}</span><span class="provenance">since inception</span></div>
					<div class="stat-tile"><span class="label">Positions</span><span class="big">{data.counts.positions}</span><span class="provenance">{data.counts.positions_open} open · {data.counts.positions_never_filled} never filled</span></div>
					<div class="stat-tile"><span class="label">Claims</span><span class="big">{data.counts.theses}</span><span class="provenance">{data.counts.traded} traded · {data.counts.declined} declined</span></div>
				</div>
				<EquityCurve series={data.equityCurve} start={data.account.start} {markers} />
			</div>
		</div>
	</div>

	<div class="block ledger">
		<div class="wrap">
			<div class="cols side-l">
				<div class="card pad-lg">
					<div class="tile-head">
						<span class="kicker">Positions</span>
						<span class="fine">outcome and attribution are separate marks</span>
					</div>
					<h2 class="tile-h">Every position it has taken.</h2>
					<div class="scrollbox tall">
						{#each sortedPositions as p}
							<a class="prow" href="/ledger/{p.id}">
								<span class="prow-id">
									<span class="sym">{p.underlying}</span>
									<span class="fine">{strategyLabel(p.strategy)}</span>
								</span>
								<span class="prow-mid">
									<StatusPill status={p.status} />
									{#if p.attribution}
										<span class="tag {ATTR_TONE[p.attribution] || 'neutral'}">{p.attribution_label}</span>
									{:else if p.status === 'open'}
										<span class="fine">attribution waits for the horizon</span>
									{/if}
								</span>
								<span class="prow-pnl {(p.last_pnl_pct ?? 0) >= 0 ? 'up' : 'down'}">
									{p.last_pnl_pct === null || p.last_pnl_pct === undefined ? '—' : pct(p.last_pnl_pct)}
								</span>
							</a>
						{/each}
					</div>
				</div>

				<div class="stack">
					<div class="card pad-lg">
						<div class="tile-head"><span class="kicker">Attribution</span></div>
						<h2 class="tile-h">Why it was right, not whether it paid.</h2>
						{#each attr.rows as r}
							<div class="abar">
								<span class="abar-top"><span>{r.label}</span><span class="fine">{r.n}</span></span>
								<span class="abar-track"><i style="width:{((r.n / attrMax) * 100).toFixed(0)}%"
									class:good={r.key === 'held_profit'} class:warn={r.key === 'held_loss'}
									class:bad={r.key === 'failed_profit'}></i></span>
								<span class="fine">{r.note}</span>
							</div>
						{/each}
						{#if attr.awaiting}
							<p class="fine" style="margin-top:.7rem">{attr.awaiting} position{attr.awaiting === 1 ? '' : 's'} still awaiting a horizon.</p>
						{/if}
					</div>

					<div class="card pad-lg">
						<div class="tile-head"><span class="kicker">Calibration</span></div>
						<h2 class="tile-h">Stated against what happened.</h2>
						<ReliabilityPlot buckets={buckets.buckets} excluded={buckets.excluded} />
					</div>
				</div>
			</div>
		</div>
	</div>

	<div class="block ledger">
		<div class="wrap">
			<div class="card pad-lg">
				<div class="tile-head"><span class="kicker">Calibration</span></div>
				<h2 class="tile-h">Scored anyway.</h2>
				<Callout>{data.calibration.verdict}</Callout>
				<div style="margin-top:1.2rem"><ForecastDots forecasts={data.forecasts} /></div>
			</div>
		</div>
	</div>

	<div class="block ledger">
		<div class="wrap">
			<div class="card pad-lg">
				<div class="tile-head"><span class="kicker">The funnel</span></div>
				<h2 class="tile-h">Where ideas go.</h2>
				<p class="muted" style="max-width:60ch; margin-bottom:1.2rem">
					Most of what Theo thinks of dies before money moves. Every step is a count from the
					record, and the part that did not go on is written next to the part that did.
				</p>
				<Funnel funnel={data.funnel} />
			</div>
		</div>
	</div>
</section>

<!-- ============================ the coach ============================ -->
<section role="tabpanel" id="panel-coach" aria-labelledby="tab-coach" hidden={tab !== 'coach'}>
	<div class="block ledger">
		<div class="wrap">
			<p class="muted" style="max-width:64ch; margin-bottom:1.2rem">
				Two levers the Coach is allowed to move, each scored by arithmetic it cannot reach. A
				challenger is promoted only on evidence, and there {data.coach.promotions_total === 1 ? 'has' : 'have'} been
				{data.coach.promotions_total} promotion{data.coach.promotions_total === 1 ? '' : 's'} so far.
			</p>

			{#if data.coach.enabled}
				<div class="cols c2">
					{#each data.coach.levers as lv}
						<div class="card pad-lg">
							<div class="tile-head">
								<span class="kicker">{lv.name}</span>
								<span class="fine">{lv.state}</span>
							</div>
							{#if lv.experiment?.posterior_series?.length > 1}
								<!-- The trace only. The run counts and the posterior bar live in
								     CoachCard below, and printing them twice on one card reads as
								     two different measurements of the same thing. -->
								<PosteriorTrace
									series={lv.experiment.posterior_series}
									promoteAt={lv.experiment.floors?.promote_at ?? 0.9}
									futilityAt={lv.experiment.floors?.futility_at ?? 0.05}
									label={lv.name}
								/>
							{:else}
								<p class="muted">No trial has been scored on this lever yet.</p>
							{/if}
							<CoachCard lever={lv} />
						</div>
					{/each}
				</div>
			{:else}
				<p class="muted">The Coach is disabled in config.</p>
			{/if}
		</div>
	</div>
</section>

<!-- ============================ close ============================ -->
<section class="block ledger">
	<div class="wrap">
		<div class="cols c3">
			<a class="card" href="/ledger"><span class="kicker">Go deeper</span><h3>Every decision, newest first.</h3></a>
			<a class="card" href="/how-it-works"><span class="kicker">Go deeper</span><h3>How the loop is built.</h3></a>
			<a class="card" href="/submission"><span class="kicker">Go deeper</span><h3>For judges.</h3></a>
		</div>
	</div>
</section>

<style>
	/* The bar: one row of identity and state, then the tabs. Deliberately not
	   sticky - the site nav already is, and two stacked sticky rows eat a
	   phone's whole screen. */
	.floor-bar { padding-bottom: 0; }
	.bar { display: flex; align-items: flex-end; justify-content: space-between;
		gap: 1.2rem; flex-wrap: wrap; }
	.bar-id h1 { font-size: clamp(1.4rem, 2.6vw, 1.9rem); margin: 0; }
	.pills-row { display: flex; align-items: center; gap: .6rem; margin-top: .4rem; flex-wrap: wrap; }
	.bar-stats { display: flex; gap: .55rem; flex-wrap: wrap; }
	.hstat { background: var(--paper-raised); border: 1px solid var(--paper-line);
		border-radius: var(--r-sharp); padding: .5rem .8rem; min-width: 104px; }
	.hstat .label { font-family: var(--mono); font-size: .62rem; letter-spacing: .1em;
		text-transform: uppercase; color: var(--ink-faint); display: block; }
	.hstat .v { font-family: var(--mono); font-size: 1rem; font-weight: 600;
		font-variant-numeric: tabular-nums; display: block; line-height: 1.3; }
	.hstat .v small { font-size: .7rem; font-weight: 500; margin-left: .25em; }
	.hstat .sub { font-family: var(--mono); font-size: .63rem; color: var(--ink-faint); }
	.hstat.spark { display: flex; align-items: center; gap: .7rem; }
	.hstat.spark svg { width: 104px; height: 30px; flex: none; }
	.rungs { display: flex; gap: 2px; margin-top: .3rem; }
	.rung { height: 4px; flex: 1; background: var(--paper-sunk); border: 1px solid var(--paper-line);
		border-radius: 1px; }
	.rung.on { background: var(--accent); border-color: var(--accent); }
	.up { color: var(--accent); } .down { color: var(--danger); }

	.tabs { display: flex; gap: .1rem; margin-top: 1.3rem;
		border-bottom: 1px solid var(--paper-line); }
	.tab { background: none; border: 0; cursor: pointer; font: inherit; font-size: .92rem;
		color: var(--ink-soft); padding: .6rem 1rem .7rem; border-bottom: 2px solid transparent;
		margin-bottom: -1px; }
	.tab:hover { color: var(--ink); }
	.tab[aria-selected="true"] { color: var(--ink); font-weight: 600;
		border-bottom-color: var(--accent); }

	.reel-head { display: flex; align-items: center; justify-content: space-between;
		gap: 1rem; margin-bottom: .7rem; flex-wrap: wrap; }
	.playb { font-family: var(--mono); font-size: .68rem; letter-spacing: .08em;
		text-transform: uppercase; border: 1px solid var(--paper-line); background: var(--paper-raised);
		border-radius: 999px; padding: .35em .95em; cursor: pointer; color: var(--ink-soft); }
	.playb:hover { border-color: var(--accent); color: var(--accent); }
	.playb[aria-pressed="true"] { background: var(--accent); border-color: var(--accent); color: var(--paper); }

	.tile-head { display: flex; align-items: baseline; justify-content: space-between;
		gap: 1rem; flex-wrap: wrap; margin-bottom: .5rem; }
	.tile-h { font-size: clamp(1rem, 1.6vw, 1.2rem); margin: 0 0 .7rem; }
	.claim { font-family: var(--serif); font-size: 1.06rem; line-height: 1.4; margin-bottom: .9rem; }

	/* Panels scroll inside themselves so a long list of competing claims does
	   not push the charts off the page. */
	.scrollbox { max-height: 22rem; overflow-y: auto; scrollbar-width: thin; padding-right: .4rem; }
	.scrollbox.tall { max-height: 30rem; }
	.wrow { padding: .6rem 0; border-bottom: 1px solid var(--paper-line); }
	.wrow:last-child { border-bottom: 0; }
	.wrow p { margin: .25rem 0 0; font-size: .88rem; }
	.fate { font-family: var(--mono); font-size: .74rem; color: var(--caution); }
	.rnd { font-family: var(--mono); font-size: .62rem; letter-spacing: .12em;
		text-transform: uppercase; color: var(--ink-faint); margin: 1rem 0 .2rem; }

	.trow { display: flex; flex-direction: column; gap: .3rem; width: 100%; text-align: left;
		background: none; border: 1px solid var(--paper-line); border-radius: var(--r-sharp);
		padding: .7rem .8rem; cursor: pointer; font: inherit; }
	.trow:hover { border-color: var(--accent); }
	.trow[aria-checked="true"] { border-color: var(--accent); background: var(--accent-soft); }
	.trow-top { display: flex; gap: .4rem; flex-wrap: wrap; }
	.trow-claim { font-size: .9rem; }

	.edge-grid { display: grid; grid-template-columns: 1fr 1fr; gap: .8rem; }
	.eg .label { font-family: var(--mono); font-size: .62rem; letter-spacing: .1em;
		text-transform: uppercase; color: var(--ink-faint); display: block; }
	.eg .n { font-family: var(--mono); font-size: 1.5rem; font-weight: 600; display: block;
		line-height: 1.2; font-variant-numeric: tabular-nums; }
	.eg .sub { font-family: var(--mono); font-size: .64rem; color: var(--ink-faint); }
	.vs { margin-top: 1rem; padding-top: .9rem; border-top: 1px solid var(--paper-line); }
	.vs .label { font-family: var(--mono); font-size: .62rem; letter-spacing: .1em;
		text-transform: uppercase; color: var(--ink-faint); display: block; margin-bottom: .5rem; }
	.vsbar { height: 9px; background: var(--paper-sunk); border: 1px solid var(--paper-line);
		border-radius: 5px; overflow: hidden; margin-bottom: .3rem; }
	.vsbar i { display: block; height: 100%; border-radius: 5px; }
	.vsrow { display: flex; justify-content: space-between; gap: 1rem; font-family: var(--mono);
		font-size: .7rem; color: var(--ink-faint); margin: 0 0 .6rem; }

	.kv { display: flex; justify-content: space-between; gap: 1rem; padding: .45rem 0;
		border-bottom: 1px dashed var(--paper-line); font-size: .88rem; }
	.kv:last-of-type { border-bottom: 0; }
	.kv .k { font-family: var(--mono); font-size: .66rem; letter-spacing: .07em;
		text-transform: uppercase; color: var(--ink-faint); }
	.kv .v { font-family: var(--mono); font-weight: 600; text-align: right; }

	.prow { display: grid; grid-template-columns: 10rem 1fr 5rem; gap: .9rem; align-items: center;
		padding: .7rem 0; border-bottom: 1px solid var(--paper-line); color: inherit;
		text-decoration: none; }
	.prow:last-child { border-bottom: 0; }
	.prow:hover { background: var(--paper-sunk); }
	.prow .sym { font-family: var(--mono); font-weight: 700; display: block; }
	.prow-mid { display: flex; gap: .4rem; align-items: center; flex-wrap: wrap; }
	.prow-pnl { font-family: var(--mono); font-weight: 600; text-align: right;
		font-variant-numeric: tabular-nums; }

	.abar { padding: .5rem 0; }
	.abar-top { display: flex; justify-content: space-between; gap: 1rem; font-size: .88rem;
		font-weight: 600; }
	.abar-track { display: block; height: 8px; background: var(--paper-sunk);
		border: 1px solid var(--paper-line); border-radius: 4px; overflow: hidden; margin: .35rem 0 .25rem; }
	.abar-track i { display: block; height: 100%; background: var(--ink-faint); }
	.abar-track i.good { background: var(--accent); }
	.abar-track i.warn { background: var(--caution); }
	.abar-track i.bad { background: var(--danger); }

	@media (max-width: 720px) {
		.edge-grid { grid-template-columns: 1fr; }
		.prow { grid-template-columns: 1fr auto; row-gap: .3rem; }
		.bar-stats { width: 100%; }
	}
</style>

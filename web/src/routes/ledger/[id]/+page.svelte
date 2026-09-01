<script>
	import { usd, pct, dateTime, strategyLabel } from '$lib/format.js';
	import StatusPill from '$lib/components/StatusPill.svelte';
	import MonoChip from '$lib/components/MonoChip.svelte';
	import Callout from '$lib/components/Callout.svelte';
	import PayoffChart from '$lib/components/PayoffChart.svelte';
	import MarkdownBody from '$lib/components/MarkdownBody.svelte';
	import SourceLink from '$lib/components/SourceLink.svelte';
	import Term from '$lib/components/Term.svelte';

	let { data } = $props();
	let p = $derived(data.position);

	const ATTR_TONE = {
		thesis_right_expression_right: 'good',
		thesis_right_expression_wrong: 'warn',
		thesis_wrong_expression_faithful: '',
		thesis_wrong_profited_anyway: 'bad',
		unscoreable: ''
	};
</script>

<svelte:head>
	<title>{p.underlying} {strategyLabel(p.strategy)} — trdrbot ledger</title>
</svelte:head>

<section class="block ledger">
	<div class="wrap narrow">
		<a href="/ledger" class="fine" style="text-decoration:none">&larr; back to the ledger</a>

		<div style="margin-top:1rem; display:flex; gap:.6rem; align-items:center; flex-wrap:wrap">
			<StatusPill status={p.status} />
			<h1 style="font-size:var(--d2)">{p.underlying} · <Term name={strategyLabel(p.strategy)} /></h1>
		</div>
		<div style="display:flex; gap:.5rem; flex-wrap:wrap; margin:.7rem 0 1.4rem">
			<MonoChip>opened {dateTime(p.opened)}</MonoChip>
			<MonoChip>expiry {p.expiry}</MonoChip>
			{#if p.close_reason}<MonoChip>closed: {p.close_reason}</MonoChip>{/if}
			{#if p.decision_ref}<MonoChip>{p.decision_ref}</MonoChip>{/if}
			{#if p.generated_by}<MonoChip>{p.generated_by}</MonoChip>{/if}
		</div>

		<!-- ── the thesis ──────────────────────────────────────────────── -->
		{#if p.thesis?.claim}
			<Callout eyebrow="The thesis">
				{p.thesis.claim}
			</Callout>
			<div class="cols c3" style="margin-top:.9rem">
				<div class="stat-tile"><span class="label">Resolves</span><span class="num">{p.thesis.horizon || 'not recorded'}</span></div>
				<div class="stat-tile"><span class="label">Band</span>
					<span class="num">{p.thesis.band_low ?? '?'}&ndash;{p.thesis.band_high ?? '?'}</span></div>
				<div class="stat-tile"><span class="label">Expected drift</span><span class="num">{pct(p.thesis.drift)}</span></div>
			</div>
		{/if}

		<!-- ── payoff (FACT) ───────────────────────────────────────────── -->
		<div class="card pad-lg" style="margin-top:1.6rem">
			<span class="tag code">Fact — contract arithmetic</span>
			<h3 style="margin-top:.3rem">Payoff at expiry</h3>
			<PayoffChart payoff={p.payoff} entrySpot={p.entry_spot} />
			{#if p.payoff.derivable}
				<div class="cols c3" style="margin-top:.4rem">
					<div class="stat-tile"><span class="label">Max loss</span><span class="num down">{usd(p.payoff.max_loss)}</span></div>
					<div class="stat-tile"><span class="label">Max profit</span>
						<span class="num up">{p.payoff.max_profit_unbounded ? 'unbounded' : usd(p.payoff.max_profit)}</span></div>
					<div class="stat-tile"><span class="label">Breakeven</span>
						<span class="num">{(p.payoff.breakevens || []).join(', ') || 'none in range'}</span></div>
				</div>
			{/if}
		</div>

		<!-- ── attribution ─────────────────────────────────────────────── -->
		{#if p.attribution}
			<div class="card" style="margin-top:1.2rem">
				<span class="tag {ATTR_TONE[p.attribution] || 'neutral'}">Attribution</span>
				<p style="margin-top:.2rem">{p.attribution_label}</p>
			</div>
		{:else}
			<Callout tone="caution" eyebrow="Not yet attributed">
				This position hasn't reached its thesis horizon, or the thesis had no checkable
				condition — attribution only fires once resolution is possible.
			</Callout>
		{/if}

		<!-- ── the story ────────────────────────────────────────────────── -->
		{#if p.story_html}
			<div style="margin-top:2rem">
				<MarkdownBody html={p.story_html} />
			</div>
		{:else}
			<Callout tone="caution" eyebrow="No trade story on record">
				This position predates the trade-blog feature (D-097) - no narrative write-up exists
				for it, only the machine record below.
			</Callout>
		{/if}

		<!-- ── provenance ───────────────────────────────────────────────── -->
		<div class="card" style="margin-top:2rem">
			<span class="kicker">Source</span>
			<div style="display:flex; flex-direction:column; gap:.3rem; margin-top:.3rem">
				<SourceLink path={p.wiki_path} sha={data.gitSha} label="wiki position record" />
				{#if p.blog_path}<SourceLink path={p.blog_path} sha={data.gitSha} label="trade blog entry" />{/if}
			</div>
		</div>
	</div>
</section>

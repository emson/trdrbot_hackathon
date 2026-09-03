<script>
	import { usd, pct, dateTime, titleCase } from '$lib/format.js';
	import Attribution2x2 from '$lib/components/Attribution2x2.svelte';
	import TickIndicator from '$lib/components/TickIndicator.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';

	let { data } = $props();
	let acct = $derived(data.account);
	let pnlTone = $derived((acct.pnl_usd ?? 0) >= 0 ? 'up' : 'down');
</script>

<svelte:head>
	<title>trdrbot — Theo, a self-improving options-trading agent</title>
</svelte:head>

<!-- ── hero ─────────────────────────────────────────────────────────── -->
<section class="block ledger">
	<div class="wrap">
		<div class="cols side">
			<div class="stack" style="gap:1.3rem">
				<PageHeader kicker="Alpaca AI Trading Agents Hackathon · paper trading">
					{#snippet heading()}Theo is a self-improving options-trading agent.{/snippet}
					Every cycle it gathers research, forms a falsifiable thesis, simulates the ways to
					trade it, and sizes the one it trusts most by a track record it has to <em>earn</em>.
					Then it scores itself honestly — whether the <strong>view</strong> was right, whether
					the <strong>structure</strong> was right, or whether it just got lucky — and only the
					first two ever move its confidence. That's the self-improving part: not a bigger model,
					a more honest one.
				</PageHeader>
				<div style="display:flex; gap:.7rem; flex-wrap:wrap">
					<a class="btn primary" href="/ledger">
						See the ledger <Icon name="arrowRight" size={16} />
					</a>
					<a class="btn ghost" href="/submission">For judges</a>
				</div>
				<TickIndicator tick={data.tick} generatedAt={data.generatedAt} now={new Date(data.generatedAt).getTime()} />
			</div>
			<div class="plate">
				<img src="/img/logo.jpeg" alt="Theo, trdrbot's mascot — a winking elf inside a speech-bubble frame with an ascending trend line" width="620" height="420" />
			</div>
		</div>
	</div>
</section>

<!-- ── live proof strip ─────────────────────────────────────────────── -->
<section class="block ledger" style="padding-top:2.2rem; padding-bottom:2.2rem">
	<div class="wrap">
		<div class="cols c4">
			<div class="card">
				<span class="stat-tile"><span class="label">Equity</span>
					<span class="big">{usd(acct.equity)}</span>
					<span class="provenance">agent/data/journal.jsonl · competence</span></span>
			</div>
			<div class="card">
				<span class="stat-tile"><span class="label">P&amp;L since $100,000 start</span>
					<span class="big {pnlTone}">{pct(acct.pnl_pct)}</span>
					<span class="provenance">{usd(acct.pnl_usd, { sign: true })}</span></span>
			</div>
			<div class="card">
				<span class="stat-tile"><span class="label">Decisions made</span>
					<span class="big">{data.counts.theses + data.counts.declined}</span>
					<span class="provenance">{data.counts.theses} theses · {data.counts.declined} declined</span></span>
			</div>
			<div class="card">
				<span class="stat-tile"><span class="label">Forecasts resolved</span>
					<span class="big">{data.counts.forecasts_resolved}</span>
					<span class="provenance">scored at zero capital risk</span></span>
			</div>
		</div>
	</div>
</section>

<!-- ── the 2x2 ──────────────────────────────────────────────────────── -->
<section class="block ledger">
	<div class="wrap">
		<div class="cols side-r">
			<div>
				<Attribution2x2 attribution={data.attribution} />
			</div>
			<div class="stack" style="gap:.9rem">
				<span class="kicker">The differentiator</span>
				<h2>Two questions, not one.</h2>
				<p class="standfirst">
					Most trading agents score themselves on profit and loss — which, over a one-week
					window, is close to statistical noise. Theo asks two separate questions instead:
					<strong>was the view right</strong>, and <strong>was the way it was expressed
					right</strong>. A profit on a wrong view never counts toward sizing up — the mechanism
					excludes it, not a policy.
				</p>
				<a class="btn ghost sm" href="/scoreboard">See the full scoreboard <Icon name="arrowRight" size={14} /></a>
			</div>
		</div>
	</div>
</section>

<!-- ── three doors ──────────────────────────────────────────────────── -->
<section class="block ledger">
	<div class="wrap">
		<h2 style="margin-bottom:1.6rem">Three ways in.</h2>
		<div class="cols c3">
			<a class="card pad-lg" href="/ledger">
				<Icon name="journal" size={22} />
				<h3>The record</h3>
				<p class="muted">Every decision the agent made, newest first — trades, declines, and
					resolved forecasts, in the agent's own words.</p>
			</a>
			<a class="card pad-lg" href="/how-it-works">
				<Icon name="automate" size={22} />
				<h3>The machine</h3>
				<p class="muted">The five-stage loop, the three ways it forms a view, and how Alpaca's
					MCP server is actually wired in.</p>
			</a>
			<a class="card pad-lg" href="/scoreboard">
				<Icon name="analytics" size={22} />
				<h3>The scorecard</h3>
				<p class="muted">P&amp;L stated plainly, calibration, the competence ladder, and the
					book's real risk shape.</p>
			</a>
		</div>
	</div>
</section>

<!-- ── latest decision ──────────────────────────────────────────────── -->
{#if data.latest}
	<section class="block ledger">
		<div class="wrap">
			<span class="kicker">Most recent</span>
			<h2 style="margin:.5rem 0 1.2rem">What Theo just did.</h2>
			<div class="card pad-lg">
				<div style="display:flex; justify-content:space-between; align-items:baseline; flex-wrap:wrap; gap:.5rem">
					<span class="tag {data.latest.kind === 'declined' ? 'neutral' : data.latest.kind === 'traded' ? 'good' : 'neutral'}">
						{titleCase(data.latest.kind)}
					</span>
					<span class="fine">{dateTime(data.latest.ts)}</span>
				</div>
				<h3 style="margin-top:.3rem">{data.latest.title}</h3>
				{#if data.latest.body_html}
					<div class="prose" style="font-size:.92rem">{@html data.latest.body_html}</div>
				{/if}
				{#if data.latest.position_id}
					<a class="btn ghost sm" style="align-self:flex-start; margin-top:.4rem" href="/ledger/{data.latest.position_id}">
						View position <Icon name="arrowRight" size={14} />
					</a>
				{/if}
			</div>
		</div>
	</section>
{/if}

<script>
	import { siteConfig } from '$lib/site.config.js';
	import { pct, usd } from '$lib/format.js';
	import MarkdownBody from '$lib/components/MarkdownBody.svelte';
	import Icon from '$lib/components/Icon.svelte';

	let { data } = $props();

	const CATEGORIES = [
		{
			title: 'P&L Performance',
			body: 'The real number, reported plainly — plus why a one-week P&L is a weak instrument for judging skill, measured rather than argued.',
			href: '/scoreboard', cta: 'See the scoreboard'
		},
		{
			title: 'Technology Implementation',
			body: "Alpaca's MCP server as the sole broker interface, one session per tick, real multi-leg orders, deterministic client order ids, a reconciler that runs before every decision.",
			href: '/how-it-works', cta: 'See how it works'
		},
		{
			title: 'Creativity & Originality',
			body: 'The attribution 2×2 — separating a right view from a lucky one — and three independent thesis sources including a creative-collision muse.',
			href: '/', cta: 'See the differentiator'
		},
		{
			title: 'Presentation & Execution',
			body: 'Every trade, every decline, every resolved forecast — published with the reasoning, not just the outcome.',
			href: '/ledger', cta: 'See the ledger'
		},
		{
			title: 'Social engagement',
			body: 'Build-in-public dev journals covering what actually happened, including the defects found and fixed along the way.',
			href: '/build-log', cta: 'See the build log'
		}
	];
</script>

<svelte:head><title>For judges — trdrbot</title></svelte:head>

<section class="block brand">
	<div class="wrap">
		<span class="kicker">Alpaca AI Trading Agents Hackathon</span>
		<h1 style="margin:.5rem 0 .8rem">For judges — everything in one place.</h1>
		<p class="lead">
			trdrbot senses markets and news, forms a falsifiable thesis, and simulates several option
			structures for expressing it. It sizes the winner by Kelly, gated on its own earned track
			record, then executes and manages the trade through Alpaca. Afterward, it scores itself
			honestly: was the <strong>view</strong> right, was the <strong>structure</strong> right, or
			did it just get lucky? Only the first two ever move its confidence. Paper trading only.
		</p>
		<div style="display:flex; gap:.7rem; flex-wrap:wrap; margin-top:1rem">
			<a class="btn ghost" href={siteConfig.deckPath} target="_blank" rel="noopener noreferrer">Slide deck <Icon name="external" size={14} /></a>
			{#if siteConfig.videoUrl}
				<a class="btn ghost" href={siteConfig.videoUrl} target="_blank" rel="noopener noreferrer">Video walkthrough <Icon name="external" size={14} /></a>
			{/if}
			{#if siteConfig.repoUrl}
				<a class="btn ghost" href={siteConfig.repoUrl} target="_blank" rel="noopener noreferrer">GitHub repository <Icon name="external" size={14} /></a>
			{/if}
		</div>
	</div>
</section>

<section class="block ledger">
	<div class="wrap">
		<h2>The five judging categories, mapped to evidence.</h2>
		<div class="cols c2" style="margin-top:1.2rem">
			{#each CATEGORIES as c}
				<a class="card pad-lg" href={c.href}>
					<span class="tag code">{c.title}</span>
					<p class="muted">{c.body}</p>
					<span class="fine" style="color:var(--accent)">{c.cta} &rarr;</span>
				</a>
			{/each}
			<div class="card pad-lg">
				<span class="tag neutral">Alpaca paper account</span>
				<p class="muted">The account ID that identifies this trading activity is supplied
					directly in the submission form, per the hackathon's own requirement — not published
					here. Every trade this account has made is published in full on this site.</p>
			</div>
		</div>
	</div>
</section>

<section class="block ledger">
	<div class="wrap narrow">
		<h2>The one-page write-up.</h2>
		<div style="margin-top:1rem">
			<MarkdownBody html={data.submissionHtml} />
		</div>
	</div>
</section>

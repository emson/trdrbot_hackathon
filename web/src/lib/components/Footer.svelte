<script>
	import { siteConfig } from '$lib/site.config.js';

	let { generatedAt = '', gitSha = '', tick = null } = $props();
</script>

<footer class="site-footer">
	<div class="wrap">
		<div class="footer-cols">
			<div class="stack" style="gap:.6rem">
				<a href="/" class="plain" style="font-family:var(--round); font-weight:600; font-size:1.05rem">trdrbot</a>
				<p class="muted" style="max-width:34ch">
					A self-improving options-trading agent that scores itself honestly, not just by P&amp;L.
					Built for the Alpaca AI Trading Agents Hackathon. Paper trading only.
				</p>
				<p class="fine">
					Built by {siteConfig.author.name} ·
					<a href={siteConfig.author.site} target="_blank" rel="noopener noreferrer"
						>{siteConfig.author.siteLabel}</a
					>
					·
					<a href={siteConfig.author.x} target="_blank" rel="noopener noreferrer"
						>{siteConfig.author.xLabel}</a
					>
				</p>
			</div>
			<div class="footer-links">
				<span class="kicker">Explore</span>
				<a href="/demo">Demo</a>
				<a href="/resources">Resources</a>
				<a href="/notes">Notes</a>
				<a href="/data">Data</a>
				<a href="/glossary">Glossary</a>
			</div>
			<div class="footer-links">
				<span class="kicker">Assets</span>
				<a href={siteConfig.deckPath} target="_blank" rel="noopener noreferrer">Slide deck</a>
				<a href="/coach-report.html" target="_blank" rel="noopener noreferrer">Coach report</a>
				<a href="/design-system.html" target="_blank" rel="noopener noreferrer">Design system</a>
				{#if siteConfig.repoUrl}
					<a href={siteConfig.repoUrl} target="_blank" rel="noopener noreferrer">GitHub</a>
				{/if}
			</div>
		</div>
		<div class="footer-bottom">
			<span class="fine">
				generated {generatedAt ? generatedAt.slice(0, 16).replace('T', ' ') + ' UTC' : 'unknown'}
				{#if tick !== null}· tick {tick}{/if}
				{#if gitSha}· <span class="chip" style="font-size:.68rem">{gitSha.slice(0, 7)}</span>{/if}
			</span>
			<span class="fine">Paper trading. Not investment advice.</span>
		</div>
	</div>
</footer>

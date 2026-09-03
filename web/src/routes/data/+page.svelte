<script>
	import { dateTime } from '$lib/format.js';
	import SourceLink from '$lib/components/SourceLink.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';

	let { data } = $props();

	// `tracked: false` = gitignored in the working repo (the agent's live,
	// ticking state) - shown as a plain path, not a GitHub link that would 404.
	const SOURCES = [
		{ path: 'agent/data/journal.jsonl', label: 'The journal', desc: 'Every decision, execution, fill and reflection the agent has recorded.', kind: 'journal_rows', tracked: false },
		{ path: 'agent/data/state/ledger.jsonl', label: 'The thesis ledger', desc: 'Every falsifiable claim ever formed, traded or not — pre-registered automatically.', kind: 'theses', tracked: false },
		{ path: 'agent/data/state/forecasts.jsonl', label: 'Forecasts', desc: 'Unconditional forecasts scored at zero capital risk, including declined setups.', kind: 'forecasts_resolved', tracked: false },
		{ path: 'agent/data/wiki/positions', label: 'Position records', desc: 'The structured machine record for every position — legs, greeks, exit rules, outcome.', kind: 'positions', tracked: true },
		{ path: 'agent/data/blog', label: 'Trade stories', desc: 'One markdown narrative per position, written for outside review.', kind: 'positions', tracked: true },
		{ path: 'agent/data/wiki', label: "The agent's wiki", desc: 'Technique notes, company dossiers, the regime page, lessons.', kind: 'notes', tracked: true },
		{ path: 'docs/dev_journals', label: 'Dev journals', desc: 'The build-in-public record of what was built and why.', kind: 'journals', tracked: true },
		{ path: 'specs/decisions.md', label: 'Decisions log', desc: 'Every named design decision, with the alternatives considered and why they lost.', kind: 'decisions_logged', tracked: true },
		{ path: 'specs/issues.md', label: 'Issues log', desc: "The project's own open bug ledger.", kind: null, tracked: true }
	];
</script>

<svelte:head><title>Data — trdrbot</title></svelte:head>

<section class="block ledger">
	<div class="wrap">
		<PageHeader kicker="Provenance">
			{#snippet heading()}Every number on this site, checkable.{/snippet}
			This site is generated directly from the files below by <code>trdrbot site export</code> —
			nothing here is hand-written or summarized from memory. What's shown as "not recorded"
			genuinely wasn't recorded, rather than being filled in with a plausible guess.
		</PageHeader>

		<div class="cols c3" style="margin-top:1.4rem">
			<div class="card"><span class="stat-tile"><span class="label">Redaction scan</span>
				<span class="tag {data.integrity.redaction_scan === 'clean' ? 'good' : 'bad'}">
					{data.integrity.redaction_scan || 'unknown'}</span>
				<span class="provenance">{data.integrity.patterns_checked} pattern(s) checked</span></span></div>
			<div class="card"><span class="stat-tile"><span class="label">Prose sanitizer</span>
				<span class="big" style="font-size:1.6rem">{data.integrity.summaries_dropped}</span>
				<span class="provenance">unreadable summaries dropped, not silently kept</span></span></div>
			<div class="card"><span class="stat-tile"><span class="label">Generated</span>
				<span class="big" style="font-size:1.15rem">{dateTime(data.generatedAt)}</span>
				<span class="provenance">tick {data.tick} · {data.gitSha?.slice(0, 7)}</span></span></div>
		</div>
	</div>
</section>

<section class="block ledger">
	<div class="wrap">
		<h2>Source files.</h2>
		<div class="scroll" style="margin-top:1rem">
			<table>
				<thead><tr><th>Source</th><th>What it is</th><th class="n">Rows exported</th></tr></thead>
				<tbody>
					{#each SOURCES as s}
						<tr>
							<td>
								{#if s.tracked}
									<SourceLink path={s.path} sha={data.gitSha} label={s.label} />
								{:else}
									<span class="chip" title="{s.path} — not tracked in git, the agent's live ticking state">{s.label}</span>
								{/if}
							</td>
							<td class="muted">{s.desc}</td>
							<td class="n">{s.kind ? (data.counts[s.kind] ?? '—') : '—'}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
		<p class="fine" style="margin-top:.8rem">
			<code>agent/data/journal.jsonl</code> and <code>agent/data/state/**</code> are append-only and
			gitignored in the working repo (they're the agent's live, ticking record) — every row
			exported here still traces back to that same file, whether or not it happens to be
			tracked in git at this moment.
		</p>
	</div>
</section>

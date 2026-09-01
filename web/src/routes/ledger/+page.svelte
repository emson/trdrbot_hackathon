<script>
	import { dateTime, titleCase } from '$lib/format.js';
	import EmptyState from '$lib/components/EmptyState.svelte';

	let { data } = $props();

	const FILTERS = [
		{ key: 'all', label: 'All' },
		{ key: 'traded', label: 'Traded' },
		{ key: 'declined', label: 'Declined' },
		{ key: 'thesis', label: 'Thesis (untraded)' },
		{ key: 'rejected', label: 'Rejected by a gate' },
		{ key: 'forecast_resolved', label: 'Forecast resolved' }
	];

	let active = $state('all');
	let counts = $derived(
		Object.fromEntries(FILTERS.map((f) => [f.key, f.key === 'all' ? data.items.length : data.items.filter((i) => i.kind === f.key).length]))
	);
	let filtered = $derived(active === 'all' ? data.items : data.items.filter((i) => i.kind === active));

	const KIND_TAG = {
		traded: 'good', declined: 'neutral', thesis: 'neutral', rejected: 'warn', forecast_resolved: 'code'
	};
	const KIND_LABEL = {
		traded: 'Traded', declined: 'Declined', thesis: 'Thesis', rejected: 'Rejected', forecast_resolved: 'Forecast'
	};
</script>

<svelte:head><title>The ledger — trdrbot</title></svelte:head>

<section class="block ledger">
	<div class="wrap">
		<span class="kicker">The central record</span>
		<h1 style="margin:.5rem 0 .6rem">Every decision, newest first.</h1>
		<p class="standfirst">
			Trades, declines, untraded theses, gate rejections and resolved forecasts — merged into
			one stream. A decline is a logged answer here, not a gap in the record: {counts.declined}
			of them carry the agent's own reasoning, verbatim.
		</p>

		<div class="chip-row" style="margin:1.6rem 0">
			{#each FILTERS as f}
				<button class="chip-btn" aria-pressed={active === f.key} onclick={() => (active = f.key)} type="button">
					{f.label} <span class="count">{counts[f.key]}</span>
				</button>
			{/each}
		</div>

		{#if filtered.length === 0}
			<EmptyState caption="Nothing here" sub="No items match this filter." />
		{:else}
			<div>
				{#each filtered as item}
					<div class="ledger-item">
						<div class="row1">
							<span class="tag {KIND_TAG[item.kind] || 'neutral'}">{KIND_LABEL[item.kind] || titleCase(item.kind)}</span>
							<span class="ts">{dateTime(item.ts)}</span>
							{#if item.tick !== null && item.tick !== undefined}<span class="ts">· tick {item.tick}</span>{/if}
							{#if item.model}<span class="ts">· {item.model}</span>{/if}
						</div>
						<div class="title">
							{#if item.position_id}
								<a href="/ledger/{item.position_id}">{item.title}</a>
							{:else}
								{item.title}
							{/if}
						</div>
						{#if item.meta}
							<div class="fine">
								{#if item.meta.probability !== undefined && item.meta.probability !== null}
									stated {(item.meta.probability * 100).toFixed(0)}%
								{/if}
								{#if item.meta.horizon}· resolves {item.meta.horizon}{/if}
								{#if item.meta.band_low !== undefined && item.meta.band_low !== null}
									· band [{item.meta.band_low}, {item.meta.band_high}]
								{/if}
								{#if item.meta.rejected_by}· rejected by {item.meta.rejected_by}{/if}
								{#if item.meta.held !== undefined}· {item.meta.held ? 'held' : 'failed'}{/if}
							</div>
						{/if}
						{#if item.body_html}
							<details class="expand">
								<summary></summary>
								<div class="prose" style="font-size:.9rem">{@html item.body_html}</div>
							</details>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
	</div>
</section>

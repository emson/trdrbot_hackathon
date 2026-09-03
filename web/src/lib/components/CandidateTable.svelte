<script>
	import { strategyLabel, usd } from '$lib/format.js';
	import Term from './Term.svelte';

	// The structures priced for one claim - survivors in ink, rejected ones
	// faint with the fate string verbatim (notes/028). Selecting a row (click,
	// or focus via keyboard) drives the payoff chart above it.
	let { rows = [], selectedName = '', onselect = () => {} } = $props();
</script>

{#if rows.length}
	<div class="scroll">
		<table class="cand-table">
			<thead>
				<tr>
					<th>Structure</th><th class="n">Entry</th><th class="n">Max profit</th>
					<th class="n">Max loss</th><th class="n"><Term name="P(profit | claim holds)" /></th>
					<th class="n">P(profit | claim fails)</th><th class="n"><Term name="Edge" /></th>
					<th>Fate</th>
				</tr>
			</thead>
			<tbody>
				{#each rows as r}
					<tr
						class={r.fate === 'candidate' ? '' : 'rejected'}
						class:selected={r.name === selectedName}
						tabindex="0"
						onmouseenter={() => onselect(r)}
						onfocus={() => onselect(r)}
						onclick={() => onselect(r)}
					>
						<td>{r.name}{#if r.chosen}<span class="tag good" style="margin-left:.4em">chosen</span>{/if}</td>
						<td class="n">{r.net !== null && r.net !== undefined ? usd(r.net) : 'not recorded'}</td>
						<td class="n">{r.max_profit !== null && r.max_profit !== undefined ? usd(r.max_profit) : 'not recorded'}</td>
						<td class="n">{r.max_loss !== null && r.max_loss !== undefined ? usd(r.max_loss) : 'not recorded'}</td>
						<td class="n">{r.p_hold !== null && r.p_hold !== undefined ? `${(r.p_hold * 100).toFixed(0)}%` : 'not recorded'}</td>
						<td class="n">{r.p_fail !== null && r.p_fail !== undefined ? `${(r.p_fail * 100).toFixed(0)}%` : 'not recorded'}</td>
						<td class="n">{r.edge !== null && r.edge !== undefined ? r.edge.toFixed(2) : 'not recorded'}</td>
						<td>
							{#if r.fate === 'candidate'}
								<span class="tag good">candidate</span>
							{:else}
								<span class="tag warn">{r.fate}</span>
							{/if}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
	<p class="fine" style="margin-top:.5rem">
		Fact — contract arithmetic: entry, max profit, max loss, breakevens.
		Modelled — lognormal, drift 0: P(profit | holds), P(profit | fails), edge.
	</p>
{:else}
	<p class="muted" style="font-size:.88rem">No structures were priced for this claim.</p>
{/if}

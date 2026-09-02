<script>
	import PageHeader from '$lib/components/PageHeader.svelte';

	let { data } = $props();

	const GROUPS = [
		{ key: 'context', title: 'Market context', sub: "The agent's own read on the current regime — rewritten as conditions change." },
		{ key: 'technique', title: 'Technique notes', sub: 'What the muse draws on when it argues a domino chain — measured rules, not folklore.' },
		{ key: 'research', title: 'Company dossiers', sub: "Per-name research the agent maintains and refreshes on its own schedule." },
		{ key: 'wiki', title: 'Lessons & log', sub: 'What the learning loop has actually taken away.' }
	];

	function group(key) {
		return data.notes.filter((n) => n.kind === key).sort((a, b) => a.title.localeCompare(b.title));
	}
</script>

<svelte:head><title>Notes — trdrbot</title></svelte:head>

<section class="block ledger">
	<div class="wrap">
		<PageHeader kicker="The agent's own wiki">
			{#snippet heading()}Notes.{/snippet}
			Every page here was written by the agent itself, not by the team — its working knowledge,
			kept current on its own schedule. {data.notes.length} pages.
		</PageHeader>
	</div>
</section>

{#each GROUPS as g}
	{@const items = group(g.key)}
	{#if items.length}
		<section class="block ledger" style="padding-top:0">
			<div class="wrap">
				<h2 style="font-size:1.3rem">{g.title}</h2>
				<p class="muted" style="margin-top:.3rem; max-width:60ch">{g.sub}</p>
				<div class="cols c3" style="margin-top:1rem">
					{#each items as n}
						<a class="card" href="/notes/{n.slug}">
							<span class="tag neutral">{n.kind_label}</span>
							<h3 style="font-size:.98rem">{n.title}</h3>
						</a>
					{/each}
				</div>
			</div>
		</section>
	{/if}
{/each}

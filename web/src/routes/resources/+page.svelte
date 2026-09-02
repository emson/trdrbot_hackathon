<script>
	import { resources } from '$lib/resources.js';
	import Icon from '$lib/components/Icon.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';

	const KIND_LABEL = { interactive: 'Interactive', reading: 'Read' };
</script>

<svelte:head><title>Resources — trdrbot</title></svelte:head>

<section class="block ledger">
	<div class="wrap">
		<PageHeader kicker="Tools & documents">
			{#snippet heading()}Resources.{/snippet}
			Interactive tools and standalone write-ups that go deeper than the main pages — starting
			with the risk model, itself. More gets added here over time.
		</PageHeader>

		{#if resources.length === 0}
			<div style="margin-top:2rem">
				<EmptyState caption="Nothing here yet" sub="Check back soon." />
			</div>
		{:else}
			<div class="cols c3" style="margin-top:1.6rem">
				{#each resources as r}
					<a class="card pad-lg" href={r.href}>
						<Icon name={r.icon || 'compass'} size={22} />
						<span class="tag {r.kind === 'interactive' ? 'good' : 'neutral'}" style="margin-top:.2rem">
							{KIND_LABEL[r.kind] || r.kind}
						</span>
						<h3>{r.title}</h3>
						<p class="muted">{r.description}</p>
					</a>
				{/each}
			</div>
		{/if}
	</div>
</section>

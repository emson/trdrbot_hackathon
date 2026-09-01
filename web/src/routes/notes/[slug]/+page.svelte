<script>
	import MarkdownBody from '$lib/components/MarkdownBody.svelte';
	import SourceLink from '$lib/components/SourceLink.svelte';

	let { data } = $props();
	let n = $derived(data.note);
</script>

<svelte:head><title>{n.title} — trdrbot notes</title></svelte:head>

<section class="block ledger">
	<div class="wrap narrow">
		<a href="/notes" class="fine" style="text-decoration:none">&larr; notes</a>
		<span class="tag neutral" style="display:inline-flex; margin-top:1rem">{n.kind_label}</span>
		<h1 style="margin:.5rem 0 1.4rem">{n.title}</h1>
		<MarkdownBody html={n.html} />
		<div class="card" style="margin-top:2rem">
			<span class="kicker">Source</span>
			<SourceLink path={n.source_path} sha={data.gitSha} />
		</div>
	</div>
</section>

<script>
	import MarkdownBody from '$lib/components/MarkdownBody.svelte';
	import SourceLink from '$lib/components/SourceLink.svelte';

	let { data } = $props();
	let j = $derived(data.journal);
</script>

<svelte:head><title>{j.title} — trdrbot build log</title></svelte:head>

<section class="block ledger">
	<div class="wrap narrow">
		<a href="/build-log" class="fine" style="text-decoration:none">&larr; build log</a>
		<span class="fine" style="display:block; margin-top:1rem">{j.date}</span>
		<h1 style="margin:.4rem 0 1.4rem">{j.title}</h1>
		<MarkdownBody html={j.html} />
		<div class="card" style="margin-top:2rem">
			<span class="kicker">Source</span>
			<SourceLink path={j.source_path} sha={data.gitSha} />
		</div>
	</div>
</section>

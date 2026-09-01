<script>
	import '../app.css';
	import Nav from '$lib/components/Nav.svelte';
	import Footer from '$lib/components/Footer.svelte';

	let { data, children } = $props();
</script>

<svelte:head>
	<title>trdrbot — Theo learns why it was right</title>
	<meta
		name="description"
		content="An autonomous options-trading agent that scores whether its view was right, whether its structure was right, or whether it just got lucky. Built for the Alpaca AI Trading Agents Hackathon."
	/>
</svelte:head>

<Nav />
<main id="main">
	{@render children?.()}
</main>
<Footer generatedAt={data.generatedAt} gitSha={data.gitSha} tick={data.tick} />

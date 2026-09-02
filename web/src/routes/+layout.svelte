<script>
	import '../app.css';
	import Nav from '$lib/components/Nav.svelte';
	import Footer from '$lib/components/Footer.svelte';

	let { data, children } = $props();
</script>

<svelte:head>
	<title>trdrbot — Theo, a self-improving options-trading agent</title>
	<meta
		name="description"
		content="Theo gathers research, forms a falsifiable thesis, simulates the ways to trade it, and sizes the one it trusts most by a track record it has to earn — then scores itself honestly on whether it was right or just lucky. Built for the Alpaca AI Trading Agents Hackathon."
	/>
</svelte:head>

<Nav />
<main id="main">
	{@render children?.()}
</main>
<Footer generatedAt={data.generatedAt} gitSha={data.gitSha} tick={data.tick} />

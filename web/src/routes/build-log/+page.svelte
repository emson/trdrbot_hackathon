<script>
	let { data } = $props();
</script>

<svelte:head><title>Build log — trdrbot</title></svelte:head>

<section class="block ledger">
	<div class="wrap narrow">
		<span class="kicker">Built in public</span>
		<h1 style="margin:.5rem 0 .8rem">The dev journal.</h1>
		<p class="standfirst">
			What actually happened, written the same day — including the defects found and why a fix
			was chosen over its alternatives. {data.journals.length} entries.
		</p>

		<div style="margin-top:1.6rem">
			{#each data.journals as j}
				<a class="card pad-lg" href="/build-log/{j.slug}" style="margin-bottom:1rem">
					<span class="fine">{j.date}</span>
					<h3 style="font-size:1.15rem; font-family:var(--serif); font-weight:600">{j.title}</h3>
					<p class="muted">{j.standfirst}</p>
				</a>
			{/each}
		</div>
	</div>
</section>

<script>
	import Icon from '$lib/components/Icon.svelte';

	let { data } = $props();
	let r = $derived(data.resource);

	let frame = $state(null);

	/* Embedded resources are standalone documents with their own copy of the
	   design system's tokens, so they honour `data-theme` exactly as this site
	   does - but as separate documents they'd otherwise follow the viewer's OS
	   preference while the site follows its own toggle, which reads as a bug
	   the moment those two disagree. Same origin, so the theme can simply be
	   mirrored onto the frame's root. No theme attribute means "no explicit
	   choice", and the embed falls back to prefers-color-scheme like the
	   site does. */
	function syncTheme() {
		try {
			const root = frame?.contentDocument?.documentElement;
			if (!root) return;
			const theme = document.documentElement.getAttribute('data-theme');
			if (theme) root.setAttribute('data-theme', theme);
			else root.removeAttribute('data-theme');
		} catch {
			// A cross-origin embed can't be reached into; it keeps its own theme.
		}
	}

	$effect(() => {
		if (!frame) return;
		syncTheme();
		const observer = new MutationObserver(syncTheme);
		observer.observe(document.documentElement, {
			attributes: true,
			attributeFilter: ['data-theme']
		});
		return () => observer.disconnect();
	});
</script>

<svelte:head><title>{r.title} — trdrbot resources</title></svelte:head>

<section class="block ledger" style="padding-bottom:1.2rem">
	<div class="wrap">
		<a href="/resources" class="fine" style="text-decoration:none">&larr; resources</a>
		<div style="display:flex; justify-content:space-between; align-items:flex-end; gap:1rem; flex-wrap:wrap; margin-top:1rem">
			<div>
				<h1 style="font-size:var(--d2)">{r.title}</h1>
				<p class="standfirst" style="margin-top:.5rem">{r.description}</p>
			</div>
			{#if r.fullPageHref}
				<a class="btn ghost sm" href={r.fullPageHref} target="_blank" rel="noopener noreferrer">
					Open full-screen <Icon name="external" size={14} />
				</a>
			{/if}
		</div>
	</div>
</section>

{#if r.embedSrc}
	<section class="block ledger" style="padding-top:0">
		<div class="wrap">
			<div class="card" style="padding:0; overflow:hidden">
				<iframe
					bind:this={frame}
					src={r.embedSrc}
					title={r.title}
					onload={syncTheme}
					style="width:100%; height:min(88vh, 1150px); border:0; display:block"
				></iframe>
			</div>
			<p class="fine" style="margin-top:.6rem">
				Scrolls independently — use "Open full-screen" above for more room.
			</p>
		</div>
	</section>
{/if}

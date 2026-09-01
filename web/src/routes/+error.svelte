<script>
	import { page } from '$app/state';
	import EmptyState from '$lib/components/EmptyState.svelte';
</script>

<div class="wrap" style="padding:4rem 0">
	<EmptyState
		img="/img/elf-thinking.jpg"
		caption={page.status === 404 ? "Nothing here" : 'Something went wrong'}
		sub={page.status === 404
			? "This page doesn't exist — maybe a stale link. Try the ledger or the home page."
			: page.error?.message || ''}
	/>
	<div style="display:flex; justify-content:center; gap:.6rem; margin-top:1rem">
		<a class="btn ghost sm" href="/">Home</a>
		<a class="btn ghost sm" href="/ledger">Ledger</a>
	</div>
</div>

<script>
	import Icon from './Icon.svelte';

	let theme = $state('system');

	$effect(() => {
		try {
			theme = localStorage.getItem('trdrbot-theme') || 'system';
		} catch {
			theme = 'system';
		}
	});

	function toggle() {
		const prefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches;
		const current = theme === 'system' ? (prefersDark ? 'dark' : 'light') : theme;
		const next = current === 'dark' ? 'light' : 'dark';
		theme = next;
		try {
			localStorage.setItem('trdrbot-theme', next);
		} catch {}
		document.documentElement.setAttribute('data-theme', next);
	}
</script>

<button class="icon-btn" onclick={toggle} aria-label="Toggle color theme" type="button">
	<Icon name={theme === 'dark' ? 'moon' : 'sun'} size={17} />
</button>

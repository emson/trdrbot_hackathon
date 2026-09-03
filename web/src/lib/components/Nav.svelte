<script>
	import { page } from '$app/state';
	import { siteConfig } from '$lib/site.config.js';
	import Icon from './Icon.svelte';
	import ThemeToggle from './ThemeToggle.svelte';

	const links = [
		{ href: '/demo', label: 'Demo' },
		{ href: '/ledger', label: 'Ledger' },
		{ href: '/scoreboard', label: 'Scoreboard' },
		{ href: '/how-it-works', label: 'How it works' },
		{ href: '/resources', label: 'Resources' },
		{ href: '/build-log', label: 'Build log' },
		{ href: '/submission', label: 'For judges' }
	];
	// Mobile-sheet-only links, folded into one array with `links` rather than
	// hardcoded separately in the markup below (found while wiring up /demo -
	// two lists of nav destinations is one more than this needs).
	const mobileExtraLinks = [
		{ href: '/notes', label: 'Notes' },
		{ href: '/data', label: 'Data' },
		{ href: '/glossary', label: 'Glossary' }
	];

	let open = $state(false);
	function isCurrent(href) {
		return page.url.pathname === href || page.url.pathname.startsWith(href + '/');
	}
</script>

<a class="skip-link" href="#main">Skip to content</a>

<nav class="site-nav">
	<div class="wrap">
		<a class="brand-mark" href="/" onclick={() => (open = false)}>
			<img src="/img/mark-icon-64.png" alt="" width="28" height="28" />
			trdrbot
		</a>
		<div class="nav-links">
			{#each links as l}
				<a href={l.href} aria-current={isCurrent(l.href) ? 'page' : undefined}>{l.label}</a>
			{/each}
		</div>
		<div class="nav-right">
			<ThemeToggle />
			{#if siteConfig.repoUrl}
				<a class="icon-btn" href={siteConfig.repoUrl} target="_blank" rel="noopener noreferrer" aria-label="GitHub repository">
					<Icon name="github" size={16} />
				</a>
			{/if}
			<button class="nav-toggle" aria-label="Toggle menu" aria-expanded={open} onclick={() => (open = !open)} type="button">
				<Icon name={open ? 'close' : 'menu'} size={18} />
			</button>
		</div>
	</div>
</nav>

{#if open}
	<div class="mobile-menu">
		<div class="wrap">
			{#each links as l}
				<a href={l.href} onclick={() => (open = false)}>{l.label}</a>
			{/each}
			{#each mobileExtraLinks as l}
				<a href={l.href} onclick={() => (open = false)}>{l.label}</a>
			{/each}
		</div>
	</div>
{/if}

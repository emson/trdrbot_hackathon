<script>
	// Hand-drawn-adjacent monoline icon set, matching the mark's line weight
	// (round caps/joins, no fill) rather than a generic icon font.
	let { name = '', size = 20 } = $props();

	const paths = {
		markets: 'M3 17l5-6 4 3 6-8m0 0h-4m4 0v4',
		research: 'M10.5 4a6.5 6.5 0 100 13 6.5 6.5 0 000-13zM20 20l-5-5',
		automate: 'M12 3v3M9 8h6a2 2 0 012 2v7a2 2 0 01-2 2H9a2 2 0 01-2-2v-7a2 2 0 012-2zM9.5 13h.01M14.5 13h.01M4 12h2M18 12h2',
		risk: 'M12 3l7 3v5c0 5-3.4 8.4-7 10-3.6-1.6-7-5-7-10V6l7-3zM9.5 12l1.8 1.8L15 10',
		journal: 'M6 4h11a1 1 0 011 1v15l-4-2-4 2-4-2V4z M9 8h6 M9 11h6',
		analytics: 'M4 20V10M11 20V4M18 20v-7',
		sun: 'M12 5V3M12 21v-2M5 12H3M21 12h-2M6.3 6.3L4.9 4.9M19.1 19.1l-1.4-1.4M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4M12 8a4 4 0 100 8 4 4 0 000-8z',
		moon: 'M20 14.5A8.5 8.5 0 119.5 4 6.8 6.8 0 0020 14.5z',
		menu: 'M4 7h16M4 12h16M4 17h16',
		close: 'M6 6l12 12M18 6L6 18',
		arrowRight: 'M4 12h15M13 6l6 6-6 6',
		external: 'M7 17L17 7M9 7h8v8',
		github: 'M12 2a10 10 0 00-3.16 19.5c.5.1.68-.22.68-.48v-1.7c-2.78.6-3.37-1.34-3.37-1.34-.46-1.15-1.11-1.46-1.11-1.46-.9-.62.07-.6.07-.6 1 .07 1.53 1.03 1.53 1.03.9 1.52 2.34 1.08 2.91.83.09-.65.35-1.08.63-1.33-2.22-.25-4.56-1.11-4.56-4.93 0-1.09.39-1.98 1.03-2.68-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.02a9.5 9.5 0 015 0c1.91-1.3 2.75-1.02 2.75-1.02.55 1.38.2 2.4.1 2.65.64.7 1.03 1.59 1.03 2.68 0 3.83-2.34 4.68-4.57 4.92.36.31.68.92.68 1.86v2.75c0 .27.18.58.69.48A10 10 0 0012 2z',
		filter: 'M4 5h16M7 12h10M10 19h4',
		check: 'M5 13l4 4L19 7',
		x: 'M6 6l12 12M18 6L6 18',
		telescope: 'M4 18l6-3M15 5l5 3-9 15-2-8-6.5-2.4L15 5z M9 15l-1 3',
		book: 'M5 4h9a3 3 0 013 3v13H8a3 3 0 01-3-3V4zM17 20a3 3 0 003-3V6',
		compass: 'M12 21a9 9 0 100-18 9 9 0 000 18zM14.5 9.5L13 13l-3.5 1.5L11 11l3.5-1.5z'
	};
</script>

<svg
	width={size}
	height={size}
	viewBox="0 0 24 24"
	fill="none"
	stroke="currentColor"
	stroke-width="1.7"
	stroke-linecap="round"
	stroke-linejoin="round"
	aria-hidden="true"
>
	<path d={paths[name] || ''} />
</svg>

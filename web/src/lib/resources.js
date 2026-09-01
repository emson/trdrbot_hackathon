// Interactive tools and standalone documents, hosted as real pages under
// /resources/*.html (synced by scripts/sync-static.mjs, which also injects
// each one's own "← Resources" back-link banner). The index page links
// straight to `href` - append here as new resources ship, no new route
// needed.
export const resources = [
	{
		slug: 'risk-appetite-explorer',
		title: 'Risk Appetite Explorer',
		description:
			'Drag the risk lever and watch what happens to the money over 50 trades — the asymmetry between winning bigger and losing your seat entirely. Uses the same math the sizing engine runs on.',
		kind: 'interactive',
		icon: 'risk',
		href: '/resources/risk-appetite-explorer.html'
	},
	{
		slug: 'architecture-explorer',
		title: 'The Trdrbot Loop',
		description:
			'The whole system, explained from the top down. Click any stage of the Sense → Think → Act → Learn loop to open it, step through one real trade end to end — the actual thesis, strikes and exit rules — then find every one of the ~45 modules by name.',
		kind: 'interactive',
		icon: 'automate',
		href: '/resources/architecture-explorer.html'
	}
];

// Interactive tools and standalone documents that live outside the main
// data-driven pages. Append here as new resources ship - the index page
// and its cards are generated entirely from this list.
export const resources = [
	{
		slug: 'risk-appetite-explorer',
		title: 'Risk Appetite Explorer',
		description:
			'Drag the risk lever and watch what happens to the money over 50 trades — the asymmetry between winning bigger and losing your seat entirely. Uses the same math the sizing engine runs on.',
		kind: 'interactive',
		icon: 'risk',
		embedSrc: '/resources/risk-appetite-explorer.html',
		fullPageHref: '/resources/risk-appetite-explorer.html'
	},
	{
		slug: 'system-architecture',
		title: 'The Trdrbot Loop',
		description:
			'The whole system, explained from the top down. Click any stage of the Sense → Think → Act → Learn loop to open it, step through one real trade end to end — the actual thesis, strikes and exit rules — then find every one of the ~45 modules by name.',
		kind: 'interactive',
		icon: 'automate',
		embedSrc: '/resources/architecture-explorer.html',
		fullPageHref: '/resources/architecture-explorer.html'
	}
];

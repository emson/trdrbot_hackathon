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
		title: 'System Architecture',
		description:
			'Where the model sits, and how little of the system it is — the Sense → Think → Act → Learn pipeline over four memory stores, with the feedback path from Learn back into Think.',
		// No embedSrc: this is one slide inside a 21-slide deck with its own
		// slide-by-slide navigation - cramped and slightly odd inside a small
		// iframe. Link straight to it instead (deck.html#architecture lands
		// directly on the diagram, keyboard/TOC nav from there work as usual).
		kind: 'reading',
		icon: 'automate',
		fullPageHref: '/deck.html#architecture'
	}
];

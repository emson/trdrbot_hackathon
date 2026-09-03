// Site-wide facts that live outside the agent's own record. Filled in once
// the corresponding asset exists; a CTA that points at an empty value is
// omitted rather than rendered as a dead link (see Nav/Footer).
export const siteConfig = {
	repoUrl: 'https://github.com/emson/trdrbot_hackathon',
	videoUrl: '',
	deckPath: '/deck.html',
	// Who built it. One source, so the byline on a page and the byline in
	// the footer cannot drift the way the hero wording did.
	author: {
		name: 'Ben Emson',
		site: 'https://benemson.com',
		siteLabel: 'benemson.com',
		x: 'https://x.com/emson',
		xLabel: 'x.com/emson'
	},
	// Set true once the competition run has stopped - swaps the live tick
	// indicator for a "record final as of" badge so the site doesn't look
	// abandoned when judging happens after the loop stops.
	frozen: false
};

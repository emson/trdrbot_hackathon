import snapshot from '$lib/data/snapshot.json';

export const prerender = true;

export function load() {
	return {
		account: snapshot.account,
		calibration: snapshot.calibration,
		attribution: snapshot.attribution,
		competence: snapshot.competence,
		book: snapshot.book,
		equityCurve: snapshot.equity_curve,
		openIssuesHtml: snapshot.docs.open_issues_html,
		counts: snapshot.counts
	};
}

import snapshot from '$lib/data/snapshot.json';

export const prerender = true;

export function load() {
	return {
		submissionHtml: snapshot.docs.submission_html,
		counts: snapshot.counts,
		account: snapshot.account
	};
}

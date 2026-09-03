import { error } from '@sveltejs/kit';
import snapshot from '$lib/data/snapshot.json';

export const prerender = true;

export function entries() {
	return snapshot.journals.map((j) => ({ slug: j.slug }));
}

export function load({ params }) {
	const journal = snapshot.journals.find((j) => j.slug === params.slug);
	if (!journal) error(404, 'Journal entry not found');
	return { journal, gitSha: snapshot.git_sha };
}

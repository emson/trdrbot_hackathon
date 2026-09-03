import { error } from '@sveltejs/kit';
import snapshot from '$lib/data/snapshot.json';

export const prerender = true;

export function entries() {
	return snapshot.notes.map((n) => ({ slug: n.slug }));
}

export function load({ params }) {
	const note = snapshot.notes.find((n) => n.slug === params.slug);
	if (!note) error(404, 'Note not found');
	return { note, gitSha: snapshot.git_sha };
}

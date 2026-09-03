import { error } from '@sveltejs/kit';
import snapshot from '$lib/data/snapshot.json';

export const prerender = true;

export function entries() {
	return snapshot.positions.map((p) => ({ id: p.id }));
}

export function load({ params }) {
	const position = snapshot.positions.find((p) => p.id === params.id);
	if (!position) error(404, 'Position not found');
	return { position, gitSha: snapshot.git_sha };
}

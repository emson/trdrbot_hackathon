import snapshot from '$lib/data/snapshot.json';

export const prerender = true;

export function load() {
	return { journals: snapshot.journals };
}

import { error } from '@sveltejs/kit';
import { resources } from '$lib/resources.js';

export const prerender = true;

export function entries() {
	return resources.map((r) => ({ slug: r.slug }));
}

export function load({ params }) {
	const resource = resources.find((r) => r.slug === params.slug);
	if (!resource) error(404, 'Resource not found');
	return { resource };
}

import snapshot from '$lib/data/snapshot.json';

export const prerender = true;

export function load() {
	return {
		account: snapshot.account,
		counts: snapshot.counts,
		attribution: snapshot.attribution,
		latest: snapshot.ledger_items[0] || null,
		generatedAt: snapshot.generated_at,
		tick: snapshot.tick
	};
}
